#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Digest-bound neutral runtime-controller activation and explicit recovery."""
from __future__ import annotations

import fcntl
import grp
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

import runtime_application as application
import runtime_binding
import runtime_controller_admin as admin
import runtime_deployment as deployment
import runtime_route_client as client

JOURNAL = admin.STATE / 'activation.json'
LAST_DEPLOYMENT = admin.STATE / 'last-deployment.json'
SOCKET_UNIT = 'rp1-gpclk-route-manager.socket'
SOCKET_GROUP = 'rp1-gpclk-route'
SERVICE_UNIT = 'rp1-gpclk-route-manager@.service'
APPLICATION_UNIT = 'wsprrypi.service'
SOCKET_PATH = Path('/run/rp1-gpclk-dkms/route-manager.sock')
MAX_RECORD = 4 * 1024 * 1024
PENDING = ('reboot-prepare', 'activation-intent', 'controller-load-intent', 'socket-start-intent',
           'manager-query-intent', 'application-restore-intent', 'rollback-intent',
           'activation-failed', 'rollback-failed')
TERMINAL = ('complete-neutral', 'recovered-inhibited')
PLAN_CONTEXTS = ('initial', 'recovered', 'idempotent', 'post-reboot')
# Delete in dependency order so every interrupted prefix remains valid for retry:
# application depends on manager, and manager depends on the route transaction.
RETIREMENT_TRANSACTIONS = ('application.json', 'manager.json', 'transaction.json')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def plan_digest(value):
    return admin.digest(canonical(value))


def validate_plan(value):
    base = {'version', 'operation', 'bindingSha256', 'artifactSetSha256',
            'bootId', 'lastDeploymentSha256', 'application',
            'socketWasActive', 'alreadyReady', 'previousActivationSha256'}
    version = value.get('version') if isinstance(value, dict) else None
    required = (base if version == 1 else
                base | {'activationContext', 'applicationInhibited'})
    if version == 3:
        required |= {'rebootEvidence'}
    if (not isinstance(value, dict) or set(value) != required or
            type(version) is not int or version not in (1, 2, 3) or
            value.get('operation') != 'neutral-activation' or
            any(not isinstance(value.get(name), str) or
                not re.fullmatch('[0-9a-f]{64}', value[name])
                for name in ('bindingSha256', 'artifactSetSha256',
                             'lastDeploymentSha256')) or
            not isinstance(value.get('bootId'), str) or
            type(value.get('socketWasActive')) is not bool or
            type(value.get('alreadyReady')) is not bool or
            (value.get('previousActivationSha256') is not None and
             (not isinstance(value['previousActivationSha256'], str) or
              not re.fullmatch('[0-9a-f]{64}', value['previousActivationSha256'])))):
        raise ValueError('neutral activation plan schema')
    if version in (2, 3) and (value.get('activationContext') not in PLAN_CONTEXTS or
                         type(value.get('applicationInhibited')) is not bool):
        raise ValueError('neutral activation plan context')
    if version in (2, 3):
        context = value['activationContext']
        previous = value['previousActivationSha256']
        if ((context == 'idempotent') != value['alreadyReady'] or
                (context == 'initial') != (previous is None) or
                (context in ('initial', 'recovered') and
                 not value['applicationInhibited']) or
                (context == 'post-reboot' and value['socketWasActive'])):
            raise ValueError('neutral activation plan context is inconsistent')
    if version == 3:
        if value['activationContext'] != 'post-reboot':
            raise ValueError('reboot evidence requires post-reboot context')
        validate_reboot_evidence(value['rebootEvidence'], value['bindingSha256'])
        if value['rebootEvidence']['bootId'] == value['bootId']:
            raise ValueError('reboot evidence must belong to an older boot')
    uuid.UUID(value['bootId'])
    application.validate_neutral_capture(value['application'])
    return value


def validate_journal(value):
    required = {'version', 'plan', 'planSha256', 'requestId', 'phase',
                'controller', 'manager', 'application', 'error'}
    if (not isinstance(value, dict) or set(value) != required or
            type(value.get('version')) is not int or value['version'] != 1 or
            value.get('phase') not in (*PENDING, *TERMINAL) or
            not isinstance(value.get('requestId'), str) or
            not isinstance(value.get('planSha256'), str) or
            not re.fullmatch('[0-9a-f]{64}', value['planSha256'])):
        raise ValueError('neutral activation journal schema')
    uuid.UUID(value['requestId'])
    validate_plan(value['plan'])
    if plan_digest(value['plan']) != value['planSha256']:
        raise ValueError('neutral activation journal plan mismatch')
    if value['controller'] is not None:
        admin.validate_observation(value['controller'])
    if value['manager'] is not None and not isinstance(value['manager'], dict):
        raise ValueError('neutral activation manager evidence')
    if value['application'] is not None and not isinstance(value['application'], dict):
        raise ValueError('neutral activation application evidence')
    if value['error'] is not None and not isinstance(value['error'], str):
        raise ValueError('neutral activation error evidence')
    return value


