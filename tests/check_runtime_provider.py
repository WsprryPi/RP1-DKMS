#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hardware-free installer-facing readiness and ensure-contract tests."""
import sys as _identity_sys
from pathlib import Path as _IdentityPath
_identity_sys.path.insert(0, str(_IdentityPath(__file__).resolve().parents[1]/'scripts'))
from version_identity import VERSION, DEBIAN, COMPATIBILITY, expand
import copy
import ast
import hashlib
import json
import lzma
from pathlib import Path
import stat
import subprocess
import sys
sys.dont_write_bytecode = True
import unittest
from unittest.mock import patch
import contextlib
import io
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_binding as binding
import build_runtime_binding as build_binding
import build_runtime_bundle as bundle_builder
import build_runtime_controller as controller_builder
import runtime_provider as provider
from runtime_layout import INVENTORY, MODULES

KERNEL = '6.18.34+rpt-rpi-2712'


def exact_binding():
    value = {'schemaVersion': 1, 'contract': binding.CONTRACT,
        'productVersion': binding.PRODUCT_VERSION,
        'compatibilityIdentities': binding.COMPATIBILITY,
        'sourceCommit': 'a'*40, 'kernel': KERNEL,
        'files': {path: provider.admin.digest(path.encode()) for path in INVENTORY},
        'modules': {name: {'name': name,
            'path': f'/lib/modules/{KERNEL}/updates/dkms/{name}.ko.xz',
            'installedFileSha256': ('1' if name == 'rp1_route_controller' else '2')*64,
            'decompressedElfSha256': ('3' if name == 'rp1_route_controller' else '4')*64,
            'compression': 'xz', 'buildNoteSha256':
                ('c' if name == 'rp1_route_controller' else 'd')*64,
            'version': binding.PRODUCT_VERSION, 'kernel': KERNEL}
            for name in MODULES},
        'externalFiles': {name: 'b'*64 for name in binding.EXTERNAL_PATHS},
        'uapiSha256': {'consumer': provider.admin.digest(
            b'/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_gpclk.h'),
            'controller': provider.admin.digest(
            b'/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_route_admin.h')},
        'controllerNoteSha256': 'c'*64, 'consumerNoteSha256': 'd'*64}
    # Bind the declared UAPI hashes to the actual fixed inventory identities.
    value['uapiSha256']['consumer'] = value['files'][
        '/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_gpclk.h']
    value['uapiSha256']['controller'] = value['files'][
        '/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_route_admin.h']
    value['artifactSetSha256'] = binding.canonical_digest(value)
    return value


def controller(route=1, flags=6, error=0):
    return {'session': 1, 'generation': 2, 'id': 9 if route else 0,
            'error': error, 'route': route, 'flags': flags}


def manager_ready(route='gpio4'):
    number = {'gpio4': 1, 'gpio20': 2}[route]
    state = controller(number)
    transaction = {'version': 1, 'boot': 'boot', 'session': state['session'],
        'binding': 'e'*64, 'request': '00000000-0000-0000-0000-000000000001',
        'target': number, 'phase': 'complete-inhibited', 'observation': state}
    query = {'schemaVersion': 1, 'contract': 'rp1-gpclk-route-manager-runtime',
        'operation': 'query', 'status': 'ok', 'state': {'profile': 'runtime',
        'activeRoute': route, 'controller': state,
        'bootId': 'boot', 'bindingSha256': 'e'*64,
        'pendingTransaction': transaction,
        'application': {'phase': 'restored'}, 'applicationRestoration': True,
        'outputEnabled': False, 'qualification': False}}
    snapshot = {'route': number, 'compatibility': 3, 'operation': 0,
        'terminal': 0, 'fault': 1, 'owner': 1,
        'lease': 1, 'outputInhibited': 1, 'operationalReady': 2,
        'gpio': 2, 'clock': 2, 'dma': 2, 'stable': 2}
    idle = {'schemaVersion': 1, 'contract': 'rp1-gpclk-route-manager-runtime',
        'operation': 'idle', 'status': 'ok', 'state': {'outputLifecycle': {
        'ready': True, 'executionAuthorized': False,
        'productionAuthority': 'root-owned-endpoint',
        'route': route, 'controller': state, 'bootId': 'boot',
        'bindingSha256': 'e'*64, 'snapshot': snapshot}}}
    return {'status': 'observed', 'query': query, 'idle': idle}


class Host:
    def __init__(self, ready=True):
        self.value = exact_binding()
        self._binding = {'status': 'valid', 'sha256': 'e'*64, 'value': self.value}
        self._artifacts = {path: {'status': 'exact', 'expectedSha256': sha,
            'actualSha256': sha} for path, sha in
            {**self.value['files'], **self.value['externalFiles']}.items()}
        self._artifacts.update({record['path']: {'status': 'exact',
            'expectedSha256': record['installedFileSha256'],
            'actualSha256': record['installedFileSha256']}
            for record in self.value['modules'].values()})
        self._journals = {name: {'status': 'absent'} for name in
            ('deployment-pending.json', 'transaction.json', 'manager.json',
             'application.json', 'activation.json')}
        self._modules = {
            'rp1_route_controller': {'status': 'loaded', 'version': VERSION,
                'buildNoteSha256': self.value['controllerNoteSha256']},
            'rp1_gpclk_dkms': {'status': 'loaded', 'version': VERSION,
                'buildNoteSha256': self.value['consumerNoteSha256']}}
        self._modules['rp1_gpclk_dkms']['outputInhibited'] = False
        self._endpoints = {name: {'status': 'owned', 'open': False}
                           for name in ('/dev/rp1-gpclk', '/dev/rp1-route-admin')}
        self._socket = {'status': 'owned'}
        self._manager = manager_ready()
        self._activation = {'status': 'absent'}
        self.files = None
        self.removal = {'version': 1, 'files': {'/fixed': {
            'before': None, 'after': provider.deployment.encode(b'exact')}}}
        self.removed = False
        self.retirement = {'version': 1,
            'operation': 'retire-post-reboot-activation',
            'bindingSha256': 'a' * 64, 'artifactSetSha256': 'b' * 64,
            'bootId': '00000000-0000-0000-0000-000000000002',
            'lastDeploymentSha256': 'c' * 64,
            'activationJournalSha256': 'd' * 64,
            'applicationIdleSha256': None,
            'transactionJournalSha256': {
                name: None for name in provider.activation.RETIREMENT_TRANSACTIONS}}
        self.retired = False
        if not ready:
            self.make_absent()

    def make_absent(self):
        self._binding = {'status': 'absent'}
        self._artifacts = {}
        self._journals = {name: {'status': 'absent'} for name in self._journals}
        self._modules = {name: {'status': 'absent'} for name in self._modules}
        self._endpoints = {name: {'status': 'absent', 'open': False} for name in self._endpoints}
        self._socket = {'status': 'absent'}
        self._manager = {'status': 'absent'}

    def binding(self): return copy.deepcopy(self._binding)
    def artifacts(self, unused): return copy.deepcopy(self._artifacts)
    def journal(self, name): return copy.deepcopy(self._journals[name])
    def module(self, name): return copy.deepcopy(self._modules[name])
    def endpoint(self, path): return copy.deepcopy(self._endpoints[path])
    def socket(self): return copy.deepcopy(self._socket)
    def services(self): return {'rp1-gpclk-route-manager.socket': {
        'load': 'loaded', 'active': 'active', 'enabled': 'enabled',
        'fragment': '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'},
        'rp1-gpclk-route-manager@.service': {'load': 'loaded', 'active': 'inactive',
        'enabled': 'static',
        'fragment': '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service'},
        'wsprrypi.service': {'load': 'loaded', 'active': 'active',
        'enabled': 'enabled', 'fragment': '/etc/systemd/system/wsprrypi.service'}}
    def manager(self): return copy.deepcopy(self._manager)
    def activation_observation(self): return copy.deepcopy(self._activation)
    def deployment_plan(self, unused):
        return {'version': 1, 'files': {provider.deployment.BINDING: {
            'before': None, 'after': provider.deployment.encode(
                json.dumps(self.value).encode())}}}
    def expected_external(self, expected):
        values = dict(expected['externalFiles'])
        values.update({record['path']: record['installedFileSha256']
                       for record in expected['modules'].values()})
        return {path: {'status': 'exact', 'expectedSha256': sha,
            'actualSha256': sha} for path, sha in values.items()}
    def deployment_removal_plan(self): return copy.deepcopy(self.removal)
    def deployment_remove(self, value, approved):
        if value != self.removal or approved != provider.deployment.plan_hash(value):
            raise ValueError('removal identity')
        self.removed = True
        return {'status': 'removed-exact-deployment'}
    def activation_retirement_plan(self): return copy.deepcopy(self.retirement)
    def activation_retire(self, value, approved):
        if value != self.retirement or approved != provider.activation.plan_digest(value):
            raise ValueError('retirement identity')
        self.retired = True
        return {'status': 'retired-post-reboot-activation',
                'activationJournalSha256': value['activationJournalSha256']}


