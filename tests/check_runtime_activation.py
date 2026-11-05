#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hardware-free neutral activation, idempotency, and recovery tests."""
import contextlib
import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_activation as activation
import runtime_binding
KERNEL = '6.18.34+rpt-rpi-2712'
import runtime_controller_admin as admin
import runtime_deployment as deployment


def captured(active=True, masked=False):
    return {'version': 1, 'wasActive': active, 'administratorMasked': masked,
        'service': {'LoadState': 'masked' if masked else 'loaded',
            'ActiveState': 'active' if active else 'inactive',
            'UnitFileState': 'masked' if masked else 'enabled',
            'MainPID': '42' if active else '0'},
        'companion': {'contract': 'wsprrypi-route-application-v1',
            'route': 'gpio4', 'transmit': False,
            'config': '/usr/local/etc/wsprrypi.ini'}}


class System:
    def __init__(self, application=None):
        self.app = application or captured()
        self.binding_value = {'schemaVersion': 2, 'contract': runtime_binding.CONTRACT,
            'productVersion': runtime_binding.PRODUCT_VERSION,
            'compatibilityIdentities': runtime_binding.COMPATIBILITY,
            'sourceCommit': 'a' * 40, 'kernel': KERNEL,
            'files': {path: admin.digest(path.encode()) for path in deployment.INVENTORY},
            'externalFiles': {path: 'b' * 64 for path in runtime_binding.EXTERNAL_PATHS},
            'uapiSha256': {}, 'controllerNoteSha256': 'c' * 64,
            'consumerNoteSha256': 'd' * 64}
        self.binding_value['uapiSha256'] = {
            'consumer': self.binding_value['files'][
                '/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_gpclk.h'],
            'controller': self.binding_value['files'][
                '/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_route_admin.h']}
        self.binding_value['artifactSetSha256'] = runtime_binding.canonical_digest(
            self.binding_value)
        self.raw = json.dumps(self.binding_value, sort_keys=True).encode()
        records = {path: {'before': None, 'after': deployment.encode(b'x')}
                   for path in deployment.DESTINATIONS}
        records[deployment.BINDING]['after'] = deployment.encode(self.raw)
        self.deployed = {'version': 2, 'application': copy.deepcopy(self.app),
                         'previousDeployment': None,
                         'files': records}
        self.deployment_raw = (json.dumps(self.deployed, sort_keys=True) + '\n').encode()
        self.journal = None
        self.records = {}
        self.controller = False
        self.consumer = False
        self.controller_open = False
        self.consumer_endpoint = False
        self.socket_active = False
        self.inhibited = True
        self.application_active = False
        self.boot_id = '00000000-0000-0000-0000-000000000001'
        self.state = {'session': 7, 'generation': 0, 'id': 0,
                      'error': 0, 'route': 0, 'flags': 0}
        self.events = []
        self.archives = []
        self.fail = None
        self.socket_unsafe = False
        self.unit_drift = False
        self.note_drift = False
        self.idle = None

    def read_record(self, path):
        return copy.deepcopy(self.journal if Path(path).name == 'activation.json'
                             else self.records.get(Path(path).name))
    def write_journal(self, value):
        activation.validate_journal(value)
        self.journal = copy.deepcopy(value); self.events.append('journal:' + value['phase'])
    def archive_journal(self, value): self.archives.append(copy.deepcopy(value))
    def retire_journal(self, expected):
        if self.journal != expected:
            raise ValueError('prior activation changed before retirement')
        self.events.append('retire-activation')
        self.journal = None
    def retire_transactions(self, expected):
        actual = {name: self.records.get(name)
                  for name in activation.RETIREMENT_TRANSACTIONS}
        if actual != expected:
            raise ValueError('prior transactions changed before retirement')
        if expected['application.json'] is not None:
            self.idle = None
        for name in activation.RETIREMENT_TRANSACTIONS:
            self.records.pop(name, None)
            self.events.append('retire:' + name)
    def retirement_idle(self, record):
        if self.idle is not None and record is None:
            raise ValueError('idle ownership')
        return None if self.idle is None else admin.digest(self.idle)
    def boot(self): return self.boot_id
    def binding(self): return self.raw, copy.deepcopy(self.binding_value)
    def last_deployment(self, raw):
        if raw != self.raw: raise ValueError('binding drift')
        return self.deployment_raw, copy.deepcopy(self.deployed)
    def module(self, name, note):
        loaded = self.controller if name == 'rp1_route_controller' else self.consumer
        return ({'status': 'loaded', 'buildNoteSha256': ('0' * 64 if self.note_drift else note),
                 'exact': not self.note_drift}
                if loaded else {'status': 'absent'})
    def endpoint(self, path, unused):
        if path == '/dev/rp1-route-admin' and self.controller:
            return {'status': 'owned', 'open': self.controller_open}
        if path == '/dev/rp1-gpclk' and self.consumer_endpoint:
            return {'status': 'owned', 'open': self.controller_open}
        return {'status': 'absent', 'open': False}
    def service(self, name):
        if name == activation.SOCKET_UNIT:
            return {'load': 'loaded', 'active': 'active' if self.socket_active else 'inactive',
                'enabled': 'enabled',
                'fragment': ('/tmp/foreign.socket' if self.unit_drift else
                    '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'),
                'MainPID': '0'}
        if name == activation.SERVICE_UNIT:
            return {'load': 'loaded', 'active': 'inactive', 'enabled': 'static',
                'fragment': '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service',
                'MainPID': '0'}
        return {'load': 'masked' if self.app['administratorMasked'] else 'loaded',
            'active': 'active' if self.application_active else 'inactive',
            'enabled': 'masked' if self.app['administratorMasked'] else 'enabled',
            'fragment': '/usr/lib/systemd/system/wsprrypi.service',
            'MainPID': self.app['service']['MainPID'] if self.application_active else '0'}
    def manager_socket(self):
        return {'status': ('unsafe' if self.socket_unsafe else 'owned')
                if self.socket_active else 'absent'}
    def inhibitor(self): return self.inhibited
    def controller_state(self): return copy.deepcopy(self.state)
    def load_controller(self):
        self.events.append('load-controller')
        if self.fail == 'load': raise ValueError('load failed')
        self.controller = True
    def unload_controller(self): self.events.append('unload-controller'); self.controller = False
    def start_socket(self):
        self.events.append('start-socket')
        if self.fail == 'socket': raise ValueError('socket failed')
        self.socket_active = True
    def stop_socket(self): self.events.append('stop-socket'); self.socket_active = False
    def manager_query(self):
        self.events.append('manager-query')
        if self.fail == 'manager': raise ValueError('manager failed')
        return {'status': 'ok', 'state': {'activeRoute': None,
            'controller': copy.deepcopy(self.state),
            'bindingSha256': admin.digest(self.raw)}}
    def restore_application(self, record):
        self.events.append('restore-application')
        if self.fail == 'restore': raise ValueError('restore failed')
        self.inhibited = False
        self.application_active = record['wasActive']
        phase = ('restored' if record['wasActive'] else
                 'administrator-masked' if record['administratorMasked'] else 'stopped')
        return {'phase': phase, 'service': record['service'], 'companion': record['companion']}
    def inhibit_application(self):
        self.events.append('inhibit-application'); self.inhibited = True
        self.application_active = False
        if self.fail == 'inhibit-after':
            raise ValueError('inhibition interrupted after service stop')
        if self.fail == 'journal-drift-after-inhibit':
            self.journal['requestId'] = '00000000-0000-0000-0000-000000000099'
        if self.fail == 'transaction-after-inhibit':
            self.records['transaction.json'] = {'pending': True}

    def capture_application(self):
        result = copy.deepcopy(self.app)
        result['wasActive'] = self.application_active
        result['service']['ActiveState'] = ('active' if self.application_active
                                            else 'inactive')
        result['service']['MainPID'] = (self.app['service']['MainPID']
                                        if self.application_active else '0')
        return result


