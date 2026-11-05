#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline ownership/fault regressions; these are not dpkg lifecycle evidence."""
import gzip
import hashlib
import lzma
import os
import json
import runpy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'tools'))
import lifecycle_metadata as module_metadata
import lifecycle_coverage as coverage
import lifecycle_results as results
import lifecycle_process as processes
import package_preflight as guard
import package_stage as stage
import package_indices as indices
import package_signatures as signatures


def put(root, name, data=b'fixture'):
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def owned_source(root):
    source = root/'usr/src/rp1-gpclk-dkms-0.0.1'
    path = put(root, str(source.relative_to(root))+'/dkms.conf')
    database = root/'var/lib/dpkg/info'
    database.mkdir(parents=True, exist_ok=True)
    (database/'rp1-gpclk-dkms.list').write_text(
        '/'+str(source.relative_to(root))+'\n/'+str(path.relative_to(root))+'\n')
    (database/'rp1-gpclk-dkms.md5sums').write_text(
        hashlib.md5(path.read_bytes()).hexdigest()+'  '+str(path.relative_to(root))+'\n')
    return source


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(guard, 'OWNER_UID', os.getuid())
        self.patch.start()
        self.features = patch.object(guard, 'native_features', return_value={'+XZ', '+ZLIB', '+ZSTD'})
        self.features.start()

    def tearDown(self):
        self.features.stop()
        self.patch.stop()
        self.temp.cleanup()

    def test_foreign_unbuilt_registration_and_different_version(self):
        root = self.root
        base = root/'var/lib/dkms/rp1-gpclk-dkms'
        for version in ('0.0.1', '0.9.0', '9.9.9'):
            path = base/version
            path.mkdir(parents=True)
            for operation in ('unpack', 'configure', 'remove'):
                with self.subTest(version=version, operation=operation), self.assertRaises(ValueError):
                    guard.check(root, operation)
                self.assertTrue(path.is_dir())
            path.rmdir()

    def test_orphan_kernel_link_and_foreign_cache_file_are_preserved(self):
        root = self.root
        source = owned_source(root)
        base = root/'var/lib/dkms/rp1-gpclk-dkms'
        base.mkdir(parents=True)
        metadata = base/'kernel-6.18.50+rpt-rpi-2712-aarch64'
        metadata.symlink_to('0.0.1/6.18.50+rpt-rpi-2712/aarch64')
        with self.assertRaisesRegex(ValueError, 'orphan'):
            guard.check(root, 'remove')
        metadata.unlink()
        version = base/'0.0.1'
        version.mkdir()
        (version/'source').symlink_to(source)
        foreign = put(root, str(version.relative_to(root))+'/foreign.txt', b'preserve')
        with self.assertRaises(ValueError):
            guard.check(root, 'remove')
        self.assertEqual(foreign.read_bytes(), b'preserve')
        foreign.unlink()
        copied = put(root, str(version.relative_to(root))+'/build/dkms.conf', b'changed source copy')
        with self.assertRaisesRegex(ValueError, 'modified DKMS source copy'):
            guard.check(root, 'remove')
        copied.write_bytes((source/'dkms.conf').read_bytes())
        guard.check(root, 'remove')
        copied.with_name('foreign').write_bytes(b'preserve cache evidence')
        with self.assertRaisesRegex(ValueError, 'foreign DKMS build file'):
            guard.check(root, 'remove')

    def test_drift_and_unlisted_files_are_preserved_before_removal(self):
        root = self.root
        source = owned_source(root)
        guard.check(root)
        config = source/'dkms.conf'
        config.write_bytes(b'administrator changes')
        for operation in ('unpack', 'configure', 'remove'):
            with self.assertRaisesRegex(ValueError, 'modified package'):
                guard.check(root, operation)
        self.assertEqual(config.read_bytes(), b'administrator changes')
        config.write_bytes(b'fixture')
        config.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'modified package mode'):
            guard.check(root, 'remove')
        config.chmod(0o644)
        foreign = source/'foreign'
        foreign.write_bytes(b'retain')
        with self.assertRaisesRegex(ValueError, 'foreign package descendant'):
            guard.check(root, 'remove')
        self.assertEqual(foreign.read_bytes(), b'retain')
        foreign.unlink()
        config.unlink()
        with self.assertRaisesRegex(ValueError, 'missing package'):
            guard.check(root)
        # dpkg may restore missing bytes on reinstall, or finish removal.
        guard.check(root, 'unpack')
        guard.check(root, 'remove')

    def test_runtime_development_and_application_ownership_refusal(self):
        root = self.root
        for name in (
            'var/lib/wsprrypi/rp1-gpclk-dkms-installation.json',
            'etc/rp1-gpclk-dkms/development/record.json',
            'usr/lib/rp1-gpclk-dkms/runtime_activation.py',
            'usr/lib/rp1-gpclk-dkms/package_preflight.py',
            'usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_gpclk.h',
            'usr/lib/rp1-gpclk-dkms/runtime-overlays/gpio20.dtbo',
            'etc/systemd/system/rp1-gpclk-route-manager@.service.d/95-runtime-controller.conf'):
            path = put(root, name, b'foreign or owning workflow evidence')
            for operation in ('unpack', 'configure', 'remove'):
                with self.subTest(name=name, operation=operation), self.assertRaises(ValueError):
                    guard.check(root, operation)
                self.assertEqual(path.read_bytes(), b'foreign or owning workflow evidence')
            path.unlink()
            # Empty directories remain residue too; remove only fixture parents.
            parent = path.parent
            while parent != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

    def test_removal_refuses_overrides_without_executing_them(self):
        path = put(self.root, 'etc/dkms/rp1-gpclk-dkms.conf', b'PRE_REMOVE="foreign"\n')
        with patch('subprocess.run') as command:
            with self.assertRaisesRegex(ValueError, 'module override'):
                guard.check(self.root, 'remove')
            command.assert_not_called()
        self.assertEqual(path.read_bytes(), b'PRE_REMOVE="foreign"\n')

    def test_compressed_signed_identity_and_duplicate_refusal(self):
        root = self.root
        source = owned_source(root)
        base = root/'var/lib/dkms/rp1-gpclk-dkms/0.0.1'
        base.mkdir(parents=True)
        (base/'source').symlink_to(source)
        kernel = '6.18.50+rpt-rpi-2712'
        (base.parent/('kernel-'+kernel+'-aarch64')).symlink_to('0.0.1/'+kernel+'/aarch64')
        put(root, 'lib/modules/'+kernel+'/build/.config', b'# unsigned header fixture\n')
        # Compact bytes test identity mechanics, not ELF/signature validity.
        elf = b'\x7fELF\x02\x01\0version=0.0.1\0signed-fixture-trailer'
        cache = put(root, str(base.relative_to(root))+'/'+kernel+'/aarch64/module/rp1_gpclk_dkms.ko', elf)
        stem = 'lib/modules/'+kernel+'/updates/dkms/rp1_gpclk_dkms.ko'
        for suffix, encode in (('', lambda x:x), ('.gz', gzip.compress), ('.xz', lzma.compress)):
            module = put(root, stem+suffix, encode(elf))
            guard.check(root, 'remove')
            cache.write_bytes(elf+b'drift')
            with self.assertRaisesRegex(ValueError, 'modified provider module'):
                guard.check(root, 'remove')
            cache.write_bytes(elf)
            module.unlink()
        first = put(root, stem, elf)
        second = put(root, stem+'.xz', lzma.compress(elf))
        with self.assertRaisesRegex(ValueError, 'duplicate compressed'):
            guard.check(root, 'remove')
        self.assertEqual(first.read_bytes(), elf)
        self.assertEqual(lzma.decompress(second.read_bytes()), elf)

    def test_incoming_guard_is_exact_source_and_before_debhelper(self):
        destination = self.root/'package'
        control = destination/'DEBIAN'
        control.mkdir(parents=True)
        path = control/'preinst'
        path.write_bytes((ROOT/'debian/rp1-gpclk-dkms.preinst').read_bytes())
        stage.preinst(destination)
        text = path.read_text()
        self.assertIn((ROOT/'scripts/package_preflight.py').read_text(), text)
        self.assertLess(text.index("python3 -I - unpack"), text.index('#DEBHELPER#'))
        for name in ('postinst', 'prerm'):
            self.assertIn('python3 -I /usr/libexec/rp1-gpclk-dkms/package_preflight.py',
                          (ROOT/('debian/rp1-gpclk-dkms.'+name)).read_text())
        with self.assertRaises(ValueError):
            stage.preinst(destination)

    def test_synthetic_predecessor_fixture_and_tamper_refusal(self):
        builder = runpy.run_path(str(ROOT/'scripts/build-lifecycle-predecessor'))
        record = json.loads((ROOT/'release/lifecycle-predecessor-v1.json').read_text())
        builder['select']('a'*40, record)
        for commit in ('main', 'a'*12, 'G'*40):
            with self.assertRaises(ValueError): builder['select'](commit, record)
        files = {'include/rp1_gpclk/version.h': (0o644,
            b'#define RP1_GPCLK_MODULE_VERSION "1.2.3"\n')}
        files.update({
            'tests/fixtures/lifecycle-legacy/'+name: (0o644, (ROOT/'tests/fixtures/lifecycle-legacy'/name).read_bytes())
            for name in record['fixtureSha256']})
        rendered, changes = builder['render'](files, record)
        self.assertIn(b'"0.0.0"', rendered['include/rp1_gpclk/version.h'][1])
        self.assertIn(b'Synthetic legacy lifecycle', rendered['debian/changelog'][1])
        self.assertIn(b'override_dh_builddeb:', rendered['debian/rules'][1])
        self.assertEqual(len(changes), len(record['fixtureSha256']))
        for name in record['fixtureSha256']:
            if name != 'rules':
                self.assertEqual(rendered['debian/'+name][1],
                    (ROOT/'tests/fixtures/lifecycle-legacy'/name).read_bytes())
        changed = json.loads(json.dumps(record))
        changed['fixtureSha256']['rules'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'fixture differs'):
            builder['render'](files, changed)
        with self.assertRaises(ValueError):
            builder['render']({'include/rp1_gpclk/version.h': (0o644, b'no version')}, record)

    def test_removal_framework_cannot_redirect_compression_or_hooks(self):
        path = put(self.root, 'etc/dkms/framework.conf')
        for text in ('compress_zstd_opts="-o /boot/config.txt"',
                     'autoinstall_all_kernels=""', 'tmp_location="/foreign"',
                     'sign_tool="/foreign"'):
            path.write_text(text+'\n')
            with self.assertRaises(ValueError):
                guard.check(self.root, 'remove')

    def test_missing_native_compression_is_refused_before_mutation(self):
        path = put(self.root, 'lib/modules/6.18.50+rpt-rpi-2712/kernel/foreign.ko.gz', gzip.compress(b'fixture'))
        with patch.object(guard, 'native_features', return_value={'+XZ', '+ZSTD'}):
            with self.assertRaisesRegex(ValueError, 'compression support'):
                guard.check(self.root, 'remove')
        self.assertEqual(gzip.decompress(path.read_bytes()), b'fixture')

    def test_explicit_depmod_failure_and_retry_are_not_masked(self):
        import subprocess
        kernel = '6.18.50+rpt-rpi-2712'
        for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
            put(self.root, 'lib/modules/'+kernel+'/updates/dkms/'+name+'.ko')
        put(self.root, 'lib/modules/'+kernel+'/build/.config', b'# unsigned fixture\n')
        command = ['/usr/sbin/depmod', '-b', str(self.root), '-a', kernel]
        with patch.object(indices, 'check'), patch.object(indices.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess(command, 64, '', 'underlying depmod failure')
            with self.assertRaises(indices.IndexFailure) as caught:
                indices.update(self.root)
            self.assertEqual(caught.exception.result['exitStatus'], 64)
            self.assertEqual(caught.exception.result['command'], command)
            self.assertIn('underlying depmod failure', caught.exception.result['diagnostic'])
            run.return_value = subprocess.CompletedProcess(command, 0, '', '')
            self.assertEqual(indices.update(self.root)['status'], 'complete')
            for path in (self.root/'lib/modules'/kernel/'updates/dkms').iterdir():
                path.unlink()
            self.assertEqual(indices.update(self.root, 'remove')['status'], 'complete')
            self.assertEqual(run.call_count, 3)

    def test_package_helper_never_creates_unowned_bytecode(self):
        import shutil
        import subprocess
        directory = self.root/'installed-helpers'
        directory.mkdir()
        for name in ('package_indices.py', 'package_preflight.py', 'package_signatures.py'):
            shutil.copyfile(ROOT/'scripts'/name, directory/name)
        subprocess.run([sys.executable, '-I', '-c',
                        'import runpy,sys; runpy.run_path(sys.argv[1])',
                        str(directory/'package_indices.py')], check=True)
        self.assertFalse((directory/'__pycache__').exists())

    def test_missing_malformed_and_unverifiable_signature_are_fail_closed(self):
        import struct
        import subprocess
        elf = b'\x7fELF\x02\x01fixture'
        cms = b'fixture CMS bytes'
        trailer = b'\0\0\x02\0\0\0\0\0'+struct.pack('>I', len(cms))
        signed = elf+cms+trailer+signatures.MAGIC
        self.assertEqual(signatures.split_signature(signed), (elf, cms))
        for data in (elf, signed[:-1], elf+cms+trailer[:8]+struct.pack('>I', 999999)+signatures.MAGIC):
            with self.assertRaises(ValueError):
                signatures.split_signature(data)
        certificate = put(self.root, 'public-certificate', b'fixture DER')
        with patch.object(signatures.subprocess, 'run') as command:
            command.return_value = subprocess.CompletedProcess(['openssl'], 7, '', 'bad certificate')
            with self.assertRaises(signatures.SignatureFailure) as caught:
                signatures.verify(signed, certificate, '/fixture/module.ko')
            self.assertEqual(caught.exception.result['exitStatus'], 7)
            self.assertEqual(caught.exception.result['stage'], 'signature')
            self.assertIn('bad certificate', caught.exception.result['diagnostic'])
            for error, status in ((FileNotFoundError('openssl missing'), 127),
                                  (subprocess.TimeoutExpired(['openssl'], 15), 124)):
                command.side_effect = error
                with self.assertRaises(signatures.SignatureFailure) as caught:
                    signatures.verify(signed, certificate, '/fixture/module.ko')
                self.assertEqual(caught.exception.result['exitStatus'], status)

    def test_exact_header_archive_inventory_is_consumed_by_provisioning(self):
        import re
        manifest = ROOT/'tools/lifecycle-headers.sha256'
        rows = [line.split() for line in manifest.read_text().splitlines() if line and not line.startswith('#')]
        expected = {'linux-base-6.18.50+rpt-rpi-2712', 'linux-base-6.18.50+rpt-rpi-v8',
                    'linux-base-rpi-2712', 'linux-base-rpi-v8', 'linux-headers-6.18.50+rpt-common-rpi',
                    'linux-headers-6.18.50+rpt-rpi-2712', 'linux-headers-6.18.50+rpt-rpi-v8',
                    'linux-headers-rpi-2712', 'linux-headers-rpi-v8', 'linux-kbuild-6.18.50+rpt'}
        self.assertEqual(len(rows), len(expected))
        self.assertEqual({name.split('_')[0] for digest, name in rows}, expected)
        self.assertEqual(len({name for digest, name in rows}), len(rows))
        for digest, name in rows:
            self.assertRegex(digest, r'^[0-9a-f]{64}$')
            self.assertRegex(name, r'^[a-z0-9.+-]+_6\.18\.50-1\+rpt1_(arm64|all)\.deb$')
        recipe = (ROOT/'tools/package-lifecycle.Containerfile').read_text()
        self.assertIn('COPY tools/lifecycle-headers.sha256 /opt/lifecycle-headers/SHA256SUMS', recipe)
        self.assertIn('sha256sum -c SHA256SUMS', recipe)
        self.assertIn('apt-get install -y --no-install-recommends ./*.deb', recipe)

    def test_lifecycle_matrix_resolves_complete_expected_states(self):
        matrix = json.loads((ROOT/'release/package-lifecycle-matrix-v1.json').read_text())
        fields = {'packageManager', 'dkms', 'modulesByKernel', 'sourceTree', 'overlays',
                  'routeRuntime', 'services', 'bootConfiguration', 'ownershipRecords',
                  'rollbackAvailability', 'operatorAction', 'machineResult', 'executionAuthorization'}
        for state in matrix['states'].values():
            self.assertEqual(set(state), fields)
            self.assertIs(state['executionAuthorization'], False)
        ids = set()
        for case in matrix['cases']:
            self.assertNotIn(case['id'], ids)
            ids.add(case['id'])
            self.assertIn(case['expectedState'], matrix['states'])
            expected = 2 if case['operation'] == 'concurrent-same-version-request' else (0 if case['disposition'] == 'permitted' else 1)
            self.assertEqual(case['exitStatus'], expected)
        self.assertEqual({case['disposition'] for case in matrix['cases']}, {'permitted', 'refused'})
        for case in matrix['cases']:
            if case['startingState'] in ('partly-configured-or-interrupted-remove',
                                          'partly-configured-or-interrupted-purge',
                                          'partly-configured-or-interrupted-remove-depmod'):
                self.assertEqual(case['expectedState'], 'absent')

    def test_lifecycle_outputs_refuse_another_git_checkout_before_docker(self):
        import subprocess
        import contextlib
        import io
        repository = self.root/'another-repository'
        repository.mkdir()
        subprocess.run(['git', 'init', '-q', str(repository)], check=True)
        driver = runpy.run_path(str(ROOT/'tools/run-package-lifecycle.py'))
        arguments = ['run-package-lifecycle', '--image', 'unused', '--candidate', str(self.root),
                     '--predecessor', str(self.root), '--output', str(repository/'results')]
        with patch.object(sys, 'argv', arguments), patch('subprocess.check_output') as docker:
            with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
                with self.assertRaises(SystemExit) as error:
                    driver['main']()
            self.assertEqual(error.exception.code, 2)
            self.assertIn('outside every Git checkout', diagnostic.getvalue())
            docker.assert_not_called()
        self.assertFalse((repository/'results').exists())

    def test_results_are_private_with_a_shared_container_directory(self):
        import subprocess
        import contextlib
        import io
        import stat
        driver = runpy.run_path(str(ROOT/'tools/run-package-lifecycle.py'))
        output = self.root/'results'
        candidate, predecessor = result_inputs(self.root)
        arguments = ['run-package-lifecycle', '--image', 'unused', '--candidate', str(candidate),
                     '--predecessor', str(predecessor), '--output', str(output),
                     '--scenario', 'missing-headers']
        native = subprocess.run

        def command(argv, **kwargs):
            if argv[0] == 'docker':
                supplied = json.loads(next(a.split('=', 1)[1] for a in argv
                    if a.startswith('RP1_LIFECYCLE_CONTEXT=')))
                (output/'missing-headers/result.json').write_text(json.dumps(result_value(supplied)))
                return subprocess.CompletedProcess(argv, 0)
            return native(argv, **kwargs)

        with patch.object(sys, 'argv', arguments), patch('subprocess.run', side_effect=command), \
                patch('subprocess.check_output', return_value=json.dumps([{'Id': IMAGE}])), \
                patch.dict(driver['main'].__globals__, {'source_identity': lambda root: COMMIT,
                    'attribute': lambda value: [], 'catalog': lambda: {},
                    'run_owned': command, 'cleanup_owned': lambda *args: {'status': 'absent'}}):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                driver['main']()
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((output/'missing-headers').stat().st_mode), 0o777)
        report = json.loads((output/'result.json').read_text())
        self.assertTrue(report['scenarios'][0]['accepted'])


