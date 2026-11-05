#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline tests of the actual kernel entrypoint and concrete admin sequencing."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import runtime_controller_admin as admin
from build_runtime_controller import generate
from overlay_builder import build_dtbo
import shutil


class Machine:
    boot = '11111111-2222-3333-4444-555555555555'
    binding_hash = 'a'*64
    def __init__(self):
        self.value = dict(session=7, generation=0, id=0, error=0, route=0, flags=0)
        self.journal = None
        self.mask = False
        self.events = []
        self.crash = None
        self.remove_error = 0
        self.apply_error = 0
    def event(self, name):
        self.events.append(name)
        if len(self.events) == self.crash:
            raise OSError('injected process death')
    def read_journal(self): return copy.deepcopy(self.journal)
    def write_journal(self, value):
        self.event('journal-before')
        self.journal = copy.deepcopy(value)
        self.event('journal-after')
    def archive_journal(self, value):
        self.archived = copy.deepcopy(value)
    def inhibit(self):
        self.event('inhibit-before')
        self.mask = True
        self.event('inhibit-after')
    def check_inhibit(self):
        assert self.mask
        self.event('inhibit-check')
    def unload(self):
        self.check_inhibit()
        self.value['flags'] &= ~admin.CONSUMER
        self.event('unload')
    def load(self):
        self.check_inhibit()
        self.value['flags'] |= admin.CONSUMER
        self.event('load')
    def call(self, operation=0, route=0, before=None):
        if operation:
            self.check_inhibit()
            assert not self.value['flags'] & admin.CONSUMER
            assert before['session'] == self.value['session']
            assert before['generation'] == self.value['generation']
            self.event('effect-before')
            self.value['generation'] += 1
            old_fault = self.value['flags'] & admin.FAULT
            if operation == admin.APPLY:
                assert self.value['id'] == 0
                self.value.update(id=9, route=route, error=self.apply_error, flags=admin.PINNED)
            else:
                self.value.update(id=9 if self.remove_error else 0,
                                  route=self.value['route'] if self.remove_error else 0,
                                  error=self.remove_error, flags=admin.PINNED if self.remove_error else 0)
            self.value['flags'] |= old_fault
            if self.value['error']: self.value['flags'] |= admin.FAULT
            self.event('effect-after')
        return self.value.copy()


