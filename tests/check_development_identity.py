#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Current identity and fail-before-mutation installation boundary tests."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("identity_workflow", ROOT / "scripts/development_workflow.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def rejected(action, message):
    try:
        action()
    except dev.Failure as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError("unsafe transition accepted")


assert '#define RP1_GPCLK_MODULE_VERSION "0.99.0"' in (ROOT / 'include/rp1_gpclk/version.h').read_text()
assert 'MODULE_VERSION(RP1_GPCLK_MODULE_VERSION)' in (ROOT / 'controller/main.c').read_text()
assert (ROOT / 'debian/changelog').read_text().startswith('rp1-gpclk-dkms (0.99.0-1) UNRELEASED;')
assert dev.sha256(ROOT / 'include/uapi/linux/rp1_gpclk.h') == '4af14cdf60471ac4b318b10d7d70824a63c74029c2934e86bbdcd1b7f06cf633'
assert json.loads((ROOT / 'uapi-identity.json').read_text())['sha256'] == \
       dev.sha256(ROOT / 'include/uapi/linux/rp1_gpclk.h')
for route in ('gpio4', 'gpio20'):
    identifier = f'v0.99.0-rp1-{route}'
    assert identifier in (ROOT / 'include/rp1_gpclk/compatibility.h').read_text()
    assert identifier in (ROOT / 'scripts/development_route_manager.py').read_text()
assert 'RP1_GPCLK_ROUTE_CANDIDATE' not in (ROOT / 'include/rp1_gpclk/compatibility.h').read_text()

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    rejected(lambda: dev.canonical_module_version(root), 'missing or substituted')
    with patch.dict(os.environ, {'RP1_GPCLK_DEVELOPMENT_ROOT': str(root)}):
        assert dev.transition_preflight('0.99.0', 'test-kernel', []) is None
        for version in ('1.0.0', '1.0.1', '1.0.2', '9.9.9', 'unknown'):
            rejected(lambda: dev.transition_preflight('0.99.0', 'test-kernel',
                [f'rp1-gpclk-dkms/{version}, test-kernel, installed']), 'explicit maintainer')
        rejected(lambda: dev.transition_preflight('0.99.0', 'test-kernel',
            ['rp1-gpclk-dkms/0.99.0, another-kernel, installed']), 'another kernel')
        old = root/'usr/src/rp1-gpclk-dkms-9.9.9'
        old.mkdir(parents=True)
        rejected(lambda: dev.transition_preflight('0.99.0', 'test-kernel', []), 'stale predecessor')
        old.rmdir()
        for path in ('etc/rp1-gpclk-dkms/runtime-controller.json',
                     'var/lib/dpkg/info/rp1-gpclk-dkms.list',
                     'var/lib/rp1-gpclk-dkms/development/route-manager.json'):
            file = root/path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('foreign')
            rejected(lambda: dev.transition_preflight('0.99.0', 'test-kernel', []), 'ownership')
            assert file.read_text() == 'foreign'
            file.unlink()
        destination = root/'usr/src/rp1-gpclk-dkms-0.99.0'
        destination.mkdir()
        rejected(lambda: dev.owned_source(destination, '0.99.0'), 'unreadable')
        (destination/'file').write_text('owned')
        manifest = dict(schema=dev.SCHEMA, classification='source-development', qualification=False,
            moduleName=dev.CANONICAL_MODULE, dkmsName=dev.PACKAGE, renderedVersion='0.99.0',
            renderedInventory=dev.inventory(destination, ['file']))
        manifest_path = destination/'DEVELOPMENT_MANIFEST.json'
        manifest_path.write_bytes(dev.canonical(manifest))
        dev.owned_source(destination, '0.99.0')
        (destination/'file').chmod(0o666)
        rejected(lambda: dev.owned_source(destination, '0.99.0'), 'permissions')
        (destination/'file').chmod(0o644)
        (destination/'file').write_text('changed')
        rejected(lambda: dev.owned_source(destination, '0.99.0'), 'modified')
        (destination/'file').write_text('owned')
        (destination/'foreign').write_text('keep')
        rejected(lambda: dev.owned_source(destination, '0.99.0'), 'foreign')
        (destination/'foreign').unlink()
        (destination/'linked-directory').symlink_to(root, target_is_directory=True)
        rejected(lambda: dev.owned_source(destination, '0.99.0'), 'symlink')
        (destination/'linked-directory').unlink()
        record = root/'ROLLBACK.json'
        value = dict(schema=dev.ROLLBACK_SCHEMA, moduleName=dev.CANONICAL_MODULE,
            kernel='test-kernel', version='0.99.0', workflowCreatedFiles=['/foreign'])
        record.write_bytes(dev.canonical(value))
        with patch.object(dev, 'require_root'), patch.object(dev, 'run') as run:
            rejected(lambda: dev.rollback(record), 'out-of-scope')
            run.assert_not_called()
            value['workflowCreatedFiles'] = [str(destination)]
            value['sourceManifestSha256'] = '0'*64
            record.write_bytes(dev.canonical(value))
            rejected(lambda: dev.rollback(record), 'another instance')
            run.assert_not_called()

