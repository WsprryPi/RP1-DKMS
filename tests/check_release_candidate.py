#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline release normal, malformed, substitution and reproducibility coverage."""
import copy
import gzip
import hashlib
import time
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import release_contract as c
from release_manifest import validate_source


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as stream:
        for name, kind, mode, uid in entries:
            item = tarfile.TarInfo(name)
            item.type, item.mode, item.uid = kind, mode, uid
            item.gid = uid
            item.linkname = '../../escape' if kind == tarfile.SYMTYPE else ''
            stream.addfile(item)
    return output.getvalue()


def run(*args, cwd=None, okay=True):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
             'GIT_CONFIG_NOSYSTEM': '1'})
    if okay:
        assert result.returncode == 0, result.stdout+'\n'+result.stderr
    return result


def snapshot(destination):
    destination.mkdir()
    names = c.git(ROOT, 'ls-files', '-c', '-o', '--exclude-standard', '-z').decode().split('\0')
    for name in names:
        if not name:
            continue
        path = destination/name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, path)
    run('git', 'init', '-q', '-b', 'fixture', cwd=destination)
    run('git', 'add', '.', cwd=destination)
    run('git', '-c', 'user.name=Offline Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-q', '-m', 'deterministic source fixture', cwd=destination)
    return c.git(destination, 'rev-parse', 'HEAD').decode().strip()


