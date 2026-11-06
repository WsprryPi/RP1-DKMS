#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded release format primitives shared by independent entrypoints."""
from __future__ import annotations
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import os
import selectors
import signal
import tempfile
import time
import subprocess
import tarfile

from version_identity import VERSION, DEBIAN
PACKAGE = 'rp1-gpclk-dkms'
SOURCE = f'{PACKAGE}-{VERSION}.tar.gz'
DEB = f'{PACKAGE}_{DEBIAN}_all.deb'
MANIFEST = 'rp1-gpclk-dkms-installation-manifest-v1.json'
METADATA = 'release-metadata.json'
COMPATIBILITY = 'rp1-gpclk-compatibility-manifest.json'
RESULT = 'candidate-validation.json'
ASSETS = {SOURCE, DEB, MANIFEST, METADATA, COMPATIBILITY, RESULT, 'SHA256SUMS'}
BEHAVIOR = dict(routeNeutral=True, outputDisabled=True, loadsModule=False,
                appliesOverlay=False, editsBootConfiguration=False, operatesServices=False)
MODULES = ['rp1_gpclk_dkms', 'rp1_route_controller']
LIMIT = 64*1024*1024
MAX_SOURCE_BYTES = 4*LIMIT
MAX_SOURCE_MEMBERS = 16384
GIT_BATCH_TIMEOUT = 120


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'duplicate JSON key: '+key)
        value[key] = item
    return value


def read_json(data):
    return json.loads(data, object_pairs_hook=unique_object)


def safe_path(name):
    require(isinstance(name, str) and len(name) <= 240 and
            re.fullmatch(r'[A-Za-z0-9_.+@/-]+', name) is not None and
            not name.startswith('/') and
            all(p not in ('', '.', '..') for p in name.split('/')), 'unsafe path: '+str(name))
    return name


def command_environment():
    return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C', 'LANG': 'C',
            'TZ': 'UTC', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_OPTIONAL_LOCKS': '0'}


def command(args, cwd=None, env=None, timeout=None):
    if env is None:
        env = command_environment()
    result = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, check=False, timeout=timeout)
    require(result.returncode == 0, 'command failed: '+str(args[0])+'\n'+
            (result.stdout+result.stderr).decode(errors='replace')[-6000:])
    return result.stdout


def git_argv(repo, *args):
    return ['git', '--no-replace-objects', '-c', 'core.fsmonitor=false',
            '-c', 'safe.directory='+str(repo), '-C', str(repo), *args]


def git(repo, *args):
    return command(git_argv(repo, *args), timeout=GIT_BATCH_TIMEOUT)


def decode_blobs(payload, objects):
    require(objects and isinstance(payload, bytes)
            and len(payload) <= MAX_SOURCE_BYTES+128*len(objects), 'invalid Git batch payload')
    offset, total, result = 0, 0, []
    for object_id in objects:
        end = payload.find(b'\n', offset, offset+128)
        require(end >= 0, 'missing Git batch header')
        header = payload[offset:end].split(b' ')
        require(len(header) == 3 and header[0] == object_id and header[1] == b'blob'
                and re.fullmatch(rb'0|[1-9][0-9]*', header[2]), 'Git batch identity/type/size differs')
        size = int(header[2]);total += size
        require(size <= LIMIT and total <= MAX_SOURCE_BYTES, 'source byte budget exceeded')
        offset = end+1
        data = payload[offset:offset+size]
        require(len(data) == size and payload[offset+size:offset+size+1] == b'\n', 'truncated Git batch object')
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data).hexdigest().encode() == object_id,
                'Git batch object hash differs')
        result.append(data);offset += size+1
    require(offset == len(payload), 'unexpected extra Git batch response')
    return result