def lock():
    return contextlib.nullcontext()


class SocketGroupTests(unittest.TestCase):
    def test_missing_group_created_and_verified_before_socket_start(self):
        events = []
        group = SimpleNamespace(gr_gid=123)
        def lookup(name):
            self.assertEqual(name, activation.SOCKET_GROUP)
            events.append('lookup')
            if len(events) == 1:
                raise KeyError(name)
            return group
        with patch.object(activation.grp, 'getgrnam', side_effect=lookup), \
             patch.object(admin, 'run', side_effect=lambda args: events.append(args)):
            activation.Linux().start_socket()
        self.assertEqual(events, ['lookup',
            ('/usr/sbin/addgroup', '--system', 'rp1-gpclk-route'), 'lookup',
            ('/usr/bin/systemctl', 'start', activation.SOCKET_UNIT)])

    def test_existing_group_reused_without_modification(self):
        with patch.object(activation.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=456)) as lookup, \
             patch.object(admin, 'run') as command:
            activation.Linux().start_socket()
            activation.Linux().start_socket()
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(command.call_args_list, [call(
            ('/usr/bin/systemctl', 'start', activation.SOCKET_UNIT))] * 2)

    def test_activation_planning_is_read_only_and_repeat_needs_no_account_effect(self):
        system = System()
        def command(args):
            if args[0] == '/usr/bin/systemctl':
                system.socket_active = True
        with patch.object(system, 'start_socket', side_effect=activation.Linux().start_socket), \
             patch.object(activation.grp, 'getgrnam', side_effect=[KeyError(), SimpleNamespace(gr_gid=123)]) as lookup, \
             patch.object(admin, 'run', side_effect=command) as run:
            plan = activation.activation_plan(system)
            lookup.assert_not_called()
            run.assert_not_called()
            result = activation.ensure(system, plan, activation.plan_digest(plan), lock)
            self.assertEqual(result['status'], 'activated-neutral')
            repeat = activation.activation_plan(system)
            self.assertEqual(activation.ensure(system, repeat, activation.plan_digest(repeat), lock)
                             ['status'], 'idempotent-no-change')
        self.assertEqual(run.call_args_list, [
            call(('/usr/sbin/addgroup', '--system', activation.SOCKET_GROUP)),
            call(('/usr/bin/systemctl', 'start', activation.SOCKET_UNIT))])
        self.assertTrue(system.application_active)
        self.assertFalse(system.consumer)

    def test_failed_group_creation_retains_inhibition_and_allows_neutral_recovery(self):
        system = System()
        plan = activation.activation_plan(system)
        with patch.object(system, 'start_socket', side_effect=activation.Linux().start_socket), \
             patch.object(activation.grp, 'getgrnam', side_effect=KeyError), \
             patch.object(admin, 'run', side_effect=ValueError('group creation failed')):
            with self.assertRaisesRegex(ValueError, 'group creation failed'):
                activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertEqual(system.journal['phase'], 'activation-failed')
        self.assertTrue(system.inhibited)
        self.assertFalse(system.application_active)
        self.assertFalse(system.socket_active)
        self.assertFalse(system.consumer)
        recovery = activation.recovery_plan(system)
        activation.ensure_recovery(system, recovery, activation.plan_digest(recovery), lock)
        self.assertEqual(system.journal['phase'], 'recovered-inhibited')
        self.assertFalse(system.controller)
        self.assertTrue(system.inhibited)

    def test_failed_group_creation_prevents_socket_start(self):
        with patch.object(activation.grp, 'getgrnam', side_effect=KeyError), \
             patch.object(admin, 'run', side_effect=ValueError('group creation failed')) as command:
            with self.assertRaisesRegex(ValueError, 'group creation failed'):
                activation.Linux().start_socket()
        command.assert_called_once_with(('/usr/sbin/addgroup', '--system', activation.SOCKET_GROUP))

    def test_group_still_absent_after_creation_prevents_socket_start(self):
        with patch.object(activation.grp, 'getgrnam', side_effect=KeyError), \
             patch.object(admin, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'service group was not created'):
                activation.Linux().start_socket()
        command.assert_called_once_with(('/usr/sbin/addgroup', '--system', activation.SOCKET_GROUP))