class Tests(unittest.TestCase):
    def test_runtime_overlay_only_removes_symbol_exports(self):
        def tree(path, node='/'):
            result = {}
            names = subprocess.check_output(['fdtget', '-p', str(path), node], text=True).splitlines()
            for name in names:
                result[node+':'+name] = subprocess.check_output(
                    ['fdtget', '-t', 'bx', str(path), node, name], text=True)
            children = subprocess.check_output(['fdtget', '-l', str(path), node], text=True).splitlines()
            for child in children:
                if node == '/' and child == '__symbols__': continue
                result.update(tree(path, node.rstrip('/')+'/'+child))
            return result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate(root)
            for route in ('gpio4', 'gpio20'):
                canonical = root/(route+'-canonical.dtbo')
                build_dtbo(ROOT/'overlays'/('rp1-gpclk-'+route+'.dts'), canonical, shutil.which('dtc'))
                runtime = root/(route+'.dtbo')
                self.assertIn('__symbols__', subprocess.check_output(['fdtget','-l',str(canonical),'/'],text=True))
                self.assertNotIn('__symbols__', subprocess.check_output(['fdtget','-l',str(runtime),'/'],text=True))
                values = tree(runtime)
                self.assertTrue(any('/__fixups__:' in name for name in values))
                self.assertTrue(any(name.startswith('/__local_fixups__/') for name in values))
                self.assertEqual(values, tree(canonical))

    def test_actual_kernel_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            generate(tmp)
            (tmp / 'linux').mkdir()
            names = ('capability', 'compat', 'fs', 'miscdevice', 'module', 'mutex', 'of',
                     'random', 'uaccess', 'utsname', 'types', 'ioctl')
            stub = ROOT / 'tests/fixtures/runtime_controller_stubs.h'
            for name in names:
                (tmp / 'linux' / (name+'.h')).write_text(f'#include "{stub}"\n')
            binary = tmp / 'controller-test'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                            '-I'+str(tmp), '-I'+str(ROOT/'include'), '-I'+str(ROOT/'include/uapi'), '-I'+str(ROOT/'controller'),
                            str(ROOT/'tests/fixtures/runtime_controller_harness.c'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_switch_both_directions(self):
        machine = Machine()
        for route in (1, 2, 1):
            result = admin.execute(machine, route)
            self.assertEqual(result['route'], route)
            self.assertTrue(machine.mask)
            self.assertEqual(machine.journal['phase'], 'complete-inhibited')

    def test_explicit_prior_boot_recovery_preserves_journal(self):
        machine = Machine(); admin.execute(machine, 2)
        old = copy.deepcopy(machine.journal)
        machine.boot = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        machine.value = dict(session=8, generation=0, id=0, error=0, route=0, flags=0)
        with self.assertRaises(ValueError): admin.execute(machine, 2)
        admin.execute(machine, recover=True)
        self.assertEqual(machine.archived, old)
        self.assertEqual(machine.journal['boot'], machine.boot)
        self.assertEqual(machine.journal['phase'], 'recovered-inhibited')
        self.assertTrue(machine.mask)
        self.assertEqual(admin.execute(machine, 2)['route'], 2)

    def test_prior_boot_recovery_rejects_nonempty_controller(self):
        machine = Machine(); admin.execute(machine, 2)
        machine.boot = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        with self.assertRaises(ValueError): admin.execute(machine, recover=True)

    def test_crash_every_boundary_requires_explicit_recovery(self):
        sample = Machine(); admin.execute(sample, 1)
        for point in range(1, len(sample.events)+1):
            machine = Machine(); machine.crash = point
            with self.assertRaises(OSError): admin.execute(machine, 1)
            machine.crash = None
            if machine.journal is None: continue
            if machine.journal['phase'] != 'complete-inhibited':
                with self.assertRaises(ValueError): admin.execute(machine, 2)
            result = admin.execute(machine, recover=True)
            self.assertEqual(result['id'], 0)
            self.assertTrue(machine.mask)
            self.assertEqual(machine.journal['phase'], 'recovered-inhibited')

    def test_remove_error_prevents_successor(self):
        machine = Machine(); admin.execute(machine, 1)
        machine.remove_error = -16
        with self.assertRaises(ValueError): admin.execute(machine, 2)
        self.assertEqual(machine.value['route'], 1)
        self.assertEqual(machine.value['id'], 9)
        self.assertTrue(machine.mask)
        self.assertEqual(machine.journal['phase'], 'remove-intent')

    def test_apply_error_preserves_recovery_record(self):
        machine = Machine(); machine.apply_error = -5
        with self.assertRaises(ValueError): admin.execute(machine, 1)
        self.assertEqual(machine.journal['phase'], 'apply-intent')
        self.assertTrue(machine.mask)
        self.assertEqual(machine.value['id'], 9)

    def test_reboot_binding_or_session_change_never_adopted(self):
        for field, value in [('boot', 'changed'), ('session', 999), ('binding', 'changed')]:
            machine = Machine(); admin.execute(machine, 1)
            machine.journal[field] = value
            start = len(machine.events)
            with self.assertRaises(ValueError): admin.execute(machine, recover=True)
            self.assertEqual(len(machine.events), start)

    def test_concrete_fixed_load_and_unload_commands(self):
        system = object.__new__(admin.Linux)
        system.check_inhibit = lambda: None
        system.note = lambda *args: None
        calls = []
        with patch.object(admin, 'run', side_effect=lambda argv: calls.append(argv)), \
             patch.object(admin, 'read_regular', return_value=b'N\n'):
            system.load()
            with patch.object(Path, 'exists', side_effect=[True, False]): system.unload()
        self.assertEqual(calls, [('/usr/sbin/modprobe', 'rp1_gpclk_dkms'),
                                 ('/usr/sbin/rmmod', 'rp1_gpclk_dkms')])
        self.assertFalse(any('force' in token or token in ('-f', '--force') for argv in calls for token in argv))

    def test_persistent_dropin_preserves_foreign_service(self):
        import runtime_application as app
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            unit = directory/'wsprrypi.service'
            unit.write_text('administrator-owned unit')
            system = object.__new__(admin.Linux)
            system.check_inhibit = lambda: None
            def command(argv):
                self.assertEqual(app.unit_file(app.DROPIN).read_bytes(), app.INHIBIT)
                if 'stop' in argv:
                    raise ValueError('stop failed')
            with patch.object(admin, 'UNIT_DIR', directory), \
                 patch.object(admin, 'safe_directory'), patch.object(admin, 'fsync_dir'), \
                 patch.object(admin, 'read_regular', side_effect=lambda path:Path(path).read_bytes()), \
                 patch.object(admin, 'run', side_effect=command):
                with self.assertRaises(ValueError): system.inhibit()
                self.assertEqual(app.unit_file(app.DROPIN).read_bytes(), app.INHIBIT)
            self.assertEqual(unit.read_text(), 'administrator-owned unit')

    def test_journal_real_atomic_replace_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            system = object.__new__(admin.Linux)
            directory = Path(tmp)
            with patch.object(admin, 'STATE', directory), patch.object(admin, 'fsync_dir') as sync:
                system.write_journal({'phase': 'before'})
                self.assertEqual((directory/'transaction.json').stat().st_mode & 0o777, 0o600)
                sync.assert_called_once_with(directory)
                before = (directory/'transaction.json').read_bytes()
                with patch.object(admin.os, 'replace', side_effect=OSError('interrupted')):
                    with self.assertRaises(OSError): system.write_journal({'phase': 'after'})
                self.assertEqual((directory/'transaction.json').read_bytes(), before)
                self.assertEqual([p.name for p in directory.iterdir()], ['transaction.json'])

    def test_unrelated_generations_and_malformed_observation_refused(self):
        for change in ('generation', 'observation', 'request', 'target'):
            machine = Machine(); admin.execute(machine, 1)
            if change == 'generation': machine.value['generation'] += 2
            elif change == 'observation': machine.journal['observation']['generation'] = True
            elif change == 'request': machine.journal['request'] = 'not-a-uuid'
            else: machine.journal['target'] = True
            count = len(machine.events)
            with self.assertRaises(ValueError): admin.execute(machine, recover=True)
            self.assertEqual(len(machine.events), count)
        with self.assertRaises(ValueError): admin.strict_json('{"x":1,"x":2}')

    def test_crashes_during_route_replacement(self):
        base = Machine(); admin.execute(base, 1); base.events = []
        sample = copy.deepcopy(base); admin.execute(sample, 2)
        for point in range(1, len(sample.events)+1):
            machine = copy.deepcopy(base); machine.crash = point
            with self.assertRaises(OSError): admin.execute(machine, 2)
            machine.crash = None
            result = admin.execute(machine, recover=True)
            self.assertEqual(result['id'], 0)
            self.assertTrue(machine.mask)

    def test_external_route_change_during_consumer_lifecycle_stops(self):
        for stage in ('load', 'unload'):
            machine = Machine()
            original = getattr(machine, stage)
            def altered():
                original()
                machine.value['generation'] += 1
            setattr(machine, stage, altered)
            with self.assertRaises(ValueError): admin.execute(machine, 1)
            self.assertTrue(machine.mask)
            self.assertNotEqual(machine.journal['phase'], 'complete-inhibited')

    def test_actual_bounded_command_runner(self):
        self.assertEqual(admin.run((sys.executable, '-c', 'print("ok")')), 'ok')

    def test_systemd_observation_is_keyed_and_uses_inert_template_instance(self):
        output = ('MainPID=0\nFragmentPath=/usr/lib/systemd/system/'
                  'rp1-gpclk-route-manager@.service\nActiveState=inactive\n'
                  'UnitFileState=static\nLoadState=loaded\n')
        with patch.object(admin, 'run', return_value=output) as command:
            observed = admin.systemd_unit(
                'rp1-gpclk-route-manager@.service', include_main_pid=True)
        self.assertEqual(observed, {'load': 'loaded', 'active': 'inactive',
            'enabled': 'static',
            'fragment': '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service',
            'MainPID': '0'})
        argv = command.call_args.args[0]
        self.assertEqual(argv[2], admin.ROUTE_MANAGER_TEMPLATE_PROBE)
        self.assertNotIn('--value', argv)

    def test_systemd_observation_rejects_missing_duplicate_or_unkeyed_fields(self):
        for output in ('LoadState=loaded\n',
                       'LoadState=loaded\nLoadState=loaded\n',
                       'loaded\ninactive\nstatic\n/unit\n'):
            with self.subTest(output=output), patch.object(admin, 'run', return_value=output):
                with self.assertRaisesRegex(ValueError, 'service observation'):
                    admin.systemd_unit('wsprrypi.service')
        with self.assertRaises(ValueError): admin.run((sys.executable, '-c', 'print("x"*70000)'))
        with self.assertRaises(ValueError): admin.run((sys.executable, '-c', 'raise SystemExit(7)'))

    def test_retained_fault_never_recovers_to_success(self):
        machine = Machine(); machine.apply_error = -5
        with self.assertRaises(ValueError): admin.execute(machine, 1)
        with self.assertRaises(ValueError): admin.execute(machine, recover=True)
        self.assertEqual(machine.value['id'], 0)
        self.assertTrue(machine.value['flags'] & admin.FAULT)
        self.assertTrue(machine.mask)

    def test_ioctl_encoding_and_error_response(self):
        self.assertEqual(admin.FORMAT.size, 64)
        system = object.__new__(admin.Linux); system.fd = 99
        def ioctl(fd, command, data, mutate):
            self.assertEqual((fd, command, mutate), (99, 0xc040b801, True))
            self.assertEqual(admin.FORMAT.unpack(data)[:6], (0, 2, 0, 0, 7, 8))
            data[:] = admin.FORMAT.pack(0, 0, 0, 0, 7, 9, 12, -16, 1, 5, 0, 0)
        with patch.object(admin.fcntl, 'ioctl', side_effect=ioctl):
            result = system.call(admin.REMOVE, before={'session': 7, 'generation': 8})
        self.assertEqual(result['error'], -16)
        self.assertEqual(result['id'], 12)

    def test_every_ioctl_operation_sends_reserved0_zero(self):
        system = object.__new__(admin.Linux); system.fd = 99
        cases = ((admin.STATUS, 0, {'session': 0, 'generation': 0}),
                 (admin.APPLY, 2, {'session': 7, 'generation': 8}),
                 (admin.REMOVE, 0, {'session': 7, 'generation': 8}))
        for operation, route, before in cases:
            with self.subTest(operation=operation):
                def ioctl(unused_fd, unused_command, data, unused_mutate):
                    fields = admin.FORMAT.unpack(data)
                    self.assertEqual(fields[:6],
                        (0, operation, route, 0, before['session'], before['generation']))
                    generation = before['generation'] + (operation != admin.STATUS)
                    data[:] = admin.FORMAT.pack(
                        0, 0, 0, 0, 7, generation, 0, 0, 0, 0, 0, 0)
                with patch.object(admin.fcntl, 'ioctl', side_effect=ioctl):
                    system.call(operation, route, before)

    def test_nonzero_reserved0_response_is_rejected(self):
        system = object.__new__(admin.Linux); system.fd = 99
        def ioctl(unused_fd, unused_command, data, unused_mutate):
            data[:] = admin.FORMAT.pack(1, 0, 0, 0, 7, 0, 0, 0, 0, 0, 0, 0)
        with patch.object(admin.fcntl, 'ioctl', side_effect=ioctl):
            with self.assertRaisesRegex(ValueError, 'response schema'):
                system.call()

    def test_admin_uapi_source_contract_names_zero_only_reserved0(self):
        header = (ROOT / 'include/uapi/linux/rp1_route_admin.h').read_text()
        controller = (ROOT / 'controller/main.c').read_text()
        self.assertNotIn('RP1_ROUTE_ADMIN_ABI', header)
        self.assertRegex(header, r'struct rp1_route_admin\s*\{\s*__u32 reserved0;')
        self.assertIn('if (request.reserved0 || request.reserved ||', controller)
        self.assertNotIn('"raspberrypi,rp1"', controller)
        for compatible in ('raspberrypi,rp1-clocks', 'raspberrypi,rp1-gpio',
                           'snps,axi-dma-1.01a'):
            self.assertIn(f'"{compatible}"', controller)


if __name__ == '__main__':
    __import__("nonempty_unittest").main()
