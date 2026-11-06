#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only package guard. Unknown administration/signing state blocks DKMS."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import hashlib
import json
import re
import shlex
import stat
import sys

OWNER_UID = 0  # Internal fixture seam; never an environment or CLI override.
KERNEL = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+\+rpt-rpi-(?:2712|v8)')
PACKAGE = 'rp1-gpclk-dkms'
# Isolated installed entrypoints explicitly import their own packaged helper.
if '__file__' in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from version_identity import (VERSION, DEBIAN, REPOSITORY, LIFECYCLE, parse,
                              transition, from_header)
INCOMING = None
RECEIPT = 'usr/libexec/rp1-gpclk-dkms/package-identity.json'


def installed_version(root, owned=None):
    if owned is None:
        listing = root/'var/lib/dpkg/info'/ (PACKAGE+'.list')
        names = regular(listing).decode().splitlines() if present(listing) else []
        owned = {root/n.lstrip('/') for n in names}
    versions = {p.name.removeprefix(PACKAGE+'-') for p in owned
                if p.parent == root/'usr/src' and p.name.startswith(PACKAGE+'-')}
    if len(versions) > 1:
        raise ValueError('ambiguous package source identity')
    version = next(iter(versions), VERSION)
    parse(version)
    return version


def package_transition(root, owned):
    """Authenticate passive outgoing package and exact incoming payload identity.

    Unknown legacy templates have no receipt, so they remain cleanup-first.
    Native outgoing scripts run only after this independent incoming preflight.
    """
    if INCOMING is None:
        return
    path = root/RECEIPT
    version = installed_version(root, owned)
    if not present(path):
        if owned:
            raise ValueError('installed package lacks passive lifecycle identity; owning removal required')
        return 'install'
    if path not in owned:
        raise ValueError('foreign package identity receipt')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate package identity field')
            result[key] = value
        return result
    old = json.loads(regular(path), object_pairs_hook=unique)
    fields = {'repository', 'lifecycle', 'productVersion', 'debianVersion', 'payload', 'uapi', 'scripts'}
    if (not isinstance(old, dict) or set(old) != fields or
            old['repository'] != REPOSITORY or old['lifecycle'] != LIFECYCLE or
            old['productVersion'] != version):
        raise ValueError('incompatible package origin or lifecycle; owning migration required')
    if not isinstance(old['scripts'], dict) or set(old['scripts']) != {'preinst', 'postinst', 'prerm'}:
        raise ValueError('missing outgoing maintainer script identity')
    for name, expected in old['scripts'].items():
        control = root/'var/lib/dpkg/info'/(PACKAGE+'.'+name)
        data = regular(control)
        if name == 'preinst':
            data, count = re.subn(rb"(?ms)^python3 -I - unpack <<'RP1_INCOMING_PREFLIGHT'\n.*?^RP1_INCOMING_PREFLIGHT\n",
                                  b'# RP1_INCOMING_PREFLIGHT\n', data)
            if count != 1:
                raise ValueError('outgoing preinst identity framing differs')
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('outgoing maintainer script was modified')
    kind = transition(version, old['debianVersion'])
    if kind == 'same' and old != INCOMING:
        kind = 'replace'
    source = root/'usr/src'/(PACKAGE+'-'+version)/'include/rp1_gpclk/version.h'
    if source not in owned or (present(source) and from_header(regular(source).decode()) != (version, old['debianVersion'])) or (kind == 'upgrade' and not present(source)):
        raise ValueError('outgoing package header and receipt disagree')
    payload = old['payload']
    if not isinstance(payload, dict) or not payload:
        raise ValueError('missing outgoing payload identity')
    for name, digest in payload.items():
        if (not isinstance(name, str) or name.startswith('/') or '..' in Path(name).parts or
                not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('unsafe outgoing payload identity')
        member = root/name
        if member not in owned:
            raise ValueError('outgoing receipt has no package ownership')
        if not present(member):
            if kind in ('same', 'replace'):
                continue
            raise ValueError('incomplete outgoing package; exact repair required before upgrade')
        if hashlib.sha256(regular(member)).hexdigest() != digest:
            raise ValueError('outgoing payload differs from identity receipt')
    return kind



def present(path):
    return path.exists() or path.is_symlink()


def payload_ownership(root, complete=False):
    """Check dpkg's complete file inventory before replacement or deletion.

    dpkg intentionally overwrites/deletes changed ordinary data files. Its
    database is therefore an ownership input, not permission to ignore drift.
    Missing files are permitted for interrupted removal/reinstall recovery;
    present files and unlisted descendants must still be attributable.
    """
    database = root/'var/lib/dpkg/info'
    listing = database/(PACKAGE+'.list')
    sums = database/(PACKAGE+'.md5sums')
    names = regular(listing).decode().splitlines() if present(listing) else []
    owned = set()
    for name in names:
        if not name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('unsafe dpkg inventory')
        owned.add(root/name.lstrip('/'))
    hashes = {}
    lines = regular(sums).decode().splitlines() if names else []
    for line in lines:
        digest, name = line.split('  ', 1)
        if not re.fullmatch('[0-9a-f]{32}', digest) or name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('unsafe dpkg checksum inventory')
        path = root/name
        if present(path) and path not in owned:
            raise ValueError('foreign package payload preserved: '+str(path))
        if path not in owned or path in hashes:
            raise ValueError('inconsistent dpkg checksum inventory')
        hashes[path] = digest
    for path in owned:
        if not present(path):
            if complete:
                raise ValueError('missing package payload requires reinstall: '+str(path))
            continue
        if path in hashes:
            expected_mode = (0o644 if path.name in ('version.h', 'package-identity.json') else 0o755 if path.name == 'rp1-gpclk-route-manager' or
                             path.is_relative_to(root/'usr/libexec/rp1-gpclk-dkms') else 0o644)
            if stat.S_IMODE(path.stat().st_mode) != expected_mode:
                raise ValueError('modified package mode preserved: '+str(path))
            if hashlib.md5(regular(path), usedforsecurity=False).hexdigest() != hashes[path]:
                raise ValueError('modified package payload preserved: '+str(path))
        elif path.is_symlink() or not path.is_dir():
            raise ValueError('unattributable package member: '+str(path))
    # These are private package directories, unlike shared /usr and /usr/lib.
    version = installed_version(root, owned)
    for name in ('usr/src/'+PACKAGE+'-'+version, 'usr/libexec/'+PACKAGE,
                 'usr/lib/'+PACKAGE+'/overlays', 'usr/share/'+PACKAGE+'/'+version,
                 'usr/share/doc/'+PACKAGE):
        path = root/name
        if present(path) and path not in owned:
            raise ValueError('foreign package payload preserved: '+str(path))
        if present(path) and (path.is_symlink() or not path.is_dir() or
                              path.stat().st_uid != OWNER_UID or
                              stat.S_IMODE(path.stat().st_mode) != 0o755):
            raise ValueError('unsafe private package directory: '+str(path))
        if path.is_dir():
            for member in path.rglob('*'):
                if member not in owned:
                    raise ValueError('foreign package descendant preserved: '+str(member))
                if member.is_dir() and (member.is_symlink() or member.stat().st_uid != OWNER_UID or
                                        stat.S_IMODE(member.stat().st_mode) != 0o755):
                    raise ValueError('unsafe private package descendant: '+str(member))
    for name in ('usr/sbin/rp1-gpclk-route-manager',
                 'usr/lib/systemd/system/rp1-gpclk-route-manager.socket',
                 'usr/lib/systemd/system/rp1-gpclk-route-manager@.service'):
        path = root/name
        if present(path) and path not in owned:
            raise ValueError('foreign package payload preserved: '+str(path))
    return owned


def registration_ownership(root, owned):
    current = installed_version(root, owned)
    source = root/'usr/src'/ (PACKAGE+'-'+current)
    for path in (root/'usr/src').glob(PACKAGE+'-*'):
        if path != source or path not in owned or present(path/'DEVELOPMENT_MANIFEST.json'):
            raise ValueError('foreign or development source requires owning removal: '+str(path))
    base = root/'var/lib/dkms'/PACKAGE
    if any(p.is_symlink() for p in (base, *base.parents)):
        raise ValueError('foreign DKMS root symlink')
    if not base.exists():
        return
    for directory in (base, *[p for p in base.parents if p.is_relative_to(root)]):
        info = directory.stat()
        if info.st_uid != OWNER_UID or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise ValueError('unsafe DKMS namespace preserved')
    version = base/current
    link = version/'source'
    if any(base.iterdir()) and (source not in owned or version.is_symlink() or
            not link.is_symlink() or link.lstat().st_uid != OWNER_UID or link.resolve() != source.resolve()):
        raise ValueError('orphan or foreign DKMS registration preserved')
    for path in base.iterdir():
        if path.name.startswith('kernel-') and path.is_symlink():
            import os
            parts = Path(os.readlink(path)).parts
            if (path.lstat().st_uid == OWNER_UID and len(parts) == 3 and parts[0] == current and KERNEL.fullmatch(parts[1]) and
                    parts[2] == 'aarch64' and path.name == 'kernel-'+parts[1]+'-'+parts[2]):
                continue
            raise ValueError('foreign DKMS kernel link preserved')
        if path.name != current or path.is_symlink() or not path.is_dir():
            raise ValueError('foreign DKMS version preserved: '+str(path))
        link = path/'source'
        if source not in owned or not link.is_symlink() or link.resolve() != source.resolve():
            raise ValueError('foreign DKMS registration preserved')
        # Executable source must remain the package's exact registered source.
        if source/'dkms.conf' not in owned:
            raise ValueError('DKMS source has no package ownership')
        cache_ownership(path, source)


def cache_ownership(version, source):
    """Bound the reviewed DKMS 3.2 cache shape before native recursive removal."""
    def directory(path):
        info = path.stat()
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != OWNER_UID or info.st_mode & 0o022:
            raise ValueError('unsafe DKMS cache directory preserved: '+str(path))

    directory(version)
    source_names = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    generated = {'make.log', 'Module.symvers', 'modules.order', '.Module.symvers.cmd', '.modules.order.cmd'}
    for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
        for suffix in ('.o', '.ko', '.mod', '.mod.c', '.mod.o'):
            generated.update({name+suffix, '.'+name+suffix+'.cmd', '.'+name+suffix+'.d'})
    for name in source_names:
        if name.endswith('.c'):
            obj = Path(name).with_suffix('.o')
            generated.update({obj.as_posix(), (obj.parent/('.'+obj.name+'.cmd')).as_posix(),
                              (obj.parent/('.'+obj.name+'.d')).as_posix()})
    generated.update('build/runtime-controller/'+name for name in
                     ('gpio4.dtbo', 'gpio20.dtbo', 'overlays.h', 'identity.json'))
    generated.add('scripts/__pycache__/overlay_builder.'+sys.implementation.cache_tag+'.pyc')
    build_names = source_names | generated
    directories = {p.as_posix() for name in build_names for p in Path(name).parents}
    for child in version.iterdir():
        if child.name == 'source':
            continue
        directory(child)
        if child.name == 'build':
            for item in child.rglob('*'):
                name = item.relative_to(child).as_posix()
                if item.is_dir():
                    if name not in directories:
                        raise ValueError('foreign DKMS build directory preserved')
                    directory(item)
                else:
                    if name not in build_names:
                        raise ValueError('foreign DKMS build file preserved: '+str(item))
                    data = regular(item)
                    if name in source_names and data != regular(source/name):
                        raise ValueError('modified DKMS source copy preserved: '+str(item))
            continue
        if not KERNEL.fullmatch(child.name):
            raise ValueError('foreign DKMS cache entry preserved: '+str(child))
        for arch in child.iterdir():
            if arch.name != 'aarch64' and not re.fullmatch(r'\.tmp_aarch64_[A-Za-z0-9]{6}', arch.name):
                raise ValueError('foreign DKMS architecture cache preserved')
            directory(arch)
            for section in arch.iterdir():
                if section.name not in ('module', 'log'):
                    raise ValueError('foreign DKMS cache section preserved')
                directory(section)
                for item in section.iterdir():
                    allowed = (item.name == 'make.log' if section.name == 'log' else
                        item.name == 'Module.symvers' or re.fullmatch(
                            r'(?:rp1_gpclk_dkms|rp1_route_controller)\.ko(?:\.(?:gz|xz|zst))?', item.name))
                    if not allowed:
                        raise ValueError('foreign DKMS cache file preserved: '+str(item))
                    regular(item)


def regular(path, mode=None):
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('unsafe symlink: '+str(part))
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER_UID or info.st_mode & 0o022:
        raise ValueError('unsafe administrator file: '+str(path))
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        raise ValueError('unsafe signing key mode')
    if info.st_size > 64*1024*1024:
        raise ValueError('administrator file exceeds bound')
    if mode is not None:
        return None
    with path.open('rb') as stream:
        value = stream.read(64*1024*1024+1)
    if len(value) > 64*1024*1024:
        raise ValueError('administrator file exceeds bound')
    return value


def framework(root):
    values = {}
    config = root/'etc/dkms'
    for path in [config/'framework.conf', *sorted((config/'framework.conf.d').glob('*.conf'))]:
        if not path.exists() and not path.is_symlink():
            continue
        for line in regular(path).decode().splitlines():
            words = shlex.split(line, comments=True)
            if not words:
                continue
            if len(words) != 1 or not re.fullmatch(r'[a-z_]+=[A-Za-z0-9/_.:+ -]*', words[0]):
                raise ValueError('dynamic DKMS configuration requires administrator review')
            key, value = words[0].split('=', 1)
            values[key] = value
    allowed = {'source_tree', 'dkms_tree', 'install_tree', 'tmp_location', 'verbose',
               'parallel_jobs', 'autoinstall_all_kernels', 'modprobe_on_install',
               'post_transaction', 'symlink_modules', 'sign_file', 'mok_signing_key',
               'mok_certificate', 'compress_gzip_opts', 'compress_xz_opts', 'compress_zstd_opts'}
    if set(values)-allowed:
        raise ValueError('unreviewed DKMS framework option')
    for key in ('modprobe_on_install', 'post_transaction', 'symlink_modules'):
        # DKMS treats any nonempty value, including "false", as enabled.
        if values.get(key):
            raise ValueError('non-passive DKMS configuration: '+key)
    for key, default in (('source_tree', '/usr/src'), ('dkms_tree', '/var/lib/dkms'),
                         ('install_tree', '/lib/modules')):
        if values.get(key, default) != default:
            raise ValueError('noncanonical DKMS tree: '+key)
    if values.get('tmp_location', '/tmp') != '/tmp':
        raise ValueError('noncanonical DKMS temporary directory')
    if 'autoinstall_all_kernels' in values and values['autoinstall_all_kernels'] != 'yes':
        raise ValueError('DKMS must retain all installed kernels')
    for key in ('compress_gzip_opts', 'compress_xz_opts', 'compress_zstd_opts'):
        if values.get(key) and not re.fullmatch('-[1-9]', values[key]):
            raise ValueError('unreviewed compression arguments: '+key)
    return values


def module_elf(path, version=VERSION):
    import bz2
    import gzip
    import io
    import lzma
    import subprocess
    data = regular(path)
    limit = 64*1024*1024
    if path.name.endswith('.ko'):
        value = data
    elif path.suffix == '.gz':
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            value = stream.read(limit+1)
    elif path.suffix in ('.xz', '.bz2'):
        decoder = (lzma.LZMADecompressor(memlimit=128*1024*1024) if path.suffix == '.xz'
                   else bz2.BZ2Decompressor())
        value = decoder.decompress(data, max_length=limit+1)
        if not decoder.eof or decoder.unused_data:
            raise ValueError('truncated, oversized or trailing module compression')
    elif path.suffix == '.zst':
        import tempfile
        with tempfile.TemporaryFile() as source:
            source.write(data)
            source.seek(0)
            with subprocess.Popen(['/usr/bin/zstd', '-q', '-d', '-c'], stdin=source,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
                value = process.stdout.read(limit+1)
                if len(value) > limit:
                    process.kill()
                if process.wait(timeout=10):
                    raise ValueError('module decompression failed')
    else:
        raise ValueError('unrecognized module compression')
    if (len(value) > limit or not value.startswith(b'\x7fELF\x02\x01') or
            re.findall(rb'(?:^|\x00)version=([^\x00]+)\x00', value) != [version.encode()]):
        raise ValueError('module ELF/version differs from package')
    return value


def module_ownership(root):
    version = installed_version(root)
    base = root/'var/lib/dkms/rp1-gpclk-dkms'
    if (base/'original_module').exists():
        raise ValueError('DKMS predecessor backup requires owning recovery')
    installed = (root/'lib/modules').resolve()
    seen = set()
    for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
        for path in installed.rglob(name+'.ko*'):
            parts = path.relative_to(installed).parts
            if (len(parts) != 4 or not KERNEL.fullmatch(parts[0]) or
                    parts[1:3] != ('updates', 'dkms') or path.is_symlink()):
                raise ValueError('foreign provider module path')
            identity = (parts[0], name)
            if identity in seen:
                raise ValueError('duplicate compressed provider module preserved')
            seen.add(identity)
            source = base/version/'source'
            if (not source.is_symlink() or source.resolve() !=
                    (root/'usr/src'/(PACKAGE+'-'+version)).resolve()):
                raise ValueError('provider module has no current DKMS source ownership')
            cached = list((base/version/parts[0]).glob('*/module/'+name+'.ko*'))
            if len(cached) != 1 or cached[0].is_symlink() or module_elf(path, version) != module_elf(cached[0], version):
                raise ValueError('foreign or modified provider module preserved')


def native_features():
    import subprocess
    try:
        result = subprocess.run(['/usr/sbin/modinfo', '--version'], capture_output=True,
                                text=True, timeout=5)
    except subprocess.TimeoutExpired as error:
        raise ValueError('native kmod capability query timed out') from error
    if result.returncode:
        raise ValueError('native kmod compression capabilities unavailable')
    return set(result.stdout.split())


def compression_policy(root):
    needed = set()
    for kernel in (root/'lib/modules').glob('*'):
        if not KERNEL.fullmatch(kernel.name):
            continue
        for suffix, feature in (('.gz', '+ZLIB'), ('.xz', '+XZ'), ('.zst', '+ZSTD')):
            if any(kernel.rglob('*.ko'+suffix)):
                needed.add(feature)
        for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
            if any(kernel.rglob(name+'.ko.bz2')):
                raise ValueError('native DKMS does not support bzip2 module lifecycle')
    if needed and not needed <= native_features():
        raise ValueError('native kmod lacks required compression support: '+','.join(sorted(needed)))


def kernel_configuration(kernel):
    config = kernel/'build/.config'
    if not config.exists():
        raise ValueError('kernel header configuration unavailable: '+kernel.name)
    effective = kernel/'build/include/config/auto.conf'
    if effective.exists():
        config = effective
    return regular(config.resolve()).decode()


def check(root=Path('/'), operation='configure'):
    if operation not in ('unpack', 'configure', 'remove'):
        raise ValueError('unknown package operation')
    owned = payload_ownership(root, complete=operation == 'configure')
    registration_ownership(root, owned)
    mode = package_transition(root, owned) if operation == 'unpack' else None
    for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
        if (root/'sys/module'/name).exists():
            raise ValueError('loaded provider blocks package mutation')
    for name in ('dev/rp1-gpclk', 'dev/rp1-route-admin',
                 'run/rp1-gpclk-dkms/route-manager.sock',
                 'etc/rp1-gpclk-dkms/runtime-controller.json',
                 'var/lib/rp1-gpclk-dkms/runtime-admin',
                 'var/lib/rp1-gpclk-dkms/route-transactions',
                 'var/lib/rp1-gpclk-dkms/development',
                 'etc/rp1-gpclk-dkms/development',
                 'etc/rp1-gpclk-dkms/enrollment.json',
                 'var/lib/wsprrypi/rp1-gpclk-dkms-installation.json',
                 'var/lib/rp1-gpclk-dkms/provider-installation.json',
                 'etc/systemd/system/rp1-gpclk-route-manager@.service.d',
                 'etc/systemd/system/sockets.target.wants/rp1-gpclk-route-manager.socket',
                 'opt/rp1-gpclk-dkms-development',
                 'usr/lib/rp1-gpclk-dkms/runtime-overlays',
                 'usr/lib/rp1-gpclk-dkms/runtime-uapi',
                 'usr/lib/rp1-gpclk-dkms/package_preflight.py',
                 'usr/lib/rp1-gpclk-dkms/uapi',
                 'usr/lib/rp1-gpclk-dkms/schema',
                 'etc/systemd/system/wsprrypi.service.d/90-rp1-route-inhibit.conf',
                 'etc/systemd/system/wsprrypi.service.d/91-rp1-route-idle.conf'):
        path = root/name
        if path.exists() or path.is_symlink():
            raise ValueError('recover through owning workflow before package mutation: '+name)
    if any((root/'usr/lib/rp1-gpclk-dkms').glob('runtime_*.py')):
        raise ValueError('runtime tool residue requires owning removal')
    for path in (root/'sys/firmware/devicetree/base').rglob('compatible'):
        data = path.read_bytes()
        if b'wsprrypi,rp1-gpclk-dkms-v1' in data.split(b'\0'):
            raise ValueError('firmware or foreign RP1 route node blocks package mutation')
    for name in ('boot/firmware/config.txt', 'boot/config.txt'):
        config = root/name
        if present(config) and re.search(r'^\s*(?:include\b|dtoverlay\s*=\s*rp1-gpclk-)',
                                        regular(config).decode(), re.M):
            raise ValueError('configured or included route state requires administrator review')
    module_ownership(root)
    values = framework(root)
    # Overrides also replace removal hooks: check them before native prerm.
    if any((root/'etc/dkms').glob('rp1-gpclk-dkms*.conf')):
        raise ValueError('administrator module override requires separate review')
    compression_policy(root)
    if operation == 'remove':
        return
    if present(root/'etc/dkms/no-autoinstall'):
        raise ValueError('administrator disabled DKMS autoinstall; explicit review required')
    kernels = sorted(p for p in (root/'lib/modules').glob('*') if KERNEL.fullmatch(p.name))
    for kernel in kernels:
        if kernel.is_symlink():
            raise ValueError('unsafe installed kernel directory')
        # DKMS prefers auto.conf; .config alone can miss its signing behavior.
        text = kernel_configuration(kernel)
        if re.search(r'^CONFIG_MODULE_SIG_HASH=', text, re.M):
            canonical = kernel/'build/scripts/sign-file'
            distro = regular((root/'etc/os-release').resolve()).decode()
            if not re.search(r'^ID=(?:"?(?:debian|raspbian)"?)$', distro, re.M):
                raise ValueError('unreviewed native DKMS signing distribution')
            if values.get('sign_file'):
                configured = root/values['sign_file'].lstrip('/')
                if not values['sign_file'].startswith('/') or regular(configured.resolve()) != regular(canonical.resolve()):
                    raise ValueError('noncanonical signing command requires separate review')
            else:
                default = root/('usr/lib/linux-kbuild-'+kernel.name.rsplit('.', 1)[0]+'/scripts/sign-file')
                configured = default if default.exists() else canonical
                if regular(configured.resolve()) != regular(canonical.resolve()):
                    raise ValueError('native signing command differs from target headers')
            if not configured.stat().st_mode & 0o111:
                raise ValueError('native signing command is not executable')
            key = values.get('mok_signing_key', '/var/lib/dkms/mok.key')
            cert = values.get('mok_certificate', '/var/lib/dkms/mok.pub')
            if not key.startswith('/') or not cert.startswith('/'):
                raise ValueError('explicit filesystem signing identity required')
            regular(root/key.lstrip('/'), 0o600)
            certificate = root/cert.lstrip('/')
            regular(certificate)
            if stat.S_IMODE(certificate.stat().st_mode) & ~0o644:
                raise ValueError('unsafe public certificate mode')

    return mode


def incoming_package(path):
    """Read bounded package data without extracting files or executing its code."""
    import subprocess
    import tarfile
    import tempfile
    import time
    data = regular(path)
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as stream:
        source.write(data); source.seek(0)
        process = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', '-'], stdin=source,
                                   stdout=stream, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic()+30
            while process.poll() is None:
                if time.monotonic() >= deadline or stream.seek(0, 2) > 128*1024*1024:
                    raise ValueError('incoming package inspection exceeded time/size bound')
                time.sleep(0.02)
            if process.returncode or stream.seek(0, 2) > 128*1024*1024:
                raise ValueError('cannot inspect bounded incoming package')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        stream.seek(0)
        try:
            with tarfile.open(fileobj=stream, mode='r:') as archive:
                matches = []
                for count, member in enumerate(archive, 1):
                    if count > 20000:
                        raise ValueError('incoming package member count exceeds bound')
                    if member.name.removeprefix('./') == RECEIPT:
                        matches.append(member)
                if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 4*1024*1024:
                    raise ValueError('missing, duplicate or unsafe incoming package identity')
                value = json.loads(archive.extractfile(matches[0]).read())
        except tarfile.TarError as error:
            raise ValueError('invalid incoming package archive') from error
    if not isinstance(value, dict):
        raise ValueError('invalid incoming identity object')
    if (value.get('repository') != REPOSITORY or value.get('lifecycle') != LIFECYCLE or
            (value.get('productVersion'), value.get('debianVersion')) != (VERSION, DEBIAN)):
        raise ValueError('candidate package differs from reviewed preflight source')
    return value


if __name__ == '__main__':
    try:
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('operation', choices=('configure', 'remove', 'unpack', 'installed'))
        parser.add_argument('--package', type=Path)
        args = parser.parse_args()
        if args.operation == 'unpack' and INCOMING is None:
            if args.package is None:
                raise ValueError('unpack preflight requires --package VERIFIED_CANDIDATE.deb')
            INCOMING = incoming_package(args.package)
        elif args.package is not None:
            raise ValueError('--package applies only to external unpack preflight')
        mode = check(operation='configure' if args.operation == 'installed' else args.operation)
        if args.operation == 'installed':
            for kernel in (Path('/lib/modules')).glob('*'):
                if not KERNEL.fullmatch(kernel.name):
                    continue
                for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
                    if len(list((kernel/'updates/dkms').glob(name+'.ko*'))) != 1:
                        raise ValueError('module missing; native DKMS repair required')
        print(json.dumps({'contract': 'rp1-gpclk-package-preflight-v1',
                          'operation': args.operation, 'status': 'permitted',
                          'routeSelected': False, 'executionAuthorized': False,
                          **({'transition': mode} if mode else {})}))
    except (OSError, ValueError, EOFError) as error:
        print(json.dumps({'contract': 'rp1-gpclk-package-preflight-v1',
                          'operation': sys.argv[1] if len(sys.argv) > 1 else None,
                          'status': 'refused', 'error': str(error)[:4096],
                          'executionAuthorized': False}), file=sys.stderr)
        raise SystemExit(1)
