#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Installer-facing runtime-provider readiness and digest-bound ensure facade.

This tool composes the existing deployment and route-manager implementations.
It does not load modules, select a route, or authorize output except through an
explicit digest-bound operation delegated to those implementations.
"""
from __future__ import annotations

import argparse
import contextlib
import grp
import json
import os
import re
from pathlib import Path
import stat
import sys
import uuid

import runtime_binding
import runtime_activation as activation
import runtime_controller_admin as admin
import runtime_deployment as deployment
import runtime_output
import runtime_route_client as client

CONTRACT = 'rp1-gpclk-runtime-readiness-v1'
UPDATE_CONTRACT = 'rp1-gpclk-runtime-update-v1'
SCHEMA_VERSION = 1
EXIT = {'exact_ready': 0, 'neutral_ready': 0, 'absent': 10,
        'deployment_required': 11, 'recovery_required': 12, 'conflict': 13,
        'activation_required': 14}
ROUTES = ('gpio4', 'gpio20')
ENDPOINTS = {'consumer': '/dev/rp1-gpclk', 'controller': '/dev/rp1-route-admin'}
SOCKET = '/run/rp1-gpclk-dkms/route-manager.sock'


def record_error(error):
    return {'status': 'error', 'detail': str(error)}


def canonical_digest(value):
    return admin.digest(json.dumps(value, sort_keys=True,
        separators=(',', ':')).encode())


def validate_idle(query, idle):
    if (not isinstance(query, dict) or not isinstance(idle, dict) or
            idle.get('schemaVersion') != 3 or
            idle.get('contract') != client.CONTRACT or
            idle.get('operation') != 'idle' or idle.get('status') != 'ok' or
            not isinstance(idle.get('state'), dict)):
        raise ValueError('runtime idle response schema')
    state = query.get('state')
    output = idle['state'].get('outputLifecycle')
    runtime_output.validate_lifecycle(output)
    if (not isinstance(state, dict) or
            output.get('route') != state.get('activeRoute') or
            output.get('controller') != state.get('controller') or
            output.get('bootId') != state.get('bootId') or
            output.get('bindingSha256') != state.get('bindingSha256')):
        raise ValueError('runtime idle response identity mismatch')
    return output


class Host:
    """Fixed production observations. Tests replace the complete adapter."""
    def __init__(self):
        self.files = deployment.Files()

    def binding(self):
        try:
            raw = admin.read_regular(admin.BINDING)
            value = runtime_binding.validate(admin.strict_json(raw))
            return {'status': 'valid', 'sha256': admin.digest(raw), 'value': value}
        except FileNotFoundError:
            return {'status': 'absent'}
        except (OSError, ValueError, TypeError, KeyError) as error:
            return record_error(error)

    def artifacts(self, binding):
        result = {}
        expected = {}
        if binding.get('status') == 'valid':
            expected.update(binding['value']['files'])
            expected.update(binding['value']['externalFiles'])
            expected.update({record['path']: record['installedFileSha256']
                             for record in binding['value']['modules'].values()})
        module_paths = ({record['path'] for record in binding.get('value', {}).get('modules', {}).values()}
                        if isinstance(binding.get('value'), dict) else set())
        for path, wanted in sorted(expected.items()):
            try:
                limit = 32*1024*1024 if path in module_paths else 4*1024*1024
                data = admin.read_regular(path, limit)
                actual = admin.digest(data)
                result[path] = {'status': 'exact' if actual == wanted else 'changed',
                                'expectedSha256': wanted, 'actualSha256': actual}
            except FileNotFoundError:
                result[path] = {'status': 'absent', 'expectedSha256': wanted}
            except (OSError, ValueError) as error:
                result[path] = record_error(error)
        return result

    def journal(self, name):
        path = admin.STATE / name
        try:
            return {'status': 'present', 'value': admin.strict_json(admin.read_regular(path, deployment.MAX_JOURNAL_BYTES))}
        except FileNotFoundError:
            return {'status': 'absent'}
        except (OSError, ValueError, TypeError) as error:
            return record_error(error)

    def module(self, name):
        root = Path('/sys/module') / name
        if not root.exists():
            return {'status': 'absent'}
        result = {'status': 'loaded'}
        for field, path in (('version', root/'version'), ('buildNoteSha256', root/'notes/.note.gnu.build-id')):
            try:
                data = admin.read_regular(path)
                result[field] = data.decode().strip() if field == 'version' else admin.digest(data)
            except (OSError, ValueError, UnicodeError) as error:
                result[field] = record_error(error)
        if name == 'rp1_gpclk_dkms':
            try:
                gate = admin.read_regular(root/'parameters/output_inhibit').decode().strip()
                result['outputInhibited'] = gate in ('Y', '1') if gate in ('Y', 'N', '0', '1') else 'unknown'
            except (OSError, ValueError, UnicodeError) as error:
                result['outputInhibited'] = record_error(error)
        return result

    def endpoint(self, path):
        try:
            info = os.lstat(path)
            if (not stat.S_ISCHR(info.st_mode) or info.st_uid != 0 or
                    info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600):
                return {'status': 'unsafe', 'ownerUid': info.st_uid,
                        'ownerGid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}
            identity = {'/dev/rp1-gpclk': '/sys/class/misc/rp1-gpclk/dev',
                        '/dev/rp1-route-admin': '/sys/class/misc/rp1-route-admin/dev'}[path]
            major, minor = admin.read_regular(identity).decode().strip().split(':')
            if info.st_rdev != os.makedev(int(major), int(minor)):
                return {'status': 'unsafe', 'reason': 'device-identity-mismatch'}
            opened = False
            scanned = 0
            for process in Path('/proc').glob('[0-9]*'):
                try:
                    descriptors = process.joinpath('fd').iterdir()
                except OSError:
                    continue
                for descriptor in descriptors:
                    scanned += 1
                    if scanned > 65536:
                        return {'status': 'owned', 'open': 'unknown', 'reason': 'fd-scan-limit'}
                    try:
                        candidate = descriptor.stat()
                    except OSError:
                        continue
                    if (candidate.st_dev, candidate.st_ino) == (info.st_dev, info.st_ino):
                        opened = True
                        break
                if opened:
                    break
            return {'status': 'owned', 'open': opened, 'ownerUid': info.st_uid,
                    'ownerGid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}
        except FileNotFoundError:
            return {'status': 'absent', 'open': False}
        except (OSError, ValueError, UnicodeError) as error:
            return record_error(error)

    def socket(self):
        try:
            info = os.lstat(SOCKET)
            group = grp.getgrnam('rp1-gpclk-route').gr_gid
            return {'status': 'owned' if stat.S_ISSOCK(info.st_mode) and
                    info.st_uid == 0 and info.st_gid == group and
                    stat.S_IMODE(info.st_mode) == 0o660 else 'unsafe',
                    'ownerUid': info.st_uid, 'ownerGid': info.st_gid,
                    'mode': stat.S_IMODE(info.st_mode)}
        except FileNotFoundError:
            return {'status': 'absent'}
        except (OSError, KeyError) as error:
            return record_error(error)

    def services(self):
        result = {}
        for name in ('rp1-gpclk-route-manager.socket',
                     'rp1-gpclk-route-manager@.service', 'wsprrypi.service'):
            try:
                result[name] = admin.systemd_unit(name)
            except (OSError, ValueError) as error:
                result[name] = record_error(error)
        return result

    def manager(self):
        try:
            query = client.exchange({'schemaVersion': 3, 'operation': 'query'})
            if (query.get('operation') != 'query' or query.get('status') != 'ok' or
                    not isinstance(query.get('state'), dict)):
                raise ValueError('runtime query response schema')
            result = {'status': 'observed', 'query': query}
            route = query.get('state', {}).get('activeRoute')
            if route in ROUTES:
                idle = client.exchange({'schemaVersion': 3,
                    'operation': 'idle', 'route': route})
                validate_idle(query, idle)
                result['idle'] = idle
            return result
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            return record_error(error)

    def deployment_plan(self, bundle):
        values = deployment.payloads(bundle)
        value = deployment.plan(self.files, values)
        return value

    def deployment_removal_plan(self):
        return deployment.removal_plan(self.files)

    def deployment_remove(self, value, approved):
        with deployment.mutation_lock():
            # Neutral-activation recovery deliberately leaves an exact,
            # inhibited terminal journal after the deployment was published.
            # Bind its retirement to both the reviewed inverse deployment and
            # the recovery contract before restoring the predeployment bytes.
            if (deployment.plan_hash(value) != approved or
                    deployment.removal_plan(self.files) != value):
                raise ValueError('reviewed deployment removal plan changed before mutation')
            system = activation.Linux()
            journal = system.read_record(activation.JOURNAL)
            transactions = None
            if journal is not None and journal.get('phase') == 'recovered-inhibited':
                record = value['files'].get(str(activation.JOURNAL))
                if not isinstance(record, dict) or deployment.decode(record.get('after')) is not None:
                    raise ValueError('deployment does not own the activation journal')
                recovery = activation.recovery_plan(system)
                if recovery.get('alreadyRecovered') is not True:
                    raise ValueError('activation journal is not exactly recovered')
                transactions = activation.recovered_route_retirement(system)
                system.archive_journal(journal)
                if transactions is not None:
                    system.retire_transactions(transactions)
                system.retire_journal(journal)
            elif journal is None:
                # WsprryPi may already have archived and retired the recovered
                # activation journal. The remaining route journals are still
                # removable only as an exact, inactive, same-boot chain.
                if deployment.existing_deployment_state(self.files) is not None:
                    # Inverse publication can already have removed its binding
                    # and every activation prerequisite. Route retirement must
                    # have finished before that publication began. Do not read a
                    # removed binding to re-prove an already absent journal chain.
                    # The retained inverse and all remaining bytes are checked by
                    # deployment.remove under this same mutation lock.
                    if any(self.files.read(str(admin.STATE / name)) is not None
                           for name in activation.RETIREMENT_TRANSACTIONS):
                        raise ValueError('route journals remain during interrupted inverse deployment')
                else:
                    transactions = activation.recovered_route_retirement(system)
                    if transactions is not None:
                        system.retire_transactions(transactions)
            deployment.remove(self.files, value, approved)
        self.files.prune_removed_directories()
        return {'status': 'removed-exact-deployment'}

    def expected_external(self, expected):
        observed = self.artifacts({'status': 'valid', 'value': expected})
        paths = set(expected['externalFiles']) | {
            record['path'] for record in expected['modules'].values()}
        return {path: observed[path] for path in paths}

    def activation_observation(self):
        try:
            return {'status': 'observed', 'value': activation.observe(activation.Linux())}
        except FileNotFoundError:
            return ({'status': 'absent'} if self.binding().get('status') == 'absent'
                    else record_error('activation provenance or prerequisite is absent'))
        except (OSError, ValueError, TypeError, KeyError) as error:
            return record_error(error)

    def activation_plan(self):
        return activation.activation_plan(activation.Linux())

    def activation_ensure(self, value, approved):
        return activation.ensure(activation.Linux(), value, approved)

    def activation_recovery_plan(self):
        return activation.recovery_plan(activation.Linux())

    def activation_recover(self, value, approved):
        return activation.ensure_recovery(activation.Linux(), value, approved)

    def activation_retirement_plan(self):
        return activation.retirement_plan(activation.Linux())

    def activation_retire(self, value, approved):
        return activation.retire(activation.Linux(), value, approved)

    def update_lock(self):
        import runtime_application
        return runtime_application.mutation_lock()

    def running_kernel(self):
        return os.uname().release

    def update_route_recover(self, expected):
        import runtime_manager
        return runtime_manager.dispatch({'schemaVersion': 3, 'operation': 'recover',
            'execute': True, 'requestId': str(uuid.uuid4()),
            'actor': 'runtime-provider-update'}, mutation_lock=contextlib.nullcontext,
            expected_recovery=expected)

    def update_stop_socket(self, expected):
        with deployment.mutation_lock():
            system = activation.Linux()
            observed = activation.observe(system)
            if observed != expected:
                raise ValueError('socket retirement observation changed')
            if (observed['socket'].get('fragment') !=
                    '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket' or
                    observed['socket'].get('load') != 'loaded' or
                    observed['managerSocket'].get('status') != 'owned'):
                raise ValueError('socket retirement requires the owned manager unit')
            if (observed['controller']['status'] != 'absent' or
                    observed['consumer']['status'] != 'absent' or
                    not observed['inhibited']):
                raise ValueError('socket retirement requires inactive inhibited runtime')
            system.stop_socket()

    def update_removal_evidence(self):
        """Read retained inverse-deployment evidence even after self-removal."""
        raw = self.files.read(deployment.LAST_DEPLOYMENT)
        pending = self.files.read(str(admin.STATE / 'deployment-pending.json'))
        if (pending is not None and raw is not None and
                admin.strict_json(pending) != admin.strict_json(raw)):
            raise ValueError('pending deployment differs from retained inverse')
        return admin.strict_json(raw or pending) if raw or pending else None

    def update_absent(self):
        baseline = self.files.packaged_baseline()
        services = self.services()
        manager_units = ('rp1-gpclk-route-manager.socket',
                         'rp1-gpclk-route-manager@.service')
        inactive_units = all(services.get(name, {}).get('load') in ('loaded', 'not-found')
            and services.get(name, {}).get('active') in ('inactive', 'failed')
            for name in manager_units)
        runtime_absent = all((data := self.files.read(path)) is None or
                    (path in baseline and admin.digest(data) == baseline[path])
                    for path in deployment.DESTINATIONS)
        return (inactive_units and runtime_absent
            and self.files.read(deployment.LAST_DEPLOYMENT) is None
            and self.files.read(str(admin.STATE / 'deployment-pending.json')) is None
            and all(self.module(name)['status'] == 'absent' for name in
                    ('rp1_route_controller', 'rp1_gpclk_dkms'))
            and all(self.endpoint(path)['status'] == 'absent' for path in ENDPOINTS.values())
            and self.socket()['status'] == 'absent')


def update_request(source, binding=None, artifacts=None, deployed=None):
    if not isinstance(source, str) or not re.fullmatch('[0-9a-f]{40}', source):
        raise ValueError('exact predecessor source commit required')
    if (binding is None) != (artifacts is None):
        raise ValueError('paired binding and artifact identities required')
    for value in (binding, artifacts, deployed):
        if value is not None and (not isinstance(value, str) or
                                  not re.fullmatch('[0-9a-f]{64}', value)):
            raise ValueError('invalid update identity digest')
    return {'sourceCommit': source, 'bindingSha256': binding,
            'artifactSetSha256': artifacts, 'deploymentPlanSha256': deployed}


def update_plan(host, request):
    """Provider-private decisions behind a stable consumer envelope."""
    result, _ = inspect(host)
    binding = result['identities']['installedBinding']
    retained = host.update_removal_evidence()
    action, detail = 'prepared', None
    if (retained is not None and request['deploymentPlanSha256'] is not None and
            deployment.plan_hash(retained) != request['deploymentPlanSha256']):
        raise ValueError('update deployment identity mismatch')
    pending = result['journals']['deployment-pending.json'].get('status') == 'present'
    if binding.get('status') == 'absent' or pending:
        if retained is None:
            if not host.update_absent():
                raise ValueError('runtime absence is unproven')
        else:
            deployment.journal_bytes(retained)
            old = runtime_binding.validate(admin.strict_json(deployment.decode(
                retained['files'][deployment.BINDING]['after'])))
            raw = deployment.decode(retained['files'][deployment.BINDING]['after'])
            if binding.get('status') != 'absent' and (binding.get('status') != 'valid' or
                    binding.get('sha256') != admin.digest(raw)):
                raise ValueError('interrupted removal binding differs from retained inverse')
            binding = {'status': 'valid', 'value': old, 'sha256': admin.digest(raw)}
            if (request['deploymentPlanSha256'] is None or
                    deployment.plan_hash(retained) != request['deploymentPlanSha256']):
                raise ValueError('interrupted removal lacks exact deployment identity')
            # The inverse deployment validates every remaining byte against the
            # retained before/after pair and refuses changed external artifacts.
            host.files.preflight_removal()
            action, detail = 'remove-deployment', host.deployment_removal_plan()
    if binding.get('status') == 'valid':
        value = binding['value']
        if (value['kernel'] != host.running_kernel() or
                value['sourceCommit'] != request['sourceCommit'] or
                (request['bindingSha256'] is not None and
                 binding['sha256'] != request['bindingSha256']) or
                (request['artifactSetSha256'] is not None and
                 value['artifactSetSha256'] != request['artifactSetSha256'])):
            raise ValueError('update installation identity mismatch')
        if action != 'remove-deployment':
            if (not result['artifacts'] or any(item.get('status') != 'exact'
                    for item in result['artifacts'].values())):
                raise ValueError('update refuses changed provider artifacts')
            classification = result['result']
            if classification == 'exact_ready':
                action = 'recover-route'
                detail = result['manager']['query']['state']
            else:
                if (any(item.get('status') != 'absent' for name, item in
                        result['modules'].items() if name == 'rp1_gpclk_dkms') or
                        result['endpoints']['consumer'].get('status') != 'absent' or
                        result['endpoints']['consumer'].get('open') is not False or
                        result['routes']['active'] is not None):
                    raise ValueError('update refuses an unsafe or unproven route')
                journal = result['journals']['activation.json']
                current = journal.get('value', {})
                observed = result['activation'].get('value', {})
                if result['modules']['rp1_route_controller'].get('status') == 'loaded':
                    state = observed.get('controllerState')
                    origin = current.get('controller')
                    if (result['endpoints']['controller'].get('status') != 'owned' or
                            result['endpoints']['controller'].get('open') is not False or
                            observed.get('controller', {}).get('exact') is not True or
                            not isinstance(state, dict)):
                        raise ValueError('update lacks a closed exact controller')
                    admin.validate_observation(state)
                    if any(state[name] for name in ('id', 'error', 'route', 'flags')):
                        raise ValueError('update refuses non-neutral controller state')
                    if (current.get('phase') == 'complete-neutral' and
                            (not isinstance(origin, dict) or origin['session'] != state['session'])):
                        raise ValueError('update controller session differs from activation')
                if classification == 'conflict':
                    raise ValueError('update refuses conflicting runtime state')
                if current and current.get('phase') != 'recovered-inhibited':
                    if result['reboot'].get('occurred') is True:
                        action, detail = 'retire-activation', host.activation_retirement_plan()
                    else:
                        action, detail = 'recover-activation', host.activation_recovery_plan()
                else:
                    if (any(item.get('status') != 'absent' for item in result['modules'].values()) or
                            any(item.get('status') != 'absent' for item in result['endpoints'].values())):
                        raise ValueError('update removal requires absent modules and endpoints')
                    if result['managerSocket'].get('status') == 'owned':
                        action, detail = 'stop-manager', observed
                    elif result['managerSocket'].get('status') == 'absent':
                        action, detail = 'remove-deployment', host.deployment_removal_plan()
                    else:
                        raise ValueError('update refuses an unowned manager socket')
    elif action != 'prepared':
        raise ValueError('update requires an attributable provider binding')
    elif binding.get('status') != 'absent':
        raise ValueError('update binding is invalid')
    plan = {'version': 1, 'goal': 'prepare-application-update', 'identity': request,
            'action': action, 'evidence': detail,
            'observationSha256': canonical_digest(result)}
    return {'schemaVersion': 1, 'contract': UPDATE_CONTRACT, 'operation': 'update-plan',
            'identity': request, 'status': 'prepared' if action == 'prepared' else 'planned',
            'planSha256': canonical_digest(plan), 'plan': plan,
            'postconditions': {'runtimeAbsent': action == 'prepared',
                              'transmissionAuthorized': False}}


def installation_status(host):
    result, _ = inspect(host)
    if result['result'] != 'neutral_ready' or not result['administrationEligible']:
        raise ValueError('installation receipt requires exact neutral readiness')
    binding = result['identities']['installedBinding']
    value = binding['value']
    observed = result['activation']['value']
    journal = result['journals']['activation.json']['value']
    controller = journal['controller']
    activation.validate_journal(journal)
    if (value['kernel'] != host.running_kernel() or
            journal['phase'] != 'complete-neutral' or
            any(controller[name] for name in ('generation', 'id', 'error', 'route', 'flags'))):
        raise ValueError('installation receipt lacks neutral activation provenance')
    deployed = host.deployment_removal_plan()
    if admin.digest(deployment.journal_bytes(deployed)) != observed['lastDeploymentSha256']:
        raise ValueError('deployment changed during installation receipt observation')
    receipt = {'readinessContract': CONTRACT, 'bindingSha256': binding['sha256'],
        'artifactSetSha256': value['artifactSetSha256'], 'sourceCommit': value['sourceCommit'],
        'productVersion': value['productVersion'], 'targetKernel': value['kernel'],
        'compatibilityIdentities': value['compatibilityIdentities'],
        'deploymentPlanSha256': deployment.plan_hash(deployed),
        'activationPlanSha256': journal['planSha256'], 'activationRequestId': journal['requestId'],
        'controllerSession': controller['session'], 'controllerGeneration': 0,
        'state': 'neutral_ready', 'route': None, 'output': 'disabled'}
    return {'schemaVersion': 1, 'contract': UPDATE_CONTRACT,
            'operation': 'installation-status', 'status': 'neutral_ready', 'receipt': receipt}


def update_execute(host, request, approved):
    with host.update_lock():
        reviewed = update_plan(host, request)
        if reviewed['planSha256'] != approved:
            raise ValueError('stale update plan; inspect and plan again before mutation')
        selected = reviewed['plan']
        action, detail = selected['action'], selected['evidence']
        if action == 'recover-route':
            reply = host.update_route_recover(detail)
            if reply.get('status') != 'recovered-inhibited':
                raise ValueError('route recovery failed; preserve evidence and re-plan')
        elif action == 'recover-activation':
            host.activation_recover(detail, activation.plan_digest(detail))
        elif action == 'retire-activation':
            host.activation_retire(detail, activation.plan_digest(detail))
        elif action == 'stop-manager':
            host.update_stop_socket(detail)
        elif action == 'remove-deployment':
            host.deployment_remove(detail, deployment.plan_hash(detail))
        elif action != 'prepared':
            raise ValueError('unsupported update action')
        # Re-plan, rather than trusting a primitive's exit code. The next public
        # result proves whether preparation is complete or another step remains.
        following = update_plan(host, request)
        if following['planSha256'] == approved and action != 'prepared':
            raise ValueError('update did not advance; no effect will be retried')
        return {'schemaVersion': 1, 'contract': UPDATE_CONTRACT,
                'operation': 'update-execute', 'identity': request,
                'planSha256': approved, 'status': following['status'],
                'postconditions': following['postconditions']}


def inspect(host, bundle=None, requested=None, configured=None, persisted=None):
    binding = host.binding()
    expected = None
    plan = None
    if bundle is not None:
        try:
            plan = host.deployment_plan(Path(bundle))
            expected = runtime_binding.validate(admin.strict_json(
                deployment.decode(plan['files'][deployment.BINDING]['after'])))
        except (OSError, ValueError, TypeError, KeyError) as error:
            expected = record_error(error)
    artifacts = host.artifacts(binding)
    expected_external = (host.expected_external(expected)
                         if isinstance(expected, dict) and 'externalFiles' in expected else {})
    journals = {name: host.journal(name) for name in
        ('deployment-pending.json', 'transaction.json', 'manager.json',
         'application.json', 'activation.json')}
    modules = {name: host.module(name) for name in ('rp1_route_controller', 'rp1_gpclk_dkms')}
    endpoints = {name: host.endpoint(path) for name, path in ENDPOINTS.items()}
    socket = host.socket()
    services = host.services()
    manager = host.manager() if socket.get('status') == 'owned' else {'status': 'absent'}
    activation_observation = (host.activation_observation()
        if hasattr(host, 'activation_observation') else {'status': 'absent'})
    result = {'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
        'profile': 'runtime', 'result': None, 'state': None,
        'compatible': False, 'eligible': False,
        'administrationCompatible': False, 'administrationEligible': False,
        'routeSelected': False, 'executionReady': False,
        'identities': {'installedBinding': binding, 'expectedBinding': expected,
            'expectedExternal': expected_external},
        'artifacts': artifacts, 'deployment': {'journal': journals['deployment-pending.json'],
            'planSha256': canonical_digest(plan) if plan is not None else None},
        'routes': {'requested': requested, 'configured': configured,
            'persisted': persisted, 'active': None},
        'endpoints': endpoints, 'managerSocket': socket, 'services': services,
        'modules': modules, 'journals': journals, 'manager': manager,
        'activation': activation_observation,
        'reboot': {'occurred': 'unknown', 'required': False},
        'safety': {'outputInhibited': 'unknown', 'operationalReady': 'unknown',
            'owner': 'unknown', 'lease': 'unknown', 'clock': 'unknown', 'gpio': 'unknown',
            'dma': 'unknown', 'endpointOpen': endpoints['consumer'].get('open', 'unknown')},
        'conflicts': [], 'remediation': []}
    classify(result, (host.activation_recovery_plan
                      if hasattr(host, 'activation_recovery_plan') else None))
    return result, plan


def classify(result, activation_recovery_plan=None):
    conflicts = result['conflicts']
    binding = result['identities']['installedBinding']
    expected = result['identities']['expectedBinding']
    journals = result['journals']
    artifacts = result['artifacts']
    modules = result['modules']
    manager = result['manager']
    activation_observation = result['activation']

    if binding.get('status') == 'error':
        conflicts.append('installed-binding-invalid')
    if isinstance(expected, dict) and expected.get('status') == 'error':
        conflicts.append('bundle-invalid')
    for path, value in result['identities']['expectedExternal'].items():
        if value.get('status') != 'exact':
            conflicts.append('external-prerequisite-conflict:'+path)
    if binding.get('status') == 'valid' and isinstance(expected, dict) and 'artifactSetSha256' in expected:
        if binding['value']['artifactSetSha256'] != expected['artifactSetSha256']:
            conflicts.append('installed-binding-differs-from-requested-bundle')
    for path, value in artifacts.items():
        if value.get('status') in ('changed', 'error'):
            conflicts.append('artifact-conflict:'+path)
    for name, value in result['endpoints'].items():
        if value.get('status') in ('unsafe', 'error'):
            conflicts.append(name+'-endpoint-unsafe')
    for name, value in result['endpoints'].items():
        if value.get('open') is not False and value.get('status') != 'absent':
            conflicts.append(name+'-endpoint-open-or-unknown')
    if result['managerSocket'].get('status') in ('unsafe', 'error'):
        conflicts.append('manager-socket-unsafe')
    if any(value.get('status') == 'error' for value in journals.values()):
        conflicts.append('deployment-or-runtime-journal-invalid')
    if activation_observation.get('status') == 'error':
        conflicts.append('activation-evidence-invalid')
    for name, value in modules.items():
        if value.get('status') == 'loaded' and value.get('version') != runtime_binding.PRODUCT_VERSION:
            conflicts.append('mixed-module-version:'+name)
        if value.get('status') == 'loaded' and binding.get('status') == 'valid':
            field = 'controllerNoteSha256' if name == 'rp1_route_controller' else 'consumerNoteSha256'
            if value.get('buildNoteSha256') != binding['value'][field]:
                conflicts.append('loaded-module-identity-mismatch:'+name)
    if modules['rp1_gpclk_dkms'].get('outputInhibited') not in (False, True, None):
        conflicts.append('output-inhibit-unknown')

    pending = journals['deployment-pending.json'].get('status') == 'present'
    activation_journal = journals['activation.json']
    query = manager.get('query', {}) if manager.get('status') == 'observed' else {}
    state = query.get('state', {}) if isinstance(query, dict) else {}
    controller = state.get('controller', {}) if isinstance(state, dict) else {}
    active = state.get('activeRoute') if isinstance(state, dict) else None
    result['routes']['active'] = active
    application = state.get('application') if isinstance(state, dict) else None
    phase = application.get('phase') if isinstance(application, dict) else None
    route_journal = state.get('pendingTransaction') if isinstance(state, dict) else None
    fault = bool(controller.get('flags', 0) & admin.FAULT) if isinstance(controller, dict) else False
    route_values = [value for value in result['routes'].values() if value is not None]
    consumer_routes = [result['routes'][name] for name in
        ('requested', 'configured', 'persisted') if result['routes'][name] is not None]
    if len(set(consumer_routes)) > 1:
        conflicts.append('route-selection-mismatch')
    if active is not None and active not in ROUTES:
        conflicts.append('ambiguous-active-route')
    transaction_valid = (isinstance(route_journal, dict) and
        set(route_journal) == {'version', 'boot', 'session', 'binding', 'request',
                               'target', 'phase', 'observation'} and
        route_journal.get('version') == 1 and
        route_journal.get('phase') in ('complete-inhibited', 'recovered-inhibited') and
        route_journal.get('observation') == controller and
        route_journal.get('session') == controller.get('session') and
        route_journal.get('binding') == state.get('bindingSha256') and
        route_journal.get('boot') == state.get('bootId'))
    if active in ROUTES and not transaction_valid:
        conflicts.append('runtime-transaction-identity-invalid')
    idle = manager.get('idle', {}) if manager.get('status') == 'observed' else {}
    output = idle.get('state', {}).get('outputLifecycle', {}) if isinstance(idle, dict) else {}
    snapshot = output.get('snapshot', {}) if isinstance(output, dict) else {}
    if active in ROUTES:
        try:
            validate_idle(query, idle)
        except ValueError:
            conflicts.append('output-lifecycle-invalid')
    partial = (binding.get('status') == 'valid' and
               any(value.get('status') == 'absent' for value in artifacts.values()))
    activation_pending = (activation_journal.get('status') == 'present' and
        activation_journal.get('value', {}).get('phase') not in activation.TERMINAL)
    unresolved = (pending or activation_pending or partial or fault or query.get('status') == 'error' or
        (binding.get('status') == 'valid' and manager.get('status') == 'error' and
         modules['rp1_route_controller'].get('status') == 'loaded') or
        (isinstance(route_journal, dict) and route_journal.get('phase') not in
         ('complete-inhibited', 'recovered-inhibited')) or
        phase in ('restoration-failed', 'route-failed') or
        (active in ROUTES and phase is not None and phase not in
         ('restored', 'stopped', 'administrator-masked')))

    if snapshot:
        result['safety'].update({'outputInhibited': snapshot.get('outputInhibited') == 2,
            'operationalReady': snapshot.get('operationalReady') == 2,
            'owner': snapshot.get('owner') != 1, 'lease': snapshot.get('lease') != 1,
            'clock': 'quiescent' if snapshot.get('clock') == 2 else 'unknown',
            'gpio': 'quiescent' if snapshot.get('gpio') == 2 else 'unknown',
            'dma': 'quiescent' if snapshot.get('dma') == 2 else 'unknown'})
        if (any(snapshot.get(key) != 1 for key in ('fault', 'owner', 'lease', 'outputInhibited')) or
                any(snapshot.get(key) != 2 for key in ('operationalReady', 'gpio', 'clock', 'dma', 'stable'))):
            conflicts.append('consumer-not-ready-closed-and-quiescent')
    aligned = bool(active in ROUTES and all(value == active for value in route_values))
    endpoints_ready = all(value.get('status') == 'owned' for value in result['endpoints'].values())
    closed = result['endpoints']['consumer'].get('open') is False
    socket_ready = result['managerSocket'].get('status') == 'owned'
    services_ready = (result['services'].get('rp1-gpclk-route-manager.socket', {}).get('load') == 'loaded' and
        result['services'].get('rp1-gpclk-route-manager.socket', {}).get('active') == 'active' and
        result['services'].get('rp1-gpclk-route-manager.socket', {}).get('fragment') ==
        '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket')
    artifacts_ready = (binding.get('status') == 'valid' and artifacts and
                       all(value.get('status') == 'exact' for value in artifacts.values()))
    modules_ready = all(value.get('status') == 'loaded' for value in modules.values())
    application_ready = phase in ('restored', 'stopped', 'administrator-masked')
    output_ready = (output.get('ready') is True and
        output.get('executionAuthorized') is False and
        output.get('productionAuthority') == 'root-owned-endpoint' and
        snapshot and snapshot.get('route') in (1, 2) and
        all(snapshot.get(key) == 1 for key in ('fault', 'owner', 'lease', 'outputInhibited')) and
        all(snapshot.get(key) == 2 for key in ('operationalReady', 'gpio', 'clock', 'dma', 'stable')))
    controller_ready = (controller.get('flags') == admin.CONSUMER | admin.PINNED and
                        controller.get('error') == 0 and controller.get('route') in (1, 2))
    neutral = (activation_observation.get('status') == 'observed' and
        activation.neutral_ready(activation_observation['value'], current_service=True))
    post_reboot_restartable = False
    post_reboot_blocked = False
    current_route_ancestry = False
    current_route_recovery = False
    route_recovery = None
    if activation_observation.get('status') == 'observed' and not neutral:
        observed_activation = activation_observation['value']
        prior_activation = observed_activation.get('activationJournal')
        if isinstance(prior_activation, dict) and prior_activation.get('phase') == 'reboot-prepare':
            result['reboot']['occurred'] = True
            try:
                post_reboot_restartable = activation.reboot_preparation_state(observed_activation)
            except (OSError, ValueError, TypeError, KeyError):
                post_reboot_blocked = True
            if post_reboot_restartable:
                unresolved = pending or partial or fault
        if (isinstance(prior_activation, dict) and
                prior_activation.get('phase') == 'complete-neutral'):
            prior_plan = prior_activation.get('plan', {})
            if prior_plan.get('bootId') != observed_activation.get('bootId'):
                result['reboot']['occurred'] = True
                try:
                    post_reboot_restartable = (
                        activation.post_reboot_reactivation_state(observed_activation))
                except (OSError, ValueError, TypeError, KeyError):
                    post_reboot_blocked = True
            else:
                try:
                    if active in ROUTES:
                        current_route_ancestry = (
                            activation.routed_from_current_neutral(observed_activation))
                    else:
                        if activation_recovery_plan is None:
                            raise ValueError('neutral recovery planner is unavailable')
                        recovery = activation_recovery_plan()
                        route_recovery = recovery.get('routeRecoverySha256')
                        current_route_recovery = (
                            isinstance(route_recovery, dict) and
                            set(route_recovery) == set(activation.RETIREMENT_TRANSACTIONS) and
                            all(isinstance(value, str) and len(value) == 64 and
                                not set(value)-set('0123456789abcdef')
                                for value in route_recovery.values()))
                except (OSError, ValueError, TypeError, KeyError):
                    post_reboot_blocked = True
                if active in ROUTES and not current_route_ancestry:
                    post_reboot_blocked = True
    application_journal = journals['application.json']
    transaction_journal = journals['transaction.json']
    application_service = result['services'].get('wsprrypi.service', {})
    restored_service = (phase == 'neutral-restored' and
        application_service.get('load') == 'loaded' and
        application_service.get('active') == 'active')
    stopped_service = (phase == 'neutral-stopped' and
        application_service.get('load') == 'loaded' and
        application_service.get('active') in ('inactive', 'failed') and
        application_service.get('enabled') not in ('masked', 'masked-runtime'))
    masked_service = (phase == 'neutral-administrator-masked' and
        (application_service.get('load') == 'masked' or
         application_service.get('enabled') in ('masked', 'masked-runtime')) and
        application_service.get('active') in ('inactive', 'failed'))
    neutral_endpoints_ready = (
        result['endpoints']['controller'].get('status') == 'owned' and
        result['endpoints']['controller'].get('open') is False and
        result['endpoints']['consumer'].get('status') == 'absent' and closed)
    completed_removal = (current_route_recovery and active is None and
        state.get('configuredRoute') is None and
        state.get('applicationInhibited') is False and
        state.get('outputEnabled') is False and
        isinstance(controller, dict) and controller.get('generation', 0) > 0 and
        all(controller.get(name) == 0 for name in ('id', 'error', 'route', 'flags')) and
        isinstance(application, dict) and
        application.get('operation') == 'remove' and
        application.get('controller') is None and
        application.get('ready') is None and
        application_journal.get('status') == 'present' and
        application_journal.get('value') == application and
        transaction_journal.get('status') == 'present' and
        transaction_journal.get('value') == route_journal and
        (restored_service or stopped_service or masked_service) and
        artifacts_ready and
        modules['rp1_route_controller'].get('status') == 'loaded' and
        modules['rp1_gpclk_dkms'].get('status') == 'absent' and
        neutral_endpoints_ready and socket_ready and services_ready)
    administration_neutral = neutral or completed_removal
    if administration_neutral:
        result['safety'].update({'outputInhibited': False, 'operationalReady': False,
            'owner': False, 'lease': False, 'clock': 'quiescent',
            'gpio': 'quiescent', 'dma': 'quiescent', 'endpointOpen': False})
        result['reboot']['occurred'] = False
    if (modules['rp1_route_controller'].get('status') == 'loaded' and
            modules['rp1_gpclk_dkms'].get('status') == 'absent' and not neutral and
            not activation_pending and not current_route_recovery):
        conflicts.append('loaded-controller-without-completed-activation')

    residue = (binding.get('status') != 'absent' or artifacts or
        any(value.get('status') == 'loaded' for value in modules.values()) or
        any(value.get('status') != 'absent' for value in result['endpoints'].values()) or
        result['managerSocket'].get('status') != 'absent' or
        any(value.get('status') != 'absent' for value in journals.values()))
    if conflicts:
        classification = 'conflict'
        result['remediation'].append('Preserve the conflicting state and use its owning migration or removal workflow.')
    elif (unresolved or post_reboot_blocked or
          (current_route_recovery and not completed_removal)):
        classification = 'recovery_required'
        if post_reboot_blocked:
            result['remediation'].append(
                'Preserve the prior-boot activation evidence and investigate the state mismatch; do not delete the journal or force activation.')
        else:
            result['remediation'].append('Use the existing deployment recover, route recover, or application restore verb indicated by the retained journal.')
    elif (artifacts_ready and modules_ready and endpoints_ready and closed and socket_ready and services_ready and
          controller_ready and application_ready and aligned and output_ready):
        classification = 'exact_ready'
    elif administration_neutral:
        classification = 'neutral_ready'
    elif not residue:
        classification = 'absent'
        result['remediation'].append('Build and review an exact runtime bundle, then approve its deployment plan digest.')
    elif artifacts_ready and modules['rp1_route_controller'].get('status') == 'absent' and modules['rp1_gpclk_dkms'].get('status') == 'absent':
        classification = 'activation_required'
        if post_reboot_restartable:
            result['remediation'].append(
                'Review and execute digest-bound post-reboot neutral reactivation before any explicit route selection.')
        else:
            result['remediation'].append('Review and execute neutral activation before any explicit route selection.')
    else:
        classification = 'deployment_required'
        result['remediation'].append('Complete the explicit deployment step; installation alone does not activate administration or select a route.')
    result['result'] = classification
    result['state'] = classification
    result['compatible'] = classification == 'exact_ready'
    result['eligible'] = classification == 'exact_ready'
    result['administrationCompatible'] = classification in ('neutral_ready', 'exact_ready')
    result['administrationEligible'] = classification in ('neutral_ready', 'exact_ready')
    result['routeSelected'] = classification == 'exact_ready'
    result['executionReady'] = classification == 'exact_ready'


def route_plan(result, route):
    if result['result'] in ('conflict', 'recovery_required', 'absent',
                            'activation_required'):
        raise ValueError('runtime state is not eligible for route planning')
    manager = result['manager']
    binding = result['identities']['installedBinding']
    if (binding.get('status') != 'valid' or not result['artifacts'] or
            any(value.get('status') != 'exact' for value in result['artifacts'].values())):
        raise ValueError('exact deployed runtime artifacts are required')
    if manager.get('status') != 'observed':
        raise ValueError('runtime manager is unavailable')
    if result['routes']['active'] == route and result['result'] == 'exact_ready':
        return {'version': 1, 'operation': 'select', 'route': route,
                'alreadyReady': True, 'bindingSha256': binding['sha256'],
                'requestedRoute': result['routes']['requested'],
                'configuredRoute': result['routes']['configured'],
                'persistedRoute': result['routes']['persisted']}
    checked = client.exchange({'schemaVersion': 3, 'operation': 'preflight', 'route': route})
    if checked.get('status') != 'ok':
        raise ValueError('route preflight failed')
    return {'version': 1, 'operation': 'select', 'route': route, 'alreadyReady': False,
        'bindingSha256': binding['sha256'],
        'requestedRoute': result['routes']['requested'],
        'configuredRoute': result['routes']['configured'],
        'persistedRoute': result['routes']['persisted'],
        'preflightToken': checked['state']['preflightToken'],
        'controller': checked['state']['controller']}


def emit(value):
    print(json.dumps(value, sort_keys=True, indent=2))


def main(host=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capabilities', 'installation-status', 'update-plan', 'update-execute', 'inspect', 'plan', 'ensure',
        'remove-plan', 'remove',
        'activation-plan', 'activation-ensure', 'activation-recover-plan',
        'activation-recover', 'activation-retire-plan', 'activation-retire',
        'route-plan', 'route-ensure'))
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--route', choices=ROUTES)
    parser.add_argument('--requested-route', choices=ROUTES)
    parser.add_argument('--configured-route', choices=ROUTES)
    parser.add_argument('--persisted-route', choices=ROUTES)
    parser.add_argument('--source-commit')
    parser.add_argument('--binding-sha256')
    parser.add_argument('--artifact-set-sha256')
    parser.add_argument('--deployment-sha256')
    args = parser.parse_args()
    host = host or Host()
    if args.operation == 'capabilities':
        emit({'schemaVersion': 1, 'contract': UPDATE_CONTRACT,
              'operation': 'capabilities', 'capabilities': ['update-plan', 'update-execute', 'installation-status'],
              'predecessorContracts': [runtime_binding.CONTRACT]})
        return 0
    if args.operation == 'installation-status':
        emit(installation_status(host))
        return 0
    if args.operation in ('update-plan', 'update-execute'):
        if any(value is not None for value in (args.bundle, args.route,
                args.requested_route, args.configured_route, args.persisted_route)):
            raise ValueError('update preparation accepts no bundle or route selection')
        request = update_request(args.source_commit, args.binding_sha256,
                                 args.artifact_set_sha256, args.deployment_sha256)
        emit(update_plan(host, request) if args.operation == 'update-plan' else
             update_execute(host, request, args.plan_sha256))
        return 0
    if args.operation in ('plan', 'ensure') and args.bundle is None:
        raise ValueError('--bundle is required')
    if args.operation in ('route-plan', 'route-ensure') and args.route is None:
        raise ValueError('--route is required')
    if args.operation.startswith('activation-') and any(
            value is not None for value in
            (args.route, args.requested_route, args.configured_route,
             args.persisted_route)):
        raise ValueError('neutral activation accepts no GPIO route')
    result, plan = inspect(host, args.bundle, args.requested_route,
        args.configured_route, args.persisted_route)
    if args.operation == 'inspect':
        emit(result)
        return EXIT[result['result']]
    if args.operation == 'plan':
        result['deployment']['plan'] = {'planSha256': canonical_digest(plan),
            'destinations': {path: {side: None if data is None else admin.digest(deployment.decode(data))
            for side, data in record.items()} for path, record in plan['files'].items()}}
        emit(result)
        return EXIT[result['result']]
    if args.operation == 'ensure':
        if result['result'] in ('conflict', 'recovery_required'):
            emit(result)
            return EXIT[result['result']]
        reviewed_digest = canonical_digest(plan)
        if args.plan_sha256 != reviewed_digest:
            raise ValueError('reviewed deployment plan digest required')
        deployment.provision_state()
        with deployment.mutation_lock():
            # Recreate the complete plan while holding the shared deployment/
            # route lock. Only the originally reviewed digest is accepted.
            plan = host.deployment_plan(args.bundle)
            digest = canonical_digest(plan)
            if reviewed_digest != digest:
                raise ValueError('reviewed deployment plan changed before mutation')
            attributable = [record for path, record in plan['files'].items()
                if path not in deployment.JOURNALS]
            if all(deployment.decode(record['before']) == deployment.decode(record['after'])
                   for record in attributable):
                result['deployment']['execution'] = 'idempotent-no-change'
            else:
                deployment.apply(host.files, plan, digest)
                result['deployment']['execution'] = 'deployed-inhibited'
        emit(result)
        return 0
    if args.operation in ('remove-plan', 'remove'):
        if (result['result'] not in ('activation_required', 'recovery_required') or
                result['routeSelected'] or
                any(value.get('status') != 'absent'
                    for value in result['modules'].values()) or
                any(value.get('status') != 'absent'
                    for value in result['endpoints'].values()) or
                result['managerSocket'].get('status') != 'absent'):
            emit(result)
            return EXIT[result['result']]
        selected = host.deployment_removal_plan()
        digest = deployment.plan_hash(selected)
        if args.operation == 'remove-plan':
            emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
                  'operation': args.operation, 'planSha256': digest,
                  'destinations': sorted(selected['files'])})
            return 0
        if args.plan_sha256 != digest:
            raise ValueError('reviewed deployment removal plan digest required')
        reply = host.deployment_remove(selected, digest)
        emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
              'operation': args.operation, 'planSha256': digest,
              'response': reply})
        return 0
    if args.operation in ('activation-retire-plan', 'activation-retire'):
        if (result['result'] not in ('activation_required', 'recovery_required') or
                result.get('reboot', {}).get('occurred') is not True or
                result['routeSelected'] or
                any(value.get('status') != 'absent'
                    for value in result['modules'].values()) or
                any(value.get('status') != 'absent'
                    for value in result['endpoints'].values()) or
                result['managerSocket'].get('status') != 'absent'):
            emit(result)
            return EXIT[result['result']]
        selected = host.activation_retirement_plan()
        digest = activation.plan_digest(selected)
        if args.operation == 'activation-retire-plan':
            emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
                  'operation': args.operation, 'planSha256': digest,
                  'plan': selected})
            return 0
        if args.plan_sha256 != digest:
            raise ValueError('reviewed post-reboot activation retirement digest required')
        reply = host.activation_retire(selected, digest)
        emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
              'operation': args.operation, 'planSha256': digest,
              'response': reply})
        return 0
    if args.operation in ('activation-plan', 'activation-ensure'):
        if result['result'] not in ('activation_required', 'neutral_ready'):
            emit(result)
            return EXIT[result['result']]
        selected = host.activation_plan()
        digest = activation.plan_digest(selected)
        if args.operation == 'activation-plan':
            result['activationPlan'] = {'planSha256': digest, **selected}
            emit(result)
            return EXIT[result['result']]
        if args.plan_sha256 != digest:
            raise ValueError('reviewed neutral activation plan digest required')
        reply = host.activation_ensure(selected, digest)
        emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
              'operation': 'activation-ensure', 'planSha256': digest,
              'response': reply})
        return 0
    if args.operation in ('activation-recover-plan', 'activation-recover'):
        selected = host.activation_recovery_plan()
        digest = activation.plan_digest(selected)
        if args.operation == 'activation-recover-plan':
            emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
                  'operation': args.operation, 'planSha256': digest,
                  'plan': selected})
            return 0
        if args.plan_sha256 != digest:
            raise ValueError('reviewed neutral recovery plan digest required')
        reply = host.activation_recover(selected, digest)
        emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
              'operation': args.operation, 'planSha256': digest,
              'response': reply})
        return 0
    selected = route_plan(result, args.route)
    route_digest = canonical_digest(selected)
    if args.operation == 'route-plan':
        result['routePlan'] = {'planSha256': route_digest, **selected}
        emit(result)
        return EXIT[result['result']]
    if args.plan_sha256 != route_digest:
        raise ValueError('reviewed route plan digest required')
    if selected['alreadyReady']:
        reply = {'status': 'idempotent-ready'}
    else:
        reply = client.exchange({'schemaVersion': 3, 'operation': 'switch',
            'route': args.route, 'execute': True, 'requestId': str(uuid.uuid4()),
            'actor': 'runtime-provider-installer',
            'preflightToken': selected['preflightToken']})
    emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
          'operation': 'route-ensure', 'planSha256': route_digest, 'response': reply})
    return 0 if reply.get('status') != 'error' else 12


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print('STOP: '+str(error), file=sys.stderr)
        emit({'schemaVersion': SCHEMA_VERSION, 'contract': CONTRACT,
              'result': 'conflict', 'state': 'conflict', 'compatible': False,
              'eligible': False, 'error': {'code': 'fail-closed', 'detail': str(error)}})
        raise SystemExit(EXIT['conflict'])