def git_blobs(repo, objects):
    require(0 < len(objects) <= MAX_SOURCE_MEMBERS
            and all(re.fullmatch(b'[0-9a-f]{40}', value) for value in objects), 'invalid batch object selection')
    with tempfile.TemporaryFile() as requests:
        requests.write(b'\n'.join(objects)+b'\n');requests.seek(0)
        process = subprocess.Popen(git_argv(repo, 'cat-file', '--batch'), stdin=requests,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=command_environment(), start_new_session=True)
        deadline = time.monotonic()+GIT_BATCH_TIMEOUT
        output, errors = bytearray(), bytearray()
        primary = None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, (output, MAX_SOURCE_BYTES+128*len(objects)))
                selector.register(process.stderr, selectors.EVENT_READ, (errors, 65536))
                while selector.get_map():
                    remaining = deadline-time.monotonic()
                    require(remaining > 0, 'Git batch deadline exceeded')
                    events = selector.select(remaining)
                    require(events, 'Git batch deadline exceeded')
                    for key, mask in events:
                        target, limit = key.data
                        chunk = os.read(key.fileobj.fileno(), min(65536, limit+1-len(target)))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            target.extend(chunk)
                            require(len(target) <= limit, 'Git batch output budget exceeded')
            remaining = deadline-time.monotonic()
            require(remaining > 0, 'Git batch deadline exceeded')
            require(process.wait(timeout=remaining) == 0,
                    'Git batch failed: '+errors.decode(errors='replace')[-6000:])
        except subprocess.TimeoutExpired as error:
            primary = error
            raise ValueError('Git batch deadline exceeded') from error
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=10)
                cleanup_deadline = time.monotonic()+10
                while True:
                    try: os.killpg(process.pid, 0)
                    except ProcessLookupError: break
                    try:
                        while os.waitpid(-process.pid, os.WNOHANG)[0]: pass
                    except ChildProcessError: pass
                    require(time.monotonic() < cleanup_deadline, 'Git batch group cleanup unresolved')
                    time.sleep(0.02)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                if primary is None: raise ValueError('Git batch cleanup unresolved') from error
                primary.add_note('secondary Git batch cleanup unresolved: '+str(error))
            finally:
                process.stdout.close();process.stderr.close()
    return decode_blobs(bytes(output), objects)


def source_files(repo, commit):
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'full exact source commit required')
    require(git(repo, 'rev-parse', commit+'^{commit}').decode().strip() == commit,
            'source commit not found')
    entries, names = [], set()
    for entry in git(repo, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not entry:
            continue
        identity, name = entry.split(b'\t', 1)
        mode, kind, blob = identity.decode().split()
        name = safe_path(name.decode())
        require(name not in names and mode in ('100644', '100755') and kind == 'blob', 'unsafe Git member: '+name)
        names.add(name);entries.append((name, mode, blob.encode()))
        require(len(entries) <= MAX_SOURCE_MEMBERS, 'source member budget exceeded')
    data = git_blobs(repo, [entry[2] for entry in entries])
    result = {}
    for (name, mode, blob), payload in zip(entries, data):
        require(not re.search(br'-----BEGIN [A-Z ]*PRIVATE KEY-----', payload), 'private key in source')
        require(not name.endswith(('.pem', '.key', '.p12', '.pfx')), 'unexpected signing material')
        result[name] = (int(mode[-3:], 8), payload)
    require(result, 'empty source tree')
    return result


def write_source(files, destination):
    destination.mkdir()
    for name, (mode, data) in sorted(files.items()):
        path = destination/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)


def epoch(repo, commit):
    return int(git(repo, 'show', '-s', '--format=%ct', commit).strip())


def build_environment(timestamp):
    # No user/host paths, locale, HOME, compiler flags or mutable build options.
    return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C', 'LANG': 'C',
            'TZ': 'UTC', 'SOURCE_DATE_EPOCH': str(timestamp),
            'PYTHONDONTWRITEBYTECODE': '1', 'DEB_BUILD_OPTIONS': 'parallel=1',
            'XZ_DEFAULTS': '-T1', 'GZIP': '', 'DH_VERBOSE': '0'}


def source_archive(files, timestamp):
    stream = io.BytesIO()
    prefix = PACKAGE+'-'+VERSION
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, (mode, data) in sorted(files.items()):
            member = tarfile.TarInfo(prefix+'/'+name)
            member.mode, member.mtime = mode, timestamp
            member.uid = member.gid = 0
            member.uname = member.gname = 'root'
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)