class FormatTests(unittest.TestCase):
    def test_unsafe_paths_links_duplicates_modes_and_ownership(self):
        cases = [('x', tarfile.REGTYPE, 0o644, 0)]
        self.assertEqual(c.tar_members(archive(cases))[0]['path'], 'x')
        for entry in [('../escape', tarfile.REGTYPE, 0o644, 0),
                      ('/absolute', tarfile.REGTYPE, 0o644, 0),
                      ('x//shadow', tarfile.REGTYPE, 0o644, 0),
                      ('x', tarfile.SYMTYPE, 0o755, 0),
                      ('x', tarfile.LNKTYPE, 0o644, 0),
                      ('x', tarfile.FIFOTYPE, 0o644, 0),
                      ('x', tarfile.REGTYPE, 0o777, 0),
                      ('x', tarfile.REGTYPE, 0o644, 1000)]:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                c.tar_members(archive([entry]))
        with self.assertRaises(ValueError):
            c.tar_members(archive(cases+cases))
        with self.assertRaises(ValueError):
            c.tar_members(archive(cases+[('x/child', tarfile.REGTYPE, 0o644, 0)]))
        with self.assertRaises(ValueError):
            c.tar_members(archive(cases)+archive([('shadow', tarfile.REGTYPE, 0o644, 0)]))

    def test_duplicate_json_keys_and_deterministic_source(self):
        with self.assertRaises(ValueError):
            c.read_json(b'{"x":1,"x":2}')
        files = {'x': (0o644, b'reviewed')}
        self.assertEqual(c.source_archive(files, 123), c.source_archive(files, 123))
        self.assertNotEqual(c.source_archive(files, 123), c.source_archive(files, 124))

    def test_git_source_excludes_unsafe_members_and_private_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run('git', 'init', '-q', '-b', 'fixture', cwd=root)
            (root/'reviewed').write_bytes(b'exact source')
            (root/'.gitattributes').write_text('reviewed export-ignore\n')
            def commit():
                run('git', 'add', '.', cwd=root)
                run('git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-qm', 'source fixture', cwd=root)
                return c.git(root, 'rev-parse', 'HEAD').decode().strip()
            revision = commit()
            self.assertIn('reviewed', c.source_files(root, revision))
            (root/'linked').symlink_to(root/'reviewed')
            with self.assertRaises(ValueError):
                c.source_files(root, commit())
            (root/'linked').unlink()
            (root/'private.key').write_bytes(b'non-secret signing fixture')
            with self.assertRaises(ValueError):
                c.source_files(root, commit())
            (root/'private.key').unlink()
            (root/'text').write_bytes(b'-----BEGIN '+b'RSA PRIVATE KEY-----')
            with self.assertRaises(ValueError):
                c.source_files(root, commit())

    def test_batch_framing_authentication_and_repeated_objects(self):
        data = b'binary\0body\n'
        oid = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest().encode()
        frame = oid+b' blob '+str(len(data)).encode()+b'\n'+data+b'\n'
        self.assertEqual(c.decode_blobs(frame+frame, [oid, oid]), [data, data])
        for payload, requested in ((frame[:-1], [oid]), (frame[:-2], [oid]),
                (frame+frame, [oid]), (frame, [oid, oid]),
                (frame.replace(b' blob ', b' tree ', 1), [oid]),
                (frame.replace(oid, b'f'*40, 1), [oid]),
                (frame.replace(data, b'B'+data[1:]), [oid]),
                (oid+b' missing\n', [oid]), (oid+b' blob -1\n', [oid]),
                (oid+b' blob 999999999\n', [oid]), (b'', [])):
            with self.subTest(payload=payload[:70]), self.assertRaises(ValueError): c.decode_blobs(payload, requested)
        with patch.object(c, 'MAX_SOURCE_BYTES', 1), self.assertRaises(ValueError): c.decode_blobs(frame, [oid])

    def test_real_git_repeated_blobs_modes_and_replacement_refusal(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            run('git', 'init', '-q', cwd=root)
            for path in ('first', 'second'):
                (root/path).write_bytes(b'independent golden bytes\n')
            (root/'second').chmod(0o755)
            run('git', 'add', '.', cwd=root)
            run('git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture', cwd=root)
            revision = run('git', 'rev-parse', 'HEAD', cwd=root).stdout.strip()
            expected = {'first': (0o644, b'independent golden bytes\n'), 'second': (0o755, b'independent golden bytes\n')}
            self.assertEqual(c.source_files(root, revision), expected)
            oid = run('git', 'rev-parse', revision+':first', cwd=root).stdout.strip()
            (root/'substitution').write_bytes(b'wrong replacement bytes')
            other = run('git', 'hash-object', '-w', 'substitution', cwd=root).stdout.strip()
            run('git', 'replace', oid, other, cwd=root)
            self.assertEqual(c.source_files(root, revision), expected)

    def test_batch_process_failure_output_guard_and_cancellation(self):
        oid = hashlib.sha1(b'blob 1\0x').hexdigest().encode()
        frame = oid+b' blob 1\nx\n'
        children = []
        native = subprocess.Popen
        def start(*args, **kwargs):
            child = native(*args, **kwargs);children.append(child);return child
        for code in ("import sys;sys.stdout.buffer.write("+repr(frame)+");sys.exit(7)", 'pass'):
            with patch.object(c, 'git_argv', return_value=[sys.executable, '-c', code]), \
                    patch.object(c.subprocess, 'Popen', side_effect=start), self.assertRaises(ValueError):
                c.git_blobs(Path('/unused'), [oid])
            self.assertIsNotNone(children[-1].poll())
        with patch.object(c, 'MAX_SOURCE_BYTES', 8), \
                patch.object(c, 'git_argv', return_value=[sys.executable, '-c', "print('x'*1000)"]), \
                self.assertRaisesRegex(ValueError, 'output budget'):
            c.git_blobs(Path('/unused'), [oid])
        with patch.object(c, 'git_argv', return_value=[sys.executable, '-c', 'import signal;signal.pause()']), \
                patch.object(c.subprocess, 'Popen', side_effect=start), \
                patch.object(c.selectors, 'DefaultSelector', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            c.git_blobs(Path('/unused'), [oid])
        self.assertIsNotNone(children[-1].poll())

    def test_success_requires_owned_descendant_group_absence(self):
        import signal
        oid = hashlib.sha1(b'blob 1\0x').hexdigest().encode()
        frame = oid+b' blob 1\nx\n'
        with tempfile.TemporaryDirectory() as name:
            pidfile = Path(name)/'descendant'
            descendant = "import os,pathlib,signal,sys;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));signal.pause()"
            parent = ("import pathlib,subprocess,sys,time;"
                "child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                "path=pathlib.Path(sys.argv[2]);deadline=time.monotonic()+30\n"
                "while not path.exists() or not path.read_text():\n"
                " if child.poll() is not None or time.monotonic() >= deadline: raise RuntimeError('descendant readiness guard')\n"
                " time.sleep(0.01)\n"
                "sys.stdout.buffer.write("+repr(frame)+")")
            try:
                with patch.object(c, 'git_argv', return_value=[sys.executable, '-c', parent, descendant, str(pidfile)]):
                    self.assertEqual(c.git_blobs(Path('/unused'), [oid]), [b'x'])
                with self.assertRaises(ProcessLookupError): os.kill(int(pidfile.read_text()), 0)
            finally:
                if pidfile.exists() and pidfile.read_text():
                    try: os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_batch_eof_before_exit_is_not_completion(self):
        oid = hashlib.sha1(b'blob 1\0x').hexdigest().encode()
        native = subprocess.Popen
        with tempfile.TemporaryDirectory() as name:
            ready = Path(name)/'ready';children = []
            code = "import os,pathlib,signal,sys;os.close(1);os.close(2);pathlib.Path(sys.argv[1]).touch();signal.pause()"
            def start(*args, **kwargs):
                child = native(*args, **kwargs);children.append(child)
                try:
                    deadline = time.monotonic()+30
                    while not ready.exists():
                        self.assertIsNone(child.poll(), 'batch child exited before readiness')
                        if time.monotonic() >= deadline: self.fail('batch child readiness guard')
                        time.sleep(0.01)
                except BaseException:
                    child.kill();child.wait(timeout=30);child.stdout.close();child.stderr.close();raise
                return child
            with patch.object(c, 'git_argv', return_value=[sys.executable, '-c', code, str(ready)]), \
                    patch.object(c.subprocess, 'Popen', side_effect=start), patch.object(c, 'GIT_BATCH_TIMEOUT', 5), \
                    self.assertRaisesRegex(ValueError, 'deadline'):
                c.git_blobs(Path('/unused'), [oid])
            self.assertIsNotNone(children[0].poll())

    def test_exact_identity_and_predecessor_rejection(self):
        files = {p.relative_to(ROOT).as_posix(): (0o644, p.read_bytes())
                 for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts
                 and p.suffix in ('.py', '.h', '.c', '.dts', '.json')}
        for name in ('debian/rules', 'debian/changelog', 'dkms.conf'):
            files[name] = (0o644, (ROOT/name).read_bytes())
        validate_source(files)
        for name, original, substitution in (
            ('include/rp1_gpclk/version.h', b'0.99.0', b'0.9.0'),
            ('include/rp1_gpclk/version.h', b'0.99.0', b'1.0.0'),
            ('include/rp1_gpclk/version.h', b'0.99.0', b'1.0.1'),
            ('include/rp1_gpclk/version.h', b'0.99.0', b'1.0.2'),
            ('include/rp1_gpclk/compatibility.h', b'v0.99.0-rp1-gpio4', b'v1.1.2-rp1-gpio4'),
            ('scripts/runtime_binding.py', b'0.99.0', b'1.1.1'),
            ('release/wsprrypi-consumer-contract.json', b'rp1-gpclk-dkms_0.99.0-1_all.deb', b'rp1-gpclk-dkms_1.0.0-1_all.deb'),
            ('include/uapi/linux/rp1_gpclk.h', b'#define', b'#define @VERSION@'),
            ('overlays/rp1-gpclk-gpio4.dts', b'"gpio4"', b'"gpio20"')):
            changed = dict(files)
            mode, data = changed[name]
            changed[name] = mode, data.replace(original, substitution)
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_source(changed)


@unittest.skipUnless(sys.platform == 'linux', 'full Debian release tests require Linux; CI runs them')
class LinuxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ('dpkg-buildpackage', 'dpkg-deb', 'dtc', 'fdtput'):
            if not shutil.which(name):
                raise AssertionError('required Linux release test tool missing: '+name)
        cls.temp = tempfile.TemporaryDirectory(prefix='rp1-release-tests-')
        cls.base = Path(cls.temp.name).resolve()
        cls.source = cls.base/'fixture'
        cls.commit = snapshot(cls.source)
        cls.candidate = cls.base/'candidate'
        cls.builder = cls.source/'scripts/build-release-candidate'
        validator = runpy.run_path(str(cls.source/'scripts/validate-release-candidate'))['validate']
        validator.__globals__['ROOT'] = cls.source
        cls.validator = staticmethod(validator)
        run(str(cls.builder), '--version', c.VERSION, '--source-commit', cls.commit,
            '--output', str(cls.candidate))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_maintained_schema_definitions(self):
        jsonschema = self.validator.__globals__['jsonschema']
        for path in (self.source/'schema').glob('*.schema.json'):
            schema = c.read_json(path.read_bytes())
            jsonschema.validators.validator_for(schema).check_schema(schema)

    def test_independent_replay_and_consumer_shape(self):
        self.assertEqual(self.validator(self.candidate, self.commit)['status'], 'PASS')
        manifest = c.read_json((self.candidate/c.MANIFEST).read_bytes())
        contract = json.loads((self.source/'release/wsprrypi-consumer-contract.json').read_text())
        self.assertEqual(set(manifest), set(contract['manifestKeys']))
        self.assertEqual(manifest['releaseChannel'], contract['stableChannel'])
        self.assertEqual(manifest['releaseTag'], 'v0.99.0')
        self.assertFalse(c.read_json((self.candidate/c.METADATA).read_bytes())['published'])
        self.assertEqual({p.name for p in self.candidate.iterdir()}, c.ASSETS)
        self.assertEqual(c.git(self.source, 'status', '--porcelain=v1'), b'')

    def test_dirty_untracked_exact_commit_and_existing_output(self):
        def refused(commit=None, output=None):
            result = run(str(self.builder), '--version', c.VERSION,
                '--source-commit', commit or self.commit, '--output', str(output or self.base/'refused'), okay=False)
            self.assertNotEqual(result.returncode, 0)
        refused(commit='devel')
        refused(commit=self.commit[:12])
        refused(output=self.candidate)
        refused(output=self.source/'output')
        path = self.source/'README.md'
        saved = path.read_bytes()
        path.write_bytes(saved+b'\nchanged\n')
        refused()
        run('git', 'update-index', '--assume-unchanged', 'README.md', cwd=self.source)
        refused()
        run('git', 'update-index', '--no-assume-unchanged', 'README.md', cwd=self.source)
        path.write_bytes(saved)
        stray = self.source/'scripts/untracked.py'
        stray.write_text('raise RuntimeError("must never execute")\n')
        refused()
        stray.unlink()
        symlink = self.base/'linked-output'
        symlink.symlink_to(self.candidate)
        refused(output=symlink)

    def test_repeat_command_ignores_cache_and_environment_poison(self):
        import importlib.util
        import importlib._bootstrap_external as cache_format
        helper = self.source/'scripts/release_contract.py'
        cache = helper.parent/'__pycache__'/('release_contract.'+sys.implementation.cache_tag+'.pyc')
        cache.parent.mkdir(exist_ok=True)
        code = compile("raise RuntimeError('untracked bytecode executed')", str(helper), 'exec')
        cache.write_bytes(cache_format._code_to_timestamp_pyc(code,
            mtime=int(helper.stat().st_mtime), source_size=helper.stat().st_size))
        poison = self.source/'build/ignored-temp'
        poison.mkdir(parents=True, exist_ok=True)
        destination = self.base/'repeat'
        result = subprocess.run([str(self.builder), '--version', c.VERSION,
            '--source-commit', self.commit, '--output', str(destination)], capture_output=True,
            text=True, env={**os.environ, 'TMPDIR': str(poison), 'PYTHONPATH': str(poison),
                            'GIT_DIR': str(poison), 'LC_ALL': 'invalid-locale'})
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(list(poison.iterdir()), [])
        self.assertTrue(all((destination/name).read_bytes() == (self.candidate/name).read_bytes()
                            for name in c.ASSETS))
        cache.unlink()

    def test_candidate_drift_during_validation_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.base) as temporary:
            candidate = Path(temporary)/'candidate'
            shutil.copytree(self.candidate, candidate)
            def drift(unused, commit, release=False):
                (candidate/c.METADATA).write_bytes(b'changed during independent verification')
                return {'status': 'PASS'}
            with patch.dict(self.validator.__globals__, {'_validate_snapshot': drift}):
                with self.assertRaisesRegex(ValueError, 'changed during validation'):
                    self.validator(candidate, self.commit)

    def test_release_profile_reproducibility_and_stale_candidate_refusal(self):
        first, second = self.base/'release-first', self.base/'release-second'
        for destination in (first, second):
            run(str(self.builder), '--version', c.VERSION, '--source-commit', self.commit,
                '--output', str(destination), '--release')
        self.assertTrue(all((first/name).read_bytes() == (second/name).read_bytes() for name in c.ASSETS))
        self.assertEqual((first/c.DEB).read_bytes(), (self.candidate/c.DEB).read_bytes())
        self.assertEqual((first/c.SOURCE).read_bytes(), (self.candidate/c.SOURCE).read_bytes())
        self.assertEqual(self.validator(first, self.commit, release=True)['classification'], 'release')
        self.assertIs(self.validator(first, self.commit, release=True)['published'], False)
        self.assertIs(c.read_json((first/c.METADATA).read_bytes())['published'], False)
        self.assertIs(c.read_json((first/c.RESULT).read_bytes())['published'], False)
        with self.assertRaises(ValueError):
            self.validator(first, self.commit)
        with self.assertRaises(ValueError):
            self.validator(self.candidate, self.commit, release=True)
        for name in (c.METADATA, c.COMPATIBILITY, c.RESULT):
            with self.subTest(stale=name), tempfile.TemporaryDirectory(dir=self.base) as temporary:
                destination = Path(temporary)/'stale'
                shutil.copytree(first, destination)
                (destination/name).write_bytes((self.candidate/name).read_bytes())
                (destination/'SHA256SUMS').write_bytes(c.checksum_bytes(destination))
                with self.assertRaises(ValueError):
                    self.validator(destination, self.commit, release=True)
        for mutation in (lambda v: v.update(releaseUrl='https://example.invalid/moving'),
                         lambda v: v.update(releaseTag='devel'),
                         lambda v: v.update(published=1),
                         lambda v: v.update(published=True),
                         lambda v: v['qualification'].update(rf=True)):
            with tempfile.TemporaryDirectory(dir=self.base) as temporary:
                destination = Path(temporary)/'forged'
                shutil.copytree(first, destination)
                value = c.read_json((destination/c.METADATA).read_bytes())
                mutation(value)
                (destination/c.METADATA).write_bytes(c.canonical(value)+b'\n')
                (destination/'SHA256SUMS').write_bytes(c.checksum_bytes(destination))
                with self.assertRaises(ValueError):
                    self.validator(destination, self.commit, release=True)

    def test_substituted_packages_with_rebound_manifests(self):
        from release_manifest import documents, encode_documents
        files = c.source_files(self.source, self.commit)
        tree = c.git(self.source, 'rev-parse', self.commit+'^{tree}').decode().strip()
        timestamp = c.epoch(self.source, self.commit)
        prefix = 'usr/src/rp1-gpclk-dkms-0.99.0/'
        for case in ('control-version', 'dkms-controller', 'uapi', 'overlay', 'omission', 'unexpected'):
            with self.subTest(case=case), tempfile.TemporaryDirectory(dir=self.base) as temporary:
                root = Path(temporary)
                candidate = root/'candidate'
                shutil.copytree(self.candidate, candidate)
                unpack = root/'unpacked'
                c.command(['dpkg-deb', '--raw-extract', str(candidate/c.DEB), str(unpack)])
                if case == 'control-version':
                    path = unpack/'DEBIAN/control'
                    path.write_text(path.read_text().replace('Version: 0.99.0-1', 'Version: 0.9.0-1'))
                elif case == 'dkms-controller':
                    path = unpack/prefix/'dkms.conf'
                    path.write_text(path.read_text().replace('BUILT_MODULE_NAME[1]="rp1_route_controller"',
                                                             'BUILT_MODULE_NAME[1]="foreign_controller"'))
                elif case == 'uapi':
                    path = unpack/prefix/'include/uapi/linux/rp1_gpclk.h'
                    path.write_bytes(path.read_bytes()+b'\n/* substituted */\n')
                elif case == 'overlay':
                    directory = unpack/'usr/lib/rp1-gpclk-dkms/overlays'
                    (directory/'rp1-gpclk-gpio4.dtbo').write_bytes((directory/'rp1-gpclk-gpio20.dtbo').read_bytes())
                elif case == 'omission':
                    (unpack/prefix/'controller/main.c').unlink()
                else:
                    (unpack/'usr/share/doc/rp1-gpclk-dkms/unexpected').write_bytes(b'extra payload')
                c.command(['dpkg-deb', '--root-owner-group', '-Zgzip', '-z9', '--threads-max=1',
                           '--build', str(unpack), str(candidate/c.DEB)], env=c.build_environment(timestamp))
                encode_documents(candidate, documents(files, self.commit, tree, timestamp, candidate))
                (candidate/'SHA256SUMS').write_bytes(c.checksum_bytes(candidate))
                with self.assertRaises((ValueError, self.validator.__globals__['jsonschema'].ValidationError)):
                    self.validator(candidate, self.commit)

    def test_artifact_and_metadata_adversaries(self):
        def changed(name, mutation):
            destination = self.base/'changed'
            shutil.copytree(self.candidate, destination)
            path = destination/name
            value = c.read_json(path.read_bytes())
            mutation(value)
            path.write_bytes(c.canonical(value)+b'\n')
            (destination/'SHA256SUMS').write_bytes(c.checksum_bytes(destination))
            try:
                with self.assertRaises((ValueError, OSError, self.validator.__globals__['jsonschema'].ValidationError)):
                    self.validator(destination, self.commit)
            finally:
                shutil.rmtree(destination)
        for mutation in (
            lambda v: v.update(unexpected=True),
            lambda v: v.update(sourceCommit='0'*40),
            lambda v: v.update(productVersion='0.9.0'),
            lambda v: v.update(releaseChannel='development'),
            lambda v: v.update(releaseTag='v0.99.0-rc.1'),
            lambda v: v['package'].update(filename='rp1-gpclk-dkms_0.9.0-1_all.deb'),
            lambda v: v['package'].update(sha256='0'*64),
            lambda v: v['uapi'].update(sha256='0'*64),
            lambda v: v['packageInventory'].pop(),
            lambda v: v['packageInventory'].append(copy.deepcopy(v['packageInventory'][0])),
            lambda v: v['installationBehavior'].update(loadsModule=True),
            lambda v: v.update(kernelModule='rp1_route_controller'),
        ):
            with self.subTest(manifest=mutation):
                changed(c.MANIFEST, mutation)
        for mutation in (
            lambda v: v.update(sourceTree='0'*40),
            lambda v: v.update(classification='release', published=True),
            lambda v: v['qualification'].update(rf=True),
            lambda v: v['qualification'].update(rf=0),
            lambda v: v['packageOwnership'].update(uid=False),
            lambda v: v.update(schemaVersion=True),
            lambda v: v['signing'].update(privateKeyIncluded=True),
            lambda v: v['routes']['gpio4'].update(dtboSha256=v['routes']['gpio20']['dtboSha256']),
            lambda v: v['routes']['gpio20'].update(compatibilityId='v0.9.0-rp1-gpio20'),
            lambda v: v['runtime'].update(binding='rp1-gpclk-runtime-binding-v2'),
            lambda v: v['modules'][1].update(name='rp1_gpclk_dkms'),
            lambda v: v['modules'][0].update(installedFileSha256='0'*64),
            lambda v: v['consumerContract'].update(stableChannel='candidate'),
        ):
            with self.subTest(provenance=mutation):
                changed(c.METADATA, mutation)
        changed(c.COMPATIBILITY, lambda v: v.update(defaultState='Qualified'))
        changed(c.RESULT, lambda v: v['reproducibility'].update(byteIdentical=False))
        for action in ('extra', 'missing', 'symlink', 'checksum', 'archive', 'duplicate-ar'):
            destination = self.base/'changed'
            shutil.copytree(self.candidate, destination)
            try:
                if action == 'extra':
                    (destination/'extra.deb').write_bytes(b'extra')
                elif action == 'missing':
                    (destination/c.METADATA).unlink()
                elif action == 'symlink':
                    p = destination/c.SOURCE
                    p.unlink()
                    p.symlink_to(self.candidate/c.SOURCE)
                elif action == 'checksum':
                    with (destination/'SHA256SUMS').open('ab') as stream:
                        stream.write((destination/'SHA256SUMS').read_bytes().splitlines()[0]+b'\n')
                elif action == 'archive':
                    (destination/c.SOURCE).write_bytes(gzip.compress(archive([('../escape', tarfile.REGTYPE, 0o644, 0)])))
                    (destination/'SHA256SUMS').write_bytes(c.checksum_bytes(destination))
                else:
                    p = destination/c.DEB
                    data = p.read_bytes()
                    size = int(data[8+48:8+58])
                    p.write_bytes(data+data[8:8+60+size+size%2])
                    with self.assertRaises(ValueError):
                        c.package_members(p)
                    (destination/'SHA256SUMS').write_bytes(c.checksum_bytes(destination))
                with self.assertRaises((ValueError, OSError, self.validator.__globals__['jsonschema'].ValidationError)):
                    self.validator(destination, self.commit)
            finally:
                shutil.rmtree(destination)


if __name__ == '__main__':
    __import__("nonempty_unittest").main()