print('Development identity and transition boundaries: PASS')

# Bundle generation cannot bind old modules to current userspace identities.
import sys
sys.path.insert(0, str(ROOT/'scripts'))
from build_runtime_binding import validate_module_version
validate_module_version(b'\x7fELF\x00version=0.99.0\x00')
for payload in (b'\x00version=1.0.1\x00', b'\x00version=9.9.9\x00', b'\x00version=0.1.0\x00', b'no version',
                b'\x00version=0.99.0\x00\x00version=9.9.9\x00'):
    try:
        validate_module_version(payload)
    except ValueError:
        pass
    else:
        raise AssertionError('predecessor or ambiguous runtime module accepted')

# Exercise maintainer-script dispatch without touching a package database.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)/'dpkg'
    path.write_text('''#!/usr/bin/env python3
import sys
assert sys.argv[1] == '--compare-versions' and sys.argv[3] in ('gt', 'lt') and sys.argv[4] == '0.99.0-1'
raise SystemExit(0 if (sys.argv[2] == '9.9.9-1' and sys.argv[3] == 'gt') or (sys.argv[2] in ('0.9.0-1', '1.0.0-1', '1.0.1-1') and sys.argv[3] == 'lt') else 1)
''')
    path.chmod(0o755)
    for args, expected in ((['install'], 0), (['upgrade', '0.9.0-1'], 1), (['upgrade', '1.0.0-1'], 1), (['upgrade', '1.0.1-1'], 1), (['upgrade', '0.99.0-1'], 0),
                           (['upgrade', '9.9.9-1'], 1), (['install', '9.9.9-1'], 1)):
        result = subprocess.run(['sh', str(ROOT/'debian/rp1-gpclk-dkms.preinst'), *args],
            env={**os.environ, 'PATH': directory+os.pathsep+os.environ['PATH']},
            capture_output=True, text=True)
        assert result.returncode == expected, result.stderr
        if expected:
            assert 'downgrade' in result.stderr or 'direct upgrade refused' in result.stderr
print('Runtime bundle and Debian downgrade guards: PASS')

import shutil
from overlay_builder import build_dtbo
spec = importlib.util.spec_from_file_location('current_route_manager', ROOT/'scripts/rp1-gpclk-route-manager.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
with tempfile.TemporaryDirectory() as directory:
    for route in ('gpio4', 'gpio20'):
        output = Path(directory)/(route+'.dtbo')
        build_dtbo(ROOT/'overlays'/('rp1-gpclk-'+route+'.dts'), output, shutil.which('dtc'))
        assert dev.sha256(output) == manager.OVERLAY_SHA256[route], route
print('Current package route overlay hashes: PASS')