def tar_members(data, timestamp=None):
    require(len(data) <= LIMIT, 'archive exceeds bound')
    if data.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            data = compressed.read(LIMIT+1)
        require(len(data) <= LIMIT, 'expanded archive exceeds bound')
    result = []
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        total = 0
        seen = set()
        root_seen = False
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/')
            if name in ('', '.'):
                require(member.name in ('.', './') and not root_seen and member.isdir() and
                        member.uid == member.gid == 0 and member.mode == 0o755 and member.size == 0,
                        'invalid or duplicate archive root')
                root_seen = True
                continue
            safe_path(name)
            require(name not in seen, 'duplicate archive member: '+name)
            seen.add(name)
            require(len(seen) <= 20000, 'too many archive members')
            require(member.isfile() or member.isdir(), 'unsafe link or special archive member')
            require(member.isfile() or member.size == 0, 'nonempty archive directory')
            require(member.uid == member.gid == 0, 'noncanonical archive ownership')
            require(member.mode in (0o644, 0o755), 'noncanonical archive permissions')
            require(not member.pax_headers, 'unexpected archive extended metadata')
            if timestamp is not None:
                require(member.mtime == timestamp, 'noncanonical archive mtime')
            total += member.size
            require(0 <= member.size <= LIMIT and total <= 128*1024*1024, 'expanded archive exceeds bound')
            payload = archive.extractfile(member).read() if member.isfile() else b''
            result.append({'path': name, 'type': 'file' if member.isfile() else 'directory',
                           'mode': f'0{member.mode:03o}', 'sha256': sha(payload),
                           'uid': member.uid, 'gid': member.gid, 'bytes': payload})
        require(not any(data[archive.offset:]), 'shadowed or trailing archive content')
    kinds = {item['path']: item['type'] for item in result}
    for name in kinds:
        require(all(kinds.get(str(parent), 'directory') == 'directory'
                    for parent in PurePosixPath(name).parents if str(parent) != '.'),
                'file shadows an archive ancestor')
    return sorted(result, key=lambda item: item['path'])


def inventory(members):
    return [{k: item[k] for k in ('path', 'type', 'mode', 'sha256')} for item in members]


def package_members(path):
    # Parse ar directly: dpkg-deb alone can ignore duplicate/shadowed ar members.
    raw = path.read_bytes()
    require(len(raw) <= LIMIT and raw.startswith(b'!<arch>\n'), 'invalid Debian ar archive')
    position, chunks, names = 8, [], []
    while position < len(raw):
        header = raw[position:position+60]
        require(len(header) == 60 and header[58:] == b'`\n', 'invalid ar member header')
        name = header[:16].decode().strip().rstrip('/')
        require(name not in names, 'duplicate Debian ar member')
        names.append(name)
        size = int(header[48:58])
        require(0 <= size <= LIMIT and int(header[28:34]) == int(header[34:40]) == 0,
                'unsafe ar size or ownership')
        require(int(header[40:48], 8) in (0o644, 0o100644), 'unsafe ar mode')
        position += 60
        chunk = raw[position:position+size]
        require(len(chunk) == size, 'truncated Debian ar member')
        chunks.append(chunk)
        position += size
        if size % 2:
            require(raw[position:position+1] == b'\n', 'invalid ar padding')
            position += 1
    require(names == ['debian-binary', 'control.tar.gz', 'data.tar.gz'] and chunks[0] == b'2.0\n',
            'unexpected Debian ar members or compression')
    expanded = []
    for chunk in chunks[1:]:
        with gzip.GzipFile(fileobj=io.BytesIO(chunk)) as stream:
            value = stream.read(LIMIT+1)
        require(len(value) <= LIMIT, 'Debian archive expansion exceeds bound')
        expanded.append(value)
    return tar_members(expanded[1]), tar_members(expanded[0])


def checksum_bytes(directory):
    return ''.join(sha((directory/name).read_bytes())+'  '+name+'\n'
                   for name in sorted(ASSETS-{'SHA256SUMS'})).encode()


def tools():
    versions = {name: command([name, flag]).decode().splitlines()[0] for name, flag in
                [('git', '--version'), ('dpkg-deb', '--version'), ('dpkg-buildpackage', '--version'),
                 ('dtc', '--version'), ('fdtput', '--version'), ('python3', '--version'),
                 ('make', '--version'), ('gzip', '--version'), ('xz', '--version')]}
    versions['packages'] = command(['dpkg-query', '-W', '-f=${Package}=${Version}\n',
        'debhelper', 'dh-dkms', 'dpkg', 'dpkg-dev', 'device-tree-compiler', 'python3',
        'python3-jsonschema', 'gzip', 'xz-utils', 'tar', 'libc6', 'zlib1g', 'liblzma5']).decode().splitlines()
    import zlib
    versions['pythonZlib'] = {'build': zlib.ZLIB_VERSION, 'runtime': zlib.ZLIB_RUNTIME_VERSION}
    versions['executablesSha256'] = {name: sha((Path('/usr/bin')/name).read_bytes())
        for name in ('git', 'dpkg-deb', 'dpkg-buildpackage', 'dtc', 'fdtput', 'python3', 'make', 'gzip', 'xz')}
    return versions
