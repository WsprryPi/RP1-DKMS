#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Current identity and fail-before-mutation installation boundary tests."""
import sys as _identity_sys
from pathlib import Path as _IdentityPath
_identity_sys.path.insert(0, str(_IdentityPath(__file__).resolve().parents[1]/'scripts'))
from version_identity import VERSION, DEBIAN, COMPATIBILITY, expand
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


assert dev.canonical_module_version(ROOT) == VERSION
assert 'MODULE_VERSION(RP1_GPCLK_MODULE_VERSION)' in (ROOT/'controller/main.c').read_text()
assert '(@DEBIAN_VERSION@) UNRELEASED;' in (ROOT/'debian/changelog').read_text()
assert json.loads((ROOT/'uapi-identity.json').read_text())['sha256'] == dev.sha256(ROOT/'include/uapi/linux/rp1_gpclk.h')
for route in ('gpio4', 'gpio20'):
    assert '"v" RP1_GPCLK_MODULE_VERSION "-rp1-'+route+'"' in (ROOT/'include/rp1_gpclk/compatibility.h').read_text()
assert 'RP1_GPCLK_ROUTE_CANDIDATE' not in (ROOT / 'include/rp1_gpclk/compatibility.h').read_text()

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    rejected(lambda: dev.canonical_module_version(root), 'missing or substituted')
    with patch.dict(os.environ, {'RP1_GPCLK_DEVELOPMENT_ROOT': str(root)}):
        assert dev.transition_preflight(VERSION, 'test-kernel', []) is None
        for version in ('0.99.0', '1.0.0', '1.0.1', '1.0.2', '9.9.9', 'unknown'):
            rejected(lambda: dev.transition_preflight(VERSION, 'test-kernel',
                [f'rp1-gpclk-dkms/{version}, test-kernel, installed']),
                'orphan' if version != 'unknown' and dev.compare_versions(VERSION, version) > 0 else 'explicit maintainer')
        rejected(lambda: dev.transition_preflight(VERSION, 'test-kernel',
            [('rp1-gpclk-dkms/' + VERSION + ', another-kernel, installed')]), 'another kernel')
        old = root/'usr/src/rp1-gpclk-dkms-9.9.9'
        old.mkdir(parents=True)
        rejected(lambda: dev.transition_preflight(VERSION, 'test-kernel', []), 'explicit maintainer')
        old.rmdir()
        for path in ('etc/rp1-gpclk-dkms/runtime-controller.json',
                     'var/lib/dpkg/info/rp1-gpclk-dkms.list',
                     'var/lib/rp1-gpclk-dkms/development/route-manager.json'):
            file = root/path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('foreign')
            rejected(lambda: dev.transition_preflight(VERSION, 'test-kernel', []), 'ownership')
            assert file.read_text() == 'foreign'
            file.unlink()
        destination = root/('usr/src/rp1-gpclk-dkms-' + VERSION + '')
        destination.mkdir()
        rejected(lambda: dev.owned_source(destination, VERSION), 'unreadable')
        (destination/'file').write_text('owned')
        manifest = dict(schema=dev.SCHEMA, classification='source-development', qualification=False,
            moduleName=dev.CANONICAL_MODULE, dkmsName=dev.PACKAGE, renderedVersion=VERSION,
            renderedInventory=dev.inventory(destination, ['file']))
        manifest_path = destination/'DEVELOPMENT_MANIFEST.json'
        manifest_path.write_bytes(dev.canonical(manifest))
        dev.owned_source(destination, VERSION)
        (destination/'file').chmod(0o666)
        rejected(lambda: dev.owned_source(destination, VERSION), 'permissions')
        (destination/'file').chmod(0o644)
        (destination/'file').write_text('changed')
        rejected(lambda: dev.owned_source(destination, VERSION), 'modified')
        (destination/'file').write_text('owned')
        (destination/'foreign').write_text('keep')
        rejected(lambda: dev.owned_source(destination, VERSION), 'foreign')
        (destination/'foreign').unlink()
        (destination/'linked-directory').symlink_to(root, target_is_directory=True)
        rejected(lambda: dev.owned_source(destination, VERSION), 'symlink')
        (destination/'linked-directory').unlink()
        record = root/'ROLLBACK.json'
        value = dict(schema=dev.ROLLBACK_SCHEMA, moduleName=dev.CANONICAL_MODULE,
            kernel='test-kernel', version=VERSION, workflowCreatedFiles=['/foreign'])
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
validate_module_version(('\x7fELF\x00version=' + VERSION + '\x00').encode())
for payload in (b'\x00version=1.0.1\x00', b'\x00version=9.9.9\x00', b'\x00version=0.1.0\x00', b'no version',
                ('\x00version=' + VERSION + '\x00\x00version=9.9.9\x00').encode()):
    try:
        validate_module_version(payload)
    except ValueError:
        pass
    else:
        raise AssertionError('predecessor or ambiguous runtime module accepted')

# Transition ordering is tested against native dpkg in check_versioning.py.
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