class Tests(unittest.TestCase):
    def rebooted_route(self, gpio=4, active=True, masked=False):
        """Minimal terminal chain matching the reproduced normal-reboot failure."""
        system = System(captured(active, masked))
        plan = activation.activation_plan(system)
        activation.ensure(system, plan, activation.plan_digest(plan), lock)
        binding = admin.digest(system.raw)
        target = 1 if gpio == 4 else 2
        state = dict(system.state, generation=1, id=1, route=target, flags=6)
        route = dict(version=1, boot=system.boot_id, session=state['session'],
            binding=binding, request='00000000-0000-0000-0000-000000000010',
            target=target, phase='complete-inhibited', observation=state)
        app = dict(version=1, boot=system.boot_id, binding=binding,
            requestId='switch-request-0001', fingerprint='e'*64,
            route='gpio'+str(gpio), token='00000000-0000-0000-0000-000000000011',
            wasActive=active, administratorMasked=masked,
            phase='restored' if active else 'administrator-masked' if masked else 'stopped',
            controller=state, ready={'pid':42, 'route':'gpio'+str(gpio)} if active else None,
            previousIdle=None)
        response = dict(schemaVersion=3, contract='rp1-gpclk-route-manager-runtime',
            operation='switch', status='complete-inhibited', state=dict(
                bootId=system.boot_id, bindingSha256=binding, controller=state,
                pendingTransaction=route, activeRoute=app['route'], outputEnabled=False,
                applicationInhibited=True, applicationRestoration=True,
                application=dict(app, phase='captured', controller=None, ready=None)))
        manager = dict(requestId=app['requestId'], actor='offline.test',
            fingerprint=app['fingerprint'], complete=True, controller=state,
            boot=system.boot_id, binding=binding, response=response)
        system.records.update({'transaction.json':route, 'manager.json':manager,
                               'application.json':app})
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = system.socket_active = False
        system.state['session'] = 8
        system.app['companion']['route'] = app['route']
        system.records = copy.deepcopy(system.records)
        return system

    def test_normal_reboot_terminal_route_reactivation(self):
        for gpio in (4, 20):
            with self.subTest(gpio=gpio):
                system = self.rebooted_route(gpio)
                before = copy.deepcopy(system.__dict__)
                plan = activation.activation_plan(system)
                self.assertEqual(system.__dict__, before, 'planning must be read-only')
                self.assertEqual(plan['activationContext'], 'post-reboot')
                activation.ensure(system, plan, activation.plan_digest(plan), lock)
                self.assertTrue(activation.neutral_ready(activation.observe(system)))
                self.assertEqual(system.state['session'], 8)
                self.assertFalse(system.consumer)
                self.assertFalse(system.records)

    def test_reboot_after_later_start_acknowledges_stopped_or_masked_route(self):
        for gpio in (4, 20):
            for masked in (False, True):
                for current_active in (False, True):
                    with self.subTest(gpio=gpio, masked=masked, active=current_active):
                        system = self.rebooted_route(gpio, active=False, masked=masked)
                        app = system.records['application.json']
                        app.update(phase='restored', ready={'pid': 99, 'route': app['route']})
                        # acknowledge() preserves the original capture even when
                        # an explicit later start completes route readiness.
                        system.app = captured(current_active, False)
                        system.app['companion']['route'] = app['route']
                        system.application_active = current_active
                        plan = activation.activation_plan(system)
                        self.assertEqual(plan['application']['wasActive'], current_active)
                        activation.ensure(system, plan, activation.plan_digest(plan), lock)
                        self.assertEqual(system.application_active, current_active)
                        self.assertTrue(activation.neutral_ready(activation.observe(system)))

    def test_reboot_rejects_restored_route_without_readiness_acknowledgement(self):
        system = self.rebooted_route(active=False)
        system.records['application.json']['phase'] = 'restored'
        with self.assertRaisesRegex(ValueError, 'terminal route restoration'):
            activation.activation_plan(system)

    def test_reboot_admission_rejects_incomplete_conflicting_or_pending_history(self):
        mutations = [lambda s, n=n: s.records.pop(n)
                     for n in activation.RETIREMENT_TRANSACTIONS]
        mutations += [
            lambda s: s.records.update({'deployment-pending.json': {'pending': True}}),
            lambda s: s.records['application.json'].update(phase='restoration-failed'),
            lambda s: s.records['application.json'].update(route='gpio20'),
            lambda s: s.records['application.json'].update(wasActive=False),
            lambda s: s.records['manager.json'].update(complete=False),
            lambda s: s.records['manager.json']['response']['state'].update(outputEnabled=True),
            lambda s: s.records['manager.json']['response']['state'].update(activeRoute='gpio20'),
            lambda s: s.records['application.json'].update(token='00000000-0000-0000-0000-000000000099'),
            lambda s: s.records['manager.json'].update(binding='0'*64),
            lambda s: s.records['transaction.json'].update(boot=s.boot_id),
            lambda s: s.records['transaction.json'].update(session=99),
            lambda s: setattr(s, 'raw', s.raw + b' '),
            lambda s: setattr(s, 'deployment_raw', s.deployment_raw + b' '),
            lambda s: s.binding_value.update(artifactSetSha256='0'*64),
            lambda s: setattr(s, 'consumer', True),
            lambda s: setattr(s, 'consumer_endpoint', True),
            lambda s: setattr(s, 'controller', True),
            lambda s: setattr(s, 'socket_active', True),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                system = self.rebooted_route(); mutate(system)
                before = copy.deepcopy(system.__dict__)
                with self.assertRaises(ValueError): activation.activation_plan(system)
                self.assertEqual(system.__dict__, before)

    def test_reboot_retirement_interruptions_preserve_current_intent_and_evidence(self):
        # Stop after each durable journal/archive/inhibitor/retirement mutation.
        for gpio in (4, 20):
            for active, masked in ((True, False), (False, False), (False, True)):
                for boundary in ('archive', 'prepare', 'inhibit', *activation.RETIREMENT_TRANSACTIONS):
                    with self.subTest(gpio=gpio, active=active, masked=masked, boundary=boundary):
                        system = self.rebooted_route(gpio)
                        # Historical active intent differs from the current administrator choice.
                        system.app = captured(active, masked)
                        system.app['companion']['route'] = 'gpio'+str(gpio)
                        system.application_active = active
                        original = copy.deepcopy(system.records)
                        plan = activation.activation_plan(system)
                        archive, write, inhibit = system.archive_journal, system.write_journal, system.inhibit_application
                        def after_archive(value):
                            archive(value)
                            if boundary == 'archive': raise KeyboardInterrupt()
                        def after_write(value):
                            write(value)
                            if boundary == 'prepare' and value['phase'] == 'reboot-prepare': raise KeyboardInterrupt()
                        def after_inhibit():
                            inhibit()
                            if boundary == 'inhibit': raise KeyboardInterrupt()
                        def retire(expected):
                            for name in activation.RETIREMENT_TRANSACTIONS:
                                system.records.pop(name, None)
                                if boundary == name: raise KeyboardInterrupt()
                        with patch.object(system, 'archive_journal', after_archive), \
                             patch.object(system, 'write_journal', after_write), \
                             patch.object(system, 'inhibit_application', after_inhibit), \
                             patch.object(system, 'retire_transactions', retire):
                            with self.assertRaises(KeyboardInterrupt):
                                activation.ensure(system, plan, activation.plan_digest(plan), lock)
                        retry = activation.activation_plan(system)
                        self.assertEqual(retry['application']['wasActive'], active)
                        self.assertEqual(retry['application']['administratorMasked'], masked)
                        activation.ensure(system, retry, activation.plan_digest(retry), lock)
                        self.assertEqual(system.application_active, active)
                        self.assertEqual(system.journal['plan']['rebootEvidence']['transactions'], original)
                        self.assertTrue(activation.neutral_ready(activation.observe(system)))
                        self.assertFalse(system.consumer)

    def test_reboot_rejects_plan_and_checkpoint_races(self):
        for phase in ('before', 'checkpoint'):
            for mutate in (lambda s: s.records['application.json'].update(token='00000000-0000-0000-0000-000000000099'),
                           lambda s: s.app['companion'].update(route='gpio20'),
                           lambda s: s.app['companion'].update(transmit=True),
                           lambda s: setattr(s, 'raw', s.raw+b' ')):
                with self.subTest(phase=phase, mutate=mutate):
                    system = self.rebooted_route(); plan = activation.activation_plan(system)
                    if phase == 'checkpoint':
                        system.fail = 'inhibit-after'
                        with self.assertRaises(ValueError): activation.ensure(system, plan, activation.plan_digest(plan), lock)
                        system.fail = None
                    mutate(system)
                    before = copy.deepcopy(system.__dict__)
                    with self.assertRaises(ValueError): activation.ensure(system, plan, activation.plan_digest(plan), lock)
                    self.assertEqual(system.__dict__, before)

    def test_reboot_rejects_stale_controller_session_and_repeats_with_fresh_sessions(self):
        system = self.rebooted_route()
        system.state['session'] = 7
        plan = activation.activation_plan(system)
        with self.assertRaisesRegex(ValueError, 'exact neutral state'):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertTrue(system.inhibited)
        system = self.rebooted_route()
        for index in range(3):
            plan = activation.activation_plan(system)
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
            repeated = activation.activation_plan(system)
            self.assertEqual(activation.ensure(system, repeated, activation.plan_digest(repeated), lock)['status'],
                             'idempotent-no-change')
            self.assertTrue(activation.neutral_ready(activation.observe(system)))
            system.boot_id = '00000000-0000-0000-0000-00000000000'+str(index+3)
            system.state['session'] += 1
            system.controller = system.socket_active = False

    def test_reboot_activation_effect_interruptions_recover_with_current_intent(self):
        for gpio in (4, 20):
            for active, masked in ((True, False), (False, False), (False, True)):
                for boundary in ('load_controller', 'start_socket', 'manager_query', 'restore_application'):
                    with self.subTest(gpio=gpio, active=active, masked=masked, boundary=boundary):
                        system = self.rebooted_route(gpio)
                        system.app = captured(active, masked)
                        system.app['companion']['route'] = 'gpio'+str(gpio)
                        system.application_active = active
                        plan = activation.activation_plan(system)
                        effect = getattr(system, boundary)
                        def interrupted(*args):
                            effect(*args)
                            raise KeyboardInterrupt()
                        with patch.object(system, boundary, interrupted):
                            with self.assertRaises(KeyboardInterrupt):
                                activation.ensure(system, plan, activation.plan_digest(plan), lock)
                        self.assertTrue(system.inhibited)
                        recovery = activation.recovery_plan(system)
                        activation.ensure_recovery(system, recovery, activation.plan_digest(recovery), lock)
                        retry = activation.activation_plan(system)
                        self.assertEqual(retry['application'], plan['application'])
                        system.state['session'] += 1
                        activation.ensure(system, retry, activation.plan_digest(retry), lock)
                        self.assertEqual(system.application_active, active)
                        self.assertFalse(system.consumer)
                        self.assertTrue(activation.neutral_ready(activation.observe(system)))

    def test_linux_binding_rejects_running_kernel_mismatch_before_module_effects(self):
        system = activation.Linux()
        with patch.object(system, 'trusted_file'), \
             patch.object(admin, 'read_regular', return_value=b'{}'), \
             patch.object(activation.runtime_binding, 'validate', return_value={'kernel': 'other-kernel'}), \
             patch.object(admin, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'running kernel'):
                system.binding()
        command.assert_not_called()

    def test_reboot_archival_race_preserves_new_state_before_checkpoint(self):
        system = self.rebooted_route(); plan = activation.activation_plan(system)
        archive = system.archive_journal
        def changed(value):
            archive(value)
            system.journal['requestId'] = '00000000-0000-0000-0000-000000000099'
        with patch.object(system, 'archive_journal', changed):
            with self.assertRaisesRegex(ValueError, 'changed during archival'):
                activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertEqual(system.journal['requestId'], '00000000-0000-0000-0000-000000000099')
        self.assertFalse(system.inhibited)

    def test_archive_publication_is_single_linked_and_retryable_after_interruption(self):
        record = self.rebooted_route().journal
        system = activation.Linux()
        def trusted(path, mode):
            info = Path(path).lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != mode or info.st_nlink != 1:
                raise ValueError('unsafe archive')
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(admin, 'STATE', Path(directory)), \
             patch.object(system, 'trusted_file', trusted), \
             patch.object(admin, 'read_regular', side_effect=lambda path, *unused: Path(path).read_bytes()), \
             patch.object(admin, 'fsync_dir', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): system.archive_journal(record)
            paths = list(Path(directory).iterdir())
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].stat().st_nlink, 1)
            system.archive_journal(record)
            self.assertEqual(json.loads(paths[0].read_text()), record)

    def test_competing_activation_is_rejected_while_manager_query_releases_lock(self):
        system = self.rebooted_route(); plan = activation.activation_plan(system)
        query = system.manager_query
        def concurrent():
            before = copy.deepcopy(system.__dict__)
            with self.assertRaises(ValueError):
                activation.ensure(system, plan, activation.plan_digest(plan), lock)
            self.assertEqual(system.__dict__, before)
            return query()
        with patch.object(system, 'manager_query', concurrent):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertTrue(activation.neutral_ready(activation.observe(system)))

    def recovered_route(self, system, *, with_application=True, removal=False):
        binding = admin.digest(system.raw)
        predecessor = {'session': system.state['session'], 'generation': 1,
            'id': 9, 'error': 0, 'route': 1,
            'flags': admin.CONSUMER | admin.PINNED}
        system.state = {'session': system.state['session'], 'generation': 2,
            'id': 0, 'error': 0, 'route': 0, 'flags': 0}
        route = {'version': 1, 'boot': system.boot_id,
            'session': system.state['session'], 'binding': binding,
            'request': '00000000-0000-0000-0000-000000000010',
            'target': 1, 'phase': 'recovered-inhibited',
            'observation': copy.deepcopy(system.state)}
        response = {'schemaVersion': 3,
            'contract': 'rp1-gpclk-route-manager-runtime',
            'operation': 'recover', 'status': 'recovered-inhibited',
            'state': {'bootId': system.boot_id, 'bindingSha256': binding,
                'controller': copy.deepcopy(system.state),
                'pendingTransaction': copy.deepcopy(route)}}
        manager = {'requestId': 'recovery-0001', 'actor': 'offline.test',
            'fingerprint': 'f' * 64, 'complete': True,
            'controller': copy.deepcopy(system.state), 'boot': system.boot_id,
            'binding': binding, 'response': response}
        system.records.update({'transaction.json': route,
                               'manager.json': manager})
        if with_application:
            record = {
                'version': 1, 'boot': system.boot_id, 'binding': binding,
                'requestId': 'switch-request-0001', 'fingerprint': 'e' * 64,
                'route': 'gpio4',
                'token': '00000000-0000-0000-0000-000000000011',
                'wasActive': True, 'administratorMasked': False,
                'phase': 'route-recovered', 'controller': predecessor,
                'ready': {'pid': 42, 'route': 'gpio4'}, 'previousIdle': None}
            if removal:
                record.update(requestId=manager['requestId'], operation='remove',
                              phase='neutral-restored', controller=None,
                              ready=None)
                captured = copy.deepcopy(record)
                captured['phase'] = 'captured'
                response['state']['application'] = captured
            system.records['application.json'] = record
        system.inhibited = not removal
        system.application_active = removal

    def test_linux_controller_status_uses_and_requires_reserved0_zero(self):
        system = activation.Linux()
        def ioctl(fd, command, data, mutate):
            self.assertEqual((fd, command, mutate), (99, admin.IOCTL, True))
            self.assertEqual(admin.FORMAT.unpack(data),
                (0, admin.STATUS, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            data[:] = admin.FORMAT.pack(0, 0, 0, 0, 7, 0, 0, 0, 0, 0, 0, 0)
        device = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_uid=0, st_gid=0)
        with patch.object(activation.os, 'open', return_value=99), \
             patch.object(activation.os, 'fstat', return_value=device), \
             patch.object(activation.os, 'close'), \
             patch.object(activation.fcntl, 'ioctl', side_effect=ioctl):
            self.assertEqual(system.controller_state(),
                {'session': 7, 'generation': 0, 'id': 0,
                 'error': 0, 'route': 0, 'flags': 0})

    def test_linux_controller_status_rejects_nonzero_reserved0_response(self):
        system = activation.Linux()
        def ioctl(unused_fd, unused_command, data, unused_mutate):
            data[:] = admin.FORMAT.pack(1, 0, 0, 0, 7, 0, 0, 0, 0, 0, 0, 0)
        device = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_uid=0, st_gid=0)
        with patch.object(activation.os, 'open', return_value=99), \
             patch.object(activation.os, 'fstat', return_value=device), \
             patch.object(activation.os, 'close'), \
             patch.object(activation.fcntl, 'ioctl', side_effect=ioctl):
            with self.assertRaisesRegex(ValueError, 'response schema'):
                system.controller_state()

    def test_linux_observes_main_pid_only_for_application_service(self):
        outputs = {
            activation.SOCKET_UNIT:
                'LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n'
                'FragmentPath=/usr/lib/systemd/system/'
                'rp1-gpclk-route-manager.socket\n',
            admin.ROUTE_MANAGER_TEMPLATE_PROBE:
                'LoadState=loaded\nActiveState=inactive\nUnitFileState=static\n'
                'FragmentPath=/usr/lib/systemd/system/'
                'rp1-gpclk-route-manager@.service\n',
            activation.APPLICATION_UNIT:
                'MainPID=0\nLoadState=loaded\nActiveState=inactive\n'
                'UnitFileState=enabled\n'
                'FragmentPath=/etc/systemd/system/wsprrypi.service\n',
        }
        commands = []
        def observe(argv):
            commands.append(argv)
            return outputs[argv[2]]
        system = object.__new__(activation.Linux)
        with patch.object(admin, 'run', side_effect=observe):
            socket = system.service(activation.SOCKET_UNIT)
            manager = system.service(activation.SERVICE_UNIT)
            application = system.service(activation.APPLICATION_UNIT)
        self.assertNotIn('MainPID', socket)
        self.assertNotIn('MainPID', manager)
        self.assertEqual(application['MainPID'], '0')
        self.assertNotIn('MainPID', commands[0][-1])
        self.assertNotIn('MainPID', commands[1][-1])
        self.assertIn('MainPID', commands[2][-1])
        outputs[activation.APPLICATION_UNIT] = outputs[
            activation.APPLICATION_UNIT].replace('MainPID=0\n', '')
        with patch.object(admin, 'run', side_effect=observe):
            with self.assertRaisesRegex(ValueError, 'service observation'):
                system.service(activation.APPLICATION_UNIT)
        with patch.object(admin, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'unsupported activation service'):
                system.service('foreign.service')
        command.assert_not_called()

    def test_plan_and_successful_neutral_activation(self):
        system = System()
        plan = activation.activation_plan(system)
        result = activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertEqual(result['status'], 'activated-neutral')
        self.assertTrue(activation.neutral_ready(activation.observe(system)))
        self.assertFalse(system.consumer)
        self.assertEqual(system.state['route'], 0)
        self.assertNotIn('load-consumer', system.events)

    def test_exact_repeat_is_true_noop(self):
        system = System(); plan = activation.activation_plan(system)
        activation.ensure(system, plan, activation.plan_digest(plan), lock)
        before = copy.deepcopy(system.events)
        repeated = activation.activation_plan(system)
        result = activation.ensure(system, repeated, activation.plan_digest(repeated), lock)
        self.assertEqual(result['status'], 'idempotent-no-change')
        self.assertEqual(system.events, before)

    def test_completed_neutral_activation_can_restart_after_clean_reboot(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        prior = copy.deepcopy(system.journal)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        plan = activation.activation_plan(system)
        self.assertEqual(plan['version'], 3)
        self.assertEqual(plan['activationContext'], 'post-reboot')
        self.assertFalse(plan['applicationInhibited'])
        self.assertEqual(plan['previousActivationSha256'],
                         admin.digest(activation.canonical(prior)))
        result = activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertEqual(result['status'], 'activated-neutral')
        self.assertEqual(system.archives, [prior])
        self.assertTrue(activation.neutral_ready(activation.observe(system)))
        self.assertFalse(system.consumer)

    def test_prior_boot_terminal_activation_can_be_retired_for_migration(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        for name in ('activationContext', 'applicationInhibited'):
            system.journal['plan'].pop(name)
        system.journal['plan']['version'] = 1
        system.journal['planSha256'] = activation.plan_digest(system.journal['plan'])
        prior = copy.deepcopy(system.journal)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        plan = activation.retirement_plan(system)
        self.assertEqual(plan['operation'], 'retire-post-reboot-activation')
        self.assertEqual(plan['activationJournalSha256'],
                         admin.digest(activation.canonical(prior)))
        self.assertEqual(plan['transactionJournalSha256'], {
            name: None for name in activation.RETIREMENT_TRANSACTIONS})
        self.assertIsNone(plan['applicationIdleSha256'])
        result = activation.retire(system, plan, activation.plan_digest(plan), lock)
        self.assertEqual(result['status'], 'retired-post-reboot-activation')
        self.assertEqual(system.archives, [])
        self.assertIsNone(system.journal)

    def test_prior_boot_route_journals_are_digest_bound_and_retired(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        prior_boot = system.boot_id
        binding = admin.digest(system.raw)
        state = {'session': 7, 'generation': 1, 'id': 9, 'error': 0,
                 'route': 1, 'flags': 6}
        route = {'version': 1, 'boot': prior_boot, 'session': 7,
                 'binding': binding,
                 'request': '00000000-0000-0000-0000-000000000001',
                 'target': 1, 'phase': 'complete-inhibited',
                 'observation': state}
        application_record = {'version': 1, 'boot': prior_boot,
            'binding': binding, 'requestId': 'request-0001',
            'fingerprint': 'f' * 64, 'route': 'gpio4',
            'token': '00000000-0000-0000-0000-000000000002',
            'wasActive': True, 'administratorMasked': False,
            'phase': 'restoration-failed', 'controller': state, 'ready': None,
            'previousIdle': None, 'error': 'readiness not acknowledged'}
        response = {'schemaVersion': 3,
            'contract': 'rp1-gpclk-route-manager-runtime',
            'operation': 'switch', 'status': 'complete-inhibited',
            'state': {'bootId': prior_boot, 'bindingSha256': binding,
                      'controller': state, 'pendingTransaction': route}}
        manager = {'requestId': 'request-0001', 'actor': 'offline.test',
            'fingerprint': 'f' * 64, 'complete': True, 'controller': state,
            'boot': prior_boot, 'binding': binding, 'response': response}
        system.records.update({'transaction.json': route,
                               'manager.json': manager,
                               'application.json': application_record})
        system.idle = __import__('runtime_application').idle_bytes(application_record)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        plan = activation.retirement_plan(system)
        self.assertEqual(plan['transactionJournalSha256'], {
            name: admin.digest(activation.canonical(system.records[name]))
            for name in activation.RETIREMENT_TRANSACTIONS})
        self.assertEqual(plan['applicationIdleSha256'], admin.digest(system.idle))
        for count in range(len(activation.RETIREMENT_TRANSACTIONS) + 1):
            interrupted = copy.deepcopy(system)
            for name in activation.RETIREMENT_TRANSACTIONS[:count]:
                interrupted.records.pop(name)
                if name == 'application.json':
                    interrupted.idle = None
            retry = activation.retirement_plan(interrupted)
            self.assertEqual(retry['transactionJournalSha256'], {
                name: (None if name not in interrupted.records else
                    admin.digest(activation.canonical(interrupted.records[name])))
                for name in activation.RETIREMENT_TRANSACTIONS})
        activation.retire(system, plan, activation.plan_digest(plan), lock)
        self.assertIsNone(system.journal)
        self.assertFalse(any(name in system.records
                             for name in activation.RETIREMENT_TRANSACTIONS))
        self.assertIsNone(system.idle)
        self.assertLess(system.events.index('retire:transaction.json'),
                        system.events.index('retire-activation'))

    def test_prior_boot_route_retirement_rejects_identity_drift(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        system.records['transaction.json'] = {'pending': True}
        with self.assertRaisesRegex(ValueError, 'not attributable'):
            activation.retirement_plan(system)

    def test_post_reboot_retirement_rejects_drift_before_effects(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        plan = activation.retirement_plan(system)
        system.journal['requestId'] = '00000000-0000-0000-0000-000000000099'
        with self.assertRaisesRegex(ValueError, 'changed since review'):
            activation.retire(system, plan, activation.plan_digest(plan), lock)
        self.assertNotIn('retire-activation', system.events)
        self.assertEqual(system.archives, [])

    def test_post_reboot_retirement_rejects_journal_race_after_replan(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        plan = activation.retirement_plan(system)
        original = system.read_record
        activation_reads = 0
        def raced(path):
            nonlocal activation_reads
            if Path(path).name == 'activation.json':
                activation_reads += 1
                if activation_reads == 2:
                    system.journal['requestId'] = (
                        '00000000-0000-0000-0000-000000000099')
            return original(path)
        system.read_record = raced
        with self.assertRaisesRegex(ValueError, 'changed after retirement review'):
            activation.retire(system, plan, activation.plan_digest(plan), lock)
        self.assertNotIn('retire-activation', system.events)

    def test_same_boot_terminal_activation_cannot_be_retired(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        with self.assertRaises(ValueError):
            activation.retirement_plan(system)

    def test_post_reboot_inhibition_interruption_is_safely_retryable(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        prior = copy.deepcopy(system.journal)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        system.fail = 'inhibit-after'
        plan = activation.activation_plan(system)
        with self.assertRaisesRegex(ValueError, 'inhibition interrupted'):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertTrue(system.inhibited)
        self.assertFalse(system.application_active)
        self.assertEqual(system.journal['phase'], 'reboot-prepare')
        self.assertEqual(system.archives, [prior])
        system.fail = None
        retry = activation.activation_plan(system)
        self.assertEqual(retry['activationContext'], 'post-reboot')
        self.assertEqual(retry, plan)
        self.assertTrue(retry['application']['wasActive'])
        activation.ensure(system, retry, activation.plan_digest(retry), lock)
        self.assertTrue(activation.neutral_ready(activation.observe(system)))

    def test_post_reboot_inhibition_rechecks_journal_and_transactions(self):
        for failure in ('journal-drift-after-inhibit', 'transaction-after-inhibit'):
            with self.subTest(failure=failure):
                system = System(); initial = activation.activation_plan(system)
                activation.ensure(system, initial, activation.plan_digest(initial), lock)
                system.boot_id = '00000000-0000-0000-0000-000000000002'
                system.controller = False
                system.socket_active = False
                plan = activation.activation_plan(system)
                system.fail = failure
                with self.assertRaisesRegex(ValueError, 'exact inactive state|transaction changed'):
                    activation.ensure(system, plan, activation.plan_digest(plan), lock)
                self.assertFalse(system.controller or system.socket_active)
                self.assertEqual(len(system.archives), 1)

    def test_post_reboot_reactivation_rejects_unsafe_or_changed_state(self):
        def rebooted():
            system = System(); plan = activation.activation_plan(system)
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
            system.boot_id = '00000000-0000-0000-0000-000000000002'
            system.controller = False
            system.socket_active = False
            return system

        mutations = (
            lambda value: setattr(value, 'consumer', True),
            lambda value: setattr(value, 'consumer_endpoint', True),
            lambda value: setattr(value, 'controller', True),
            lambda value: setattr(value, 'socket_active', True),
            lambda value: value.records.update({'transaction.json': {'pending': True}}),
            lambda value: value.journal['manager']['state'].update(bindingSha256='0' * 64),
            lambda value: value.journal['application'].pop('service'),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                system = rebooted(); mutate(system)
                with self.assertRaises(ValueError):
                    activation.activation_plan(system)

    def test_post_reboot_plan_preserves_current_stopped_service_intent(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        system.application_active = False
        plan = activation.activation_plan(system)
        self.assertFalse(plan['application']['wasActive'])
        activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertFalse(system.application_active)
        self.assertTrue(activation.neutral_ready(activation.observe(system)))

    def test_same_boot_terminal_activation_still_requires_recovery(self):
        system = System(); plan = activation.activation_plan(system)
        activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        system.application_active = False
        system.inhibited = True
        with self.assertRaisesRegex(ValueError, 'evidence differs'):
            activation.activation_plan(system)

    def test_version_one_activation_plan_remains_valid(self):
        plan = activation.activation_plan(System())
        legacy = {name: value for name, value in plan.items()
                  if name not in ('activationContext', 'applicationInhibited')}
        legacy['version'] = 1
        self.assertEqual(activation.validate_plan(legacy), legacy)

    def test_version_two_activation_context_must_be_consistent(self):
        plan = activation.activation_plan(System())
        for field, value in (('activationContext', 'idempotent'),
                             ('applicationInhibited', False),
                             ('previousActivationSha256', '0' * 64)):
            with self.subTest(field=field):
                changed = copy.deepcopy(plan); changed[field] = value
                with self.assertRaisesRegex(ValueError, 'context'):
                    activation.validate_plan(changed)

    def test_malformed_completed_manager_evidence_fails_closed(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        system.journal['manager']['state'] = []
        with self.assertRaisesRegex(ValueError, 'evidence differs'):
            activation.activation_plan(system)

    def test_digest_and_plan_drift_fail_before_effects(self):
        system = System(); plan = activation.activation_plan(system)
        with self.assertRaisesRegex(ValueError, 'digest'):
            activation.ensure(system, plan, '0' * 64, lock)
        system.socket_active = True
        with self.assertRaisesRegex(ValueError, 'changed'):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertNotIn('load-controller', system.events)

    def test_consumer_endpoint_open_controller_and_route_conflicts(self):
        mutations = (
            lambda value: setattr(value, 'consumer', True),
            lambda value: setattr(value, 'consumer_endpoint', True),
            lambda value: (setattr(value, 'controller', True),
                           setattr(value, 'controller_open', True)),
            lambda value: (setattr(value, 'controller', True),
                           value.state.update(route=1, id=9, flags=4)),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                system = System(); mutate(system)
                with self.assertRaises(ValueError): activation.activation_plan(system)

    def test_load_socket_manager_and_restoration_failures_retain_inhibition(self):
        for failure in ('load', 'socket', 'manager', 'restore'):
            with self.subTest(failure=failure):
                system = System(); system.fail = failure
                plan = activation.activation_plan(system)
                with self.assertRaises(ValueError):
                    activation.ensure(system, plan, activation.plan_digest(plan), lock)
                self.assertTrue(system.inhibited)
                self.assertEqual(system.journal['phase'], 'activation-failed')

    def test_stopped_and_administrator_masked_state_are_preserved(self):
        for record, phase in ((captured(False, False), 'stopped'),
                              (captured(False, True), 'administrator-masked')):
            with self.subTest(phase=phase):
                system = System(record); plan = activation.activation_plan(system)
                activation.ensure(system, plan, activation.plan_digest(plan), lock)
                self.assertEqual(system.journal['application']['phase'], phase)

    def test_recovery_unloads_only_neutral_controller_and_stops_owned_socket(self):
        system = System(); system.fail = 'manager'
        plan = activation.activation_plan(system)
        with self.assertRaises(ValueError):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.fail = None
        reviewed = activation.recovery_plan(system)
        result = activation.ensure_recovery(system, reviewed,
            activation.plan_digest(reviewed), lock)
        self.assertEqual(result['status'], 'recovered-inhibited')
        self.assertFalse(system.controller or system.socket_active)
        self.assertTrue(system.inhibited)

    def test_recovery_handles_loaded_controller_when_initial_status_failed(self):
        system = System()
        plan = activation.activation_plan(system)
        system.controller = True
        system.journal = {'version': 1, 'plan': plan,
            'planSha256': activation.plan_digest(plan),
            'requestId': '00000000-0000-0000-0000-000000000002',
            'phase': 'activation-failed', 'controller': None, 'manager': None,
            'application': None, 'error': '[Errno 22] Invalid argument'}
        activation.validate_journal(system.journal)
        reviewed = activation.recovery_plan(system)
        result = activation.ensure_recovery(
            system, reviewed, activation.plan_digest(reviewed), lock)
        self.assertEqual(result['status'], 'recovered-inhibited')
        self.assertFalse(system.controller)
        self.assertTrue(system.inhibited)

    def test_recovery_unloads_nonzero_neutral_controller_only_with_exact_route_evidence(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        self.recovered_route(system)
        reviewed = activation.recovery_plan(system)
        self.assertEqual(reviewed['version'], 2)
        self.assertEqual(reviewed['controllerState'], system.state)
        self.assertEqual(set(reviewed['routeRecoverySha256']),
                         set(activation.RETIREMENT_TRANSACTIONS))
        result = activation.ensure_recovery(
            system, reviewed, activation.plan_digest(reviewed), lock)
        self.assertEqual(result['status'], 'recovered-inhibited')
        self.assertFalse(system.controller)

    def test_recovery_accepts_exact_completed_route_removal(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        self.recovered_route(system, removal=True)
        reviewed = activation.recovery_plan(system)
        self.assertEqual(set(reviewed['routeRecoverySha256']),
                         set(activation.RETIREMENT_TRANSACTIONS))
        result = activation.ensure_recovery(
            system, reviewed, activation.plan_digest(reviewed), lock)
        self.assertEqual(result['status'], 'recovered-inhibited')
        self.assertFalse(system.controller)

    def test_recovery_rejects_removal_terminal_that_differs_from_capture(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        self.recovered_route(system, removal=True)
        system.records['application.json']['wasActive'] = False
        with self.assertRaisesRegex(ValueError, 'differs from its capture'):
            activation.recovery_plan(system)

    def test_inactive_recovered_route_journals_are_retirement_eligible(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        self.recovered_route(system)
        reviewed = activation.recovery_plan(system)
        activation.ensure_recovery(
            system, reviewed, activation.plan_digest(reviewed), lock)
        system.journal = None
        transactions = activation.recovered_route_retirement(system)
        self.assertEqual(transactions, {
            name: system.records.get(name)
            for name in activation.RETIREMENT_TRANSACTIONS})
        system.retire_transactions(transactions)
        self.assertIsNone(activation.recovered_route_retirement(system))

    def test_inactive_recovered_route_retirement_accepts_only_ordered_suffixes(self):
        for removed in range(len(activation.RETIREMENT_TRANSACTIONS) + 1):
            with self.subTest(removed=removed):
                system = System(); initial = activation.activation_plan(system)
                activation.ensure(system, initial, activation.plan_digest(initial), lock)
                self.recovered_route(system); reviewed = activation.recovery_plan(system)
                activation.ensure_recovery(
                    system, reviewed, activation.plan_digest(reviewed), lock)
                system.journal = None
                for name in activation.RETIREMENT_TRANSACTIONS[:removed]:
                    system.records.pop(name)
                remaining = activation.recovered_route_retirement(system)
                if removed == len(activation.RETIREMENT_TRANSACTIONS):
                    self.assertIsNone(remaining)
                else:
                    self.assertEqual(remaining, {
                        name: system.records.get(name)
                        for name in activation.RETIREMENT_TRANSACTIONS})

        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        self.recovered_route(system); reviewed = activation.recovery_plan(system)
        activation.ensure_recovery(
            system, reviewed, activation.plan_digest(reviewed), lock)
        system.journal = None
        system.records.pop('manager.json')
        with self.assertRaisesRegex(ValueError, 'lacks its manager journal'):
            activation.recovered_route_retirement(system)

    def test_inactive_recovered_route_retirement_rejects_drift(self):
        mutations = (
            lambda value: value.records['manager.json']['response'].update(status='error'),
            lambda value: value.records['application.json']['controller'].update(generation=0),
            lambda value: setattr(value, 'inhibited', False),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                system = System(); initial = activation.activation_plan(system)
                activation.ensure(system, initial, activation.plan_digest(initial), lock)
                self.recovered_route(system); reviewed = activation.recovery_plan(system)
                activation.ensure_recovery(
                    system, reviewed, activation.plan_digest(reviewed), lock)
                system.journal = None; mutate(system)
                with self.assertRaises(ValueError):
                    activation.recovered_route_retirement(system)

    def test_completed_route_descends_from_current_neutral_activation(self):
        system = System(); initial = activation.activation_plan(system)
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        self.recovered_route(system)
        system.state.update(generation=1, id=9, route=1,
                            flags=admin.CONSUMER | admin.PINNED)
        route = system.records['transaction.json']
        route['phase'] = 'complete-inhibited'
        route['observation'] = copy.deepcopy(system.state)
        manager = system.records['manager.json']
        manager['controller'] = copy.deepcopy(system.state)
        manager['response']['operation'] = 'switch'
        manager['response']['status'] = 'complete-inhibited'
        manager['response']['state']['controller'] = copy.deepcopy(system.state)
        manager['response']['state']['pendingTransaction'] = copy.deepcopy(route)
        application_record = system.records['application.json']
        application_record.update(
            phase='restored', controller=copy.deepcopy(system.state),
            requestId=manager['requestId'], fingerprint=manager['fingerprint'])
        self.assertTrue(activation.routed_from_current_neutral(
            activation.observe(system)))
        application_record['controller']['generation'] = 0
        with self.assertRaisesRegex(ValueError, 'application route ancestry'):
            activation.routed_from_current_neutral(activation.observe(system))

    def test_nonzero_neutral_recovery_evidence_drift_fails_before_unload(self):
        mutations = (
            lambda value: value.records.pop('transaction.json'),
            lambda value: value.records['manager.json']['response'].update(status='error'),
            lambda value: value.records['application.json']['controller'].update(generation=0),
            lambda value: value.state.update(generation=3),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                system = System(); initial = activation.activation_plan(system)
                activation.ensure(system, initial, activation.plan_digest(initial), lock)
                self.recovered_route(system); mutate(system)
                with self.assertRaises(ValueError):
                    activation.recovery_plan(system)
                self.assertTrue(system.controller)

    def test_recovery_rejects_active_route_and_boot_change(self):
        system = System(); system.fail = 'manager'; plan = activation.activation_plan(system)
        with self.assertRaises(ValueError):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.fail = None; system.state.update(route=1, id=9, flags=4)
        reviewed = activation.recovery_plan(system)
        with self.assertRaisesRegex(ValueError, 'non-neutral'):
            activation.ensure_recovery(system, reviewed, activation.plan_digest(reviewed), lock)
        system = System(); system.fail = 'load'; plan = activation.activation_plan(system)
        with self.assertRaises(ValueError):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        with self.assertRaisesRegex(ValueError, 'cross-boot'):
            activation.recovery_plan(system)

    def test_recovery_rejects_binding_deployment_and_controller_identity_drift(self):
        mutations = (
            lambda value: setattr(value, 'raw', value.raw + b' '),
            lambda value: setattr(value, 'deployment_raw', value.deployment_raw + b' '),
            lambda value: setattr(value, 'note_drift', True),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                system = System(); system.fail = 'manager'
                plan = activation.activation_plan(system)
                with self.assertRaises(ValueError):
                    activation.ensure(system, plan, activation.plan_digest(plan), lock)
                system.fail = None; mutate(system)
                with self.assertRaises(ValueError):
                    activation.recovery_plan(system)

    def test_malformed_journal_is_rejected(self):
        system = System(); system.journal = {'phase': 'complete-neutral'}
        with self.assertRaisesRegex(ValueError, 'journal schema'):
            activation.activation_plan(system)

    def test_pending_transactions_unit_socket_and_application_races_fail_closed(self):
        for name in ('deployment-pending.json', 'transaction.json', 'manager.json',
                     'application.json'):
            with self.subTest(record=name):
                system = System(); system.records[name] = {'pending': True}
                with self.assertRaisesRegex(ValueError, 'transaction'):
                    activation.activation_plan(system)
        system = System(); system.unit_drift = True
        with self.assertRaisesRegex(ValueError, 'unit identity'):
            activation.activation_plan(system)
        system = System(); system.socket_active = True; system.socket_unsafe = True
        with self.assertRaisesRegex(ValueError, 'socket identity'):
            activation.activation_plan(system)
        system = System(); system.application_active = True
        with self.assertRaisesRegex(ValueError, 'not stopped'):
            activation.activation_plan(system)

    def test_build_note_drift_after_load_and_foreign_exact_controller_are_rejected(self):
        system = System(); system.note_drift = True
        plan = activation.activation_plan(system)
        with self.assertRaisesRegex(ValueError, 'exact neutral'):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        self.assertTrue(system.inhibited)
        system = System(); system.controller = True
        with self.assertRaisesRegex(ValueError, 'no completed activation ownership'):
            activation.activation_plan(system)

    def test_recovered_activation_can_restart_without_losing_evidence(self):
        system = System(); system.fail = 'manager'; plan = activation.activation_plan(system)
        with self.assertRaises(ValueError):
            activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.fail = None; recovery = activation.recovery_plan(system)
        activation.ensure_recovery(system, recovery, activation.plan_digest(recovery), lock)
        restart = activation.activation_plan(system)
        activation.ensure(system, restart, activation.plan_digest(restart), lock)
        self.assertEqual(len(system.archives), 1)
        self.assertTrue(activation.neutral_ready(activation.observe(system)))

    def test_controller_session_and_application_pid_drift_break_idempotency(self):
        system = System(); plan = activation.activation_plan(system)
        activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.state['session'] += 1
        with self.assertRaisesRegex(ValueError, 'recovery'):
            activation.activation_plan(system)
        system = System(); plan = activation.activation_plan(system)
        activation.ensure(system, plan, activation.plan_digest(plan), lock)
        system.app['service']['MainPID'] = '99'
        with self.assertRaisesRegex(ValueError, 'recovery'):
            activation.activation_plan(system)


if __name__ == '__main__':
    __import__("nonempty_unittest").main()
