#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hardware-free protocol/admin and durable deployment failure tests."""
import copy
import json
from pathlib import Path
import sys
import unittest
import tempfile
import os
import stat
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_manager as manager
import runtime_deployment as deploy
import runtime_controller_admin as admin
import runtime_binding
import runtime_activation
KERNEL = '6.18.34+rpt-rpi-2712'
from check_runtime_controller import Machine


class System(Machine):
    def __init__(self):
        super().__init__()
        self.record = None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def inhibited(self): return self.mask
    def read_record(self, name):
        if name != 'activation.json': return None
        application = {'version': 1, 'wasActive': True,
            'administratorMasked': False,
            'service': {'LoadState': 'loaded', 'ActiveState': 'active',
                'UnitFileState': 'enabled', 'MainPID': '42'},
            'companion': {'contract': 'wsprrypi-route-application-v1',
                'route': 'gpio4', 'transmit': False,
                'config': '/usr/local/etc/wsprrypi.ini'}}
        plan = {'version': 1, 'operation': 'neutral-activation',
            'bindingSha256': self.binding_hash, 'artifactSetSha256': 'b' * 64,
            'bootId': self.boot, 'lastDeploymentSha256': 'c' * 64,
            'application': application, 'socketWasActive': False,
            'alreadyReady': False, 'previousActivationSha256': None}
        return {'version': 1, 'plan': plan,
            'planSha256': runtime_activation.plan_digest(plan),
            'requestId': '00000000-0000-0000-0000-000000000001',
            'phase': 'complete-neutral', 'controller': self.call(),
            'manager': {}, 'application': {'phase': 'restored'}, 'error': None}
    def read_manager_record(self): return copy.deepcopy(self.record)
    def write_manager_record(self, value): self.record = copy.deepcopy(value)


class Files:
    def packaged_baseline(self): return {}
    def __init__(self):
        self.values = {}
        self.count = 0
        self.crash = None
        self.mask = False
        self.loaded = False
        self.external_valid = True
        self.removal_safe = True
        self.restored = None
        self.restore_fails = False
        self.application = {'version': 1, 'wasActive': True,
            'administratorMasked': False,
            'service': {'LoadState': 'loaded', 'ActiveState': 'active',
                'UnitFileState': 'enabled', 'MainPID': '42'},
            'companion': {'contract': 'wsprrypi-route-application-v1',
                'route': 'gpio4', 'transmit': False,
                'config': '/usr/local/etc/wsprrypi.ini'}}
    def read(self, path): return self.values.get(path)
    def write(self, path, data):
        self.values[path] = data
        self.count += 1
        if self.count == self.crash:
            raise OSError('crash after durable write')
    def preflight(self):
        if self.loaded: raise ValueError('loaded module')
    def verify_external(self, unused):
        if not self.external_valid: raise ValueError('external prerequisite mismatch')
    def application_state(self): return copy.deepcopy(self.application)
    def verify_application(self, expected):
        if expected != self.application: raise ValueError('application changed')
    def quiesce(self): self.mask = True
    def refresh(self): pass
    def preflight_removal(self):
        if not self.removal_safe: raise ValueError('active runtime')
    def restore_application(self, capture):
        if self.restore_fails: raise ValueError('restore failed')
        self.restored = copy.deepcopy(capture)


