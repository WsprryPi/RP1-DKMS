#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reviewed, journaled runtime-profile filesystem deployment. Never loads modules."""
import argparse
import base64
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import package_preflight
import runtime_controller_admin as admin
from runtime_binding import validate as validate_binding
from runtime_layout import INVENTORY

MAX_FILE_BYTES = 32*1024*1024
MAX_JOURNAL_BYTES = 32*1024*1024
BINDING = str(admin.BINDING)
LAST_DEPLOYMENT = str(admin.STATE / 'last-deployment.json')
JOURNALS = {str(admin.STATE / name) for name in
            ('transaction.json', 'manager.json', 'application.json', 'activation.json')}
DESTINATIONS = set(INVENTORY) | {BINDING} | JOURNALS
RUNTIME_LIBRARY = Path('/usr/lib/rp1-gpclk-dkms')


def provision_state():
    """Create only the fixed runtime state hierarchy for an approved mutation."""
    parent = admin.STATE.parent
    admin.safe_directory(parent.parent)
    for path, mode in ((parent, 0o755), (admin.STATE, 0o700)):
        try:
            path.mkdir(mode=mode)
            admin.fsync_dir(path.parent)
        except FileExistsError:
            pass
        admin.safe_directory(path)


def existing_deployment_state(files):
    journal = files.read(str(admin.STATE / 'transaction.json'))
    if journal is not None:
        record = admin.strict_json(journal)
        if (record.get('phase') != 'recovered-inhibited' or
                record.get('observation', {}).get('id') != 0):
            raise ValueError('runtime journal is not recovered to no route; preserve and investigate')
    return files.read(str(admin.STATE / 'deployment-pending.json'))


def removal_plan(files):
    """Return the exact retained deployment for a reviewed inverse mutation."""
    pending = existing_deployment_state(files)
    raw = files.read(LAST_DEPLOYMENT)
    if (pending is not None and raw is not None and
            admin.strict_json(pending) != admin.strict_json(raw)):
        raise ValueError('pending deployment differs from retained inverse')
    if pending is not None:
        raw = pending
    if raw is None:
        raise ValueError('no retained deployment to remove')
    value = admin.strict_json(raw)
    journal_bytes(value)
    if value['previousDeployment'] is not None:
        raise ValueError('stacked deployment requires its owning removal workflow')
    return value


def encode(data):
    return None if data is None else base64.b64encode(data).decode('ascii')


def decode(data):
    return None if data is None else base64.b64decode(data, validate=True)


