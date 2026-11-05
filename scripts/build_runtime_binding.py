#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create local deployment-review metadata from compiled modules; never install."""
import hashlib
import bz2
import gzip
import json
import lzma
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import platform
from runtime_inventory import module_note
from runtime_layout import INVENTORY
from runtime_binding import (APPLICATION, COMPATIBILITY, CONTRACT, PRODUCT_VERSION,
                             canonical_digest, validate)

ROOT = Path(__file__).resolve().parents[1]
MAX_MODULE_BYTES = 64 * 1024 * 1024


def validate_module_version(payload):
    """Do not bind predecessor modules to current userspace/overlay source."""
    versions = re.findall(rb'(?:^|\x00)version=([^\x00]+)\x00', payload)
    if versions != [PRODUCT_VERSION.encode()]:
        raise ValueError('runtime module version differs from 0.99.0 development source')


def source_commit():
    value = subprocess.run(('git', '-C', str(ROOT), 'rev-parse', 'HEAD'),
        check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    if not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('source commit identity unavailable')
    return value


def companion_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('application companion must be a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            value = stream.read(4*1024*1024 + 1)
        if len(value) > 4*1024*1024:
            raise ValueError('application companion exceeds bound')
        return value
    finally:
        os.close(fd)


def module_payload(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('runtime module must be a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(MAX_MODULE_BYTES + 1)
        if len(data) > MAX_MODULE_BYTES:
            raise ValueError('runtime module exceeds bound')
    finally:
        os.close(fd)
    if path.name.endswith('.ko'):
        payload, kind = data, 'none'
    elif path.name.endswith('.ko.xz'):
        payload, kind = lzma.decompress(data), 'xz'
    elif path.name.endswith('.ko.gz'):
        payload, kind = gzip.decompress(data), 'gz'
    elif path.name.endswith('.ko.bz2'):
        payload, kind = bz2.decompress(data), 'bz2'
    elif path.name.endswith('.ko.zst'):
        result = subprocess.run(('zstd', '-q', '-d', '-c'), input=data,
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError('runtime module zstd decompression failed')
        payload, kind = result.stdout, 'zst'
    else:
        raise ValueError('unsupported runtime module compression')
    if len(payload) > MAX_MODULE_BYTES:
        raise ValueError('decompressed runtime module exceeds bound')
    return payload, kind


def installed_module(directory, name, kernel=None):
    kernel = kernel or platform.release()
    matches = sorted(directory.glob(name + '.ko*'))
    if len(matches) != 1:
        raise ValueError('exactly one installed runtime module required: ' + name)
    path = matches[0]
    if path.is_symlink() or not path.is_file():
        raise ValueError('installed runtime module is missing or substituted: ' + name)
    payload, compression = module_payload(path)
    if not payload.startswith(b'\x7fELF\x02\x01'):
        raise ValueError('exact-kernel ELF64 module required')
    validate_module_version(payload)
    if b'vermagic=' + kernel.encode() + b' ' not in payload:
        raise ValueError('runtime module vermagic differs from target kernel')
    installed = f'/lib/modules/{kernel}/updates/dkms/{path.name}'
    return {'name': name, 'path': installed,
            'installedFileSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'decompressedElfSha256': hashlib.sha256(payload).hexdigest(),
            'compression': compression,
            'buildNoteSha256': hashlib.sha256(module_note(payload)).hexdigest(),
            'version': PRODUCT_VERSION, 'kernel': kernel}, payload


def build(directory, application_companion, kernel=None):
    kernel = kernel or platform.release()
    from build_runtime_controller import generate
    generate(ROOT / "build/runtime-controller")
    companion = Path(application_companion)
    companion = companion_bytes(companion)
    values = {'schemaVersion': 3, 'contract': CONTRACT,
              'productVersion': PRODUCT_VERSION,
              'compatibilityIdentities': COMPATIBILITY,
              'sourceCommit': source_commit(), 'kernel': kernel, 'files': {}, 'modules': {},
              'externalFiles': {APPLICATION: hashlib.sha256(companion).hexdigest()},
              'uapiSha256': {}}
    payloads = {}
    for module, field in (('rp1_route_controller', 'controllerNoteSha256'),
                          ('rp1_gpclk_dkms', 'consumerNoteSha256')):
        record, payload = installed_module(directory, module, kernel)
        values['modules'][module] = record
        payloads[module] = payload
        values[field] = record['buildNoteSha256']
    consumer = payloads['rp1_gpclk_dkms']
    if b'rp1_runtime_controller=1\0' not in consumer or b'rp1_route_controller' not in consumer:
        raise ValueError('interlocked consumer required')
    if b'alias=of:' in consumer:
        raise ValueError('runtime consumer must not autoload from OF aliases')
    for destination, source in INVENTORY.items():
        if not source.endswith('.ko'):
            values['files'][destination] = hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
    values['uapiSha256'] = {
        'consumer': values['files']['/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_gpclk.h'],
        'controller': values['files']['/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_route_admin.h']}
    values['artifactSetSha256'] = canonical_digest(values)
    return validate(values)


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        raise SystemExit('usage: build_runtime_binding.py INSTALLED_DKMS_MODULE_DIRECTORY WSPRRYPI_APPLICATION_COMPANION [KERNEL]')
    print(json.dumps(build(Path(sys.argv[1]), Path(sys.argv[2]),
                           sys.argv[3] if len(sys.argv) == 4 else None),
                     indent=2, sort_keys=True))