def deployment_values(journals_none=False):
    value = {'schemaVersion':3, 'contract':runtime_binding.CONTRACT,
        'productVersion':runtime_binding.PRODUCT_VERSION,
        'compatibilityIdentities':runtime_binding.COMPATIBILITY,
        'sourceCommit':'a'*40, 'kernel':KERNEL,
        'controllerNoteSha256':'a'*64, 'consumerNoteSha256':'b'*64,
        'files':{name:admin.digest(b'new') for name in deploy.INVENTORY},
        'modules': {name: {'name': name,
            'path': f'/lib/modules/{KERNEL}/updates/dkms/{name}.ko.xz',
            'installedFileSha256': ('1' if name == 'rp1_route_controller' else '2')*64,
            'decompressedElfSha256': ('3' if name == 'rp1_route_controller' else '4')*64,
            'compression': 'xz', 'buildNoteSha256':
                ('a' if name == 'rp1_route_controller' else 'b')*64,
            'version': runtime_binding.PRODUCT_VERSION, 'kernel': KERNEL}
            for name in ('rp1_route_controller', 'rp1_gpclk_dkms')},
        'externalFiles':{name:'c'*64 for name in runtime_binding.EXTERNAL_PATHS},
        'uapiSha256':{
            'consumer':admin.digest(b'new'), 'controller':admin.digest(b'new')}}
    value['artifactSetSha256'] = runtime_binding.canonical_digest(value)
    result = {path:b'new' for path in deploy.DESTINATIONS}
    result[deploy.BINDING] = json.dumps(value).encode()
    if journals_none:
        result.update({path:None for path in deploy.JOURNALS})
    return result


