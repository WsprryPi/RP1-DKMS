#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Behavioral version, installed-helper, payload conflict and upgrade regressions."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import version_identity as identity
import package_preflight as guard
import package_stage as stage


class Tests(unittest.TestCase):
    def test_semver_precedence(self):
        ordered = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta',
                   '1.0.0-beta', '1.0.0-beta.2', '1.0.0-beta.11',
                   '1.0.0-rc.1', '1.0.0', '1.2.0', '1.10.0', '2.0.0']
        for left, right in zip(ordered, ordered[1:]):
            self.assertLess(identity.compare(left, right), 0)
            self.assertGreater(identity.compare(right, left), 0)
        self.assertEqual(identity.compare('1.0.0+abc', '1.0.0+def'), 0)

    def test_malformed_and_ambiguous_versions(self):
        for bad in ('v1.0.0', '1.0', '01.0.0', '1.01.0', '1.0.01',
                    '1.0.0-01', '1.0.0-a..b', '1.0.0+', '1.0.0\n',
                    '1.0.0;false', '1.0.0-ä', '1'*100, None, True):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                identity.parse(bad)
        header = (ROOT/'include/rp1_gpclk/version.h').read_text()
        with self.assertRaises(ValueError):
            identity.from_header(header+header)

    @unittest.skipUnless(shutil.which('dpkg'), 'native Debian comparison requires dpkg')
    def test_semantic_and_debian_transition_classification(self):
        cases = [('1.0.0', '1.0.0-1', '1.0.0', '1.0.0-1', 'same'),
                 ('1.0.0', '1.0.0-1', '1.0.0', '1.0.0-2', 'upgrade'),
                 ('1.2.0', '1.2.0-1', '1.10.0', '1.10.0-1', 'upgrade'),
                 ('1.0.0-rc.1', '1.0.0~rc.1-1', '1.0.0', '1.0.0-1', 'upgrade'),
                 ('1.0.0+abc', '1.0.0+abc-1', '1.0.0+def', '1.0.0+def-1', 'replace')]
        for old, old_deb, new, new_deb, expected in cases:
            self.assertEqual(identity.transition(old, old_deb, new, new_deb), expected)
        for old, old_deb, new, new_deb in (
                ('2.0.0', '2.0.0-1', '1.0.0', '1.0.0-1'),
                ('1.0.0', '1.0.0-2', '1.0.0', '1.0.0-1'),
                ('1.0.0', '3.0.0-1', '2.0.0', '2.0.0-1')):
            with self.assertRaises(ValueError):
                identity.transition(old, old_deb, new, new_deb)

    def test_debian_projection_and_revision(self):
        self.assertEqual(identity.debian_version('2.3.4-rc.2+build.7', '3'),
                         '2.3.4~rc.2+build.7-3')
        for revision in ('0', '-1', '1;false', '01', ''):
            with self.assertRaises(ValueError):
                identity.debian_version('2.3.4', revision)

    def test_standalone_identity_without_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT/'scripts/version_identity.py', root/'version_identity.py')
            shutil.copyfile(ROOT/'include/rp1_gpclk/version.h', root/'version.h')
            result = subprocess.run([sys.executable, '-I', str(root/'version_identity.py'), 'json'],
                                    check=True, capture_output=True, text=True, cwd='/tmp')
            self.assertEqual(json.loads(result.stdout), {'productVersion': identity.VERSION,
                'debianVersion': identity.DEBIAN, 'filename': identity.DEB})

    def test_single_declaration_propagates_to_new_source(self):
        # An unrelated version/revision tests derivation, not today's literal.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT/'scripts', root/'scripts', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'include', root/'include')
            header = root/'include/rp1_gpclk/version.h'
            text = header.read_text().replace('"'+identity.VERSION+'"', '"7.12.3-rc.4"')
            text = re.sub(r'#define RP1_GPCLK_DEBIAN_REVISION "[^"]+"', '#define RP1_GPCLK_DEBIAN_REVISION "8"', text)
            header.write_text(text)
            shutil.copyfile(ROOT/'dkms.conf', root/'dkms.conf')
            result = subprocess.run([sys.executable, '-c',
                'import json,version_identity as v,package_stage as p,runtime_binding as b; '
                'print(json.dumps([v.VERSION,v.DEBIAN,v.DEB,b.PRODUCT_VERSION,b.COMPATIBILITY,p.render_dkms(open("dkms.conf").read())]))'],
                cwd=root, env={**os.environ, 'PYTHONPATH': str(root/'scripts'), 'PYTHONDONTWRITEBYTECODE':'1'},
                capture_output=True, text=True, check=True)
            value = json.loads(result.stdout)
            self.assertEqual(value[:4], ['7.12.3-rc.4', '7.12.3~rc.4-8',
                'rp1-gpclk-dkms_7.12.3~rc.4-8_all.deb', '7.12.3-rc.4'])
            self.assertEqual(value[4]['gpio4'], 'v7.12.3-rc.4-rp1-gpio4')
            self.assertIn('PACKAGE_VERSION="7.12.3-rc.4"', value[5])

    def payload(self, root, version='1.2.0', revision='1'):
        header = ('#define RP1_GPCLK_MODULE_VERSION "'+version+'"\n'
                  '#define RP1_GPCLK_DEBIAN_REVISION "'+revision+'"\n')
        name = f'usr/src/{identity.PACKAGE}-{version}/include/rp1_gpclk/version.h'
        path = root/name
        path.parent.mkdir(parents=True)
        path.write_text(header)
        payload = {name: hashlib.sha256(path.read_bytes()).hexdigest()}
        receipt = {'repository': identity.REPOSITORY, 'lifecycle': identity.LIFECYCLE,
            'productVersion': version, 'debianVersion': identity.debian_version(version, revision),
            'payload': payload, 'uapi': {'consumer':'a'*64}, 'scripts': {}}
        database = root/'var/lib/dpkg/info'
        database.mkdir(parents=True)
        for script in ('preinst', 'postinst', 'prerm'):
            data = b'# RP1_INCOMING_PREFLIGHT\n' if script == 'preinst' else b'# fixture\n'
            receipt['scripts'][script] = hashlib.sha256(data).hexdigest()
            if script == 'preinst':
                data = b"python3 -I - unpack <<'RP1_INCOMING_PREFLIGHT'\n# fixture\nRP1_INCOMING_PREFLIGHT\n"
            (database/(identity.PACKAGE+'.'+script)).write_bytes(data)
        record = root/guard.RECEIPT
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps(receipt))
        source = root/'usr/src'/(identity.PACKAGE+'-'+version)
        owned = {source, path, record}
        return receipt, owned, path

    @unittest.skipUnless(shutil.which('dpkg'), 'native Debian comparison requires dpkg')
    def test_compatible_upgrade_uses_outgoing_identity(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(guard,'OWNER_UID',os.getuid()):
            root = Path(directory)
            old, owned, path = self.payload(root)
            new = copy.deepcopy(old)
            new.update(productVersion='1.10.0',debianVersion='1.10.0-1')
            with patch.object(guard,'INCOMING',new), patch.object(guard,'VERSION','1.10.0'), patch.object(guard,'DEBIAN','1.10.0-1'), patch.object(guard,'transition',side_effect=lambda a,b: identity.transition(a,b,'1.10.0','1.10.0-1')):
                guard.package_transition(root,owned)
                self.assertEqual(guard.installed_version(root,owned),'1.2.0')
                path.unlink()
                with self.assertRaisesRegex(ValueError,'repair|header'):
                    guard.package_transition(root,owned)

    @unittest.skipUnless(shutil.which('dpkg'), 'native Debian comparison requires dpkg')
    def test_same_version_replacement_missing_repair_and_foreign_preservation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(guard,'OWNER_UID',os.getuid()):
            root = Path(directory)
            old,owned,path = self.payload(root)
            compare = lambda a,b: identity.transition(a,b,'1.2.0','1.2.0-1')
            with patch.object(guard,'INCOMING',old),patch.object(guard,'transition',side_effect=compare):
                guard.package_transition(root,owned)
                original = path.read_bytes()
                path.write_text('modified')
                with self.assertRaises(ValueError):guard.package_transition(root,owned)
                self.assertEqual(path.read_text(),'modified')
                path.unlink()
                guard.package_transition(root,owned)
                path.write_bytes(original)
                changed = copy.deepcopy(old);changed['scripts']['preinst']='c'*64
                with patch.object(guard,'INCOMING',changed):
                    self.assertEqual(guard.package_transition(root,owned),'replace')
                for field,value in (('repository','foreign/repo'),('lifecycle','legacy')):
                    changed=copy.deepcopy(old);changed[field]=value
                    (root/guard.RECEIPT).write_text(json.dumps(changed))
                    with self.assertRaisesRegex(ValueError,'incompatible'):
                        guard.package_transition(root,owned)

    def test_no_executable_current_version_literals(self):
        # The authoritative header and explicit arbitrary test data are allowed.
        for directory,pattern in (('scripts','*.py'),('tools','*.py')):
            for path in (ROOT/directory).glob(pattern):
                self.assertNotIn(identity.VERSION,path.read_text(),str(path))
        self.assertNotIn(identity.VERSION,(ROOT/'debian/rp1-gpclk-dkms.preinst').read_text())


if __name__ == '__main__': __import__("nonempty_unittest").main()