class Tests(unittest.TestCase):
    def inspect(self, host, **routes):
        return provider.inspect(host, **routes)[0]

    def test_exact_ready_and_absent_are_stable(self):
        exact = self.inspect(Host())
        self.assertEqual(exact['result'], 'exact_ready')
        self.assertTrue(exact['compatible'] and exact['eligible'])
        self.assertTrue(exact['safety']['operationalReady'])
        self.assertFalse(exact['safety']['outputInhibited'])
        self.assertFalse(exact['safety']['owner'])
        self.assertFalse(exact['safety']['lease'])
        self.assertEqual(provider.EXIT['exact_ready'], 0)
        absent = self.inspect(Host(False))
        self.assertEqual(absent['result'], 'absent')
        self.assertEqual(provider.EXIT['absent'], 10)

    def test_bad_ensure_digest_cannot_provision_state(self):
        host = Host(False)
        with patch.object(sys, 'argv', ['runtime_provider.py', 'ensure',
                '--bundle', '/reviewed', '--plan-sha256', '0'*64]), \
             patch.object(provider.deployment, 'provision_state') as provision, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'reviewed deployment plan digest'):
                provider.main(host)
        provision.assert_not_called()

    def test_plan_is_nonmutating_and_approved_ensure_provisions_before_apply(self):
        host = Host(False)
        plan = host.deployment_plan(Path('/reviewed'))
        digest = provider.canonical_digest(plan)
        with patch.object(sys, 'argv', ['runtime_provider.py', 'plan',
                '--bundle', '/reviewed']), \
             patch.object(provider.deployment, 'provision_state') as provision, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), provider.EXIT['absent'])
        provision.assert_not_called()
        with patch.object(sys, 'argv', ['runtime_provider.py', 'ensure',
                '--bundle', '/reviewed', '--plan-sha256', digest]), \
             patch.object(provider.deployment, 'provision_state') as provision, \
             patch.object(provider.deployment, 'mutation_lock',
                          return_value=contextlib.nullcontext()), \
             patch.object(provider.deployment, 'apply') as apply, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        provision.assert_called_once_with()
        apply.assert_called_once()

    def test_activation_required_after_complete_deployment(self):
        host = Host()
        host._modules['rp1_route_controller'] = {'status': 'absent'}
        host._modules['rp1_gpclk_dkms'] = {'status': 'absent'}
        host._endpoints['/dev/rp1-route-admin'] = {'status': 'absent', 'open': False}
        host._endpoints['/dev/rp1-gpclk'] = {'status': 'absent', 'open': False}
        host._socket = {'status': 'absent'}
        host._manager = {'status': 'absent'}
        self.assertEqual(self.inspect(host)['result'], 'activation_required')

    def test_terminal_reboot_and_interrupted_retirement_use_public_activation_facade(self):
        import check_runtime_activation as fixture
        for gpio in (4, 20):
            for interrupted in (False, True):
                with self.subTest(gpio=gpio, interrupted=interrupted):
                    system = fixture.Tests().rebooted_route(gpio)
                    if interrupted:
                        selected = provider.activation.activation_plan(system)
                        system.fail = 'inhibit-after'
                        with self.assertRaises(ValueError):
                            provider.activation.ensure(system, selected,
                                provider.activation.plan_digest(selected), fixture.lock)
                        system.fail = None
                    host = Host()
                    host._modules = {name: {'status': 'absent'} for name in host._modules}
                    host._endpoints = {name: {'status': 'absent', 'open': False} for name in host._endpoints}
                    host._socket = {'status': 'absent'}
                    host._manager = {'status': 'absent'}
                    host._activation = {'status': 'observed', 'value': provider.activation.observe(system)}
                    host._journals = {name: {'status': 'present', 'value': value} if value else
                        {'status': 'absent'} for name, value in {
                            'activation.json': system.journal,
                            **provider.activation.observe(system)['transactions']}.items()}
                    host.activation_plan = lambda: provider.activation.activation_plan(system)
                    host.activation_ensure = lambda value, digest: provider.activation.ensure(system, value, digest, fixture.lock)
                    before = copy.deepcopy(system.__dict__)
                    self.assertEqual(self.inspect(host)['result'], 'activation_required')
                    self.assertEqual(system.__dict__, before)
                    output = io.StringIO()
                    with patch.object(sys, 'argv', ['runtime_provider.py', 'activation-plan']), contextlib.redirect_stdout(output):
                        self.assertEqual(provider.main(host), provider.EXIT['activation_required'])
                    plan = json.loads(output.getvalue())['activationPlan']
                    self.assertEqual(system.__dict__, before)
                    with patch.object(sys, 'argv', ['runtime_provider.py', 'activation-ensure', '--plan-sha256', plan['planSha256']]), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(provider.main(host), 0)
                    self.assertTrue(provider.activation.neutral_ready(provider.activation.observe(system)))
                    self.assertFalse(system.consumer)

    def test_restartable_post_reboot_activation_is_reported_explicitly(self):
        host = Host()
        host._modules = {name: {'status': 'absent'} for name in host._modules}
        host._endpoints = {name: {'status': 'absent', 'open': False}
                           for name in host._endpoints}
        host._socket = {'status': 'absent'}
        host._manager = {'status': 'absent'}
        host._activation = {'status': 'observed', 'value': {
            'bootId': '00000000-0000-0000-0000-000000000002',
            'activationJournal': {'phase': 'complete-neutral', 'plan': {
                'bootId': '00000000-0000-0000-0000-000000000001'}}}}
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'post_reboot_reactivation_state',
                          return_value=True):
            result = self.inspect(host)
        self.assertEqual(result['result'], 'activation_required')
        self.assertTrue(result['reboot']['occurred'])
        self.assertIn('post-reboot neutral reactivation', result['remediation'][0])

    def test_current_boot_neutral_ancestry_allows_exact_active_route(self):
        host = Host()
        host._activation = {'status': 'observed', 'value': {
            'bootId': '00000000-0000-0000-0000-000000000001',
            'activationJournal': {'phase': 'complete-neutral', 'plan': {
                'bootId': '00000000-0000-0000-0000-000000000001'}}}}
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'routed_from_current_neutral',
                          return_value=True):
            self.assertEqual(self.inspect(host)['result'], 'exact_ready')
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'routed_from_current_neutral',
                          side_effect=ValueError('ancestry drift')):
            self.assertEqual(self.inspect(host)['result'], 'recovery_required')

    def test_current_boot_recovered_route_is_activation_recovery_not_conflict(self):
        host = Host()
        neutral = controller(0, 0)
        host._modules['rp1_gpclk_dkms'] = {'status': 'absent'}
        host._endpoints['/dev/rp1-gpclk'] = {'status': 'absent', 'open': False}
        host._manager['query']['state'].update(
            activeRoute=None, controller=neutral,
            pendingTransaction={'phase': 'recovered-inhibited'},
            application={'phase': 'route-recovered'})
        host._manager.pop('idle')
        host._journals['activation.json'] = {'status': 'present',
            'value': {'phase': 'complete-neutral'}}
        host._activation = {'status': 'observed', 'value': {
            'bootId': 'boot', 'activationJournal': {
                'phase': 'complete-neutral', 'plan': {'bootId': 'boot'}}}}
        host.activation_recovery_plan = lambda: {'routeRecoverySha256': {
            name: ('a' if index == 0 else 'b' if index == 1 else 'c') * 64
            for index, name in enumerate(
                provider.activation.RETIREMENT_TRANSACTIONS)}}
        with patch.object(provider.activation, 'neutral_ready', return_value=False):
            result = self.inspect(host)
        self.assertEqual(result['result'], 'recovery_required')
        self.assertEqual(result['conflicts'], [])
        self.assertNotIn('loaded-controller-without-completed-activation',
                         result['conflicts'])
        host.activation_recovery_plan = lambda: (_ for _ in ()).throw(
            ValueError('route recovery ancestry drift'))
        with patch.object(provider.activation, 'neutral_ready', return_value=False):
            drifted = self.inspect(host)
        self.assertEqual(drifted['result'], 'conflict')
        self.assertIn('loaded-controller-without-completed-activation',
                      drifted['conflicts'])

    def completed_removal(self, phase='neutral-restored'):
        host = Host()
        neutral = controller(0, 0)
        application_record = {'phase': phase, 'operation': 'remove',
            'controller': None, 'ready': None}
        transaction = {'phase': 'recovered-inhibited'}
        host._modules['rp1_gpclk_dkms'] = {'status': 'absent'}
        host._endpoints['/dev/rp1-gpclk'] = {'status': 'absent', 'open': False}
        host._manager['query']['state'].update(activeRoute=None,
            configuredRoute=None, controller=neutral,
            pendingTransaction=transaction, application=application_record,
            applicationInhibited=False, outputEnabled=False)
        host._manager.pop('idle')
        host._journals['transaction.json'] = {
            'status': 'present', 'value': copy.deepcopy(transaction)}
        host._journals['application.json'] = {
            'status': 'present', 'value': copy.deepcopy(application_record)}
        host._journals['activation.json'] = {'status': 'present',
            'value': {'phase': 'complete-neutral'}}
        host._activation = {'status': 'observed', 'value': {
            'bootId': 'boot', 'activationJournal': {
                'phase': 'complete-neutral', 'plan': {'bootId': 'boot'}}}}
        host.activation_recovery_plan = lambda: {'routeRecoverySha256': {
            name: ('a' if index == 0 else 'b' if index == 1 else 'c') * 64
            for index, name in enumerate(
                provider.activation.RETIREMENT_TRANSACTIONS)}}
        return host

    def test_completed_route_removal_is_reusable_neutral_state(self):
        for phase in ('neutral-restored', 'neutral-stopped',
                      'neutral-administrator-masked'):
            with self.subTest(phase=phase):
                host = self.completed_removal(phase)
                if phase == 'neutral-stopped':
                    host.services = lambda: {**Host.services(host),
                        'wsprrypi.service': {'load': 'loaded', 'active': 'inactive',
                            'enabled': 'enabled'}}
                elif phase == 'neutral-administrator-masked':
                    host.services = lambda: {**Host.services(host),
                        'wsprrypi.service': {'load': 'masked', 'active': 'inactive',
                            'enabled': 'masked'}}
                with patch.object(provider.activation, 'neutral_ready', return_value=False):
                    result = self.inspect(host)
                self.assertEqual(result['result'], 'neutral_ready')
                self.assertTrue(result['administrationEligible'])
                for route in ('gpio4', 'gpio20'):
                    checked = {'status': 'ok', 'state': {
                        'preflightToken': route[4] * 64,
                        'controller': controller(0, 0)}}
                    with patch.object(provider.client, 'exchange', return_value=checked):
                        plan = provider.route_plan(result, route)
                    self.assertFalse(plan['alreadyReady'])
                    self.assertEqual(plan['route'], route)
                rejected = {'status': 'error', 'state': {}}
                with patch.object(provider.client, 'exchange', return_value=rejected):
                    with self.assertRaisesRegex(ValueError,
                            'route preflight failed'):
                        provider.route_plan(result, 'gpio20')

    def test_completed_removal_requires_every_identity_and_safety_fact(self):
        mutations = (
            lambda host: host._manager['query']['state'].update(configuredRoute='gpio20'),
            lambda host: host._manager['query']['state'].update(applicationInhibited=True),
            lambda host: host._manager['query']['state'].update(outputEnabled=True),
            lambda host: host._manager['query']['state'].update(activeRoute='gpio20'),
            lambda host: host._manager['query']['state']['controller'].update(route=2),
            lambda host: host._manager['query']['state']['controller'].update(generation=0),
            lambda host: host._manager['query']['state']['application'].update(operation='switch'),
            lambda host: host._manager['query']['state']['application'].update(controller={}),
            lambda host: host._manager['query']['state']['application'].update(ready={}),
            lambda host: host._manager['query']['state']['application'].update(
                phase='neutral-restoration-failed'),
            lambda host: host._journals['application.json'].update(value={'phase': 'changed'}),
            lambda host: host._journals['transaction.json'].update(value={'phase': 'changed'}),
            lambda host: setattr(host, 'services', lambda: {
                **Host.services(host), 'wsprrypi.service': {
                    'load': 'loaded', 'active': 'inactive', 'enabled': 'enabled'}}),
            lambda host: host._modules.update(rp1_gpclk_dkms={
                'status': 'loaded', 'version': VERSION,
                'buildNoteSha256': host.value['consumerNoteSha256']}),
            lambda host: host._endpoints['/dev/rp1-gpclk'].update(status='owned'),
            lambda host: setattr(host, 'activation_recovery_plan', lambda: {
                'routeRecoverySha256': {'transaction.json': 'a' * 64}}),
            lambda host: setattr(host, 'activation_recovery_plan', lambda: {
                'routeRecoverySha256': {name: 'z' * 64 for name in
                    provider.activation.RETIREMENT_TRANSACTIONS}}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                host = self.completed_removal()
                mutate(host)
                with patch.object(provider.activation, 'neutral_ready', return_value=False):
                    result = self.inspect(host)
                self.assertNotEqual(result['result'], 'neutral_ready')
                with self.assertRaisesRegex(ValueError,
                        'runtime state is not eligible for route planning'):
                    provider.route_plan(result, 'gpio20')

    def test_unproven_post_reboot_activation_requires_investigation(self):
        host = Host()
        host._modules = {name: {'status': 'absent'} for name in host._modules}
        host._endpoints = {name: {'status': 'absent', 'open': False}
                           for name in host._endpoints}
        host._socket = {'status': 'absent'}
        host._manager = {'status': 'absent'}
        host._activation = {'status': 'observed', 'value': {
            'bootId': '00000000-0000-0000-0000-000000000002',
            'activationJournal': {'phase': 'complete-neutral', 'plan': {
                'bootId': '00000000-0000-0000-0000-000000000001'}}}}
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'post_reboot_reactivation_state',
                          side_effect=ValueError('identity drift')):
            result = self.inspect(host)
        self.assertEqual(result['result'], 'recovery_required')
        self.assertTrue(result['reboot']['occurred'])
        self.assertIn('Preserve the prior-boot activation evidence',
                      result['remediation'][0])

    def test_reviewed_removal_is_limited_to_inactive_activation_required_state(self):
        host = Host()
        host._modules = {name: {'status': 'absent'} for name in host._modules}
        host._endpoints = {name: {'status': 'absent', 'open': False}
                           for name in host._endpoints}
        host._socket = {'status': 'absent'}
        host._manager = {'status': 'absent'}
        digest = provider.deployment.plan_hash(host.removal)
        with patch.object(sys, 'argv', ['runtime_provider.py', 'remove-plan']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        with patch.object(sys, 'argv', ['runtime_provider.py', 'remove',
                '--plan-sha256', '0'*64]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'reviewed deployment removal'):
                provider.main(host)
        self.assertFalse(host.removed)
        with patch.object(sys, 'argv', ['runtime_provider.py', 'remove',
                '--plan-sha256', digest]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        self.assertTrue(host.removed)

    def test_real_host_retires_exact_recovered_activation_before_removal(self):
        journal = {'version': 1, 'phase': 'recovered-inhibited'}
        activation_path = str(provider.activation.JOURNAL)
        value = {'version': 1, 'files': {activation_path: {
            'before': None, 'after': None}}}
        digest = provider.deployment.plan_hash(value)
        events = []
        system = SimpleNamespace(
            read_record=lambda path: journal,
            archive_journal=lambda current: events.append(('archive', current)),
            retire_journal=lambda current: events.append(('retire', current)),
            retire_transactions=lambda current: events.append(
                ('retire-transactions', current)))
        files = SimpleNamespace(prune_removed_directories=lambda: events.append(('prune', None)))
        host = provider.Host.__new__(provider.Host)
        host.files = files
        with patch.object(provider.deployment, 'mutation_lock',
                          return_value=contextlib.nullcontext()), \
             patch.object(provider.deployment, 'removal_plan', return_value=value), \
             patch.object(provider.deployment, 'remove',
                          side_effect=lambda *args: events.append(('remove', None))), \
             patch.object(provider.activation, 'Linux', return_value=system), \
             patch.object(provider.activation, 'recovery_plan',
                          return_value={'alreadyRecovered': True}), \
             patch.object(provider.activation, 'recovered_route_retirement',
                          return_value=None):
            self.assertEqual(host.deployment_remove(value, digest),
                             {'status': 'removed-exact-deployment'})
        self.assertEqual([event[0] for event in events],
                         ['archive', 'retire', 'remove', 'prune'])

    def test_real_host_retires_orphaned_exact_route_journals_before_removal(self):
        transactions = {name: {'name': name}
                        for name in provider.activation.RETIREMENT_TRANSACTIONS}
        value = {'version': 1, 'files': {}}
        digest = provider.deployment.plan_hash(value)
        events = []
        system = SimpleNamespace(
            read_record=lambda path: None,
            retire_transactions=lambda current: events.append(
                ('retire-transactions', current)))
        host = provider.Host.__new__(provider.Host)
        host.files = SimpleNamespace(
            read=lambda path: None,
            prune_removed_directories=lambda: events.append(('prune', None)))
        with patch.object(provider.deployment, 'mutation_lock',
                          return_value=contextlib.nullcontext()), \
             patch.object(provider.deployment, 'removal_plan', return_value=value), \
             patch.object(provider.deployment, 'remove',
                          side_effect=lambda *args: events.append(('remove', None))), \
             patch.object(provider.activation, 'Linux', return_value=system), \
             patch.object(provider.activation, 'recovered_route_retirement',
                          return_value=transactions):
            self.assertEqual(host.deployment_remove(value, digest),
                             {'status': 'removed-exact-deployment'})
        self.assertEqual(events, [
            ('retire-transactions', transactions),
            ('remove', None), ('prune', None),
        ])

    def test_real_host_does_not_retire_recovery_on_unreviewed_removal(self):
        journal = {'version': 1, 'phase': 'recovered-inhibited'}
        events = []
        system = SimpleNamespace(
            read_record=lambda path: journal,
            archive_journal=lambda current: events.append('archive'),
            retire_journal=lambda current: events.append('retire'))
        host = provider.Host.__new__(provider.Host)
        host.files = SimpleNamespace()
        value = {'version': 1, 'files': {}}
        with patch.object(provider.deployment, 'mutation_lock',
                          return_value=contextlib.nullcontext()), \
             patch.object(provider.deployment, 'removal_plan', return_value=value), \
             patch.object(provider.activation, 'Linux', return_value=system):
            with self.assertRaisesRegex(ValueError, 'reviewed deployment removal'):
                host.deployment_remove(value, '0' * 64)
        self.assertEqual(events, [])

    def test_reviewed_post_reboot_activation_retirement(self):
        host = Host()
        host._modules = {name: {'status': 'absent'} for name in host._modules}
        host._endpoints = {name: {'status': 'absent', 'open': False}
                           for name in host._endpoints}
        host._socket = {'status': 'absent'}
        host._manager = {'status': 'absent'}
        host._activation = {'status': 'observed', 'value': {
            'bootId': '00000000-0000-0000-0000-000000000002',
            'activationJournal': {'phase': 'complete-neutral', 'plan': {
                'bootId': '00000000-0000-0000-0000-000000000001'}}}}
        digest = provider.activation.plan_digest(host.retirement)
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'post_reboot_reactivation_state',
                          return_value=True), \
             patch.object(sys, 'argv', ['runtime_provider.py',
                          'activation-retire-plan']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'post_reboot_reactivation_state',
                          return_value=True), \
             patch.object(sys, 'argv', ['runtime_provider.py', 'activation-retire',
                          '--plan-sha256', digest]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        self.assertTrue(host.retired)

    def test_reviewed_post_reboot_retirement_accepts_recovery_classification(self):
        host = Host()
        host._modules = {name: {'status': 'absent'} for name in host._modules}
        host._endpoints = {name: {'status': 'absent', 'open': False}
                           for name in host._endpoints}
        host._socket = {'status': 'absent'}
        host._manager = {'status': 'absent'}
        host._activation = {'status': 'observed', 'value': {
            'bootId': '00000000-0000-0000-0000-000000000002',
            'activationJournal': {'phase': 'complete-neutral', 'plan': {
                'bootId': '00000000-0000-0000-0000-000000000001'}}}}
        host._journals['transaction.json'] = {'status': 'present', 'value': {}}
        digest = provider.activation.plan_digest(host.retirement)
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'post_reboot_reactivation_state',
                          side_effect=ValueError('prior transactions')), \
             patch.object(sys, 'argv', ['runtime_provider.py',
                          'activation-retire-plan']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        with patch.object(provider.activation, 'neutral_ready', return_value=False), \
             patch.object(provider.activation, 'post_reboot_reactivation_state',
                          side_effect=ValueError('prior transactions')), \
             patch.object(sys, 'argv', ['runtime_provider.py', 'activation-retire',
                          '--plan-sha256', digest]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.main(host), 0)
        self.assertTrue(host.retired)

    def test_neutral_ready_is_administration_only(self):
        host = Host()
        host._modules['rp1_gpclk_dkms'] = {'status': 'absent'}
        host._endpoints['/dev/rp1-gpclk'] = {'status': 'absent', 'open': False}
        host._manager['query']['state'].update(activeRoute=None,
            controller=controller(0, 0), pendingTransaction=None, application=None)
        host._manager.pop('idle')
        host._journals['activation.json'] = {'status': 'present',
            'value': {'phase': 'complete-neutral'}}
        host._activation = {'status': 'observed', 'value': {'neutral': True}}
        with patch.object(provider.activation, 'neutral_ready', return_value=True):
            result = self.inspect(host)
        self.assertEqual(result['result'], 'neutral_ready')
        self.assertTrue(result['administrationCompatible'])
        self.assertTrue(result['administrationEligible'])
        self.assertFalse(result['compatible'] or result['eligible'])
        self.assertFalse(result['routeSelected'] or result['executionReady'])

    def test_partial_file_publication_requires_recovery(self):
        host = Host()
        host._artifacts[next(iter(host._artifacts))] = {'status': 'absent'}
        self.assertEqual(self.inspect(host)['result'], 'recovery_required')

    def test_changed_foreign_or_mixed_identity_conflicts(self):
        mutations = []
        def changed(host): host._artifacts[next(iter(host._artifacts))]['status'] = 'changed'
        mutations.append(changed)
        mutations.append(lambda host: host._endpoints['/dev/rp1-gpclk'].update(status='unsafe'))
        mutations.append(lambda host: host._modules['rp1_route_controller'].update(version='foreign'))
        mutations.append(lambda host: host._modules['rp1_route_controller'].update(buildNoteSha256='0'*64))
        mutations.append(lambda host: host._binding.update(status='error', detail='malformed'))
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                host = Host(); mutate(host)
                self.assertEqual(self.inspect(host)['result'], 'conflict')

    def test_open_endpoint_and_route_disagreement_conflict(self):
        host = Host(); host._endpoints['/dev/rp1-gpclk']['open'] = True
        self.assertEqual(self.inspect(host)['result'], 'conflict')
        host = Host()
        result = self.inspect(host, requested='gpio4', configured='gpio20', persisted='gpio4')
        self.assertEqual(result['result'], 'conflict')
        self.assertIn('route-selection-mismatch', result['conflicts'])

    def test_pending_fault_and_restoration_failure_require_recovery(self):
        host = Host(); host._journals['deployment-pending.json'] = {'status': 'present', 'value': {}}
        self.assertEqual(self.inspect(host)['result'], 'recovery_required')
        host = Host(); host._manager['query']['state']['controller']['flags'] = 7
        self.assertEqual(self.inspect(host)['result'], 'recovery_required')
        host = Host(); host._manager['query']['state']['application']['phase'] = 'restoration-failed'
        self.assertEqual(self.inspect(host)['result'], 'recovery_required')

    def test_service_failure_requires_completion_and_busy_output_conflicts(self):
        host = Host()
        host.services = lambda: {'rp1-gpclk-route-manager.socket': {
            'load': 'loaded', 'active': 'inactive', 'enabled': 'enabled',
            'fragment': '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'}}
        self.assertEqual(self.inspect(host)['result'], 'deployment_required')
        host = Host()
        host._manager['idle']['state']['outputLifecycle']['snapshot']['owner'] = 2
        self.assertEqual(self.inspect(host)['result'], 'conflict')

    def test_provider_rejects_missing_mistyped_or_disagreeing_authorization(self):
        for mutation in ('missing', 'string', 'disagree'):
            with self.subTest(mutation=mutation):
                host = Host()
                lifecycle = host._manager['idle']['state']['outputLifecycle']
                if mutation == 'missing':
                    lifecycle.pop('executionAuthorized')
                elif mutation == 'string':
                    lifecycle['executionAuthorized'] = 'false'
                else:
                    lifecycle['executionAuthorized'] = True
                result = self.inspect(host)
                self.assertEqual(result['result'], 'conflict')
                self.assertIn('output-lifecycle-invalid', result['conflicts'])

    def test_real_provider_forwarding_requires_boolean_authorization(self):
        query = manager_ready()['query']
        for mutation in ('missing', 'string', 'disagree'):
            idle = manager_ready()['idle']
            lifecycle = idle['state']['outputLifecycle']
            if mutation == 'missing':
                lifecycle.pop('executionAuthorized')
            elif mutation == 'string':
                lifecycle['executionAuthorized'] = 'false'
            else:
                lifecycle['executionAuthorized'] = True
            with self.subTest(mutation=mutation), \
                 patch.object(provider.client, 'exchange', side_effect=[query, idle]):
                self.assertEqual(provider.Host().manager()['status'], 'error')

    def test_provider_rejects_stale_lifecycle_identities_and_error_envelope(self):
        for field, value in (('route', 'gpio20'), ('controller', controller(2)),
                             ('bootId', 'stale'), ('bindingSha256', 'f'*64)):
            with self.subTest(field=field):
                host = Host()
                host._manager['idle']['state']['outputLifecycle'][field] = value
                result = self.inspect(host)
                self.assertEqual(result['result'], 'conflict')
                self.assertIn('output-lifecycle-invalid', result['conflicts'])
        host = Host()
        host._manager['idle']['status'] = 'error'
        result = self.inspect(host)
        self.assertEqual(result['result'], 'conflict')
        self.assertIn('output-lifecycle-invalid', result['conflicts'])

    def test_malformed_runtime_transaction_conflicts(self):
        host = Host()
        host._manager['query']['state']['pendingTransaction']['foreign'] = True
        self.assertEqual(self.inspect(host)['result'], 'conflict')

    def test_missing_application_prerequisite_blocks_plan(self):
        host = Host(False)
        host.expected_external = lambda expected: {path: {'status': 'absent'}
            for path in [*expected['externalFiles'],
                         *(item['path'] for item in expected['modules'].values())]}
        result = provider.inspect(host, bundle=Path('/reviewed'))[0]
        self.assertEqual(result['result'], 'conflict')
        self.assertTrue(any(item.startswith('external-prerequisite-conflict:')
                            for item in result['conflicts']))

    def test_binding_digest_rejects_any_identity_substitution(self):
        value = exact_binding()
        binding.validate(value)
        for field in ('sourceCommit', 'productVersion'):
            altered = copy.deepcopy(value)
            altered[field] = 'f'*40 if field == 'sourceCommit' else '0.9.1'
            with self.assertRaises(ValueError): binding.validate(altered)
        altered = copy.deepcopy(value)
        altered['files'][next(iter(altered['files']))] = '0'*64
        with self.assertRaises(ValueError): binding.validate(altered)
        altered = copy.deepcopy(value)
        altered['uapiSha256']['consumer'] = '0'*64
        altered['artifactSetSha256'] = binding.canonical_digest(
            {key: item for key, item in altered.items()
             if key != 'artifactSetSha256'})
        with self.assertRaises(ValueError):
            binding.validate(altered)

    def test_binding_accepts_an_exact_nonreference_stock_kernel(self):
        value = exact_binding()
        kernel = '6.20.1+rpt-rpi-2712'
        value['kernel'] = kernel
        for name, record in value['modules'].items():
            record['kernel'] = kernel
            record['path'] = f'/lib/modules/{kernel}/updates/dkms/{name}.ko.xz'
        value['artifactSetSha256'] = binding.canonical_digest(
            {key: item for key, item in value.items()
             if key != 'artifactSetSha256'})
        self.assertIs(binding.validate(value), value)
        value['modules']['rp1_gpclk_dkms']['path'] = (
            f'/lib/modules/{KERNEL}/updates/dkms/rp1_gpclk_dkms.ko.xz')
        value['artifactSetSha256'] = binding.canonical_digest(
            {key: item for key, item in value.items()
             if key != 'artifactSetSha256'})
        with self.assertRaises(ValueError):
            binding.validate(value)

    def test_application_companion_read_is_bounded_and_nofollow(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            companion = root/'companion.py'; companion.write_bytes(b'pass\n')
            self.assertEqual(build_binding.companion_bytes(companion), b'pass\n')
            link = root/'link.py'; link.symlink_to(companion)
            with self.assertRaises(OSError): build_binding.companion_bytes(link)
            companion.write_bytes(b'x'*(4*1024*1024+1))
            with self.assertRaisesRegex(ValueError, 'bound'):
                build_binding.companion_bytes(companion)

    def test_installed_module_accepts_one_compressed_artifact_and_rejects_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = (('\x7fELF\x02\x01\x00version=' + VERSION + '\x00vermagic=').encode() +
                       KERNEL.encode() + b' fixture')
            compressed = root/'rp1_gpclk_dkms.ko.xz'
            compressed.write_bytes(lzma.compress(payload))
            with patch.object(build_binding, 'module_note', return_value=b'fixture-note'):
                record, observed = build_binding.installed_module(
                    root, 'rp1_gpclk_dkms', KERNEL)
            self.assertEqual(observed, payload)
            self.assertEqual(record['compression'], 'xz')
            self.assertEqual(record['installedFileSha256'],
                             hashlib.sha256(compressed.read_bytes()).hexdigest())
            self.assertEqual(record['decompressedElfSha256'],
                             hashlib.sha256(payload).hexdigest())
            (root/'rp1_gpclk_dkms.ko').write_bytes(payload)
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                build_binding.installed_module(root, 'rp1_gpclk_dkms', KERNEL)

    def test_runtime_bundle_rebuild_is_byte_deterministic(self):
        import hashlib
        import tempfile
        import shutil
        origin = Path(__file__).resolve().parents[1]
        def checkout_bytes():
            return {str(p.relative_to(origin)): (stat.S_IMODE(p.lstat().st_mode),
                    p.readlink().as_posix() if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in origin.rglob('*') if (p.is_file() or p.is_symlink())
                    and '.git' not in p.relative_to(origin).parts}
        before = checkout_bytes()
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as patches:
            root = Path(directory).resolve(); source = root/'source'; source.mkdir()
            inputs = {value for value in INVENTORY.values() if not value.startswith('build/')}
            inputs.update('overlays/rp1-gpclk-'+route+'.dts' for route in ('gpio4', 'gpio20'))
            for name in inputs:
                target = source/name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origin/name, target)
            for module in (bundle_builder, build_binding, controller_builder):
                patches.enter_context(patch.object(module, 'ROOT', source))
            # Synthetic ELF identity fixtures exercise bundle/binding format logic;
            # module-note decoding and Git provenance have separate real tests.
            patches.enter_context(patch.object(build_binding, 'module_note', return_value=b'fixture-note'))
            patches.enter_context(patch.object(build_binding, 'source_commit', return_value='a'*40))
            controller_builder.generate(source/'build/runtime-controller')
            modules = root/'modules'; modules.mkdir()
            prefix = b'\x7fELF\x02\x01\0'
            consumer = (prefix + ('version=' + VERSION + '\x00rp1_runtime_controller=1\x00').encode() +
                b'rp1_route_controller\0vermagic=' + KERNEL.encode() + b' ')
            controller_data = prefix + ('version=' + VERSION + '\x00vermagic=').encode() + KERNEL.encode() + b' '
            for route in ('gpio4', 'gpio20'):
                controller_data += (source/'build/runtime-controller'/(route+'.dtbo')).read_bytes()
            (modules/'rp1_gpclk_dkms.ko').write_bytes(consumer)
            (modules/'rp1_route_controller.ko').write_bytes(controller_data)
            companion = root/'route_application.py'; companion.write_text('pass\n')
            first = root/'first'; second = root/'second'
            for route in ('gpio4', 'gpio20'):
                (source/'build/runtime-controller'/(route+'.dtbo')).write_bytes(b'poisoned stale output')
            value = bundle_builder.bundle(modules, first, companion, KERNEL)
            bundle_builder.bundle(modules, second, companion, KERNEL)
            for destination, name in INVENTORY.items():
                self.assertEqual(value['files'][destination], hashlib.sha256((source/name).read_bytes()).hexdigest())
            (modules/'rp1_route_controller.ko').write_bytes(prefix+('version=' + VERSION + '\x00vermagic=').encode()+KERNEL.encode()+b' ')
            with self.assertRaisesRegex(ValueError, 'embedded overlay'):
                bundle_builder.bundle(modules, root/'failed', companion, KERNEL)
            self.assertFalse((root/'failed').exists())
            first_files = {path.name: path.read_bytes() for path in first.iterdir()}
            second_files = {path.name: path.read_bytes() for path in second.iterdir()}
            self.assertEqual(first_files, second_files)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o700)
            bootstrap = {
                'runtime_deployment.py', 'runtime_controller_admin.py',
                'runtime_layout.py', 'runtime_application.py',
                'runtime_output.py', 'runtime_provider.py', 'runtime_binding.py',
                'runtime_activation.py', 'runtime_route_client.py', 'runtime_manager.py', 'package_preflight.py',
            }
            self.assertTrue(bootstrap <= set(first_files))
            # Include imports inside functions: the update facade uses a lazy
            # manager import that ordinary top-level import smoke tests miss.
            for name in bootstrap:
                for node in ast.walk(ast.parse(first_files[name], filename=name)):
                    imports = ([alias.name.split('.')[0] for alias in node.names]
                               if isinstance(node, ast.Import) else
                               [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom)
                               and node.level == 0 and node.module else [])
                    for module in imports:
                        if module.startswith('runtime_'):
                            self.assertIn(module + '.py', bootstrap, name + ' imports ' + module)
            subprocess.run([sys.executable, '-B', '-c',
                'import sys; sys.path.insert(0, sys.argv[1]); import runtime_provider, runtime_activation',
                str(first)], check=True)
        self.assertEqual(checkout_bytes(), before)

    def test_binding_deploys_manager_units_and_only_externalizes_application(self):
        self.assertEqual(binding.EXTERNAL_PATHS, {binding.APPLICATION})
        self.assertEqual(INVENTORY[
            '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'],
            'systemd/rp1-gpclk-route-manager.socket')
        self.assertEqual(INVENTORY[
            '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service'],
            'systemd/rp1-gpclk-route-manager@.service')

    def test_route_plan_binds_preflight_and_is_idempotent_when_ready(self):
        result = self.inspect(Host())
        plan = provider.route_plan(result, 'gpio4')
        self.assertTrue(plan['alreadyReady'])
        result['result'] = 'deployment_required'
        result['routes']['active'] = None
        checked = {'status': 'ok', 'state': {'preflightToken': 'a'*64,
            'controller': controller(0, 0)}}
        with patch.object(provider.client, 'exchange', return_value=checked):
            plan = provider.route_plan(result, 'gpio20')
        digest = provider.canonical_digest(plan)
        altered = copy.deepcopy(plan); altered['route'] = 'gpio4'
        self.assertNotEqual(digest, provider.canonical_digest(altered))

    def test_idle_active_route_can_be_explicitly_planned_to_other_route(self):
        result = self.inspect(Host(), requested='gpio20', configured='gpio20',
                              persisted='gpio20')
        self.assertEqual(result['result'], 'deployment_required')
        checked = {'status': 'ok', 'state': {'preflightToken': 'a'*64,
            'controller': controller(1)}}
        with patch.object(provider.client, 'exchange', return_value=checked):
            plan = provider.route_plan(result, 'gpio20')
        self.assertEqual(plan['configuredRoute'], 'gpio20')
        self.assertEqual(plan['controller']['route'], 1)

    def test_installed_client_preserves_reconcile_output_verb(self):
        replies = []
        def exchange(request):
            replies.append(request)
            return {'schemaVersion': 1, 'contract': provider.client.CONTRACT,
                    'status': 'ok', 'state': {}}
        with patch.object(sys, 'argv', ['runtime_route_client.py',
                'reconcile-output', 'gpio4']), \
             patch.object(provider.client, 'exchange', exchange), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(provider.client.main(), 0)
        self.assertEqual(replies, [{'schemaVersion': 1,
            'operation': 'reconcile-output', 'route': 'gpio4'}])

    def test_schema_and_exit_status_contract(self):
        schema = json.loads((Path(__file__).resolve().parents[1] /
            'schema/rp1-gpclk-runtime-readiness-v1.schema.json').read_text())
        self.assertEqual(schema['properties']['contract']['const'], provider.CONTRACT)
        self.assertEqual(schema['properties']['result']['enum'],
            ['absent', 'deployment_required', 'activation_required', 'neutral_ready',
             'exact_ready', 'recovery_required', 'conflict'])
        self.assertEqual(provider.EXIT, {'exact_ready': 0, 'neutral_ready': 0,
            'absent': 10, 'deployment_required': 11, 'recovery_required': 12,
            'conflict': 13, 'activation_required': 14})
        self.assertEqual(provider.CONTRACT, 'rp1-gpclk-runtime-readiness-v1')


class UpdateHost(Host):
    """Real activation planners/executors over the existing offline system."""
    def __init__(self, active=True, masked=False, removed=False):
        import check_runtime_activation as fixture
        super().__init__()
        self.fixture = fixture
        self.system = fixture.System(fixture.captured(active, masked))
        self.system.binding_value = self.value
        self.system.raw = json.dumps(self.value, sort_keys=True).encode()
        self.system.deployed['files'][provider.deployment.BINDING]['after'] = provider.deployment.encode(self.system.raw)
        self.system.deployment_raw = provider.deployment.journal_bytes(self.system.deployed)
        initial = provider.activation.activation_plan(self.system)
        provider.activation.ensure(self.system, initial, provider.activation.plan_digest(initial), fixture.lock)
        if removed:
            fixture.Tests().recovered_route(self.system, removal=True)
            phase = 'neutral-administrator-masked' if masked else 'neutral-restored' if active else 'neutral-stopped'
            self.system.records['application.json'].update(phase=phase,
                wasActive=active, administratorMasked=masked)
            captured = self.system.records['manager.json']['response']['state']['application']
            captured.update(wasActive=active, administratorMasked=masked)
            self.system.application_active = active
        self.absent = False
        self.busy = False
        self.effects = []

    def running_kernel(self): return KERNEL
    def binding(self):
        return {'status': 'absent'} if self.absent else {
            'status': 'valid', 'sha256': provider.admin.digest(self.system.raw), 'value': self.value}
    def artifacts(self, unused): return {} if self.absent else super().artifacts(unused)
    def journal(self, name):
        value = None if self.absent else self.system.read_record(name)
        return {'status': 'present', 'value': value} if value is not None else {'status': 'absent'}
    def module(self, name):
        loaded = self.system.controller if name == 'rp1_route_controller' else self.system.consumer
        return super().module(name) if loaded and not self.absent else {'status': 'absent'}
    def endpoint(self, path): return self.system.endpoint(path, None)
    def socket(self): return self.system.manager_socket()
    def services(self):
        return {name: self.system.service(name) for name in super().services()}
    def activation_observation(self):
        return {'status': 'absent'} if self.absent else {
            'status': 'observed', 'value': provider.activation.observe(self.system)}
    def manager(self):
        state = {'profile': 'runtime', 'controller': copy.deepcopy(self.system.state),
            'bootId': self.system.boot_id, 'bindingSha256': provider.admin.digest(self.system.raw),
            'activeRoute': {1: 'gpio4', 2: 'gpio20'}.get(self.system.state['route']),
            'configuredRoute': None, 'qualification': False, 'outputEnabled': False,
            'applicationInhibited': self.system.inhibited, 'applicationRestoration': True,
            'pendingTransaction': self.system.read_record('transaction.json'),
            'application': self.system.read_record('application.json')}
        value = {'status': 'observed', 'query': {'schemaVersion': 1,
            'contract': provider.client.CONTRACT, 'operation': 'query', 'status': 'ok', 'state': state}}
        if self.system.consumer:
            value['idle'] = manager_ready(state['activeRoute'])['idle']
            value['idle']['state']['outputLifecycle'].update(controller=state['controller'],
                bootId=state['bootId'], bindingSha256=state['bindingSha256'])
        return value
    def activation_recovery_plan(self): return provider.activation.recovery_plan(self.system)
    def activation_recover(self, value, digest):
        self.effects.append('recover-activation')
        return provider.activation.ensure_recovery(self.system, value, digest, self.fixture.lock)
    def activation_retirement_plan(self): return provider.activation.retirement_plan(self.system)
    def activation_retire(self, value, digest):
        self.effects.append('retire-activation')
        return provider.activation.retire(self.system, value, digest, self.fixture.lock)
    def update_removal_evidence(self): return None if self.absent else self.system.deployed
    def deployment_removal_plan(self): return copy.deepcopy(self.system.deployed)
    def deployment_remove(self, value, digest):
        self.effects.append('remove-deployment')
        if provider.deployment.plan_hash(value) != digest or self.system.controller or self.system.consumer:
            raise ValueError('unsafe inverse deployment')
        if self.system.journal:
            self.system.archive_journal(self.system.journal)
            tx = provider.activation.recovered_route_retirement(self.system)
            if tx: self.system.retire_transactions(tx)
            self.system.retire_journal(self.system.journal)
        self.absent = True
        return {'status': 'removed-exact-deployment'}
    def update_absent(self): return self.absent
    def update_stop_socket(self, expected): self.system.stop_socket()
    def select_route(self, gpio):
        self.fixture.Tests().recovered_route(self.system)
        s = self.system
        s.state.update(generation=1, id=9, route=1 if gpio == 4 else 2,
                       flags=provider.admin.CONSUMER | provider.admin.PINNED)
        tx = s.records['transaction.json']
        tx.update(phase='complete-inhibited', observation=copy.deepcopy(s.state), target=s.state['route'])
        manager = s.records['manager.json']
        manager.update(controller=copy.deepcopy(s.state))
        manager['response'].update(operation='switch', status='complete-inhibited')
        manager['response']['state'].update(controller=copy.deepcopy(s.state), pendingTransaction=copy.deepcopy(tx))
        s.records['application.json'].update(phase='restored', controller=copy.deepcopy(s.state),
            route='gpio'+str(gpio), requestId=manager['requestId'], fingerprint=manager['fingerprint'])
        s.records['application.json']['ready']['route'] = 'gpio'+str(gpio)
        s.consumer = s.consumer_endpoint = s.application_active = True
        s.inhibited = False
    def update_route_recover(self, expected):
        self.effects.append('recover-route')
        target = self.system.state['route']
        self.fixture.Tests().recovered_route(self.system)
        self.system.records['transaction.json']['target'] = target
        self.system.records['manager.json']['response']['state']['pendingTransaction']['target'] = target
        app = self.system.records['application.json']
        app['controller']['route'] = target
        app['route'] = app['ready']['route'] = 'gpio4' if target == 1 else 'gpio20'
        self.system.consumer = self.system.consumer_endpoint = False
        self.system.application_active = False
        return {'status': 'recovered-inhibited'}
    @contextlib.contextmanager
    def update_lock(self):
        if self.busy: raise ValueError('concurrent update')
        self.busy = True
        try: yield
        finally: self.busy = False


class RemovalHost(UpdateHost):
    """Actual inverse deployment over the existing in-memory filesystem."""
    def __init__(self):
        super().__init__()
        import check_runtime_manager as fixture
        self.files = fixture.Files()
        values = {path: path.encode() for path in provider.deployment.INVENTORY}
        values.update({path: None for path in provider.deployment.JOURNALS})
        values[provider.deployment.BINDING] = self.system.raw
        self.system.deployed = provider.deployment.plan(self.files, values)
        provider.deployment.apply(self.files, self.system.deployed,
                                  provider.deployment.plan_hash(self.system.deployed))
        self.system.controller = self.system.consumer = self.system.socket_active = False
        self.system.journal = None
        self.system.records = {}
        self.files.prune_removed_directories = lambda: None
        self.system.binding = self.system_binding
    def system_binding(self):
        raw = self.files.read(provider.deployment.BINDING)
        if raw is None:
            raise FileNotFoundError(provider.deployment.BINDING)
        return raw, binding.validate(provider.admin.strict_json(raw))
    def binding(self):
        raw = self.files.read(provider.deployment.BINDING)
        return {'status': 'absent'} if raw is None else {
            'status': 'valid', 'sha256': provider.admin.digest(raw),
            'value': binding.validate(provider.admin.strict_json(raw))}
    def journal(self, name):
        raw = self.files.read(str(provider.admin.STATE / name))
        return {'status': 'absent'} if raw is None else {
            'status': 'present', 'value': provider.admin.strict_json(raw)}
    def artifacts(self, unused):
        return {path: {'status': 'exact' if self.files.read(path) == path.encode() else 'absent'}
                for path in provider.deployment.INVENTORY}
    def activation_observation(self): return {'status': 'absent'}
    update_removal_evidence = provider.Host.update_removal_evidence
    deployment_removal_plan = provider.Host.deployment_removal_plan
    def deployment_remove(self, value, digest):
        self.effects.append('remove-deployment')
        # Production facade, with system reads/locks replaced at the boundary.
        with patch.object(provider.deployment, 'mutation_lock', self.fixture.lock), \
             patch.object(provider.activation, 'Linux', return_value=self.system):
            return provider.Host.deployment_remove(self, value, digest)
    update_absent = provider.Host.update_absent


class UpdateTests(unittest.TestCase):
    def test_update_absence_accepts_only_authenticated_passive_package_units(self):
        host = RemovalHost()
        host.files.values = {}
        host.files.packaged_baseline = lambda: {}
        host.services = lambda: {name: {'load': 'loaded', 'active': 'inactive'} for name in
            ('rp1-gpclk-route-manager.socket', 'rp1-gpclk-route-manager@.service')}
        host.module = lambda name: {'status': 'absent'}
        host.endpoint = lambda path: {'status': 'absent'}
        host.socket = lambda: {'status': 'absent'}
        self.assertTrue(host.update_absent())
        unit = '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'
        host.files.values[unit] = b'passive packaged unit'
        self.assertFalse(host.update_absent())
        host.files.packaged_baseline = lambda: {unit: provider.admin.digest(b'passive packaged unit')}
        self.assertTrue(host.update_absent())
        host.files.values[unit] = b'foreign modification'
        self.assertFalse(host.update_absent())
        host.files.values[unit] = b'passive packaged unit'
        host.files.values[provider.deployment.BINDING] = b'leftover runtime'
        self.assertFalse(host.update_absent())

    def request(self, host):
        return provider.update_request(host.value['sourceCommit'],
            provider.admin.digest(host.system.raw), host.value['artifactSetSha256'],
            provider.deployment.plan_hash(host.system.deployed))

    def test_neutral_and_completed_removal_sequences(self):
        for removed in (False, True):
            for active, masked in ((True, False), (False, False), (False, True)):
                with self.subTest(removed=removed, active=active, masked=masked):
                    host = UpdateHost(active, masked, removed)
                    request = self.request(host)
                    receipt = provider.installation_status(host)
                    self.assertEqual(receipt['receipt']['controllerGeneration'], 0)
                    before = copy.deepcopy(host.system.__dict__)
                    plan = provider.update_plan(host, request)
                    self.assertEqual(host.system.__dict__, before, 'planning cannot mutate state')
                    self.assertEqual(plan['plan']['action'], 'recover-activation')
                    for _ in range(4):
                        reply = provider.update_execute(host, request, plan['planSha256'])
                        if reply['status'] == 'prepared': break
                        plan = provider.update_plan(host, request)
                    self.assertTrue(reply['postconditions']['runtimeAbsent'])
                    self.assertEqual(host.effects, ['recover-activation', 'remove-deployment'])
                    self.assertTrue(provider.update_plan(host, request)['postconditions']['runtimeAbsent'])

    def test_later_neutral_generations_are_attributed_by_real_recovery_planner(self):
        for generation in (2, 4, 20):
            host = UpdateHost(removed=True)
            s = host.system
            s.state['generation'] = generation
            tx = s.records['transaction.json']; tx['observation']['generation'] = generation
            manager = s.records['manager.json']
            manager['controller']['generation'] = generation
            manager['response']['state']['controller']['generation'] = generation
            manager['response']['state']['pendingTransaction']['observation']['generation'] = generation
            plan = provider.update_plan(host, self.request(host))
            self.assertEqual(plan['plan']['action'], 'recover-activation')

    def test_stale_plan_and_concurrency_refuse_before_effects(self):
        for mutate in (lambda h: setattr(h, 'busy', True),
                       lambda h: setattr(h.system, 'boot_id', '00000000-0000-0000-0000-000000000002'),
                       lambda h: h.system.state.update(session=99),
                       lambda h: h.system.state.update(flags=8),
                       lambda h: setattr(h.system, 'controller_open', True),
                       lambda h: h._artifacts[next(iter(h._artifacts))].update(status='changed')):
            host = UpdateHost(removed=True); request = self.request(host)
            plan = provider.update_plan(host, request)
            mutate(host)
            with self.assertRaises((ValueError, KeyError)):
                provider.update_execute(host, request, plan['planSha256'])
            self.assertEqual(host.effects, [])

    def test_missing_or_changed_removal_evidence_cannot_be_prepared(self):
        for name in ('transaction.json', 'manager.json', 'application.json'):
            for mutation in ('missing', 'changed'):
                host = UpdateHost(removed=True)
                if mutation == 'missing': host.system.records.pop(name)
                else: host.system.records[name]['boot'] = 'foreign'
                with self.assertRaises(ValueError): provider.update_plan(host, self.request(host))
                self.assertEqual(host.effects, [])

    def test_interrupted_recovery_requires_a_new_plan_and_preserves_evidence(self):
        host = UpdateHost(removed=True); request = self.request(host)
        plan = provider.update_plan(host, request)
        with patch.object(host.system, 'unload_controller', side_effect=ValueError('interrupted')):
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                provider.update_execute(host, request, plan['planSha256'])
        self.assertEqual(host.system.journal['phase'], 'rollback-failed')
        with self.assertRaisesRegex(ValueError, 'stale update plan'):
            provider.update_execute(host, request, plan['planSha256'])
        plan = provider.update_plan(host, request)
        provider.update_execute(host, request, plan['planSha256'])
        self.assertFalse(host.system.controller)

    def test_public_capability_discovery_has_no_host_observations(self):
        with patch.object(sys, 'argv', ['runtime_provider.py', 'capabilities']), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(provider.main(object()), 0)
        self.assertEqual(json.loads(output.getvalue())['contract'], provider.UPDATE_CONTRACT)

    def test_installer_start_after_neutral_activation_allows_route_preflight(self):
        host = UpdateHost(active=False)
        host.system.application_active = True
        host.system.app['service']['MainPID'] = '99'
        # The immutable activation capture stays stopped; current service intent
        # can change independently after completion.
        self.assertFalse(host.system.journal['plan']['application']['wasActive'])
        result, _ = provider.inspect(host)
        self.assertEqual(result['result'], 'neutral_ready')
        self.assertFalse(provider.activation.neutral_ready(provider.activation.observe(host.system)),
                         'activation completion still requires exact captured restoration')
        for route in ('gpio4', 'gpio20'):
            with patch.object(provider.client, 'exchange', return_value={
                    'status': 'ok', 'state': {'preflightToken': 'a' * 64,
                    'controller': host.system.state}}):
                self.assertEqual(provider.route_plan(result, route)['route'], route)

    def test_post_reboot_neutral_update_uses_provider_retirement(self):
        host = UpdateHost()
        host.system.boot_id = '00000000-0000-0000-0000-000000000002'
        host.system.controller = host.system.socket_active = host.system.application_active = False
        plan = provider.update_plan(host, self.request(host))
        self.assertEqual(plan['plan']['action'], 'retire-activation')
        reply = provider.update_execute(host, self.request(host), plan['planSha256'])
        self.assertEqual(reply['status'], 'planned')
        self.assertIsNone(host.system.journal)

    def test_selected_routes_recover_before_neutral_update(self):
        for gpio in (4, 20):
            host = UpdateHost(); host.select_route(gpio)
            request = self.request(host)
            plan = provider.update_plan(host, request)
            self.assertEqual(plan['plan']['action'], 'recover-route')
            for _ in range(4):
                reply = provider.update_execute(host, request, plan['planSha256'])
                if reply['status'] == 'prepared': break
                plan = provider.update_plan(host, request)
            self.assertEqual(reply['status'], 'prepared')
            self.assertEqual(host.effects, ['recover-route', 'recover-activation', 'remove-deployment'])

    def test_installer_readiness_still_rejects_invalid_service_states(self):
        for changes in ({'fragment': '/tmp/foreign.service'}, {'active': 'activating'},
                        {'active': 'active', 'MainPID': '0'}, {'MainPID': 'unknown'},
                        {'load': 'masked', 'active': 'active'}):
            host = UpdateHost(); service = host.system.service
            def changed(name):
                original = service(name)
                return {**original, **changes} if name == provider.activation.APPLICATION_UNIT else original
            with patch.object(host.system, 'service', side_effect=changed):
                self.assertNotEqual(provider.inspect(host)[0]['result'], 'neutral_ready')


    def test_receipt_distinguishes_plan_digest_from_journal_byte_digest(self):
        host = UpdateHost()
        receipt = provider.installation_status(host)['receipt']
        self.assertEqual(receipt['deploymentPlanSha256'], provider.deployment.plan_hash(host.system.deployed))
        self.assertNotEqual(receipt['deploymentPlanSha256'], provider.admin.digest(host.system.deployment_raw))
        changed = copy.deepcopy(host.system.deployed)
        changed['application']['companion']['route'] = 'gpio20'
        with patch.object(host, 'deployment_removal_plan', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'deployment changed'):
                provider.installation_status(host)

    def test_passive_readiness_accepts_a_real_systemd_mask(self):
        host = UpdateHost(active=False, masked=True)
        service = host.system.service
        def masked(name):
            value = service(name)
            if name == provider.activation.APPLICATION_UNIT: value['fragment'] = '/dev/null'
            return value
        with patch.object(host.system, 'service', side_effect=masked):
            self.assertEqual(provider.inspect(host)[0]['result'], 'neutral_ready')

    def test_inverse_deployment_retries_every_durable_interruption(self):
        # Includes provider source, binding, unit-file self-removal and both
        # sides of the last-deployment/pending barrier transition.
        for offset in range(1, len(provider.deployment.DESTINATIONS) + 4):
            with self.subTest(write=offset):
                host = RemovalHost(); request = self.request(host)
                plan = provider.update_plan(host, request)
                host.files.crash = host.files.count + offset
                with self.assertRaises(OSError):
                    provider.update_execute(host, request, plan['planSha256'])
                host.files.crash = None
                retry = provider.update_plan(host, request)
                if retry['status'] != 'prepared':
                    reply = provider.update_execute(host, request, retry['planSha256'])
                    self.assertEqual(reply['status'], 'prepared')
                self.assertTrue(host.update_absent())
                self.assertEqual(host.files.restored, host.files.application)

    def test_interrupted_removal_preserves_restore_failure_and_foreign_bytes(self):
        host = RemovalHost(); request = self.request(host)
        plan = provider.update_plan(host, request)
        host.files.restore_fails = True
        with self.assertRaisesRegex(ValueError, 'restore failed'):
            provider.update_execute(host, request, plan['planSha256'])
        self.assertIsNotNone(host.files.read(str(provider.admin.STATE / 'deployment-pending.json')))
        host.files.restore_fails = False
        path = next(iter(provider.deployment.INVENTORY))
        host.files.values[path] = b'foreign'
        retry = provider.update_plan(host, request)
        writes = host.files.count
        with self.assertRaisesRegex(ValueError, 'destination changed'):
            provider.update_execute(host, request, retry['planSha256'])
        self.assertEqual(host.files.count, writes)
        host.files.values[path] = None
        retry = provider.update_plan(host, request)
        self.assertEqual(provider.update_execute(host, request, retry['planSha256'])['status'], 'prepared')

    def test_interrupted_inverse_refuses_remaining_route_journals(self):
        host = RemovalHost(); request = self.request(host)
        plan = provider.update_plan(host, request)
        host.files.restore_fails = True
        with self.assertRaisesRegex(ValueError, 'restore failed'):
            provider.update_execute(host, request, plan['planSha256'])
        self.assertIsNone(host.files.read(provider.deployment.BINDING))
        host.files.restore_fails = False
        for name in provider.activation.RETIREMENT_TRANSACTIONS:
            with self.subTest(journal=name):
                path = str(provider.admin.STATE / name)
                host.files.values[path] = b'{"foreign":true}'
                writes = host.files.count
                with self.assertRaises(ValueError):
                    retry = provider.update_plan(host, request)
                    provider.update_execute(host, request, retry['planSha256'])
                self.assertEqual(writes, host.files.count)
                self.assertEqual(host.files.values[path], b'{"foreign":true}')
                host.files.values[path] = None
        retry = provider.update_plan(host, request)
        self.assertEqual(provider.update_execute(host, request, retry['planSha256'])['status'], 'prepared')

    def test_absence_refuses_an_active_cached_manager_unit(self):
        host = RemovalHost(); request = self.request(host)
        plan = provider.update_plan(host, request)
        provider.update_execute(host, request, plan['planSha256'])
        services = host.services()
        services['rp1-gpclk-route-manager.socket']['active'] = 'active'
        with patch.object(host, 'services', return_value=services):
            with self.assertRaisesRegex(ValueError, 'absence is unproven'):
                provider.update_plan(host, request)

    def test_update_rejects_recorded_deployment_drift_before_effects(self):
        host = UpdateHost(); request = self.request(host)
        request['deploymentPlanSha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'deployment identity'):
            provider.update_plan(host, request)
        self.assertEqual(host.effects, [])


if __name__ == '__main__':
    __import__("nonempty_unittest").main()
