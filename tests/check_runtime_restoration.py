#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Public manager workflow with real journals/drop-ins and fake system effects."""
import contextlib
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_application as app
import runtime_controller_admin as admin
import runtime_manager as manager
import runtime_activation
from check_runtime_controller import Machine


class System(Machine):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.active = True
        self.masked = False
        self.loaded = True
        self.locked = False
        self.configured = 'gpio4'
        self.started = 0
        self.fail = None
        self.pid = 321
        self.pre_ack = None

    def __enter__(self):
        assert not self.locked, 'startup would deadlock on manager lock'
        self.locked = True
        return self

    def __exit__(self, *args): self.locked = False
    def read_record(self, name):
        path = self.root/name
        return json.loads(path.read_text()) if path.exists() else None
    write_record = admin.Linux.write_record
    def read_journal(self): return self.read_record('transaction.json')
    def write_journal(self, value): self.write_record('transaction.json', value)
    def read_manager_record(self): return self.read_record('manager.json')
    def write_manager_record(self, value): self.write_record('manager.json', value)
    def inhibit(self):
        app.write_owned(app.unit_file(app.DROPIN), app.INHIBIT)
        self.active = False
        self.mask = True
        self.event('inhibit')
    def check_inhibit(self):
        assert not self.active
        assert app.unit_file(app.DROPIN).read_bytes() == app.INHIBIT
    def inhibited(self): return app.unit_file(app.DROPIN).exists() and not self.active
    def output_snapshot(self):
        return dict(route=self.value['route'], compatibility=3, operation=0,
                    terminal=0, fault=1, owner=1,
                    lease=1, outputInhibited=1, operationalReady=2,
                    gpio=2, clock=2, dma=2, stable=2)
    def observation(self):
        return dict(LoadState='masked' if self.masked else ('loaded' if self.loaded else 'not-found'),
                    ActiveState='active' if self.active else 'inactive',
                    UnitFileState='masked' if self.masked else 'enabled', MainPID=str(self.pid if self.active else 0))
    def helper(self, operation, *args):
        if self.fail == operation:
            raise ValueError('injected '+operation)
        if operation == 'configure':
            assert not self.active
            self.configured = args[0]
        return dict(contract='wsprrypi-route-application-v1', route=self.configured, transmit=False)
    def command(self, argv):
        if 'start' in argv:
            assert not self.locked
            assert not app.unit_file(app.DROPIN).exists()
            self.started += 1
            if self.fail == 'start': raise ValueError('injected start')
            self.active = True
            record = self.read_record('application.json')
            if record['phase'] == 'neutral-start-intent':
                return ''
            # An independent startup connection exercises public dispatch while
            # the mutation workflow is alive but its controller lock is released.
            self.pre_ack = manager.dispatch(
                dict(schemaVersion=3, operation='idle', route=self.configured),
                lambda:self)
            assert self.read_record('application.json')['phase'] == 'start-intent'
            assert self.pre_ack['state']['outputLifecycle']['executionAuthorized'] is False
            manager.dispatch(dict(schemaVersion=3, operation='application-ready', route=self.configured,
                token=record['token'], pid=self.pid, transmit=False), lambda:self)
        return ''


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.system = System(root)
        capture = {'version': 1, 'wasActive': True,
            'administratorMasked': False,
            'service': {'LoadState': 'loaded', 'ActiveState': 'active',
                'UnitFileState': 'enabled', 'MainPID': str(self.system.pid)},
            'companion': {'contract': 'wsprrypi-route-application-v1',
                'route': 'gpio4', 'transmit': False,
                'config': '/usr/local/etc/wsprrypi.ini'}}
        plan = {'version': 1, 'operation': 'neutral-activation',
            'bindingSha256': self.system.binding_hash, 'artifactSetSha256': 'b' * 64,
            'bootId': self.system.boot, 'lastDeploymentSha256': 'c' * 64,
            'application': capture, 'socketWasActive': False,
            'alreadyReady': False, 'previousActivationSha256': None}
        activation_record = {'version': 1, 'plan': plan,
            'planSha256': runtime_activation.plan_digest(plan),
            'requestId': '00000000-0000-0000-0000-000000000001',
            'phase': 'complete-neutral', 'controller': self.system.call(),
            'manager': {}, 'application': {'phase': 'restored'}, 'error': None}
        (root / 'activation.json').write_text(json.dumps(activation_record))
        self.stack = contextlib.ExitStack()
        for obj, name, value in (
            (admin,'STATE',root), (admin,'UNIT_DIR',root),
            (admin,'safe_directory',lambda path:None), (admin,'fsync_dir',lambda path:None),
            (admin,'read_regular',lambda path,*args:Path(path).read_bytes()),
            (admin,'run',self.system.command), (app,'service',self.system.observation),
            (app,'helper',self.system.helper), (app,'mutation_lock',contextlib.nullcontext)):
            self.stack.enter_context(patch.object(obj, name, value))
    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()
    def dispatch(self, value): return manager.dispatch(value, lambda:self.system)
    def switch(self, route='gpio20', ident='request-0001'):
        checked = self.dispatch(dict(schemaVersion=3, operation='preflight', route=route))
        return self.dispatch(dict(schemaVersion=3, operation='switch', route=route,
            requestId=ident, actor='offline.test', execute=True, preflightToken=checked['state']['preflightToken']))
    def test_running_application_restored_and_requester_not_required(self):
        result = self.switch()
        self.assertEqual(result['status'], 'restored')
        self.assertTrue(self.system.active)
        self.assertEqual(self.system.configured, 'gpio20')
        self.assertEqual(self.system.started, 1)
        self.assertIs(self.system.pre_ack['state']['outputLifecycle']['ready'], True)
        self.assertIs(self.system.pre_ack['state']['outputLifecycle']['executionAuthorized'], False)
        self.assertFalse(app.unit_file(app.DROPIN).exists())
        self.assertFalse(app.unit_file(app.IDLE_DROPIN).exists())
        self.assertEqual(self.dispatch(dict(schemaVersion=3,operation='query'))['state']['application']['phase'], 'restored')

    def remove(self, route='gpio4', ident='remove-0001'):
        return self.dispatch(dict(schemaVersion=3, operation='remove', route=route,
            requestId=ident, actor='offline.test', execute=True))

    def test_remove_restores_running_application_after_exact_neutral_proof(self):
        self.switch('gpio4', 'setup-route-0001')
        result = self.remove()
        self.assertEqual(result['status'], 'neutral-restored')
        self.assertTrue(self.system.active)
        self.assertEqual(self.system.value['route'], 0)
        self.assertFalse(app.unit_file(app.DROPIN).exists())
        self.assertEqual(result['state']['application']['phase'], 'neutral-restored')

    def test_remove_preserves_stopped_and_masked_service_intent(self):
        for masked in (False, True):
            with self.subTest(masked=masked):
                self.tearDown(); self.setUp()
                self.system.active = False
                self.system.masked = masked
                self.switch('gpio4', 'setup-route-0001')
                result = self.remove(ident='remove-'+str(masked)+'-0001')
                self.assertEqual(result['status'],
                    'neutral-administrator-masked' if masked else 'neutral-stopped')
                self.assertFalse(self.system.active)
                self.assertEqual(self.system.started, 0)
                self.assertEqual(self.system.masked, masked)
                self.assertFalse(app.unit_file(app.DROPIN).exists())

    def test_remove_restart_failure_retains_inhibitor_and_retries_without_route_effects(self):
        self.switch('gpio4', 'setup-route-0001')
        self.system.fail = 'start'
        result = self.remove()
        self.assertEqual(result['error']['code'], 'neutral-application-restoration-failed')
        self.assertEqual(self.system.value['route'], 0)
        self.assertTrue(app.unit_file(app.DROPIN).exists())
        self.system.fail = None
        result = self.remove(ident='remove-0002')
        self.assertEqual(result['status'], 'neutral-restored')
        self.assertTrue(self.system.active)
        self.assertEqual(result['state']['application']['error'], 'injected start')
        self.assert_removal_ancestry()

    def assert_removal_ancestry(self):
        records = {name:self.system.read_record(name)
                   for name in runtime_activation.RETIREMENT_TRANSACTIONS}
        runtime_activation._validate_same_boot_recovered_route(records,
            self.system.call(), self.system.boot, self.system.binding_hash)

    def test_remove_retry_after_inhibitor_and_service_effects(self):
        class Crash(BaseException): pass
        for boundary in ('unlink', 'reload', 'start'):
            for after in (False, True):
                for active, masked in ((True, False), (False, False), (False, True)):
                    if boundary == 'start' and not active:
                        continue
                    with self.subTest(boundary=boundary, after=after, active=active, masked=masked):
                        self.tearDown(); self.setUp()
                        self.system.active, self.system.masked = active, masked
                        self.switch('gpio4', 'setup-route-0001')
                        original_remove = app.remove_owned
                        original_command = self.system.command
                        def removing(path, data):
                            hit = boundary == 'unlink' and path == app.unit_file(app.DROPIN)
                            if hit and not after: raise Crash()
                            original_remove(path, data)
                            if hit and after: raise Crash()
                        def command(argv):
                            phase = self.system.read_record('application.json')['phase']
                            hit = phase == 'neutral-start-intent' and (
                                (boundary == 'reload' and 'daemon-reload' in argv) or
                                (boundary == 'start' and 'start' in argv))
                            if hit and not after: raise Crash()
                            result = original_command(argv)
                            if hit and after: raise Crash()
                            return result
                        with patch.object(app, 'remove_owned', removing), \
                             patch.object(admin, 'run', command):
                            with self.assertRaises(Crash): self.remove()
                        state = self.system.call()
                        result = self.remove(ident='remove-retry-0001')
                        self.assertEqual(result['status'], 'neutral-restored' if active else
                            'neutral-administrator-masked' if masked else 'neutral-stopped')
                        self.assertEqual(self.system.call(), state)
                        self.assertEqual(self.system.active, active)
                        self.assertEqual(self.system.masked, masked)
                        self.assert_removal_ancestry()

    def test_completed_removal_preflight_rejects_changed_service_intent(self):
        self.switch('gpio4', 'setup-route-0001')
        self.remove()
        self.system.active = False
        before = list(self.system.events)
        with self.assertRaisesRegex(ValueError, 'service state changed'):
            self.dispatch(dict(schemaVersion=3, operation='preflight', route='gpio20'))
        self.assertEqual(before, self.system.events)

    def test_removal_ancestry_rejects_changed_capture_and_accepts_only_diagnostics(self):
        self.switch('gpio4', 'setup-route-0001')
        self.remove()
        original = self.system.read_record('application.json')
        for key, changed in (('wasActive', False), ('administratorMasked', True),
                ('requestId', 'foreign-request'), ('route', 'gpio20'),
                ('fingerprint', '0'*64), ('phase', 'neutral-stopped'),
                ('error', {'malformed':True})):
            with self.subTest(key=key):
                self.system.write_record('application.json', dict(original, **{key:changed}))
                with self.assertRaises(ValueError): self.assert_removal_ancestry()
        self.system.write_record('application.json', dict(original, error='retained failure'))
        self.assert_removal_ancestry()

    def test_gpio20_removal_and_interrupted_restoration_use_only_gpio20_evidence(self):
        class Crash(BaseException): pass
        for active, masked in ((True, False), (False, False), (False, True)):
            with self.subTest(active=active, masked=masked):
                self.tearDown(); self.setUp()
                self.system.active, self.system.masked = active, masked
                self.switch('gpio20', 'setup-route-0020')
                original = app.remove_owned
                def interrupted(path, data):
                    original(path, data)
                    if path == app.unit_file(app.DROPIN): raise Crash()
                with patch.object(app, 'remove_owned', interrupted):
                    with self.assertRaises(Crash): self.remove('gpio20')
                with self.assertRaisesRegex(ValueError, 'matching removal'):
                    self.remove('gpio4', 'wrong-route-0004')
                result = self.remove('gpio20', 'remove-retry-0020')
                self.assertEqual(result['state']['application']['route'], 'gpio20')
                self.assertEqual(self.system.read_journal()['target'], 2)
                self.assertEqual(self.system.active, active)
                self.assert_removal_ancestry()

    def test_remove_rejects_stale_route_without_effects(self):
        self.switch('gpio4', 'setup-route-0001')
        before = copy.deepcopy(self.system.value)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.remove('gpio20')
        self.assertEqual(self.system.value, before)
        self.assertTrue(self.system.active)

    def test_remove_is_idempotent_for_same_and_new_request_ids(self):
        self.switch('gpio4', 'setup-route-0001')
        first = self.remove()
        event_count = len(self.system.events)
        self.assertEqual(self.remove(), first)
        second = self.remove(ident='remove-0002')
        self.assertEqual(second['status'], 'neutral-restored')
        self.assertEqual(len(self.system.events), event_count)

    def test_remove_completes_a_matching_prior_recovered_route(self):
        self.switch('gpio4', 'setup-route-0001')
        recovered = self.dispatch(dict(schemaVersion=3, operation='recover', execute=True,
            requestId='recovery-0001', actor='offline.test'))
        self.assertEqual(recovered['status'], 'recovered-inhibited')
        self.assertFalse(self.system.active)
        result = self.remove(ident='remove-after-recovery-0001')
        self.assertEqual(result['status'], 'neutral-restored')
        self.assertTrue(self.system.active)
        self.assert_removal_ancestry()

    def test_foreign_inhibitor_survives_failed_removal(self):
        self.switch('gpio4', 'setup-route-0001')
        app.unit_file(app.DROPIN).write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError, 'inhibition'):
            self.remove()
        self.assertEqual(app.unit_file(app.DROPIN).read_bytes(), b'foreign')
        self.assertTrue(self.system.active)

    def test_remove_is_retryable_at_every_durable_journal_boundary(self):
        class Crash(BaseException): pass
        self.switch('gpio4', 'setup-route-0001')
        writes = []
        original = self.system.write_record
        def trace(name, value):
            original(name, value)
            writes.append((name, value.get('phase')))
        with patch.object(self.system, 'write_record', trace):
            self.remove()
        for boundary in range(1, len(writes)+1):
            with self.subTest(boundary=boundary, write=writes[boundary-1]):
                self.tearDown(); self.setUp()
                self.switch('gpio4', 'setup-route-0001')
                original = self.system.write_record
                count = 0
                def crash(name, value):
                    nonlocal count
                    original(name, value)
                    count += 1
                    if count == boundary:
                        raise Crash()
                with patch.object(self.system, 'write_record', crash):
                    with self.assertRaises(Crash):
                        self.remove()
                result = self.remove(ident='remove-retry-'+str(boundary))
                self.assertEqual(result['status'], 'neutral-restored')
                self.assertTrue(self.system.active)
                self.assertEqual(self.system.value['route'], 0)
    def test_stopped_and_administrator_masked_are_not_started(self):
        for masked in (False, True):
            with self.subTest(masked=masked):
                self.system.active = False
                self.system.masked = masked
                result = self.switch(ident='request-'+str(masked)+'-0001')
                self.assertEqual(result['status'], 'administrator-masked' if masked else 'stopped')
                self.assertEqual(self.system.started, 0)
                self.assertEqual(self.system.masked, masked)
                self.assertTrue(app.unit_file(app.IDLE_DROPIN).exists())
    def test_missing_and_foreign_service_are_not_overwritten(self):
        self.system.loaded = False
        with self.assertRaises(ValueError): self.switch()
        self.assertFalse(self.system.events)
        self.assertIsNone(self.system.read_record('application.json'))
    def test_removal_error_preserves_errno_and_id(self):
        self.switch()
        self.system.remove_error = -16
        result = self.switch('gpio4', 'request-0002')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['kernelError'], -16)
        self.assertEqual(result['error']['overlayId'], 9)
        self.assertEqual(self.system.configured, 'gpio20')
        self.assertFalse(self.system.active)
    def test_configuration_and_restart_failure_can_restore_without_overlay_effects(self):
        for failure in ('configure', 'start'):
            with self.subTest(failure=failure):
                self.system.fail = failure
                result = self.switch(ident='request-'+failure+'-0001')
                self.assertEqual(result['error']['code'], 'application-restoration-failed')
                before = copy.deepcopy(self.system.value)
                self.assertFalse(self.system.active)
                self.system.fail = None
                result = self.dispatch(dict(schemaVersion=3, operation='restore', execute=True))
                self.assertEqual(result['status'], 'restored')
                self.assertEqual(self.system.value, before)
    def test_foreign_dropin_survives(self):
        path = app.unit_file(app.DROPIN)
        path.parent.mkdir()
        path.write_bytes(b'foreign')
        with self.assertRaises(ValueError): self.switch()
        self.assertEqual(path.read_bytes(), b'foreign')
        self.assertTrue(self.system.active)
    def test_stale_ack_and_pending_output_are_rejected(self):
        self.system.fail = 'start'
        self.switch()
        with self.assertRaises(ValueError):
            self.dispatch(dict(schemaVersion=3,operation='reconcile-output',route='gpio20'))
        with self.assertRaises(ValueError):
            self.dispatch(dict(schemaVersion=3,operation='application-ready',route='gpio20',token='a'*36,pid=321,transmit=False))
    def test_prior_boot_restoration_does_not_start(self):
        self.system.fail = 'start'
        self.switch()
        self.system.boot = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        with self.assertRaises(ValueError):
            self.dispatch(dict(schemaVersion=3,operation='restore',execute=True))
        self.assertFalse(self.system.active)

    def test_every_durable_journal_boundary_has_a_recovery_path(self):
        class Crash(BaseException): pass
        writes = []
        original = self.system.write_record
        def trace(name, value):
            original(name, value)
            writes.append((name, value.get('phase')))
        with patch.object(self.system, 'write_record', trace):
            self.switch()
        for boundary in range(1, len(writes)+1):
            with self.subTest(boundary=boundary, write=writes[boundary-1]):
                self.tearDown()
                self.setUp()
                original = self.system.write_record
                count = 0
                def crash(name, value):
                    nonlocal count
                    original(name, value)
                    count += 1
                    if count == boundary: raise Crash()
                with patch.object(self.system, 'write_record', crash):
                    with self.assertRaises(Crash): self.switch()
                record = self.system.read_record('application.json')
                journal = self.system.read_journal()
                if journal and journal['phase'] == 'complete-inhibited' and self.system.value['route'] == 2:
                    result = self.dispatch(dict(schemaVersion=3, operation='restore', execute=True))
                else:
                    result = self.dispatch(dict(schemaVersion=3, operation='recover', execute=True,
                        requestId='recovery-0001', actor='offline.test'))
                    self.assertNotEqual(result['status'], 'error')
                    result = self.switch(ident='request-0002')
                self.assertEqual(result['status'], 'restored', record)
                self.assertTrue(self.system.active)
                self.assertEqual(self.system.configured, 'gpio20')

    def test_stopped_first_start_acknowledgement_removes_only_owned_override(self):
        self.system.active = False
        self.switch()
        self.system.active = True
        record = self.system.read_record('application.json')
        self.dispatch(dict(schemaVersion=3,operation='application-ready',route='gpio20',
            token=record['token'],pid=self.system.pid,transmit=False))
        self.assertFalse(app.unit_file(app.IDLE_DROPIN).exists())
        self.assertEqual(self.system.read_record('application.json')['phase'], 'restored')

    def test_real_mutation_lock_excludes_a_second_worker(self):
        # Re-enable the real lock, replacing only its root-owner observation.
        self.stack.close()
        with patch.object(admin, 'STATE', Path(self.tmp.name)), patch.object(admin, 'safe_directory'), patch.object(os, 'fstat', return_value=type('Info', (), {'st_uid':0, 'st_mode':0o100600})()):
            with app.mutation_lock():
                with self.assertRaises(BlockingIOError):
                    with app.mutation_lock(): pass

    def test_first_switch_after_deployment_inhibition(self):
        self.system.inhibit()
        self.assertEqual(self.switch()['status'], 'stopped')
        self.assertFalse(app.unit_file(app.DROPIN).exists())

    def test_recover_second_switch_preserves_prior_idle_override_ownership(self):
        self.system.active = False
        self.switch()
        self.system.fail = 'configure'
        self.assertEqual(self.switch('gpio4', 'request-0002')['status'], 'error')
        result = self.dispatch(dict(schemaVersion=3,operation='recover',execute=True,
            requestId='recover-0001',actor='offline.test'))
        self.assertNotEqual(result['status'], 'error')
        self.system.fail = None
        self.assertEqual(self.switch(ident='request-0003')['status'], 'stopped')

    def test_malformed_application_journal_is_not_used_for_service_effects(self):
        self.switch()
        record = self.system.read_record('application.json')
        record['token'] = 'token\nExecStart=/foreign'
        self.system.write_record('application.json', record)
        before = list(self.system.events)
        with self.assertRaises(ValueError):
            self.dispatch(dict(schemaVersion=3,operation='restore',execute=True))
        self.assertEqual(self.system.events, before)

    def test_unbound_application_operation_is_not_used_for_removal(self):
        self.switch('gpio4', 'setup-route-0001')
        record = self.system.read_record('application.json')
        record['operation'] = 'foreign'
        self.system.write_record('application.json', record)
        before = list(self.system.events)
        with self.assertRaisesRegex(ValueError, 'application operation'):
            self.remove()
        self.assertEqual(self.system.events, before)

    def test_process_exit_after_acknowledgement_is_not_reported_as_restored(self):
        def observation():
            value = self.system.observation()
            record = self.system.read_record('application.json')
            if self.system.locked and record and record['ready']:
                value.update(ActiveState='inactive', MainPID='0')
            return value
        with patch.object(app, 'service', observation):
            result = self.switch()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'application-restoration-failed')
        self.assertTrue(self.system.inhibited())


if __name__ == '__main__': __import__("nonempty_unittest").main()
