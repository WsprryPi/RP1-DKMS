# SPDX-License-Identifier: MIT
"""Bounded, attributable acceptance of disposable lifecycle results."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

CONTRACT = 'rp1-gpclk-package-lifecycle-v2'
LIMIT = 16 * 1024 * 1024
SCENARIOS = ('packaged-runtime-baseline', 'clean-cycle', 'missing-payload',
             'package-lock', 'dependency-recovery', 'header-profiles',
             'multi-kernel', 'missing-headers', 'unpack-recovery', 'foreign-state',
             'fault-add', 'fault-build', 'fault-install', 'fault-depmod',
             'fault-remove', 'fault-purge', 'fault-remove-depmod', 'fault-unpack',
             'fault-gcc', 'fault-signature', 'compression-signing', 'predecessor',
             'fault-preinstall', 'fault-inventory', 'fault-configure')
IDENTITY_KEYS = {'sourceCommit', 'candidatePackageSha256',
                 'predecessorPackageSha256', 'imageId'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def decode(data):
    require(len(data) <= LIMIT, 'JSON exceeds bound')
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: require(False, 'nonfinite JSON'))


def read_regular(path, limit=LIMIT):
    """Read one stable regular inode; neither links nor paths are trust anchors."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                'single-linked regular file required')
        require(before.st_size <= limit, 'file exceeds bound')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        current = os.lstat(path)
        fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns,
                                 s.st_ctime_ns, s.st_mode, s.st_nlink)
        require(len(data) <= limit and fingerprint(before) == fingerprint(after)
                == fingerprint(current), 'file changed during acceptance')
        return data
    finally:
        os.close(fd)


def source_identity(root):
    """Bind mounted source bytes to HEAD, including index-hidden modifications."""
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C',
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_OPTIONAL_LOCKS': '0'}
    def git(*args):
        return subprocess.run(['git', '--no-replace-objects', '-c',
            'core.fsmonitor=false', '-c', 'safe.directory=' + str(root),
            '-C', str(root), *args], env=env, check=True,
            capture_output=True, timeout=30).stdout
    commit = git('rev-parse', 'HEAD').decode().strip()
    require(re.fullmatch('[0-9a-f]{40}', commit), 'exact SHA-1 source commit required')
    require(not git('status', '--porcelain=v1', '--untracked-files=all'),
            'dirty or untracked lifecycle source')
    for entry in git('ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not entry:
            continue
        identity, name = entry.split(b'\t', 1)
        mode, kind, blob = identity.decode().split()
        require(mode in ('100644', '100755') and kind == 'blob', 'unsafe source member')
        name = name.decode()
        require(re.fullmatch('[A-Za-z0-9_.+@/-]+', name)
                and not name.startswith('/')
                and all(p not in ('', '.', '..') for p in name.split('/')), 'unsafe source path')
        path = root / name
        data = read_regular(path, 64 * 1024 * 1024)
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(digest == blob and bool(path.stat().st_mode & 0o111) == (mode == '100755'),
                'source differs from commit: ' + name)
    require(git('rev-parse', 'HEAD').decode().strip() == commit, 'source revision changed')
    return commit


def input_identity(candidate, predecessor, image_id, commit):
    manifest = decode(read_regular(candidate / 'rp1-gpclk-dkms-installation-manifest-v1.json'))
    old = decode(read_regular(predecessor / 'predecessor.json'))
    require(manifest['sourceCommit'] == commit, 'candidate source differs from checkout')
    def package(directory, name, expected):
        require(isinstance(name, str) and Path(name).name == name and name.endswith('.deb'),
                'invalid package basename')
        actual = hashlib.sha256(read_regular(directory / name, 64 * 1024 * 1024)).hexdigest()
        require(actual == expected, 'package hash differs from manifest')
        return actual
    identity = {'sourceCommit': commit, 'imageId': image_id,
        'candidatePackageSha256': package(candidate, manifest['package']['filename'],
                                          manifest['package']['sha256']),
        'predecessorPackageSha256': package(predecessor, old['package'], old['packageSha256'])}
    validate_identity(identity)
    return identity


def validate_identity(identity):
    require(isinstance(identity, dict) and set(identity) == IDENTITY_KEYS,
            'identity fields differ')
    for key in IDENTITY_KEYS:
        pattern = ('[0-9a-f]{40}' if key == 'sourceCommit' else
                   'sha256:[0-9a-f]{64}' if key == 'imageId' else '[0-9a-f]{64}')
        require(isinstance(identity[key], str) and re.fullmatch(pattern, identity[key]),
                'invalid identity: ' + key)


def selection(scenarios):
    require(scenarios and len(scenarios) == len(set(scenarios))
            and set(scenarios) <= set(SCENARIOS), 'empty, duplicate or unknown scenario set')
    return tuple(scenarios)


def context(run_id, scenario, identity):
    validate_identity(identity)
    require(isinstance(run_id, str) and re.fullmatch('[0-9a-f]{32}', run_id), 'invalid run identity')
    selection((scenario,))
    return {'runId': run_id, 'scenario': scenario, 'identity': identity}


def envelope(expected, status, error, steps):
    return {'contract': CONTRACT, 'schemaVersion': 2, **expected,
            'status': status, 'error': error, 'steps': steps,
            'realPackageManager': True, 'hardwareQualification': False,
            'rfQualification': False}


def accept(path, expected, exit_status):
    value = decode(read_regular(path))
    keys = {'contract', 'schemaVersion', 'runId', 'scenario', 'identity', 'status',
            'error', 'steps', 'realPackageManager', 'hardwareQualification', 'rfQualification'}
    require(isinstance(value, dict) and set(value) == keys, 'result fields differ')
    require(value['contract'] == CONTRACT and type(value['schemaVersion']) is int
            and value['schemaVersion'] == 2, 'result version differs')
    for key in ('runId', 'scenario', 'identity'):
        require(value[key] == expected[key], 'result attribution differs: ' + key)
    validate_identity(value['identity'])
    require(value['realPackageManager'] is True and value['hardwareQualification'] is False
            and value['rfQualification'] is False, 'result evidence class differs')
    require(type(exit_status) is int and exit_status == 0 and value['status'] == 'PASS'
            and value['error'] is None, 'scenario did not pass')
    require(isinstance(value['steps'], list) and 0 < len(value['steps']) <= 1024,
            'missing or excessive completed work')
    for step in value['steps']:
        require(isinstance(step, dict) and set(step) == {
            'stage', 'command', 'exitStatus', 'before', 'after', 'diagnosticTail'},
            'step fields differ')
        require(isinstance(step['stage'], str) and 0 < len(step['stage']) <= 256
                and isinstance(step['command'], list) and step['command']
                and all(isinstance(a, str) and len(a) <= 4096 for a in step['command'])
                and type(step['exitStatus']) is int
                and isinstance(step['diagnosticTail'], str)
                and len(step['diagnosticTail']) <= 8192, 'invalid completed step')
        for observed in (step['before'], step['after']):
            require(isinstance(observed, dict) and observed.get('endpointsAbsent') is True
                    and observed.get('modulesUnloaded') is True, 'step activation or unknown safety')
    return value