COMMIT = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64


def result_inputs(root):
    candidate, predecessor = root/'candidate', root/'predecessor'
    candidate.mkdir(); predecessor.mkdir()
    for directory in (candidate, predecessor):
        (directory/'package.deb').write_bytes(b'package fixture, never installed')
    digest = hashlib.sha256((candidate/'package.deb').read_bytes()).hexdigest()
    (candidate/'rp1-gpclk-dkms-installation-manifest-v1.json').write_text(json.dumps({
        'sourceCommit': COMMIT, 'package': {'filename': 'package.deb', 'sha256': digest}}))
    (predecessor/'predecessor.json').write_text(json.dumps({
        'package': 'package.deb', 'packageSha256': digest}))
    return candidate, predecessor


def result_value(expected):
    # Independent wire fixture: do not derive its contract/keys from the producer.
    observed = {'endpointsAbsent': True, 'modulesUnloaded': True}
    return {'contract': 'rp1-gpclk-package-lifecycle-v2', 'schemaVersion': 2,
        **expected, 'status': 'PASS', 'error': None,
        'steps': [{'stage': 'checked-boundary', 'command': ['fixture'], 'exitStatus': 0,
                   'before': observed.copy(), 'after': observed.copy(), 'diagnosticTail': ''}],
        'realPackageManager': True, 'hardwareQualification': False, 'rfQualification': False}


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.identity = {'sourceCommit': COMMIT, 'imageId': IMAGE,
            'candidatePackageSha256': 'c'*64, 'predecessorPackageSha256': 'd'*64}
        self.expected = results.context('e'*32, 'clean-cycle', self.identity)
        self.path = self.root/'result.json'

    def accept(self, value, code=0):
        self.path.write_text(json.dumps(value))
        return results.accept(self.path, self.expected, code)

    def test_positive_wire_and_producer_contract(self):
        value = result_value(self.expected)
        self.assertEqual(self.accept(value), value)
        self.assertEqual(results.envelope(self.expected, 'PASS', None, value['steps']), value)

    def test_attribution_types_safety_and_completed_work(self):
        import copy
        base = result_value(self.expected)
        mutations = [lambda v: v.update(schemaVersion=True),
            lambda v: v.update(schemaVersion=1), lambda v: v.update(contract='old'),
            lambda v: v.update(runId='f'*32), lambda v: v.update(scenario='foreign-state'),
            lambda v: v['identity'].update(sourceCommit='f'*40),
            lambda v: v['identity'].update(imageId='sha256:'+'f'*64),
            lambda v: v['identity'].update(candidatePackageSha256='f'*64),
            lambda v: v['identity'].update(predecessorPackageSha256='f'*64),
            lambda v: v.update(status='FAIL'), lambda v: v.update(error='failed'),
            lambda v: v.update(steps=[]), lambda v: v.update(realPackageManager=1),
            lambda v: v.update(hardwareQualification=True),
            lambda v: v.update(rfQualification=True), lambda v: v.update(extra=True),
            lambda v: v['steps'][0].update(exitStatus=True),
            lambda v: v['steps'][0]['after'].update(modulesUnloaded=1),
            lambda v: v['steps'][0]['before'].update(endpointsAbsent=False)]
        for change in mutations:
            value = copy.deepcopy(base); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError): self.accept(value)
        for code in (1, -15, True):
            with self.subTest(code=code), self.assertRaises(ValueError): self.accept(base, code)

    def test_missing_unsafe_and_malformed_results(self):
        with self.assertRaises(OSError): results.accept(self.path, self.expected, 0)
        for data in ('{}', '{', '{"x":1,"x":2}', 'NaN'):
            self.path.write_text(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                results.accept(self.path, self.expected, 0)
        self.path.unlink(); self.path.symlink_to(self.root/'missing')
        with self.assertRaises(OSError): results.accept(self.path, self.expected, 0)
        self.path.unlink(); self.path.write_bytes(b'x'*(results.LIMIT+1))
        with self.assertRaises(ValueError): results.accept(self.path, self.expected, 0)

    def test_changed_result_during_read(self):
        self.path.write_text(json.dumps(result_value(self.expected)))
        real = results.os.fstat
        count = 0
        def observation(fd):
            nonlocal count
            count += 1
            if count == 2: self.path.write_bytes(b'changed')
            return real(fd)
        with patch.object(results.os, 'fstat', side_effect=observation):
            with self.assertRaisesRegex(ValueError, 'changed'): results.accept(self.path, self.expected, 0)

    def test_selection_context_and_package_substitution(self):
        for selected in ((), ('clean-cycle', 'clean-cycle'), ('unknown',)):
            with self.assertRaises(ValueError): results.selection(selected)
        self.assertEqual(results.selection(('clean-cycle',)), ('clean-cycle',))
        with self.assertRaises(ValueError): results.context('bad', 'clean-cycle', self.identity)
        candidate, predecessor = result_inputs(self.root)
        identity = results.input_identity(candidate, predecessor, IMAGE, COMMIT)
        self.assertEqual(identity['sourceCommit'], COMMIT)
        (candidate/'package.deb').write_bytes(b'changed')
        with self.assertRaises(ValueError): results.input_identity(candidate, predecessor, IMAGE, COMMIT)

    def test_source_rejects_hidden_worktree_changes(self):
        import subprocess
        source = self.root/'source'; source.mkdir()
        (source/'input').write_text('reviewed')
        def git(*args):
            return subprocess.run(['git', '-C', str(source), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git('init', '-q'); git('add', 'input')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'fixture')
        self.assertEqual(results.source_identity(source), git('rev-parse', 'HEAD'))
        git('update-index', '--assume-unchanged', 'input')
        (source/'input').write_text('substituted')
        with self.assertRaisesRegex(ValueError, 'differs'): results.source_identity(source)

    def test_driver_rejects_false_success_and_collects_all_requested_results(self):
        import contextlib
        import io
        import subprocess
        candidate, predecessor = result_inputs(self.root)
        driver = runpy.run_path(str(ROOT/'tools/run-package-lifecycle.py'))
        native = subprocess.run
        for fault in ('none', 'missing', 'empty', 'stale', 'source', 'exit', 'cleanup', 'launch-cleanup', 'cancel', 'log-symlink', 'coverage-omission'):
            output = self.root/fault
            calls = []
            def command(argv, **kwargs):
                if argv[0] != 'docker': return native(argv, **kwargs)
                supplied = json.loads(next(a.split('=', 1)[1] for a in argv
                    if a.startswith('RP1_LIFECYCLE_CONTEXT=')))
                calls.append(supplied['scenario'])
                if fault == 'launch-cleanup': raise OSError('launch refused')
                if fault == 'cancel': raise KeyboardInterrupt('cancelled')
                value = result_value(supplied)
                broken = supplied['scenario'] == results.SCENARIOS[0]
                if broken and fault == 'log-symlink':
                    secret = self.root/'secret'; secret.write_text('PRIVATE DIAGNOSTIC MUST NOT LEAK')
                    (output/supplied['scenario']/'container.log').symlink_to(secret)
                if broken and fault == 'empty': value['steps'] = []
                if broken and fault == 'stale': value['runId'] = '0'*32
                if broken and fault == 'source': value['identity'] = dict(value['identity'], sourceCommit='0'*40)
                if not (broken and fault == 'missing'):
                    (output/supplied['scenario']/'result.json').write_text(json.dumps(value))
                return subprocess.CompletedProcess(argv, 1 if broken and fault in ('exit', 'log-symlink') else 0)
            args = ['driver', '--image', 'fixture', '--candidate', str(candidate),
                    '--predecessor', str(predecessor), '--output', str(output)]
            diagnostic = io.StringIO()
            with self.subTest(fault=fault), patch.object(sys, 'argv', args), \
                    patch('subprocess.run', side_effect=command), \
                    patch('subprocess.check_output', return_value=json.dumps([{'Id': IMAGE}])), \
                    patch.dict(driver['main'].__globals__, {'source_identity': lambda root: COMMIT,
                    'attribute': lambda value: [], 'catalog': lambda: {'missing': {}} if fault == 'coverage-omission' else {},
                    'run_owned': command, 'cleanup_owned': lambda *args: {
                        'status': 'unresolved' if fault in ('cleanup', 'launch-cleanup') else 'absent',
                        'error': 'cleanup refused'}}), \
                    contextlib.redirect_stdout(diagnostic), self.assertRaises(SystemExit) as caught:
                driver['main']()
            self.assertEqual(caught.exception.code, 0 if fault == 'none' else 1)
            self.assertEqual(tuple(calls), results.SCENARIOS[:1] if fault == 'cancel' else results.SCENARIOS)
            report = json.loads((output/'result.json').read_text())
            self.assertEqual(len(report['scenarios']), 1 if fault == 'cancel' else len(results.SCENARIOS))
            self.assertNotIn('PRIVATE DIAGNOSTIC MUST NOT LEAK', diagnostic.getvalue())
            if fault == 'launch-cleanup':
                self.assertIn('launch refused', report['scenarios'][0]['error'])
                self.assertEqual(report['scenarios'][0]['cleanup']['error'], 'cleanup refused')


class ImportTests(unittest.TestCase):
    def test_real_entrypoint_ignores_poisoned_helper_cache_and_pythonpath(self):
        import importlib.util
        import py_compile
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve();tools = root/'tools'
            shutil.copytree(ROOT/'tools', tools, ignore=shutil.ignore_patterns('__pycache__'))
            poison = root/'poison.py';poison.write_text("raise RuntimeError('POISONED HELPER CACHE')\n")
            cache = Path(importlib.util.cache_from_source(str(tools/'lifecycle_results.py')))
            cache.parent.mkdir(parents=True)
            py_compile.compile(str(poison), cfile=str(cache),
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH, doraise=True)
            (root/'uuid.py').write_text("raise RuntimeError('POISONED PYTHONPATH')\n")
            result = subprocess.run([sys.executable, str(tools/'run-package-lifecycle.py'), '--help'],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, 'PYTHONPATH': str(root), 'PYTHONPYCACHEPREFIX': str(root/'foreign-cache')})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--candidate', result.stdout)
            self.assertNotIn('POISONED', result.stderr)


class SummaryTests(unittest.TestCase):
    def test_summary_cannot_turn_empty_or_rejected_work_into_pass(self):
        import copy
        summarize = runpy.run_path(str(ROOT/'tools/summarize-lifecycle.py'))['summary']
        value = {'status': 'PASS', 'completeMatrix': True, 'coveredCaseIds': list(coverage.catalog()),
                 'scenarios': [{'scenario': name, 'accepted': True, 'exitStatus': 0,
                                'cleanup': {'status': 'absent'}} for name in results.SCENARIOS]}
        self.assertEqual(len(summarize(value)), len(results.SCENARIOS))
        for defect in ('empty', 'duplicate', 'missing', 'rejected', 'cleanup', 'coverage'):
            changed = copy.deepcopy(value)
            if defect == 'empty': changed['scenarios'] = []
            if defect == 'duplicate': changed['scenarios'][1] = changed['scenarios'][0]
            if defect == 'missing': changed['scenarios'].pop()
            if defect == 'rejected': changed['scenarios'][0]['accepted'] = False
            if defect == 'cleanup': changed['scenarios'][0]['cleanup']['status'] = 'unresolved'
            if defect == 'coverage': changed['coveredCaseIds'].pop()
            with self.subTest(defect=defect), self.assertRaises(ValueError): summarize(changed)


class MetadataTests(unittest.TestCase):
    def test_module_stamp_rejects_unsafe_files_and_detects_substitution(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/'module.ko';path.write_bytes(b'fixture')
            before = module_metadata.module_stamp(path)
            replacement = path.with_name('replacement');replacement.write_bytes(b'fixture')
            replacement.replace(path)
            self.assertNotEqual(module_metadata.module_stamp(path), before)
            link = path.with_name('link');link.symlink_to(path)
            with self.assertRaises(ValueError): module_metadata.module_stamp(link)
            link.unlink();os.link(path, link)
            with self.assertRaises(ValueError): module_metadata.module_stamp(path)
            link.unlink()
            with path.open('wb') as stream: stream.truncate(64*1024*1024+1)
            with self.assertRaises(ValueError): module_metadata.module_stamp(path)

    def test_independent_native_record_and_refusals(self):
        from types import SimpleNamespace
        record = ('filename: /fixture.ko\0version=0.0.1\0vermagic=kernel SMP\0'
                  'alias=first\0alias=second\0depends=controller\0'
                  'signature: AA:BB:\n CC:DD\0')
        def parse(text=record, code=0):
            return module_metadata.metadata(SimpleNamespace(returncode=code, stdout=text))
        value = parse()
        self.assertEqual(value, {'version': '0.0.1', 'vermagic': 'kernel SMP', 'aliases': 'first\nsecond',
            'depends': 'controller', 'signer': '', 'signatureKey': '', 'signatureAlgorithm': '',
            'signatureHash': '', 'controllerInterlock': ''})
        signed = record+'signer: Test signer\0sig_key: AB:CD\0sig_id: PKCS#7\0sig_hashalgo: sha256\0'
        self.assertEqual(parse(signed)['signer'], 'Test signer')
        for text, code in ((record, 1), (record[:-1], 0), ('bad\0', 0),
                (record.replace('version=0.0.1\0',''), 0),
                (record+'version=9.9.9\0', 0), (record+'depends=other\0', 0),
                (record+'signer=bad\nvalue\0', 0), (record+'x='+'x'*65536+'\0', 0)):
            with self.subTest(code=code, text=text[:60]), self.assertRaises(ValueError): parse(text, code)


class CoverageTests(unittest.TestCase):
    def test_independent_preinstall_vector_and_adversaries(self):
        import copy
        absent = {'packageManager': '', 'modules': [], 'dkms': '', 'sourceTrees': [],
                  'bootSha256': 'a'*64, 'endpointsAbsent': True, 'modulesUnloaded': True}
        installed = dict(absent, packageManager='ii  0.0.1-1',
                         modules=[{'version': '0.0.1'}]*4, dkms='x: installed\ny: installed', sourceTrees=['source'])
        steps = [
            {'stage': 'interrupted-preinstall', 'command': ['dpkg', '-i', 'candidate'],
             'exitStatus': 1, 'before': absent, 'after': absent},
            {'stage': 'retry-preinstall', 'command': ['dpkg', '-i', 'candidate'],
             'exitStatus': 0, 'before': absent, 'after': installed},
            {'stage': 'purge', 'command': ['dpkg', '--purge', 'rp1-gpclk-dkms'],
             'exitStatus': 0, 'before': installed, 'after': absent}]
        value = {'scenario': 'fault-preinstall', 'steps': steps}
        self.assertEqual([row['caseId'] for row in coverage.attribute(value)], ['34', '35'])
        for defect in ('missing', 'duplicate', 'context', 'command', 'exit', 'state', 'starting', 'cleanup'):
            changed = copy.deepcopy(value)
            if defect == 'missing': changed['steps'].pop(0)
            if defect == 'duplicate': changed['steps'].insert(0, changed['steps'][0])
            if defect == 'context': changed['scenario'] = 'fault-inventory'
            if defect == 'command': changed['steps'][0]['command'] = ['true']
            if defect == 'exit': changed['steps'][0]['exitStatus'] = 0
            if defect == 'state': changed['steps'][1]['after']['modules'] = []
            if defect == 'starting': changed['steps'][0]['before']['modules'] = [{'version': '0.9.0'}]
            if defect == 'cleanup': changed['steps'].pop()
            with self.subTest(defect=defect), self.assertRaises(ValueError): coverage.attribute(changed)
        self.assertEqual(set(coverage.catalog()), {str(i) for i in range(1, 70)})


class ProcessTests(unittest.TestCase):
    def test_engine_observation_and_ownership(self):
        cid, run, scenario = 'c'*64, 'd'*32, 'clean-cycle'
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/'owned.cid'
            for fault in ('absent', 'normal', 'rm-race', 'daemon', 'foreign', 'stale', 'remains', 'symlink'):
                with self.subTest(fault=fault):
                    path.unlink(missing_ok=True)
                    if fault == 'symlink': path.symlink_to(Path(name)/'unknown')
                    else: path.write_text(('e'*64 if fault == 'stale' else cid)+'\n')
                    remaining = fault != 'absent'
                    removed = []
                    def docker(args):
                        nonlocal remaining
                        if fault == 'daemon': raise ValueError('daemon unavailable')
                        if args[0] == 'ps': return cid+'\n' if remaining else ''
                        if args[0] == 'inspect':
                            return json.dumps([{'Id': cid, 'Image': IMAGE,
                                'Config': {'Labels': {processes.RUN_LABEL: 'other' if fault == 'foreign' else run,
                                    processes.SCENARIO_LABEL: scenario}}}])
                        self.assertEqual(args, ['rm', '-f', cid])
                        removed.append(cid)
                        remaining = fault == 'remains'
                        if fault == 'rm-race': raise ValueError('already removed')
                        return ''
                    with patch.object(processes, 'docker', side_effect=docker):
                        outcome = processes.cleanup_owned(path, run, scenario, IMAGE)
                    self.assertEqual(outcome['status'], 'absent' if fault in ('absent', 'normal', 'rm-race') else 'unresolved')
                    if fault in ('foreign', 'stale', 'symlink', 'daemon'): self.assertFalse(removed)
                    if fault == 'rm-race': self.assertTrue(outcome['diagnostics'])

    def test_real_process_reaped_on_failure_with_bounded_file_output(self):
        import time
        import subprocess
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ready = root/'ready'
            code = ("import pathlib, signal, sys; sys.stdout.write('x'*100000); sys.stdout.flush(); "
                    "pathlib.Path(sys.argv[1]).touch(); signal.pause()")
            with (root/'output').open('w') as stream:
                with self.assertRaisesRegex(RuntimeError, 'initiating failure'):
                    with processes.owned_process([sys.executable, '-c', code, str(ready)], stream) as child:
                        deadline = time.monotonic()+30
                        while not ready.exists():
                            self.assertIsNone(child.poll())
                            if time.monotonic() >= deadline: self.fail('child readiness watchdog')
                            time.sleep(0.01)
                        raise RuntimeError('initiating failure')
                self.assertIsNotNone(child.poll())
                self.assertFalse(processes.group_exists(child.pid))
            self.assertEqual((root/'output').stat().st_size, 100000)
            with (root/'output').open('w') as stream:
                outcome = processes.run_owned([sys.executable, '-c', 'raise SystemExit(7)'], stream, timeout=30)
                self.assertEqual(outcome.returncode, 7)

    def test_output_and_overall_deadline_are_failure_guards(self):
        import contextlib
        import subprocess
        with tempfile.TemporaryFile() as stream:
            stream.write(b'x'*100)
            stream.flush()
            with self.assertRaisesRegex(ValueError, 'byte budget'):
                processes.run_owned([sys.executable, '-c', 'pass'], stream, 30, output_limit=10)
        class Child:
            def wait(self, timeout):
                raise subprocess.TimeoutExpired(['progressing-child'], timeout)
        with tempfile.TemporaryFile() as stream, \
                patch.object(processes, 'owned_process', return_value=contextlib.nullcontext(Child())), \
                patch.object(processes.time, 'monotonic', side_effect=[0, 1, 2, 3, 6]):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                processes.run_owned(['progressing-child'], stream, timeout=5)
            self.assertEqual(caught.exception.timeout, 5)

    def test_cancellation_is_deferred_only_for_cleanup(self):
        import signal
        with processes.cancellation_signals() as state:
            handler = signal.getsignal(signal.SIGTERM)
            state.deferred = True
            handler(signal.SIGTERM, None)
            self.assertTrue(state.requested)
            state.deferred = False
            with self.assertRaises(KeyboardInterrupt): handler(signal.SIGINT, None)


if __name__ == '__main__':
    __import__("nonempty_unittest").main()