class Linux:
    """Fixed production effects; tests inject a complete fake."""
    def read_record(self, path):
        try:
            self.trusted_file(Path(path), 0o600)
            return admin.strict_json(admin.read_regular(path, MAX_RECORD))
        except FileNotFoundError:
            return None

    def write_journal(self, value):
        validate_journal(value)
        shell = admin.Linux.__new__(admin.Linux)
        shell.write_record('activation.json', value)

    def archive_journal(self, value):
        validate_journal(value)
        identity = admin.digest(canonical(value))
        path = admin.STATE / ('prior-activation-' + identity + '.json')
        data = canonical(value) + b'\n'
        try:
            self.trusted_file(path, 0o600)
            if admin.read_regular(path, MAX_RECORD) != data:
                raise ValueError('prior activation archive identity conflict')
            return
        except FileNotFoundError:
            pass
        fd, temporary = tempfile.mkstemp(prefix='activation-archive-', dir=admin.STATE)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # The shared mutation lock serializes publishers. Rename keeps
            # the published archive single-linked even across process death.
            if path.exists() or path.is_symlink():
                self.trusted_file(path, 0o600)
                if admin.read_regular(path, MAX_RECORD) != data:
                    raise ValueError('prior activation archive appeared with different bytes')
            else:
                os.replace(temporary, path)
            admin.fsync_dir(admin.STATE)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def retire_journal(self, expected):
        current = self.read_record(JOURNAL)
        if current != expected:
            raise ValueError('prior activation changed before retirement')
        path = Path(JOURNAL)
        path.unlink()
        admin.fsync_dir(path.parent)

    def retire_transactions(self, expected):
        """Remove an exact prior-boot journal set, leaving activation until last."""
        if set(expected) != set(RETIREMENT_TRANSACTIONS):
            raise ValueError('fixed retirement transaction inventory required')
        for name in RETIREMENT_TRANSACTIONS:
            if self.read_record(admin.STATE / name) != expected[name]:
                raise ValueError('prior transaction changed before retirement: ' + name)
        if expected['application.json'] is not None:
            application.remove_idle(expected['application.json'])
        for name in RETIREMENT_TRANSACTIONS:
            if expected[name] is not None:
                path = admin.STATE / name
                path.unlink()
                admin.fsync_dir(path.parent)

    def retirement_idle(self, record):
        path = application.unit_file(application.IDLE_DROPIN)
        try:
            self.trusted_file(path, 0o644)
            installed = admin.read_regular(path)
        except FileNotFoundError:
            return None
        if record is None:
            raise ValueError('prior idle override lacks application ownership')
        owners = [application.idle_bytes(record)]
        if record.get('previousIdle'):
            owners.append(application.idle_bytes(dict(
                record, token=record['previousIdle'])))
        if installed not in owners:
            raise ValueError('prior idle override differs from application ownership')
        return admin.digest(installed)

    def boot(self):
        value = admin.read_regular('/proc/sys/kernel/random/boot_id').decode().strip()
        uuid.UUID(value)
        return value

    def binding(self):
        self.trusted_file(admin.BINDING, 0o644)
        raw = admin.read_regular(admin.BINDING)
        value = runtime_binding.validate(admin.strict_json(raw))
        if value['kernel'] != os.uname().release:
            raise ValueError('activation binding kernel differs from running kernel')
        for path, expected in {**value['files'], **value['externalFiles']}.items():
            mode = 0o755 if path == runtime_binding.APPLICATION else 0o644
            self.trusted_file(Path(path), mode)
            limit = 32 * 1024 * 1024 if path.endswith('.ko') else 4 * 1024 * 1024
            if admin.digest(admin.read_regular(path, limit)) != expected:
                raise ValueError('activation artifact mismatch: ' + path)
        for module, record in value['modules'].items():
            path = record['path']
            self.trusted_file(Path(path), 0o644)
            if admin.digest(admin.read_regular(path, 32 * 1024 * 1024)) != record['installedFileSha256']:
                raise ValueError('activation DKMS module mismatch: ' + path)
            if admin.run(('/usr/sbin/modinfo', '-F', 'filename', module)) != path:
                raise ValueError('activation module resolution mismatch: ' + module)
        return raw, value

    def trusted_file(self, path, mode):
        info = Path(path).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or
                stat.S_IMODE(info.st_mode) != mode or info.st_nlink != 1):
            raise ValueError('activation file ownership/mode/link mismatch: ' + str(path))

    def last_deployment(self, binding_raw):
        self.trusted_file(LAST_DEPLOYMENT, 0o600)
        raw = admin.read_regular(LAST_DEPLOYMENT, deployment.MAX_JOURNAL_BYTES)
        value = admin.strict_json(raw)
        deployment.journal_bytes(value)
        installed = deployment.decode(value['files'][deployment.BINDING]['after'])
        if installed != binding_raw:
            raise ValueError('last deployment binding differs')
        return raw, value

    def module(self, name, note):
        root = Path('/sys/module') / name
        if not root.exists():
            return {'status': 'absent'}
        actual = admin.digest(admin.read_regular(root / 'notes/.note.gnu.build-id'))
        return {'status': 'loaded', 'buildNoteSha256': actual,
                'exact': actual == note}

    def endpoint(self, path, identity):
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return {'status': 'absent', 'open': False}
        if (not stat.S_ISCHR(info.st_mode) or info.st_uid or info.st_gid or
                stat.S_IMODE(info.st_mode) != 0o600):
            return {'status': 'unsafe'}
        major, minor = admin.read_regular(identity).decode().strip().split(':')
        if info.st_rdev != os.makedev(int(major), int(minor)):
            return {'status': 'unsafe'}
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
                    return {'status': 'owned', 'open': 'unknown'}
                try:
                    candidate = descriptor.stat()
                except OSError:
                    continue
                if (candidate.st_dev, candidate.st_ino) == (info.st_dev, info.st_ino):
                    opened = True
                    break
            if opened:
                break
        return {'status': 'owned', 'open': opened}

    def service(self, name):
        if name not in {SOCKET_UNIT, SERVICE_UNIT, APPLICATION_UNIT}:
            raise ValueError('unsupported activation service: ' + name)
        return admin.systemd_unit(
            name, include_main_pid=(name == APPLICATION_UNIT))

    def manager_socket(self):
        try:
            info = os.lstat(SOCKET_PATH)
        except FileNotFoundError:
            return {'status': 'absent'}
        group = grp.getgrnam(SOCKET_GROUP).gr_gid
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid or info.st_gid != group or
                stat.S_IMODE(info.st_mode) != 0o660):
            return {'status': 'unsafe', 'ownerUid': info.st_uid,
                    'ownerGid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}
        return {'status': 'owned', 'ownerUid': info.st_uid,
                'ownerGid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}

    def inhibitor(self):
        try:
            path = application.unit_file(application.DROPIN)
            self.trusted_file(path, 0o644)
            if admin.read_regular(path) != application.INHIBIT:
                raise ValueError('activation inhibitor ownership differs')
            return True
        except FileNotFoundError:
            return False

    def controller_state(self):
        fd = os.open(admin.ENDPOINT, os.O_RDWR | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISCHR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o077:
                raise ValueError('controller endpoint ownership')
            data = bytearray(admin.FORMAT.pack(0, admin.STATUS, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            fcntl.ioctl(fd, admin.IOCTL, data, True)
            reserved0, op, route, reserved, session, generation, oid, error, active, flags, r1, r2 = admin.FORMAT.unpack(data)
            if reserved0 or op or route or reserved or r1 or r2:
                raise ValueError('controller response schema')
            value = {'session': session, 'generation': generation, 'id': oid,
                     'error': error, 'route': active, 'flags': flags}
            admin.validate_observation(value)
            return value
        finally:
            os.close(fd)

    def load_controller(self):
        admin.run(('/usr/sbin/modprobe', 'rp1_route_controller'))

    def unload_controller(self):
        admin.run(('/usr/sbin/rmmod', 'rp1_route_controller'))

    def start_socket(self):
        # Source-development installs do not run the Debian postinst that
        # normally creates this persistent service group. Provision it only
        # within approved activation, never during inspection or planning.
        try:
            grp.getgrnam(SOCKET_GROUP)
        except KeyError:
            admin.run(('/usr/sbin/addgroup', '--system', SOCKET_GROUP))
            try:
                grp.getgrnam(SOCKET_GROUP)
            except KeyError as error:
                raise ValueError('route-manager service group was not created') from error
        admin.run(('/usr/bin/systemctl', 'start', SOCKET_UNIT))

    def stop_socket(self):
        admin.run(('/usr/bin/systemctl', 'stop', SOCKET_UNIT))

    def manager_query(self):
        return client.exchange({'schemaVersion': 3, 'operation': 'query'})

    def restore_application(self, record):
        return application.neutral_restore(record)

    def inhibit_application(self):
        application.neutral_inhibit()

    def capture_application(self):
        return application.neutral_capture()


def observe(system):
    raw, binding = system.binding()
    deployment_raw, deployed = system.last_deployment(raw)
    activation = system.read_record(JOURNAL)
    if activation is not None:
        validate_journal(activation)
    controller = system.module('rp1_route_controller', binding['controllerNoteSha256'])
    consumer = system.module('rp1_gpclk_dkms', binding['consumerNoteSha256'])
    controller_endpoint = system.endpoint('/dev/rp1-route-admin',
        '/sys/class/misc/rp1-route-admin/dev')
    consumer_endpoint = system.endpoint('/dev/rp1-gpclk',
        '/sys/class/misc/rp1-gpclk/dev')
    socket_service = system.service(SOCKET_UNIT)
    manager_service = system.service(SERVICE_UNIT)
    application_service = system.service(APPLICATION_UNIT)
    manager_socket = system.manager_socket()
    controller_state = system.controller_state() if controller['status'] == 'loaded' else None
    transactions = {}
    for name in ('deployment-pending.json', 'transaction.json', 'manager.json',
                 'application.json'):
        value = system.read_record(admin.STATE / name)
        transactions[name] = value
    return {'bindingSha256': admin.digest(raw),
        'artifactSetSha256': binding['artifactSetSha256'], 'bootId': system.boot(),
        'lastDeploymentSha256': admin.digest(deployment_raw),
        'application': deployed['application'], 'activationJournal': activation,
        'controller': controller, 'consumer': consumer,
        'controllerEndpoint': controller_endpoint, 'consumerEndpoint': consumer_endpoint,
        'controllerState': controller_state, 'socket': socket_service,
        'managerSocket': manager_socket, 'managerService': manager_service,
        'applicationService': application_service,
        'transactions': transactions, 'inhibited': system.inhibitor()}


def application_matches(capture, observed):
    masked = observed.get('load') == 'masked' or observed.get('enabled') in (
        'masked', 'masked-runtime')
    if masked != capture['administratorMasked']:
        return False
    return (observed.get('active') == 'active' if capture['wasActive'] else
            observed.get('active') in ('inactive', 'failed'))


def restored_application_matches(journal, observed):
    if not application_matches(journal['plan']['application'], observed):
        return False
    outcome = journal.get('application')
    service = outcome.get('service') if isinstance(outcome, dict) else None
    if not isinstance(service, dict):
        return False
    if journal['plan']['application']['wasActive']:
        return observed.get('MainPID') == service.get('MainPID') != '0'
    return observed.get('MainPID') == '0'


def completed_journal_matches_installation(journal, observed):
    """Require complete prior-boot evidence before it may be superseded."""
    if journal['phase'] != 'complete-neutral':
        return False
    plan = journal['plan']
    if (plan['bindingSha256'] != observed['bindingSha256'] or
            plan['artifactSetSha256'] != observed['artifactSetSha256'] or
            plan['lastDeploymentSha256'] != observed['lastDeploymentSha256'] or
            plan['bootId'] == observed['bootId']):
        return False
    controller = journal.get('controller')
    manager = journal.get('manager')
    outcome = journal.get('application')
    capture = plan['application']
    manager_state = manager.get('state') if isinstance(manager, dict) else None
    outcome_service = outcome.get('service') if isinstance(outcome, dict) else None
    expected_phase = ('restored' if capture['wasActive'] else
        'administrator-masked' if capture['administratorMasked'] else 'stopped')
    if not isinstance(outcome_service, dict):
        return False
    historical_capture = dict(capture)
    historical_capture['service'] = outcome_service
    try:
        application.validate_neutral_capture(historical_capture)
    except (ValueError, TypeError, KeyError):
        return False
    return bool(isinstance(controller, dict) and
        not any(controller[name] for name in
            ('generation', 'id', 'error', 'route', 'flags')) and
        isinstance(manager, dict) and manager.get('status') == 'ok' and
        isinstance(manager_state, dict) and manager_state.get('activeRoute') is None and
        manager_state.get('controller') == controller and
        manager_state.get('bindingSha256') == observed['bindingSha256'] and
        isinstance(outcome, dict) and outcome.get('phase') == expected_phase and
        isinstance(outcome.get('companion'), dict) and
        outcome['companion'].get('transmit') is False)


def post_reboot_reactivation_state(observed):
    """Return whether exact inactive state may start a new boot transaction."""
    journal = observed['activationJournal']
    if journal is None or journal['phase'] != 'complete-neutral':
        return False
    if not completed_journal_matches_installation(journal, observed):
        raise ValueError('neutral activation evidence differs; explicit recovery or investigation required')
    if (observed['controller']['status'] != 'absent' or
            observed['consumer']['status'] != 'absent' or
            observed['controllerEndpoint']['status'] != 'absent' or
            observed['consumerEndpoint']['status'] != 'absent' or
            observed['socket'].get('active') != 'inactive' or
            observed['managerSocket'].get('status') != 'absent' or
            observed['transactions'].get('deployment-pending.json') is not None):
        raise ValueError('prior-boot neutral activation did not reach an inactive current boot')
    validate_reboot_evidence(reboot_evidence(observed), observed['bindingSha256'])
    if observed['inhibited']:
        if observed['applicationService'].get('active') not in ('inactive', 'failed'):
            raise ValueError('post-reboot inhibition did not stop the application')
    return True


def reboot_evidence(observed, idle=None):
    journal = observed['activationJournal']
    return {'bootId': journal['plan']['bootId'], 'controller': journal['controller'],
        'transactions': {name: observed['transactions'].get(name)
                         for name in RETIREMENT_TRANSACTIONS},
        'idleSha256': idle}


def validate_reboot_evidence(evidence, binding):
    """Full terminal ancestry only; migration's partial suffix is not admission."""
    if (not isinstance(evidence, dict) or set(evidence) !=
            {'bootId', 'controller', 'transactions', 'idleSha256'} or
            not isinstance(evidence['transactions'], dict) or
            set(evidence['transactions']) != set(RETIREMENT_TRANSACTIONS) or
            (evidence['idleSha256'] is not None and
             (not isinstance(evidence['idleSha256'], str) or
              not re.fullmatch('[0-9a-f]{64}', evidence['idleSha256'])))):
        raise ValueError('invalid reboot evidence')
    uuid.UUID(evidence['bootId'])
    origin = evidence['controller']
    admin.validate_observation(origin)
    if any(origin[name] for name in ('generation', 'id', 'error', 'route', 'flags')):
        raise ValueError('reboot ancestry lacks its neutral origin')
    tx = evidence['transactions']
    if all(value is None for value in tx.values()):
        if evidence['idleSha256'] is not None:
            raise ValueError('neutral reboot has an unowned idle override')
        return
    if any(value is None for value in tx.values()):
        raise ValueError('reboot requires a complete terminal journal chain')
    route, manager, app = (tx[name] for name in
                          ('transaction.json', 'manager.json', 'application.json'))
    boot = evidence['bootId']
    _validate_prior_route_transaction(route, boot, binding)
    _validate_prior_manager(manager, route, boot, binding)
    application.validate_journal(app)
    state = route['observation']
    if state['session'] != origin['session'] or state['generation'] <= 0:
        raise ValueError('prior route does not descend from neutral origin')
    if route['phase'] == 'recovered-inhibited':
        application.validate_removal_capture(app, manager, route, state, boot, binding)
        if app['phase'] not in application.REMOVAL_TERMINAL:
            raise ValueError('prior removal did not finish restoration')
        return
    captured = manager['response']['state'].get('application')
    application.validate_journal(captured)
    mutable = {'phase', 'controller', 'ready', 'error', 'inhibitionError', 'routeError'}
    response_state = manager['response']['state']
    if (captured['phase'] != 'captured' or captured['controller'] is not None or
            captured['ready'] is not None or
            {key: value for key, value in captured.items() if key not in mutable} !=
            {key: value for key, value in app.items() if key not in mutable} or
            response_state.get('activeRoute') != app['route'] or
            response_state.get('outputEnabled') is not False or
            response_state.get('applicationInhibited') is not True or
            response_state.get('applicationRestoration') is not True):
        raise ValueError('prior restoration differs from captured route intent')
    expected = ('restored' if app['wasActive'] else
                'administrator-masked' if app['administratorMasked'] else 'stopped')
    # A later explicit start can acknowledge a stopped or formerly masked
    # route. acknowledge() keeps the immutable original service capture.
    # The terminal readiness record proves completion, never current intent.
    restored = app['phase'] == 'restored' and app['ready'] is not None
    if ((app['phase'] != expected and not restored) or app.get('operation', 'switch') != 'switch' or
            app['wasActive'] and app['administratorMasked'] or
            (app['ready'] is not None) != (app['phase'] == 'restored') or
            app['controller'] != state or app['boot'] != boot or
            app['binding'] != binding or app['route'] != {1: 'gpio4', 2: 'gpio20'}[route['target']] or
            app['requestId'] != manager['requestId'] or
            app['fingerprint'] != manager['fingerprint']):
        raise ValueError('prior application is not an exact terminal route restoration')


def reboot_preparation_state(observed):
    """Validate an interrupted, journaled retirement without claiming live ownership."""
    journal = observed['activationJournal']
    if journal is None or journal['phase'] != 'reboot-prepare':
        return False
    plan = journal['plan']
    if (plan['version'] != 3 or any(journal[name] is not None
            for name in ('controller', 'manager', 'application', 'error')) or
            any(plan[name] != observed[name] for name in
                ('bindingSha256', 'artifactSetSha256', 'lastDeploymentSha256', 'bootId')) or
            any(observed[name]['status'] != 'absent' for name in
                ('controller', 'consumer', 'controllerEndpoint', 'consumerEndpoint')) or
            observed['socket'].get('active') != 'inactive' or
            observed['socket'].get('load') != 'loaded' or
            observed['socket'].get('fragment') != '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket' or
            observed['managerService'].get('load') != 'loaded' or
            observed['managerService'].get('fragment') != '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service' or
            observed['managerSocket']['status'] != 'absent' or
            observed['transactions'].get('deployment-pending.json') is not None):
        raise ValueError('reboot preparation differs from exact inactive state')
    expected = plan['rebootEvidence']['transactions']
    remaining = False
    for name in RETIREMENT_TRANSACTIONS:
        actual = observed['transactions'][name]
        if actual is not None:
            remaining = True
            if actual != expected[name]:
                raise ValueError('reboot transaction changed during retirement')
        elif expected[name] is not None and (remaining or not observed['inhibited']):
            raise ValueError('reboot retirement order or inhibition is inconsistent')
    return True


def revalidate_reboot_preparation(system, expected=None):
    observed = observe(system)
    if not reboot_preparation_state(observed):
        raise ValueError('reboot preparation checkpoint is absent')
    record = observed['activationJournal']
    if expected is not None and record != expected:
        raise ValueError('reboot preparation changed from exact inactive state')
    plan = record['plan']
    capture = system.capture_application()
    application.validate_neutral_capture(capture)
    if (capture['administratorMasked'] != plan['application']['administratorMasked'] or
            capture['companion'] != plan['application']['companion'] or
            ((not observed['inhibited'] or capture['wasActive']) and
             capture != plan['application']) or
            (observed['inhibited'] and capture['wasActive'] and
             not plan['application']['wasActive'])):
        raise ValueError('current application intent changed during reboot preparation')
    evidence = plan['rebootEvidence']
    idle = system.retirement_idle(evidence['transactions']['application.json'])
    if idle != evidence['idleSha256'] and not (idle is None and observed['inhibited']):
        raise ValueError('reboot idle override changed during retirement')
    return plan, observed


def _validate_prior_route_transaction(value, boot, binding):
    required = {'version', 'boot', 'session', 'binding', 'request', 'target',
                'phase', 'observation'}
    if (not isinstance(value, dict) or set(value) != required or
            type(value.get('version')) is not int or value['version'] != 1 or
            value.get('boot') != boot or value.get('binding') != binding or
            type(value.get('session')) is not int or
            type(value.get('target')) is not int or value.get('target') not in (1, 2) or
            value.get('phase') not in ('complete-inhibited', 'recovered-inhibited')):
        raise ValueError('prior route transaction is not attributable and terminal')
    if not isinstance(value.get('request'), str):
        raise ValueError('prior route transaction request identity is invalid')
    uuid.UUID(value['request'])
    admin.validate_observation(value['observation'])
    observation = value['observation']
    complete = value['phase'] == 'complete-inhibited'
    if (observation['session'] != value['session'] or
            observation['error'] != 0 or
            (complete and (observation['route'] != value['target'] or
                           observation['id'] <= 0 or
                           observation['flags'] != admin.CONSUMER | admin.PINNED)) or
            (not complete and (observation['route'] != 0 or
                               observation['id'] != 0 or
                               observation['flags'] != 0))):
        raise ValueError('prior route transaction observation is inconsistent')


def _validate_prior_manager(value, route, boot, binding):
    required = {'requestId', 'actor', 'fingerprint', 'complete', 'controller',
                'boot', 'binding', 'response'}
    if (not isinstance(value, dict) or set(value) != required or
            value.get('boot') != boot or value.get('binding') != binding or
            value.get('complete') is not True or
            not isinstance(value.get('requestId'), str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{7,63}', value['requestId']) or
            not isinstance(value.get('actor'), str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:@/-]{1,127}', value['actor']) or
            not isinstance(value.get('fingerprint'), str) or
            not re.fullmatch('[0-9a-f]{64}', value['fingerprint'])):
        raise ValueError('prior manager transaction is not attributable and complete')
    admin.validate_observation(value['controller'])
    if value['controller'] != route['observation']:
        raise ValueError('prior manager controller differs from route transaction')
    response = value['response']
    if not isinstance(response, dict) or not isinstance(response.get('state'), dict):
        raise ValueError('prior manager response schema')
    state = response['state']
    expected_status = ({'recovered-inhibited', 'complete-inhibited'}
                       if route['phase'] == 'recovered-inhibited'
                       else {'complete-inhibited'})
    if (response.get('schemaVersion') != 3 or
            response.get('contract') != 'rp1-gpclk-route-manager-runtime' or
            response.get('operation') != ('switch' if route['phase'] ==
                'complete-inhibited' else 'recover') or
            response.get('status') not in expected_status or
            state.get('bootId') != boot or state.get('bindingSha256') != binding or
            state.get('controller') != value['controller'] or
            state.get('pendingTransaction') != route):
        raise ValueError('prior manager response is inconsistent')


def _prior_boot_retirement_transactions(observed):
    transactions = observed['transactions']
    if transactions.get('deployment-pending.json') is not None:
        raise ValueError('pending deployment cannot be retired as route evidence')
    journal = observed['activationJournal']
    prior_boot = journal['plan']['bootId']
    binding = observed['bindingSha256']
    route = transactions.get('transaction.json')
    manager = transactions.get('manager.json')
    application_record = transactions.get('application.json')
    if route is not None:
        _validate_prior_route_transaction(route, prior_boot, binding)
    if manager is not None:
        if route is None:
            raise ValueError('prior manager transaction lacks its route journal')
        _validate_prior_manager(manager, route, prior_boot, binding)
    if application_record is not None:
        if route is None or application.validate_journal(application_record) != application_record:
            raise ValueError('prior application transaction lacks its route journal')
        expected_route = {1: 'gpio4', 2: 'gpio20'}[route['target']]
        if (application_record.get('boot') != prior_boot or
                application_record.get('binding') != binding or
                application_record.get('route') != expected_route or
                application_record.get('controller') not in (None, route['observation']) or
                (manager is not None and
                 (application_record.get('requestId') != manager['requestId'] or
                  application_record.get('fingerprint') != manager['fingerprint']))):
            raise ValueError('prior application transaction is inconsistent')
    return {name: transactions.get(name) for name in RETIREMENT_TRANSACTIONS}


def post_reboot_retirement_state(observed):
    """Validate exact inactive state and attributable prior-boot journals."""
    journal = observed['activationJournal']
    if journal is None or journal['phase'] != 'complete-neutral':
        return None
    if not completed_journal_matches_installation(journal, observed):
        raise ValueError('neutral activation evidence differs; preserve and investigate')
    if journal['plan']['bootId'] == observed['bootId']:
        raise ValueError('same-boot terminal activation cannot be retired')
    if (observed['controller']['status'] != 'absent' or
            observed['consumer']['status'] != 'absent' or
            observed['controllerEndpoint']['status'] != 'absent' or
            observed['consumerEndpoint']['status'] != 'absent' or
            observed['socket'].get('active') == 'active' or
            observed['managerSocket'].get('status') != 'absent'):
        raise ValueError('prior-boot retirement requires an inactive current boot')
    if (observed['inhibited'] and
            observed['applicationService'].get('active') not in ('inactive', 'failed')):
        raise ValueError('post-reboot inhibition did not stop the application')
    return _prior_boot_retirement_transactions(observed)


def retirement_plan(system):
    """Bind retirement of exact terminal activation evidence from an older boot."""
    observed = observe(system)
    transactions = post_reboot_retirement_state(observed)
    if transactions is None:
        raise ValueError('no prior-boot terminal activation evidence to retire')
    journal = observed['activationJournal']
    return {'version': 2, 'operation': 'retire-post-reboot-activation',
        'bindingSha256': observed['bindingSha256'],
        'artifactSetSha256': observed['artifactSetSha256'],
        'bootId': observed['bootId'],
        'lastDeploymentSha256': observed['lastDeploymentSha256'],
        'activationJournalSha256': admin.digest(canonical(journal)),
        'applicationIdleSha256': system.retirement_idle(
            transactions['application.json']),
        'transactionJournalSha256': {name: (None if value is None else
            admin.digest(canonical(value))) for name, value in transactions.items()}}


def retire(system, reviewed, approved, lock=deployment.mutation_lock):
    required = {'version', 'operation', 'bindingSha256', 'artifactSetSha256',
        'bootId', 'lastDeploymentSha256', 'activationJournalSha256',
        'applicationIdleSha256', 'transactionJournalSha256'}
    if (not isinstance(reviewed, dict) or set(reviewed) != required or
            reviewed.get('version') != 2 or
            reviewed.get('operation') != 'retire-post-reboot-activation' or
            (reviewed.get('applicationIdleSha256') is not None and
             (not isinstance(reviewed['applicationIdleSha256'], str) or
              not re.fullmatch('[0-9a-f]{64}', reviewed['applicationIdleSha256']))) or
            not isinstance(reviewed.get('transactionJournalSha256'), dict) or
            set(reviewed['transactionJournalSha256']) != set(RETIREMENT_TRANSACTIONS) or
            any(value is not None and
                (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value))
                for value in reviewed['transactionJournalSha256'].values()) or
            plan_digest(reviewed) != approved):
        raise ValueError('reviewed post-reboot activation retirement required')
    with lock():
        current = retirement_plan(system)
        if current != reviewed:
            raise ValueError('post-reboot activation retirement changed since review')
        journal = system.read_record(JOURNAL)
        transactions = {name: system.read_record(admin.STATE / name)
                        for name in RETIREMENT_TRANSACTIONS}
        idle = system.retirement_idle(transactions['application.json'])
        if (journal is None or admin.digest(canonical(journal)) !=
                reviewed['activationJournalSha256'] or
                idle != reviewed['applicationIdleSha256'] or
                any((None if value is None else admin.digest(canonical(value))) !=
                    reviewed['transactionJournalSha256'][name]
                    for name, value in transactions.items())):
            raise ValueError('post-reboot journals changed after retirement review')
        system.retire_transactions(transactions)
        system.retire_journal(journal)
    return {'status': 'retired-post-reboot-activation',
        'activationJournalSha256': reviewed['activationJournalSha256']}


def neutral_ready(observation, *, current_service=False):
    # Activation completion verifies the captured service intent strictly.
    # Later passive readiness must allow an administrator/installer to start,
    # stop or restart that application without invalidating neutral hardware.
    service = observation.get('applicationService', {})
    stable_service = (
        service.get('fragment') in ('/etc/systemd/system/wsprrypi.service',
                                    '/usr/lib/systemd/system/wsprrypi.service') and
        ((service.get('load') == 'loaded' and service.get('active') == 'active' and
          service.get('enabled') not in ('masked', 'masked-runtime') and
          isinstance(service.get('MainPID'), str) and service['MainPID'].isdigit() and
          int(service['MainPID']) > 0) or
         (service.get('load') in ('loaded', 'masked') and
          service.get('active') in ('inactive', 'failed') and service.get('MainPID') == '0')))
    stable_service = stable_service or (
        service.get('fragment') == '/dev/null' and service.get('load') == 'masked' and
        service.get('enabled') in ('masked', 'masked-runtime') and
        service.get('active') in ('inactive', 'failed') and service.get('MainPID') == '0')
    journal = observation['activationJournal']
    return bool(journal and journal['phase'] == 'complete-neutral' and
        journal['plan']['bindingSha256'] == observation['bindingSha256'] and
        journal['plan']['artifactSetSha256'] == observation['artifactSetSha256'] and
        journal['plan']['bootId'] == observation['bootId'] and
        observation['controller'].get('status') == 'loaded' and
        observation['controller'].get('exact') is True and
        isinstance(observation['controller'].get('buildNoteSha256'), str) and
        observation['consumer']['status'] == 'absent' and
        observation['controllerEndpoint'].get('status') == 'owned' and
        observation['controllerEndpoint'].get('open') is False and
        observation['consumerEndpoint'].get('status') == 'absent' and
        observation['controllerState'] and
        journal.get('controller') == observation['controllerState'] and
        not any(observation['controllerState'][name] for name in
                ('generation', 'id', 'error', 'route', 'flags')) and
        observation['socket'].get('active') == 'active' and
        observation['managerSocket'].get('status') == 'owned' and
        observation['socket'].get('fragment') ==
            '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket' and
        observation['managerService'].get('load') == 'loaded' and
        observation['managerService'].get('fragment') ==
            '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service' and
        not observation['inhibited'] and
        (stable_service if current_service else
         restored_application_matches(journal, observation['applicationService'])) and
        isinstance(journal.get('application'), dict) and
        journal['application'].get('phase') in application.TERMINAL)


def activation_plan(system):
    observed = observe(system)
    if reboot_preparation_state(observed):
        return revalidate_reboot_preparation(system)[0]
    already = neutral_ready(observed)
    journal = observed['activationJournal']
    post_reboot = False
    if journal is not None and not already and journal['phase'] != 'recovered-inhibited':
        post_reboot = post_reboot_reactivation_state(observed)
        if not post_reboot:
            raise ValueError('neutral activation journal requires explicit recovery')
    if not post_reboot and any(value is not None for value in observed['transactions'].values()):
        raise ValueError('deployment, route, manager, or application transaction is pending')
    if observed['consumer']['status'] != 'absent' or observed['consumerEndpoint']['status'] != 'absent':
        raise ValueError('transmission consumer must remain absent')
    if observed['controller']['status'] == 'loaded' and not already:
        raise ValueError('loaded controller has no completed activation ownership')
    if observed['controller']['status'] not in ('absent', 'loaded') or not observed['controller'].get('exact', True):
        raise ValueError('controller identity conflict')
    if observed['controllerEndpoint'].get('open') not in (False, None):
        raise ValueError('controller endpoint is open or unknown')
    if observed['consumerEndpoint'].get('open') not in (False, None):
        raise ValueError('consumer endpoint is open or unknown')
    if (observed['socket'].get('load') != 'loaded' or
            observed['socket'].get('fragment') !=
                '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket' or
            observed['managerService'].get('load') != 'loaded' or
            observed['managerService'].get('fragment') !=
                '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service'):
        raise ValueError('systemd runtime unit identity conflict')
    if observed['managerSocket'].get('status') == 'unsafe' or (
            observed['socket'].get('active') == 'active' and
            observed['managerSocket'].get('status') != 'owned') or (
            observed['socket'].get('active') != 'active' and
            observed['managerSocket'].get('status') != 'absent'):
        raise ValueError('manager socket identity conflict')
    if not already and not post_reboot and not observed['inhibited']:
        raise ValueError('reviewed deployment inhibition is absent')
    if (not already and not post_reboot and
            observed['applicationService'].get('active') not in ('inactive', 'failed')):
        raise ValueError('application is not stopped behind deployment inhibition')
    if already:
        context = 'idempotent'
    elif post_reboot:
        context = 'post-reboot'
    elif journal is not None:
        context = 'recovered'
    else:
        context = 'initial'
    activation_application = observed['application'] if journal is None else journal['plan']['application']
    if post_reboot:
        # Historical service/transmission intent never authorizes this boot.
        activation_application = system.capture_application()
        application.validate_neutral_capture(activation_application)
    result = {'version': 3 if post_reboot else 2, 'operation': 'neutral-activation',
        'bindingSha256': observed['bindingSha256'],
        'artifactSetSha256': observed['artifactSetSha256'],
        'bootId': observed['bootId'],
        'lastDeploymentSha256': observed['lastDeploymentSha256'],
        'application': activation_application,
        'socketWasActive': observed['socket'].get('active') == 'active',
        'alreadyReady': already,
        'activationContext': context,
        'applicationInhibited': observed['inhibited'],
        'previousActivationSha256': (admin.digest(canonical(journal))
                                     if journal is not None else None)}

    if post_reboot:
        result['rebootEvidence'] = reboot_evidence(observed, system.retirement_idle(
            observed['transactions'].get('application.json')))
    validate_plan(result)
    return result


def _save(system, record, phase, **values):
    record.update(phase=phase, **values)
    system.write_journal(record)


def ensure(system, reviewed, approved, lock=deployment.mutation_lock):
    validate_plan(reviewed)
    if plan_digest(reviewed) != approved:
        raise ValueError('reviewed neutral activation plan digest required')
    record = None
    try:
        with lock():
            current = activation_plan(system)
            if current != reviewed:
                raise ValueError('neutral activation plan changed since review')
            if current['alreadyReady']:
                return {'status': 'idempotent-no-change', 'journal': system.read_record(JOURNAL)}
            previous = system.read_record(JOURNAL)
            if current['activationContext'] == 'post-reboot':
                if previous['phase'] == 'reboot-prepare':
                    preparation = previous
                else:
                    if admin.digest(canonical(previous)) != current['previousActivationSha256']:
                        raise ValueError('prior activation changed before archival')
                    system.archive_journal(previous)
                    if activation_plan(system) != current:
                        raise ValueError('reboot state changed during archival')
                    preparation = {'version': 1, 'plan': current, 'planSha256': approved,
                        'requestId': str(uuid.uuid4()), 'phase': 'reboot-prepare',
                        'controller': None, 'manager': None, 'application': None, 'error': None}
                    # Persist current intent and all prior journals before the first effect.
                    system.write_journal(preparation)
                revalidate_reboot_preparation(system, preparation)
                system.inhibit_application()
                unused, observed = revalidate_reboot_preparation(system, preparation)
                if not observed['inhibited'] or observed['applicationService']['active'] not in ('inactive', 'failed'):
                    raise ValueError('reboot inhibition did not establish exact inactive state')
                system.retire_transactions({name: observed['transactions'][name]
                                            for name in RETIREMENT_TRANSACTIONS})
                revalidate_reboot_preparation(system, preparation)
                record = dict(preparation)
                _save(system, record, 'activation-intent')
            else:
                if previous is not None:
                    if previous['phase'] != 'recovered-inhibited':
                        raise ValueError('activation journal is not restartable')
                    system.archive_journal(previous)
                record = {'version': 1, 'plan': current, 'planSha256': approved,
                    'requestId': str(uuid.uuid4()), 'phase': 'activation-intent',
                    'controller': None, 'manager': None, 'application': None, 'error': None}
                system.write_journal(record)
            _save(system, record, 'controller-load-intent')
            system.load_controller()
            observed = observe(system)
            state = observed['controllerState']
            if (observed['controller'].get('exact') is not True or
                    observed['consumer']['status'] != 'absent' or
                    observed['consumerEndpoint']['status'] != 'absent' or
                    not state or any(state[name] for name in ('generation', 'id', 'error', 'route', 'flags')) or
                    (current.get('rebootEvidence') is not None and
                     state['session'] == current['rebootEvidence']['controller']['session'])):
                raise ValueError('controller did not establish exact neutral state')
            _save(system, record, 'socket-start-intent', controller=state)
            if not current['socketWasActive']:
                system.start_socket()
            observed = observe(system)
            if (observed['socket'].get('active') != 'active' or
                    observed['managerSocket'].get('status') != 'owned' or
                    observed['socket'].get('fragment') !=
                        '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket' or
                    observed['managerService'].get('load') != 'loaded' or
                    observed['managerService'].get('fragment') !=
                        '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service'):
                raise ValueError('exact manager socket/service infrastructure is unavailable')
            _save(system, record, 'manager-query-intent')
        reply = system.manager_query()
        state = reply.get('state', {}) if isinstance(reply, dict) else {}
        if (reply.get('status') != 'ok' or state.get('activeRoute') is not None or
                state.get('controller') != record['controller'] or
                state.get('bindingSha256') != reviewed['bindingSha256']):
            raise ValueError('manager did not confirm exact neutral controller state')
        with lock():
            current_record = system.read_record(JOURNAL)
            validate_journal(current_record)
            if current_record['requestId'] != record['requestId'] or current_record['phase'] != 'manager-query-intent':
                raise ValueError('activation journal changed during manager query')
            observed = observe(system)
            if (observed['bindingSha256'] != reviewed['bindingSha256'] or
                    observed['artifactSetSha256'] != reviewed['artifactSetSha256'] or
                    observed['lastDeploymentSha256'] != reviewed['lastDeploymentSha256'] or
                    observed['bootId'] != reviewed['bootId'] or
                    observed['controllerState'] != record['controller'] or
                    observed['consumer']['status'] != 'absent' or
                    observed['consumerEndpoint']['status'] != 'absent' or
                    observed['socket'].get('active') != 'active' or
                    observed['managerSocket'].get('status') != 'owned'):
                raise ValueError('activation identity changed before application restoration')
            _save(system, record, 'application-restore-intent', manager=reply)
            outcome = system.restore_application(reviewed['application'])
            observed = observe(system)
            if (observed['consumer']['status'] != 'absent' or
                    observed['consumerEndpoint']['status'] != 'absent' or
                    observed['controllerState'] != record['controller'] or observed['inhibited'] or
                    not application_matches(reviewed['application'],
                                            observed['applicationService'])):
                raise ValueError('neutral state changed during application restoration')
            _save(system, record, 'complete-neutral', application=outcome)
            return {'status': 'activated-neutral', 'journal': record}
    except BaseException as error:
        if record is not None:
            try:
                with lock():
                    retained = validate_journal(system.read_record(JOURNAL))
                    if (retained['requestId'] != record['requestId'] or
                            retained['plan'] != record['plan']):
                        raise ValueError('activation ownership changed; retain competing evidence')
                    try:
                        system.inhibit_application()
                    except BaseException as inhibition_error:
                        error = ValueError(str(error) + '; inhibition failure: ' + str(inhibition_error))
                    _save(system, record, 'activation-failed', error=str(error))
            except BaseException:
                pass
        raise


def _validate_same_boot_recovered_route(transactions, controller, boot, binding):
    """Validate a complete or interruption-safe suffix of recovered route journals."""
    route = transactions.get('transaction.json')
    manager = transactions.get('manager.json')
    application_record = transactions.get('application.json')
    if route is None:
        if manager is not None or application_record is not None:
            raise ValueError('recovered route journal retirement order is inconsistent')
        return None
    _validate_prior_route_transaction(route, boot, binding)
    if route['phase'] != 'recovered-inhibited' or route['observation'] != controller:
        raise ValueError('route recovery does not match the neutral controller')
    if manager is not None:
        _validate_prior_manager(manager, route, boot, binding)
    if application_record is not None:
        if manager is None:
            raise ValueError('recovered application journal lacks its manager journal')
        application.validate_journal(application_record)
        predecessor = application_record.get('controller')
        target = {1: 'gpio4', 2: 'gpio20'}[route['target']]
        if (application_record.get('boot') != boot or
                application_record.get('binding') != binding or
                application_record.get('route') != target):
            raise ValueError('application route recovery is inconsistent')
        if application_record.get('phase') == 'route-recovered':
            if not isinstance(predecessor, dict):
                raise ValueError('application route recovery lacks its predecessor')
            admin.validate_observation(predecessor)
            if (predecessor['session'] != controller['session'] or
                    predecessor['generation'] + 1 != controller['generation'] or
                    predecessor['error'] != 0 or predecessor['id'] <= 0 or
                    predecessor['route'] != route['target'] or
                    predecessor['flags'] != admin.CONSUMER | admin.PINNED):
                raise ValueError('application predecessor does not lead to recovered controller')
        elif application_record.get('phase') in application.REMOVAL_TERMINAL:
            application.validate_removal_capture(application_record, manager,
                                                  route, controller, boot, binding)
        else:
            raise ValueError('application route recovery is not terminal')
    return {name: transactions.get(name) for name in RETIREMENT_TRANSACTIONS}


def routed_from_current_neutral(observed):
    """Validate a current-boot neutral activation as ancestry of an active route."""
    journal = observed['activationJournal']
    if journal is None or journal.get('phase') != 'complete-neutral':
        return False
    validate_journal(journal)
    plan = journal['plan']
    if (plan['bootId'] != observed['bootId'] or
            plan['bindingSha256'] != observed['bindingSha256'] or
            plan['artifactSetSha256'] != observed['artifactSetSha256'] or
            plan['lastDeploymentSha256'] != observed['lastDeploymentSha256']):
        raise ValueError('neutral activation ancestry differs from the installation')
    origin = journal.get('controller')
    controller = observed.get('controllerState')
    if not isinstance(origin, dict) or not isinstance(controller, dict):
        raise ValueError('neutral activation ancestry lacks controller identity')
    admin.validate_observation(origin)
    admin.validate_observation(controller)
    if (any(origin[name] for name in ('generation', 'id', 'error', 'route', 'flags')) or
            controller['session'] != origin['session'] or
            controller['generation'] <= origin['generation'] or
            controller['id'] <= 0 or controller['error'] != 0 or
            controller['route'] not in (1, 2) or
            controller['flags'] != admin.CONSUMER | admin.PINNED):
        raise ValueError('active controller does not descend from neutral activation')
    transactions = observed['transactions']
    if transactions.get('deployment-pending.json') is not None:
        raise ValueError('pending deployment blocks neutral route ancestry')
    route = transactions.get('transaction.json')
    manager = transactions.get('manager.json')
    application_record = transactions.get('application.json')
    if route is None or manager is None or application_record is None:
        raise ValueError('neutral route ancestry lacks its completed journal chain')
    _validate_prior_route_transaction(
        route, observed['bootId'], observed['bindingSha256'])
    if (route['phase'] != 'complete-inhibited' or
            route['observation'] != controller or
            route['target'] != controller['route']):
        raise ValueError('active route transaction differs from its controller')
    _validate_prior_manager(manager, route, observed['bootId'],
                            observed['bindingSha256'])
    application.validate_journal(application_record)
    expected_route = {1: 'gpio4', 2: 'gpio20'}[controller['route']]
    if (application_record.get('phase') not in application.TERMINAL or
            application_record.get('boot') != observed['bootId'] or
            application_record.get('binding') != observed['bindingSha256'] or
            application_record.get('route') != expected_route or
            application_record.get('controller') != controller or
            application_record.get('requestId') != manager['requestId'] or
            application_record.get('fingerprint') != manager['fingerprint']):
        raise ValueError('active application route ancestry is inconsistent')
    return True


def _same_boot_route_recovery(observed):
    """Return exact journals that attribute a nonzero neutral generation."""
    controller = observed['controllerState']
    if controller is None or controller['generation'] == 0:
        return None
    admin.validate_observation(controller)
    if any(controller[name] for name in ('id', 'error', 'route', 'flags')):
        return None
    transactions = observed['transactions']
    if transactions.get('deployment-pending.json') is not None:
        raise ValueError('pending deployment blocks route recovery attribution')
    if transactions.get('manager.json') is None:
        return None
    return _validate_same_boot_recovered_route(
        transactions, controller, observed['bootId'], observed['bindingSha256'])


def recovered_route_retirement(system):
    """Return exact same-boot recovered journals in an inactive removal window."""
    observed = observe(system)
    transactions = observed['transactions']
    if transactions.get('deployment-pending.json') is not None:
        raise ValueError('pending deployment blocks recovered route retirement')
    if not any(transactions.get(name) is not None
               for name in RETIREMENT_TRANSACTIONS):
        return None
    route = transactions.get('transaction.json')
    if route is None:
        raise ValueError('recovered route transaction is absent')
    controller = route.get('observation') if isinstance(route, dict) else None
    if not isinstance(controller, dict):
        raise ValueError('recovered route observation is absent')
    admin.validate_observation(controller)
    if (controller['generation'] == 0 or
            any(controller[name] for name in ('id', 'error', 'route', 'flags'))):
        raise ValueError('recovered route observation is not neutral')
    if (observed['controller']['status'] != 'absent' or
            observed['consumer']['status'] != 'absent' or
            observed['controllerEndpoint']['status'] != 'absent' or
            observed['consumerEndpoint']['status'] != 'absent' or
            observed['socket'].get('active') == 'active' or
            observed['managerSocket'].get('status') != 'absent' or
            not observed['inhibited'] or
            observed['applicationService'].get('active') not in ('inactive', 'failed')):
        raise ValueError('recovered route retirement requires an inactive inhibited runtime')
    return _validate_same_boot_recovered_route(
        transactions, controller, observed['bootId'], observed['bindingSha256'])


def recovery_plan(system):
    observed = observe(system)
    journal = observed['activationJournal']
    if journal is None:
        raise ValueError('no neutral activation journal to recover')
    validate_journal(journal)
    if journal['plan']['bootId'] != observed['bootId']:
        raise ValueError('cross-boot neutral activation requires investigation')
    if (journal['plan']['bindingSha256'] != observed['bindingSha256'] or
            journal['plan']['artifactSetSha256'] != observed['artifactSetSha256'] or
            journal['plan']['lastDeploymentSha256'] != observed['lastDeploymentSha256']):
        raise ValueError('activation provenance changed; preserve for investigation')
    if (observed['controller']['status'] == 'loaded' and
            observed['controller'].get('exact') is not True):
        raise ValueError('foreign or mismatched controller blocks neutral recovery')
    controller = observed['controllerState']
    route_recovery = _same_boot_route_recovery(observed)
    if (controller and controller['generation'] != 0 and
            route_recovery is None):
        raise ValueError('nonzero neutral controller lacks exact route recovery evidence')
    return {'version': 2, 'operation': 'neutral-activation-recovery',
        'activationJournalSha256': admin.digest(canonical(journal)),
        'bindingSha256': observed['bindingSha256'], 'bootId': observed['bootId'],
        'controllerLoaded': observed['controller']['status'] == 'loaded',
        'controllerState': controller,
        'routeRecoverySha256': (None if route_recovery is None else {
            name: admin.digest(canonical(value)) if value is not None else None
            for name, value in route_recovery.items()}),
        'socketWasActive': journal['plan']['socketWasActive'],
        'alreadyRecovered': journal['phase'] == 'recovered-inhibited'}


def ensure_recovery(system, reviewed, approved, lock=deployment.mutation_lock):
    if plan_digest(reviewed) != approved:
        raise ValueError('reviewed neutral recovery plan digest required')
    with lock():
        if recovery_plan(system) != reviewed:
            raise ValueError('neutral recovery plan changed since review')
        if reviewed['alreadyRecovered']:
            return {'status': 'idempotent-no-change'}
        journal = system.read_record(JOURNAL)
        _save(system, journal, 'rollback-intent')
        try:
            system.inhibit_application()
            observed = observe(system)
            if observed['consumer']['status'] != 'absent' or observed['consumerEndpoint']['status'] != 'absent':
                raise ValueError('consumer state blocks neutral recovery')
            if observed['controller']['status'] == 'loaded':
                state = observed['controllerState']
                if (state != reviewed['controllerState'] or
                        any(state[name] for name in ('id', 'error', 'route', 'flags')) or
                        (state['generation'] != 0 and
                         recovery_plan(system)['routeRecoverySha256'] !=
                         reviewed['routeRecoverySha256'])):
                    raise ValueError('non-neutral controller blocks unload')
                system.unload_controller()
            if not reviewed['socketWasActive']:
                system.stop_socket()
            observed = observe(system)
            if (observed['controller']['status'] != 'absent' or
                    observed['controllerEndpoint']['status'] != 'absent' or
                    (not reviewed['socketWasActive'] and
                     (observed['socket'].get('active') == 'active' or
                      observed['managerSocket'].get('status') != 'absent')) or
                    (reviewed['socketWasActive'] and
                     (observed['socket'].get('active') != 'active' or
                      observed['managerSocket'].get('status') != 'owned' or
                      observed['socket'].get('fragment') !=
                        '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket' or
                      observed['managerService'].get('load') != 'loaded' or
                      observed['managerService'].get('fragment') !=
                        '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service'))):
                raise ValueError('controller remains after neutral recovery')
            _save(system, journal, 'recovered-inhibited', controller=None,
                  manager=None, application=None, error=None)
            return {'status': 'recovered-inhibited', 'journal': journal}
        except BaseException as error:
            _save(system, journal, 'rollback-failed', error=str(error))
            raise