class Tests(unittest.TestCase):
    def request(self, system, route='gpio4', ident='request-0001'):
        reply = manager._dispatch({'schemaVersion':3, 'operation':'preflight', 'route':route}, lambda:system)
        return {'schemaVersion':3, 'operation':'switch', 'route':route, 'execute':True,
                'actor':'offline.test', 'requestId':ident,
                'preflightToken':reply['state']['preflightToken']}

    def test_complete_switch_replay_recovery(self):
        system = System()
        request = self.request(system)
        first = manager._dispatch(request, lambda:system)
        self.assertEqual(first['status'], 'complete-inhibited')
        count = len(system.events)
        self.assertEqual(manager._dispatch(request, lambda:system), first)
        self.assertEqual(len(system.events), count)
        request = self.request(system, 'gpio20', 'request-0002')
        self.assertEqual(manager._dispatch(request, lambda:system)['state']['activeRoute'], 'gpio20')
        result = manager._dispatch({'schemaVersion':3,'operation':'recover','execute':True,
            'requestId':'recover-0001','actor':'offline.test'}, lambda:system)
        self.assertIsNone(result['state']['activeRoute'])
        self.assertEqual(result['status'], 'recovered-inhibited')
        self.assertTrue(system.mask)

    def test_error_ownership_preserved(self):
        system = System()
        manager._dispatch(self.request(system), lambda:system)
        system.remove_error = -16
        result = manager._dispatch(self.request(system, 'gpio20', 'request-0002'), lambda:system)
        self.assertEqual(result['error']['kernelError'], -16)
        self.assertEqual(result['error']['overlayId'], 9)
        self.assertTrue(system.mask)
        self.assertEqual(system.value['route'], 1)

    def test_stale_boot_and_conflict_rejected(self):
        system = System()
        request = self.request(system)
        system.value['generation'] += 1
        with self.assertRaises(ValueError): manager._dispatch(request, lambda:system)
        self.assertFalse(system.events)
        request = self.request(system)
        manager._dispatch(request, lambda:system)
        system.boot = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        with self.assertRaises(ValueError): manager._dispatch(request, lambda:system)

    def test_legacy_effect_and_extra_fields_rejected(self):
        for operation in ('switch', 'apply-and-reboot', 'reconcile', 'recover'):
            with self.assertRaises(ValueError): manager.parse({'schemaVersion':1,'operation':operation})
        with self.assertRaises(ValueError): manager.parse({'schemaVersion':3,'operation':'query','execute':True})
        self.assertEqual(manager.parse({'operation':'query'})['schemaVersion'], 3)

    def test_every_deployment_crash_recovers_exact_old_bytes(self):
        values = deployment_values(journals_none=True)
        for crash in range(1, len(values)+4):
            files = Files()
            files.values = {path:b'old' for path in values}
            plan = deploy.plan(files, values)
            files.crash = crash
            try:
                deploy.apply(files, plan, deploy.plan_hash(plan))
            except OSError:
                files.crash = None
                pending = files.read(str(admin.STATE/'deployment-pending.json'))
                if pending is not None:
                    # A restarted process has only disk bytes, not the old object.
                    recovered_plan = admin.strict_json(pending)
                    self.assertEqual(recovered_plan, plan)
                    deploy.apply(files, recovered_plan, deploy.plan_hash(recovered_plan), recover=True)
                    self.assertTrue(all(files.read(path) == b'old' for path in values))
                else:
                    self.assertTrue(all(files.read(path) == values[path] for path in values))
            self.assertIsNone(files.read(str(admin.STATE/'deployment-pending.json')))

    def test_real_atomic_files_restore_and_incomplete_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = deploy.Files()
            # Only privilege/ancestor checks are replaced. Actual temporary-file,
            # fsync, rename and unlink implementations run in a disposable root.
            def read(path, limit=32*1024*1024):
                return Path(path).read_bytes()
            def sync(path):
                fd = os.open(path, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
            with patch.object(admin, 'safe_directory', lambda path: None), \
                 patch.object(admin, 'read_regular', read), \
                 patch.object(admin, 'fsync_dir', sync):
                path = str(Path(directory) / 'nested' / 'payload')
                backend.write(path, b'old')
                self.assertEqual(backend.read(path), b'old')
                backend.write(path, b'new')
                self.assertEqual(backend.read(path), b'new')
                backend.write(path, None)
                self.assertIsNone(backend.read(path))
                self.assertEqual(list(Path(path).parent.iterdir()), [])

    def test_only_trusted_system_library_alias_is_accepted(self):
        def info(path):
            return SimpleNamespace(st_uid=0, st_mode=(stat.S_IFLNK | 0o777) if str(path)=='/lib' else stat.S_IFDIR | 0o755)
        with patch.object(Path, 'lstat', info), patch.object(os, 'readlink', return_value='usr/lib'):
            admin.safe_directory(Path('/lib/modules/example/updates/dkms'))
        with patch.object(Path, 'lstat', info), patch.object(os, 'readlink', return_value='/tmp/foreign'):
            with self.assertRaises(ValueError): admin.safe_directory(Path('/lib/modules'))

    def test_replay_does_not_claim_lost_inhibition(self):
        system = System()
        request = self.request(system)
        manager._dispatch(request, lambda:system)
        system.mask = False
        with self.assertRaises(ValueError): manager._dispatch(request, lambda:system)

    def test_loaded_module_refusal_has_no_pending_marker(self):
        files = Files()
        files.loaded = True
        value = deploy.plan(files, deployment_values())
        with self.assertRaisesRegex(ValueError, 'loaded'):
            deploy.apply(files, value, deploy.plan_hash(value))
        self.assertEqual(files.count, 0)
        self.assertFalse(files.mask)

    def test_oversized_or_malformed_journal_has_no_effects(self):
        files = Files()
        value = deploy.plan(files, deployment_values())
        with patch.object(deploy, 'MAX_JOURNAL_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'read bound'):
                deploy.apply(files, value, deploy.plan_hash(value))
        self.assertEqual(files.count, 0)
        value['version'] = True
        with self.assertRaises(ValueError): deploy.apply(files, value, deploy.plan_hash(value))
        self.assertEqual(files.count, 0)

    def test_bundle_reads_bound_and_reject_nonregular_members(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'member'
            path.write_bytes(b'12345')
            with self.assertRaisesRegex(ValueError, 'bound'): deploy.bundle_read(path, 4)
            self.assertEqual(deploy.bundle_read(path, 5), b'12345')
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError): deploy.bundle_read(link)

    def test_binding_is_read_once_and_same_bytes_are_installed(self):
        value = {'schemaVersion':3, 'contract':runtime_binding.CONTRACT,
            'productVersion':runtime_binding.PRODUCT_VERSION,
            'compatibilityIdentities':runtime_binding.COMPATIBILITY,
            'sourceCommit':'a'*40, 'kernel':KERNEL,
            'controllerNoteSha256':'a'*64, 'consumerNoteSha256':'b'*64,
            'files':{name:admin.digest(b'payload') for name in deploy.INVENTORY},
            'modules': {name: {'name': name,
                'path': f'/lib/modules/{KERNEL}/updates/dkms/{name}.ko.xz',
                'installedFileSha256': ('1' if name == 'rp1_route_controller' else '2')*64,
                'decompressedElfSha256': ('3' if name == 'rp1_route_controller' else '4')*64,
                'compression': 'xz', 'buildNoteSha256':
                    ('a' if name == 'rp1_route_controller' else 'b')*64,
                'version': runtime_binding.PRODUCT_VERSION, 'kernel': KERNEL}
                for name in ('rp1_route_controller', 'rp1_gpclk_dkms')},
            'externalFiles':{name:'c'*64 for name in runtime_binding.EXTERNAL_PATHS},
            'uapiSha256':{
                'consumer':admin.digest(b'payload'), 'controller':admin.digest(b'payload')}}
        value['artifactSetSha256'] = runtime_binding.canonical_digest(value)
        raw = json.dumps(value).encode()
        reads = []
        def read(unused, name, limit=deploy.MAX_FILE_BYTES):
            reads.append(name)
            return raw if name == 'binding.json' else b'payload'
        with patch.object(deploy.os, 'open', return_value=9), \
             patch.object(deploy.os, 'fstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR|0o700)), \
             patch.object(deploy.os, 'close'), patch.object(deploy, 'bundle_member', read):
            values = deploy.payloads(Path('/offline'))
        self.assertEqual(reads.count('binding.json'), 1)
        self.assertEqual(values[deploy.BINDING], raw)

    def test_invalid_binding_rejected_before_payload_reads(self):
        for value in ([], {'files':None}, {'schemaVersion':True, 'kernel':KERNEL,
                'files':{}, 'controllerNoteSha256':'a'*64, 'consumerNoteSha256':'b'*64}):
            with patch.object(deploy.os, 'open', return_value=9), \
                 patch.object(deploy.os, 'fstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR|0o700)), \
                 patch.object(deploy.os, 'close'), \
                 patch.object(deploy, 'bundle_member', return_value=json.dumps(value).encode()) as reader:
                with self.assertRaises(ValueError): deploy.payloads(Path('/offline'))
                self.assertEqual(reader.call_count, 1)

    def test_bundle_directory_symlink_and_writable_directory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root/'bundle'; bundle.mkdir(); bundle.chmod(0o777)
            with self.assertRaisesRegex(ValueError, 'writable'):
                deploy.payloads(bundle)
            link = root/'link'; link.symlink_to(bundle, target_is_directory=True)
            with self.assertRaises(OSError): deploy.payloads(link)

    def test_deployment_lock_excludes_concurrent_ensure(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(admin, 'STATE', Path(directory)), \
             patch.object(admin, 'safe_directory'), \
             patch.object(deploy.os, 'geteuid', return_value=0), \
             patch.object(deploy.os, 'uname', return_value=SimpleNamespace(release=KERNEL)), \
             patch.object(deploy.os, 'fstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o600, st_uid=0)):
            with deploy.mutation_lock():
                with self.assertRaises(BlockingIOError):
                    with deploy.mutation_lock(): pass

    def test_approved_mutation_provisions_fixed_state_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root/'var/lib'; base.mkdir(parents=True)
            state = base/'rp1-gpclk-dkms/runtime-admin'
            def validate(path):
                info = Path(path).lstat()
                if (not stat.S_ISDIR(info.st_mode) or
                        stat.S_IMODE(info.st_mode) & 0o022):
                    raise ValueError('untrusted directory')
            with patch.object(admin, 'STATE', state), \
                 patch.object(admin, 'safe_directory', side_effect=validate), \
                 patch.object(admin, 'fsync_dir') as sync:
                deploy.provision_state()
                deploy.provision_state()
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(state.parent.stat().st_mode), 0o755)
            self.assertEqual(sync.call_count, 2)

    def test_state_provisioning_rejects_unsafe_existing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root/'var/lib'; base.mkdir(parents=True)
            parent = base/'rp1-gpclk-dkms'; parent.mkdir(mode=0o777)
            parent.chmod(0o777)
            state = parent/'runtime-admin'
            def validate(path):
                info = Path(path).lstat()
                if (not stat.S_ISDIR(info.st_mode) or
                        stat.S_IMODE(info.st_mode) & 0o022):
                    raise ValueError('untrusted directory')
            with patch.object(admin, 'STATE', state), \
                 patch.object(admin, 'safe_directory', side_effect=validate):
                with self.assertRaisesRegex(ValueError, 'untrusted'):
                    deploy.provision_state()

    def test_state_provisioning_rejects_symlinked_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root/'var/lib'; base.mkdir(parents=True)
            parent = base/'rp1-gpclk-dkms'; parent.mkdir()
            target = root/'foreign'; target.mkdir()
            state = parent/'runtime-admin'; state.symlink_to(target)
            def validate(path):
                info = Path(path).lstat()
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError('untrusted directory')
            with patch.object(admin, 'STATE', state), \
                 patch.object(admin, 'safe_directory', side_effect=validate):
                with self.assertRaisesRegex(ValueError, 'untrusted'):
                    deploy.provision_state()

    def test_removed_directory_pruning_accepts_only_bounded_runtime_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root/'state'; state.mkdir(); lock = state/'lock'
            lock.write_bytes(b''); lock.chmod(0o600)
            application_lock = state/'application-lock'
            application_lock.write_bytes(b''); application_lock.chmod(0o600)
            archive = b'{"phase":"complete-neutral"}'
            archive_path = state/('prior-activation-' + admin.digest(archive) + '.json')
            archive_path.write_bytes(archive + b'\n'); archive_path.chmod(0o600)
            library = root/'runtime'; cache = library/'__pycache__'
            cache.mkdir(parents=True)
            (cache/'runtime_provider.cpython-313.pyc').write_bytes(b'derived')
            files = deploy.Files()
            with patch.object(admin, 'STATE', state), \
                 patch.object(deploy, 'RUNTIME_LIBRARY', library), \
                 patch.object(admin, 'safe_directory'), \
                 patch.object(admin, 'fsync_dir'):
                files.prune_removed_directories(expected_uid=os.geteuid())
            self.assertFalse(state.exists() or library.exists())

    def test_passive_package_baseline_preserves_only_exact_overlays(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            names = ('usr/lib/systemd/system/rp1-gpclk-route-manager.socket',
                     'usr/lib/systemd/system/rp1-gpclk-route-manager@.service',
                     'usr/lib/rp1-gpclk-dkms/overlays/rp1-gpclk-gpio4.dtbo',
                     'usr/lib/rp1-gpclk-dkms/overlays/rp1-gpclk-gpio20.dtbo')
            paths = []
            for name in names:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode()); path.chmod(0o644)
                paths.append(path)
            database = root/'var/lib/dpkg/info'; database.mkdir(parents=True)
            (database/'rp1-gpclk-dkms.list').write_text(''.join('/'+name+'\n' for name in names) +
                '/usr/lib/rp1-gpclk-dkms/overlays\n')
            (database/'rp1-gpclk-dkms.md5sums').write_text(''.join(
                hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()+'  '+name+'\n' for name in names))
            files = deploy.Files()
            with patch.object(admin, 'run', return_value='install ok installed\n0.99.0-1'), \
                 patch.object(admin, 'safe_directory'), patch.object(admin, 'read_regular', side_effect=lambda p, limit: Path(p).read_bytes()), \
                 patch.object(deploy.package_preflight, 'OWNER_UID', os.geteuid()):
                baseline = files.packaged_baseline(root)
                self.assertEqual(set(baseline), set(map(str, paths)))
                for bad in ('changed', 'missing', 'foreign'):
                    if bad == 'changed': paths[-1].write_bytes(b'changed')
                    elif bad == 'missing': paths[-1].unlink()
                    else:
                        paths[-1].write_bytes(names[-1].encode())
                        (paths[-1].parent/'foreign.dtbo').write_bytes(b'foreign')
                    with self.assertRaises(ValueError): files.packaged_baseline(root)
                (paths[-1].parent/'foreign.dtbo').unlink()
            library = root/'usr/lib/rp1-gpclk-dkms'
            for name in ('schema', 'runtime-uapi', 'runtime-overlays'):
                (library/name).mkdir()
            cache = library/'__pycache__'; cache.mkdir()
            (cache/'package_preflight.cpython-313.pyc').write_bytes(b'cache')
            with patch.object(files, 'packaged_baseline', return_value=baseline), \
                 patch.object(admin, 'STATE', root/'absent-state'), \
                 patch.object(deploy, 'RUNTIME_LIBRARY', library), \
                 patch.object(admin, 'safe_directory'), patch.object(admin, 'fsync_dir'), \
                 patch.object(admin, 'read_regular', side_effect=lambda p, limit: Path(p).read_bytes()):
                files.prune_removed_directories(expected_uid=os.geteuid())
                self.assertTrue(library.exists())
                self.assertEqual(set(library.iterdir()), {library/'overlays'})
                self.assertTrue(all(path.exists() for path in paths))
                with patch.object(files, 'packaged_baseline', side_effect=FileNotFoundError('missing database')):
                    with self.assertRaises(FileNotFoundError):
                        files.prune_removed_directories(expected_uid=os.geteuid())
                with patch.object(admin, 'read_regular', side_effect=FileNotFoundError('overlay race')):
                    with self.assertRaises(FileNotFoundError):
                        files.prune_removed_directories(expected_uid=os.geteuid())
                (library/'foreign').write_bytes(b'preserve')
                with self.assertRaisesRegex(ValueError, 'unexpected residue'):
                    files.prune_removed_directories(expected_uid=os.geteuid())
                self.assertEqual((library/'foreign').read_bytes(), b'preserve')

    def test_removed_directory_pruning_rejects_unowned_application_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root/'state'; state.mkdir()
            lock = state/'lock'; lock.write_bytes(b''); lock.chmod(0o600)
            application_lock = state/'application-lock'
            application_lock.write_bytes(b'foreign'); application_lock.chmod(0o644)
            library = root/'runtime'; library.mkdir()
            with patch.object(admin, 'STATE', state), \
                 patch.object(deploy, 'RUNTIME_LIBRARY', library), \
                 patch.object(admin, 'safe_directory'), \
                 patch.object(admin, 'fsync_dir'):
                with self.assertRaisesRegex(ValueError, 'application-lock identity'):
                    deploy.Files().prune_removed_directories(
                        expected_uid=os.geteuid())
            self.assertTrue(application_lock.exists())
            self.assertTrue(lock.exists())

    def test_removed_directory_pruning_rejects_unowned_activation_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root/'state'; state.mkdir(); lock = state/'lock'
            lock.write_bytes(b''); lock.chmod(0o600)
            archive = state/('prior-activation-' + '0'*64 + '.json')
            archive.write_bytes(b'foreign\n'); archive.chmod(0o600)
            library = root/'runtime'; library.mkdir()
            with patch.object(admin, 'STATE', state), \
                 patch.object(deploy, 'RUNTIME_LIBRARY', library), \
                 patch.object(admin, 'safe_directory'), \
                 patch.object(admin, 'fsync_dir'):
                with self.assertRaisesRegex(ValueError, 'archive identity differs'):
                    deploy.Files().prune_removed_directories(expected_uid=os.geteuid())
            self.assertTrue(archive.exists())

    def test_removed_directory_pruning_rejects_unexpected_bytecode_residue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root/'state'; state.mkdir(); lock = state/'lock'
            lock.write_bytes(b''); lock.chmod(0o600)
            library = root/'runtime'; cache = library/'__pycache__'
            cache.mkdir(parents=True); (cache/'foreign.pyc').write_bytes(b'x')
            with patch.object(admin, 'STATE', state), \
                 patch.object(deploy, 'RUNTIME_LIBRARY', library), \
                 patch.object(admin, 'safe_directory'), \
                 patch.object(admin, 'fsync_dir'):
                with self.assertRaisesRegex(ValueError, 'unexpected runtime bytecode'):
                    deploy.Files().prune_removed_directories(expected_uid=os.geteuid())

    def test_neutrality_rechecked_after_application_stop(self):
        loaded = False
        def stop(shell):
            nonlocal loaded
            loaded = True
        with patch.object(Path, 'exists', lambda path:loaded), \
             patch.object(admin, 'read_regular', return_value=b'boot'), \
             patch.object(admin.Linux, 'inhibit', stop):
            with self.assertRaisesRegex(ValueError, 'loaded module'):
                deploy.Files().quiesce()

    def test_removal_preflight_requires_inactive_exact_units(self):
        exact = {
            'load': 'loaded', 'active': 'inactive', 'enabled': 'disabled',
            'fragment': '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'}
        template = dict(exact, enabled='static',
            fragment='/usr/lib/systemd/system/rp1-gpclk-route-manager@.service')
        with patch.object(deploy.Files, 'preflight'), \
             patch.object(Path, 'exists', return_value=False), \
             patch.object(admin, 'systemd_unit', side_effect=[exact, template]):
            deploy.Files().preflight_removal()
        changed = dict(exact, fragment='/tmp/foreign.socket')
        with patch.object(deploy.Files, 'preflight'), \
             patch.object(Path, 'exists', return_value=False), \
             patch.object(admin, 'systemd_unit', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'substituted runtime unit'):
                deploy.Files().preflight_removal()

    def test_provider_recovery_revalidates_state_under_controller_lock(self):
        system = System()
        reviewed = manager.response(system, 'query', system.call())['state']
        reviewed['bindingSha256'] = 'f' * 64
        request = {'schemaVersion': 3, 'operation': 'recover', 'execute': True,
                   'requestId': 'provider-1234', 'actor': 'offline.test'}
        with patch.object(admin, 'execute') as effects:
            with self.assertRaisesRegex(ValueError, 'stale provider recovery'):
                manager._dispatch(request, lambda: system, expected_recovery=reviewed)
        effects.assert_not_called()
        self.assertIsNone(system.record)

    def test_removal_preflight_accepts_only_attributed_missing_units(self):
        files = Files()
        retained = deploy.plan(files, deployment_values(journals_none=True))
        missing = {'load': 'not-found', 'active': 'inactive',
                   'enabled': '', 'fragment': ''}
        for mutation in ('none', 'foreign-file', 'unowned-before', 'no-plan'):
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(retained)
                if mutation == 'unowned-before':
                    value['files']['/usr/lib/systemd/system/rp1-gpclk-route-manager.socket']['before'] = deploy.encode(b'old')
                with patch.object(deploy.Files, 'preflight'), \
                     patch.object(Path, 'exists', return_value=False), \
                     patch.object(admin, 'systemd_unit', return_value=missing), \
                     patch.object(deploy.Files, 'read', return_value=b'foreign' if mutation == 'foreign-file' else None), \
                     patch.object(deploy, 'removal_plan', side_effect=ValueError('no plan') if mutation == 'no-plan' else None, return_value=value):
                    if mutation == 'none':
                        deploy.Files().preflight_removal()
                    else:
                        with self.assertRaises(ValueError):
                            deploy.Files().preflight_removal()

    def test_quiescence_failure_preserves_barrier(self):
        files = Files()
        value = deploy.plan(files, deployment_values())
        with patch.object(files, 'quiesce', side_effect=ValueError('stop incomplete')):
            with self.assertRaises(ValueError): deploy.apply(files, value, deploy.plan_hash(value))
        self.assertIsNotNone(files.read(str(admin.STATE/'deployment-pending.json')))
        self.assertTrue(all(files.read(path) is None for path in deploy.DESTINATIONS))

    def test_change_during_quiescence_blocks_publication(self):
        files = Files()
        values = deployment_values()
        value = deploy.plan(files, values)
        changed = sorted(values)[0]
        def quiesce():
            files.mask = True
            files.values[changed] = b'foreign'
        files.quiesce = quiesce
        with self.assertRaisesRegex(ValueError, 'during quiescence'):
            deploy.apply(files, value, deploy.plan_hash(value))
        self.assertIsNotNone(files.read(str(admin.STATE/'deployment-pending.json')))
        self.assertTrue(all(files.read(path) is None for path in values if path != changed))

    def test_external_prerequisite_change_during_quiescence_blocks_publication(self):
        files = Files()
        values = deployment_values()
        value = deploy.plan(files, values)
        def quiesce():
            files.mask = True
            files.external_valid = False
        files.quiesce = quiesce
        with self.assertRaisesRegex(ValueError, 'external prerequisite'):
            deploy.apply(files, value, deploy.plan_hash(value))
        self.assertIsNotNone(files.read(str(admin.STATE/'deployment-pending.json')))
        self.assertTrue(all(files.read(path) is None for path in values))

    def test_foreign_change_blocks_all_recovery(self):
        files = Files()
        values = deployment_values()
        plan = deploy.plan(files, values)
        path = sorted(values)[0]
        files.values[path] = b'foreign'
        with self.assertRaises(ValueError): deploy.apply(files, plan, deploy.plan_hash(plan), recover=True)
        self.assertEqual(files.count, 0)
        with self.assertRaises(ValueError): deploy.apply(files, plan, '0'*64)

    def test_reviewed_removal_restores_exact_predeployment_bytes_and_application(self):
        files = Files()
        value = deploy.plan(files, deployment_values(journals_none=True))
        digest = deploy.plan_hash(value)
        deploy.apply(files, value, digest)
        self.assertEqual(deploy.removal_plan(files), value)
        deploy.remove(files, value, digest)
        self.assertTrue(all(files.read(path) is None for path in deploy.DESTINATIONS))
        self.assertIsNone(files.read(deploy.LAST_DEPLOYMENT))
        self.assertEqual(files.restored, files.application)

    def test_removal_rejects_digest_drift_active_runtime_and_foreign_bytes(self):
        for failure in ('digest', 'active', 'foreign'):
            with self.subTest(failure=failure):
                files = Files()
                value = deploy.plan(files, deployment_values(journals_none=True))
                digest = deploy.plan_hash(value)
                deploy.apply(files, value, digest)
                if failure == 'active': files.removal_safe = False
                if failure == 'foreign': files.values[sorted(deploy.INVENTORY)[0]] = b'foreign'
                with self.assertRaises(ValueError):
                    deploy.remove(files, value, '0'*64 if failure == 'digest' else digest)
                self.assertIsNone(files.restored)

    def test_removal_retains_barrier_through_application_restore_and_can_retry(self):
        files = Files()
        value = deploy.plan(files, deployment_values(journals_none=True))
        digest = deploy.plan_hash(value)
        deploy.apply(files, value, digest)
        files.restore_fails = True
        with self.assertRaisesRegex(ValueError, 'restore failed'):
            deploy.remove(files, value, digest)
        pending = str(admin.STATE/'deployment-pending.json')
        self.assertIsNotNone(files.read(pending))
        self.assertIsNone(files.read(deploy.LAST_DEPLOYMENT))
        self.assertEqual(deploy.removal_plan(files), value)
        files.restore_fails = False
        deploy.remove(files, value, digest)
        self.assertIsNone(files.read(pending))
        self.assertEqual(files.restored, files.application)


if __name__ == '__main__':
    __import__("nonempty_unittest").main()