def bundle_read(path, limit=MAX_FILE_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('bundle member must be a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('bundle member exceeds bound')
        return data
    finally:
        os.close(fd)


def bundle_member(directory_fd, name, limit=MAX_FILE_BYTES):
    if '/' in name or name in ('', '.', '..'):
        raise ValueError('invalid fixed bundle member')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                 dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('bundle member must be a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('bundle member exceeds bound')
        return data
    finally:
        os.close(fd)


def payloads(directory):
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise ValueError('bundle directory is writable by group or other')
        raw = bundle_member(directory_fd, 'binding.json', 1024*1024)
        binding = admin.strict_json(raw)
        validate_binding(binding)
        result = {}
        for destination in sorted(INVENTORY):
            data = bundle_member(directory_fd, admin.digest(destination.encode())+'.bin')
            if len(data) > 32*1024*1024 or admin.digest(data) != binding['files'][destination]:
                raise ValueError('bundle hash mismatch')
            result[destination] = data
        result[BINDING] = raw
        result.update({path: None for path in JOURNALS})
        return result
    finally:
        os.close(directory_fd)


class Files:
    """Production paths only. Tests substitute this adapter, not environment paths."""
    def packaged_baseline(self, root=Path('/')):
        """Authenticate passive package files that inverse deployment restores.

        This is observational package ownership, never permission to mutate it.
        Source-development has no package baseline. A present database must
        describe the exact current package and its complete unchanged payload.
        """
        listing = root/'var/lib/dpkg/info/rp1-gpclk-dkms.list'
        if not listing.exists() and not listing.is_symlink():
            return {}
        status = admin.run(('/usr/bin/dpkg-query', '-W', '-f=${Status}\n${Version}',
                            'rp1-gpclk-dkms'))
        if status != 'install ok installed\n0.0.1-1':
            raise ValueError('passive package baseline requires exact installed 0.0.1-1')
        owned = package_preflight.payload_ownership(root, complete=True)
        names = ('usr/lib/systemd/system/rp1-gpclk-route-manager.socket',
                 'usr/lib/systemd/system/rp1-gpclk-route-manager@.service',
                 'usr/lib/rp1-gpclk-dkms/overlays/rp1-gpclk-gpio4.dtbo',
                 'usr/lib/rp1-gpclk-dkms/overlays/rp1-gpclk-gpio20.dtbo')
        result = {}
        for name in names:
            path = root/name
            if path not in owned:
                raise ValueError('passive package baseline lacks ownership: '+str(path))
            admin.safe_directory(path.parent)
            result[str(path)] = admin.digest(admin.read_regular(path, MAX_FILE_BYTES))
        library = root/'usr/lib/rp1-gpclk-dkms'
        overlays = library/'overlays'
        expected = {overlays, overlays/'rp1-gpclk-gpio4.dtbo', overlays/'rp1-gpclk-gpio20.dtbo'}
        if set(library.rglob('*')) != expected:
            raise ValueError('unexpected residue beside passive package overlays')
        return result

    def read(self, path):
        try:
            admin.safe_directory(Path(path).parent)
            if path in INVENTORY or path == BINDING:
                if stat.S_IMODE(Path(path).lstat().st_mode) != 0o644:
                    raise ValueError('destination mode is not 0644; preserve and review: '+path)
            return admin.read_regular(path, MAX_JOURNAL_BYTES if Path(path).is_relative_to(admin.STATE) else MAX_FILE_BYTES)
        except FileNotFoundError:
            return None

    def write(self, path, data):
        path = Path(path)
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        admin.safe_directory(parent)
        for directory in reversed(missing):
            directory.mkdir(mode=0o755)
            admin.fsync_dir(directory.parent)
        admin.safe_directory(path.parent)
        if data is None:
            path.unlink(missing_ok=True)
            admin.fsync_dir(path.parent)
            return
        fd, temporary = tempfile.mkstemp(prefix='.runtime-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o600 if path.is_relative_to(admin.STATE) else 0o644)
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            admin.fsync_dir(path.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def preflight(self):
        # No automatic module unload or boot edits. The operator must separately
        # establish a neutral deployment window; a loaded module is a hard stop.
        for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
            if Path('/sys/module', name).exists():
                raise ValueError('loaded module; separately authorize neutral migration first')

    def verify_external(self, binding):
        validate_binding(binding)
        for path, expected in binding['externalFiles'].items():
            admin.safe_directory(Path(path).parent)
            if admin.digest(admin.read_regular(path, 4*1024*1024)) != expected:
                raise ValueError('external prerequisite mismatch: '+path)
        for module, record in binding['modules'].items():
            path = record['path']
            admin.safe_directory(Path(path).parent)
            if admin.digest(admin.read_regular(path, MAX_FILE_BYTES)) != record['installedFileSha256']:
                raise ValueError('external DKMS module mismatch: '+path)
            if admin.run(('/usr/sbin/modinfo', '-F', 'filename', module)) != path:
                raise ValueError('external DKMS module resolution mismatch: '+module)

    def quiesce(self):
        self.preflight()
        shell = admin.Linux.__new__(admin.Linux)
        shell.boot = admin.read_regular('/proc/sys/kernel/random/boot_id').decode().strip()
        shell.inhibit()
        self.preflight()

    def application_state(self):
        import runtime_application as application
        try:
            from runtime_activation import validate_journal
            activation = admin.strict_json(admin.read_regular(
                admin.STATE / 'activation.json', MAX_JOURNAL_BYTES))
            validate_journal(activation)
            if activation['phase'] == 'recovered-inhibited':
                if admin.read_regular(application.unit_file(application.DROPIN)) != application.INHIBIT:
                    raise ValueError('recovered activation inhibition is absent')
                return activation['plan']['application']
        except FileNotFoundError:
            pass
        return application.neutral_capture()

    def verify_application(self, expected):
        if self.application_state() != expected:
            raise ValueError('application state changed since deployment review')

    def refresh(self):
        admin.run(('/usr/sbin/depmod', '-a', os.uname().release))
        admin.run(('/usr/bin/systemctl', 'daemon-reload'))

    def preflight_removal(self):
        self.preflight()
        for path in ('/dev/rp1-route-admin', '/dev/rp1-gpclk',
                     '/run/rp1-gpclk-dkms/route-manager.sock'):
            if Path(path).exists():
                raise ValueError('active runtime endpoint blocks deployment removal: '+path)
        units = {
            'rp1-gpclk-route-manager.socket':
                '/usr/lib/systemd/system/rp1-gpclk-route-manager.socket',
            admin.ROUTE_MANAGER_TEMPLATE:
                '/usr/lib/systemd/system/rp1-gpclk-route-manager@.service',
        }
        for unit, fragment in units.items():
            observed = admin.systemd_unit(unit)
            # Inverse deployment may already have removed these exact files
            # before interruption. Missing units are admissible only with a
            # retained, schema-valid removal plan owning their absence.
            if (observed['load'] == 'not-found' and
                    observed['active'] == 'inactive' and
                    observed['enabled'] in ('not-found', '') and not observed['fragment']):
                retained = removal_plan(self)
                journal_bytes(retained)
                if (decode(retained['files'][fragment]['before']) is None and
                        self.read(fragment) is None):
                    continue
            if (observed['load'] != 'loaded' or
                    observed['active'] not in ('inactive', 'failed') or
                    observed['enabled'] not in ('disabled', 'static') or
                    observed['fragment'] != fragment):
                raise ValueError('active or substituted runtime unit blocks deployment removal: '+unit)

    def restore_application(self, capture):
        import runtime_application as application
        return application.neutral_restore(capture)

    def prune_removed_directories(self, expected_uid=0):
        locks = []
        for name in ('lock', 'application-lock'):
            lock = admin.STATE / name
            try:
                info = lock.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or
                        stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise ValueError(name + ' identity changed during removal')
                locks.append((lock, info.st_dev, info.st_ino))
            except FileNotFoundError:
                pass
        for lock, device, inode in locks:
            current = lock.lstat()
            if (current.st_dev, current.st_ino) != (device, inode):
                raise ValueError(lock.name + ' changed before removal')
            lock.unlink()
            admin.fsync_dir(admin.STATE)
        archives = []
        try:
            admin.safe_directory(admin.STATE)
            for path in admin.STATE.glob('prior-activation-*.json'):
                match = re.fullmatch(r'prior-activation-([0-9a-f]{64})\.json',
                                     path.name)
                info = path.lstat()
                if (match is None or not stat.S_ISREG(info.st_mode) or
                        info.st_uid != expected_uid or
                        stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise ValueError('unexpected prior activation archive: '+str(path))
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    opened = os.fstat(fd)
                    if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or
                            not stat.S_ISREG(opened.st_mode) or
                            opened.st_uid != expected_uid or
                            stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_nlink != 1):
                        raise ValueError('prior activation archive changed during validation: '+str(path))
                    with os.fdopen(fd, 'rb', closefd=False) as stream:
                        data = stream.read(MAX_JOURNAL_BYTES + 1)
                finally:
                    os.close(fd)
                if len(data) > MAX_JOURNAL_BYTES:
                    raise ValueError('prior activation archive exceeds read bound: '+str(path))
                if (not data.endswith(b'\n') or data.endswith(b'\n\n') or
                        admin.digest(data[:-1]) != match.group(1)):
                    raise ValueError('prior activation archive identity differs: '+str(path))
                archives.append((path, info.st_dev, info.st_ino))
            for path, device, inode in archives:
                current = path.lstat()
                if (current.st_dev, current.st_ino) != (device, inode):
                    raise ValueError('prior activation archive changed before removal: '+str(path))
                path.unlink()
                admin.fsync_dir(admin.STATE)
        except FileNotFoundError:
            pass
        cache = RUNTIME_LIBRARY / '__pycache__'
        try:
            admin.safe_directory(cache)
            for path in cache.iterdir():
                info = path.lstat()
                if (not re.fullmatch(r'(?:runtime_[A-Za-z0-9_]+|package_preflight)\.cpython-[0-9]+\.pyc',
                                     path.name) or
                        not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or
                        stat.S_IMODE(info.st_mode) & 0o022 or info.st_nlink != 1):
                    raise ValueError('unexpected runtime bytecode residue: '+str(path))
                path.unlink()
                admin.fsync_dir(cache)
            cache.rmdir()
            admin.fsync_dir(cache.parent)
        except FileNotFoundError:
            pass
        for path in (admin.STATE, RUNTIME_LIBRARY/'schema',
                     RUNTIME_LIBRARY/'runtime-uapi',
                     RUNTIME_LIBRARY/'runtime-overlays',
                     RUNTIME_LIBRARY):
            baseline = self.packaged_baseline() if path == RUNTIME_LIBRARY else {}
            if baseline:
                overlays = path/'overlays'
                expected = {overlays, overlays/'rp1-gpclk-gpio4.dtbo',
                            overlays/'rp1-gpclk-gpio20.dtbo'}
                admin.safe_directory(path)
                admin.safe_directory(overlays)
                if set(path.rglob('*')) != expected:
                    raise ValueError('unexpected residue beside passive package overlays')
                for member in expected - {overlays}:
                    if admin.digest(admin.read_regular(member, MAX_FILE_BYTES)) != baseline.get(str(member)):
                        raise ValueError('passive package overlay changed during removal')
                continue
            try:
                path.rmdir()
                admin.fsync_dir(path.parent)
            except FileNotFoundError:
                pass
            except OSError as error:
                raise ValueError('unexpected residue blocks directory removal: '+str(path)) from error


def plan(files, values):
    if set(values) != DESTINATIONS:
        raise ValueError('fixed deployment inventory required')
    application = files.application_state()
    return {'version': 1, 'application': application,
        'previousDeployment': encode(files.read(LAST_DEPLOYMENT)),
        'files': {path: {'before': encode(files.read(path)),
        'after': encode(values[path])} for path in sorted(values)}}


def plan_hash(value):
    return admin.digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def journal_bytes(value):
    if (not isinstance(value, dict) or
            set(value) != {'version', 'application', 'previousDeployment', 'files'} or
            type(value['version']) is not int or value['version'] != 1 or
            not isinstance(value['files'], dict) or set(value['files']) != DESTINATIONS):
        raise ValueError('fixed deployment plan schema required')
    import runtime_application as application
    application.validate_neutral_capture(value['application'])
    decode(value['previousDeployment'])
    serialized = (json.dumps(value, sort_keys=True)+'\n').encode()
    if len(serialized) > MAX_JOURNAL_BYTES:
        raise ValueError('deployment journal exceeds recovery read bound')
    for record in value['files'].values():
        if not isinstance(record, dict) or set(record) != {'before', 'after'}:
            raise ValueError('deployment file record schema')
        for data in record.values():
            if data is not None and not isinstance(data, str):
                raise ValueError('deployment bytes must be base64 or null')
            decode(data)
    return serialized


def apply(files, value, approved, recover=False, retain_barrier=False):
    encoded = journal_bytes(value)
    if plan_hash(value) != approved or value.get('version') != 1 or set(value['files']) != DESTINATIONS:
        raise ValueError('reviewed plan digest/inventory required')
    # Check ALL ownership before any restoration; preserve foreign changes.
    for path, record in value['files'].items():
        current = files.read(path)
        allowed = (decode(record['before']), decode(record['after'])) if recover else (decode(record['before']),)
        if current not in allowed:
            raise ValueError('destination changed since review: '+path)
    binding = validate_binding(admin.strict_json(decode(value['files'][BINDING]['after'])))
    current_deployment = files.read(LAST_DEPLOYMENT)
    allowed_deployments = ((decode(value['previousDeployment']), encoded)
                           if recover else (decode(value['previousDeployment']),))
    if current_deployment not in allowed_deployments:
        raise ValueError('last deployment record changed since review')
    files.verify_external(binding)
    if not recover:
        files.verify_application(value['application'])
    pending = str(admin.STATE / 'deployment-pending.json')
    existing = files.read(pending)
    if existing is not None and admin.strict_json(existing) != value:
        raise ValueError('another deployment requires recovery')
    files.preflight()
    files.write(pending, encoded)
    files.quiesce()
    files.verify_external(binding)
    # Quiescence can take time. Revalidate the complete reviewed baseline after
    # it and before the first publication; a changed byte retains the pending
    # barrier and requires explicit recovery/investigation.
    for path, record in value['files'].items():
        current = files.read(path)
        allowed = (decode(record['before']), decode(record['after'])) if recover else (decode(record['before']),)
        if current not in allowed:
            raise ValueError('destination changed during quiescence: '+path)
    # Binding and profile are last. The persistent barrier covers all partial
    # updates and all refresh failures, including after every file was written.
    paths = sorted(value['files'], key=lambda p: (p == BINDING or p.endswith('.conf'), p))
    for path in paths:
        files.write(path, decode(value['files'][path]['before' if recover else 'after']))
    files.refresh()
    files.write(LAST_DEPLOYMENT,
                decode(value['previousDeployment']) if recover else encoded)
    if not retain_barrier:
        files.write(pending, None)


def remove(files, value, approved):
    if plan_hash(value) != approved or removal_plan(files) != value:
        raise ValueError('reviewed deployment removal plan changed before mutation')
    files.preflight_removal()
    apply(files, value, approved, recover=True, retain_barrier=True)
    files.restore_application(value['application'])
    files.write(str(admin.STATE / 'deployment-pending.json'), None)


@contextlib.contextmanager
def mutation_lock():
    if os.geteuid() != 0:
        raise ValueError('root required')
    admin.safe_directory(admin.STATE)
    fd = os.open(admin.STATE / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('lock ownership')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'install', 'recover',
                                              'remove-plan', 'remove'))
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    files = Files()
    if args.operation in ('remove-plan', 'remove'):
        value = removal_plan(files)
    elif args.operation == 'recover':
        admin.safe_directory(admin.STATE)
        pending = existing_deployment_state(files)
        if pending is None:
            raise ValueError('no pending deployment')
        value = admin.strict_json(pending)
    else:
        if args.bundle is None:
            raise ValueError('bundle required')
        if existing_deployment_state(files) is not None:
            raise ValueError('pending deployment requires recovery')
        value = plan(files, payloads(args.bundle))
    journal_bytes(value)
    reviewed = plan_hash(value)
    if args.operation in ('plan', 'remove-plan') or not args.plan_sha256:
        print(json.dumps({'planSha256':reviewed, 'destinations':{path:{side:None if data is None else admin.digest(decode(data)) for side,data in record.items()} for path,record in value['files'].items()},
                          'applicationRemainsInhibited':True}, indent=2))
        return
    if args.plan_sha256 != reviewed:
        raise ValueError('reviewed plan digest required')
    if args.operation not in ('recover', 'remove'):
        provision_state()
    with mutation_lock():
        pending = existing_deployment_state(files)
        if args.operation == 'remove':
            value = removal_plan(files)
        elif args.operation == 'recover':
            value = admin.strict_json(pending) if pending is not None else None
        else:
            if pending is not None:
                raise ValueError('pending deployment requires recovery')
            value = plan(files, payloads(args.bundle))
        if value is None or plan_hash(value) != reviewed:
            raise ValueError('reviewed deployment plan changed before mutation')
        if args.operation == 'remove':
            remove(files, value, reviewed)
        else:
            apply(files, value, reviewed, args.operation == 'recover')
    if args.operation == 'remove':
        files.prune_removed_directories()
        print('Exact runtime deployment removed; application state restored.')
    else:
        print('Files deployed/recovered; application remains masked. No module activated.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit('STOP: '+str(error))
