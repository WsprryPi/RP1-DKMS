#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Opt-in clock-disabled administration. Installation is a separate gate.

CLI paths and subprocesses are fixed. An installed root-owned exact-artifact
binding is mandatory. This is cooperative service inhibition, not root isolation.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import selectors
import time
import struct
import subprocess
import sys
import tempfile
import uuid
from runtime_binding import validate as validate_binding

STATE = Path('/var/lib/rp1-gpclk-dkms/runtime-admin')
BINDING = Path('/etc/rp1-gpclk-dkms/runtime-controller.json')
ENDPOINT = '/dev/rp1-route-admin'
UNIT_DIR = Path('/etc/systemd/system')
ROUTE_MANAGER_TEMPLATE = 'rp1-gpclk-route-manager@.service'
ROUTE_MANAGER_TEMPLATE_PROBE = 'rp1-gpclk-route-manager@runtime-inspect.service'
FORMAT = struct.Struct('=IIIIQQiiIIQQ')
IOCTL = 0xc040b801
STATUS, APPLY, REMOVE = 0, 1, 2
FAULT, CONSUMER, PINNED = 1, 2, 4


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, limit=1024*1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted file: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('file limit')
        return data
    finally:
        os.close(fd)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted directory')
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_directory(path):
    # Validate every ancestor; never follow a caller-controlled state symlink.
    current = Path('/')
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if current == Path('/lib') and stat.S_ISLNK(info.st_mode):
            if info.st_uid != 0 or os.readlink(current) not in ('usr/lib', '/usr/lib'):
                raise ValueError('untrusted system library alias')
            current = Path('/usr/lib')
            safe_directory(current)
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted directory: ' + str(current))


def run(argv):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                                     'LC_ALL': 'C', 'SYSTEMD_PAGER': 'cat'})
    output = bytearray()
    deadline = time.monotonic() + 15
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError('command timeout; kernel effects may still be pending')
                chunk = os.read(process.stdout.fileno(), min(4096, 65537-len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > 65536:
                    raise ValueError('command output limit')
        code = process.wait(timeout=max(0.001, deadline-time.monotonic()))
        if code:
            raise ValueError('fixed command failed: ' + argv[0] + ' exit=' + str(code) + ': ' + output.decode('utf-8', errors='replace')[-2048:].strip())
        return output.decode('utf-8').strip()
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass  # Never turn a userspace timeout into a kernel completion claim.
        process.stdout.close()


def systemd_unit(name, include_main_pid=False):
    """Observe fixed unit properties without relying on output order."""
    observed = (ROUTE_MANAGER_TEMPLATE_PROBE
                if name == ROUTE_MANAGER_TEMPLATE else name)
    properties = ['LoadState', 'ActiveState', 'UnitFileState', 'FragmentPath']
    if include_main_pid:
        properties.append('MainPID')
    text = run(('/usr/bin/systemctl', 'show', observed,
        '--property=' + ','.join(properties)))
    values = {}
    for line in text.splitlines():
        if '=' not in line:
            raise ValueError('service observation schema: ' + name)
        key, value = line.split('=', 1)
        if key in values:
            raise ValueError('duplicate service observation: ' + name)
        values[key] = value
    if set(values) != set(properties):
        raise ValueError('service observation schema: ' + name)
    result = {'load': values['LoadState'], 'active': values['ActiveState'],
        'enabled': values['UnitFileState'], 'fragment': values['FragmentPath']}
    if include_main_pid:
        result['MainPID'] = values['MainPID']
    return result


class Linux:
    def __init__(self, wait_for_lock=False, allow_activation_query=False):
        self.wait_for_lock = wait_for_lock
        self.allow_activation_query = allow_activation_query
        self.lock = self.fd = None
        try:
            self.initialize()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        for name in ('fd', 'lock'):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def initialize(self):
        if os.geteuid() != 0:
            raise ValueError('root required')
        safe_directory(STATE)
        self.lock = os.open(STATE / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(self.lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('lock ownership')
        deadline = time.monotonic() + (15 if self.wait_for_lock else 0)
        while True:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        if (STATE / 'deployment-pending.json').exists():
            raise ValueError('unfinished deployment; recover before route administration')
        safe_directory(BINDING.parent)
        raw = read_regular(BINDING)
        self.binding = strict_json(raw)
        self.binding_hash = digest(raw)
        validate_binding(self.binding)
        if self.binding['kernel'] != os.uname().release:
            raise ValueError('binding kernel differs from running kernel')
        activation = self.read_record('activation.json')
        if activation is not None:
            from runtime_activation import validate_journal
            validate_journal(activation)
            if (activation['phase'] != 'complete-neutral' and
                    not (self.allow_activation_query and
                         activation['phase'] == 'manager-query-intent')):
                raise ValueError('neutral activation requires completion or recovery')
        from runtime_layout import INVENTORY
        expected = set(INVENTORY)
        if not isinstance(self.binding['files'], dict) or set(self.binding['files']) != expected:
            raise ValueError('fixed artifact inventory required')
        for name, sha in self.binding['files'].items():
            safe_directory(Path(name).parent)
            if not isinstance(sha, str) or len(sha) != 64 or digest(read_regular(name, 32*1024*1024)) != sha:
                raise ValueError('artifact mismatch: ' + name)
        for name, sha in self.binding['externalFiles'].items():
            safe_directory(Path(name).parent)
            if digest(read_regular(name, 4*1024*1024)) != sha:
                raise ValueError('external companion mismatch: ' + name)
        for module, record in self.binding['modules'].items():
            name = record['path']
            safe_directory(Path(name).parent)
            if digest(read_regular(name, 32*1024*1024)) != record['installedFileSha256']:
                raise ValueError('DKMS module artifact mismatch: ' + name)
            if run(('/usr/sbin/modinfo', '-F', 'filename', module)) != name:
                raise ValueError('module resolution mismatch')
        if digest(Path(__file__).read_bytes()) != self.binding['files']['/usr/lib/rp1-gpclk-dkms/runtime_controller_admin.py']:
            raise ValueError('executing tool mismatch')
        if run(('/usr/sbin/modinfo', '-F', 'rp1_runtime_controller', 'rp1_gpclk_dkms')) != '1':
            raise ValueError('consumer lacks interlock')
        self.boot = read_regular('/proc/sys/kernel/random/boot_id').decode().strip()
        uuid.UUID(self.boot)
        self.note('rp1_route_controller', 'controllerNoteSha256')
        if Path('/sys/module/rp1_gpclk_dkms').exists():
            self.note('rp1_gpclk_dkms', 'consumerNoteSha256')
            if read_regular('/sys/module/rp1_gpclk_dkms/parameters/output_inhibit').strip() not in (b'N', b'0', b'Y', b'1'):
                raise ValueError('loaded consumer output-inhibit state is unknown')
        self.fd = os.open(ENDPOINT, os.O_RDWR | os.O_NOFOLLOW)
        info = os.fstat(self.fd)
        if not stat.S_ISCHR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('controller endpoint ownership')
        major, minor = read_regular('/sys/class/misc/rp1-route-admin/dev').decode().strip().split(':')
        if info.st_rdev != os.makedev(int(major), int(minor)):
            raise ValueError('controller endpoint identity')

    def note(self, module, key):
        if digest(read_regular(f'/sys/module/{module}/notes/.note.gnu.build-id')) != self.binding[key]:
            raise ValueError('loaded build note mismatch')

    def call(self, operation=STATUS, route=0, before=None):
        before = before or {'session': 0, 'generation': 0}
        data = bytearray(FORMAT.pack(0, operation, route, 0, before['session'],
                                    before['generation'], 0, 0, 0, 0, 0, 0))
        fcntl.ioctl(self.fd, IOCTL, data, True)
        reserved0, op, route, reserved, session, generation, oid, error, active, flags, r1, r2 = FORMAT.unpack(data)
        if reserved0 or op or route or reserved or r1 or r2 or not session or active not in (0, 1, 2) or flags & ~7:
            raise ValueError('controller response schema')
        result = dict(session=session, generation=generation, id=oid, error=error, route=active, flags=flags)
        validate_observation(result)
        if operation and (session != before['session'] or generation != before['generation'] + 1):
            raise ValueError('effect response generation/session mismatch')
        return result

    def inhibit(self):
        from runtime_application import write_owned, unit_file, DROPIN, INHIBIT
        write_owned(unit_file(DROPIN), INHIBIT)
        run(('/usr/bin/systemctl', 'daemon-reload'))
        run(('/usr/bin/systemctl', 'stop', 'wsprrypi.service'))
        self.check_inhibit()

    def check_inhibit(self):
        from runtime_application import unit_file, DROPIN, INHIBIT
        if read_regular(unit_file(DROPIN)) != INHIBIT:
            raise ValueError('persistent inhibit lost')
        if run(('/usr/bin/systemctl', 'show', 'wsprrypi.service', '--property=ActiveState', '--value')) not in ('inactive', 'failed'):
            raise ValueError('application still active')
        if read_regular('/proc/sys/kernel/random/boot_id').decode().strip() != self.boot:
            raise ValueError('boot changed')

    def unload(self):
        self.check_inhibit()
        if Path('/sys/module/rp1_gpclk_dkms').exists():
            self.note('rp1_gpclk_dkms', 'consumerNoteSha256')
            if read_regular('/sys/module/rp1_gpclk_dkms/parameters/output_inhibit').strip() not in (b'N', b'0', b'Y', b'1'):
                raise ValueError('consumer output-inhibit state is unknown')
            run(('/usr/sbin/rmmod', 'rp1_gpclk_dkms'))
        if Path('/sys/module/rp1_gpclk_dkms').exists():
            raise ValueError('consumer remains loaded')

    def load(self):
        self.check_inhibit()
        run(('/usr/sbin/modprobe', 'rp1_gpclk_dkms'))
        self.note('rp1_gpclk_dkms', 'consumerNoteSha256')
        if read_regular('/sys/module/rp1_gpclk_dkms/parameters/output_inhibit').strip() not in (b'N', b'0'):
            raise ValueError('production consumer unexpectedly output-inhibited')

    def inhibited(self):
        try:
            self.check_inhibit()
            return True
        except (ValueError, OSError):
            return False

    def output_snapshot(self):
        from runtime_output import snapshot
        return snapshot()

    def output_resume(self):
        from runtime_application import remove_owned, unit_file, DROPIN, INHIBIT
        self.check_inhibit()
        if self.read_record('application.json'):
            raise ValueError('use restore --execute for the application transaction')
        remove_owned(unit_file(DROPIN), INHIBIT)
        try:
            run(('/usr/bin/systemctl', 'daemon-reload'))
        except BaseException:
            self.inhibit()
            raise

    def read_manager_record(self):
        return self.read_record('manager.json')

    def write_manager_record(self, value):
        self.write_record('manager.json', value)

    def read_journal(self):
        return self.read_record('transaction.json')

    def read_record(self, name):
        try:
            return strict_json(read_regular(STATE / name))
        except FileNotFoundError:
            return None

    def write_journal(self, value):
        self.write_record('transaction.json', value)

    def archive_journal(self, value):
        identity = digest(json.dumps(value, sort_keys=True).encode())
        self.write_record('prior-boot-' + identity + '.json', value)

    def write_record(self, filename, value):
        data = (json.dumps(value, sort_keys=True) + '\n').encode()
        fd, name = tempfile.mkstemp(prefix='journal-', dir=STATE)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, STATE / filename)
            fsync_dir(STATE)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def validate_observation(value):
    if (not isinstance(value, dict) or set(value) != {'session', 'generation', 'id', 'error', 'route', 'flags'} or
            any(type(v) is not int for v in value.values()) or not 0 < value['session'] < 2**64 or
            not 0 <= value['generation'] < 2**64 or not 0 <= value['id'] < 2**31 or
            not -4095 <= value['error'] <= 0 or value['route'] not in (0, 1, 2) or
            not 0 <= value['flags'] <= 7 or
            (value['id'] == 0) != (value['route'] == 0) or
            (value['id'] > 0 and not value['flags'] & PINNED) or
            (value['flags'] & CONSUMER and value['id'] == 0)):
        raise ValueError('invalid controller observation')


def execute(system, route=None, recover=False):
    previous = system.read_journal()
    current = system.call()
    validate_observation(current)
    if previous is not None:
        if (not isinstance(previous, dict) or set(previous) != {'version', 'boot', 'session', 'binding', 'request', 'target', 'phase', 'observation'} or
                type(previous['version']) is not int or previous['version'] != 1 or
                not isinstance(previous['request'], str) or type(previous['target']) is not int or
                previous['binding'] != system.binding_hash or
                previous['target'] not in (1, 2) or previous['phase'] not in
                ('inhibit-intent', 'unload-intent', 'remove-intent', 'apply-intent', 'load-intent', 'complete-inhibited', 'recovered-inhibited')):
            raise ValueError('journal mismatch; preserve inhibition and investigate')
        uuid.UUID(previous['request'])
        uuid.UUID(previous['boot'])
        observed = previous['observation']
        validate_observation(observed)
        if type(previous['session']) is not int or observed['session'] != previous['session']:
            raise ValueError('journal observation session mismatch')
        if previous['boot'] != system.boot:
            if not recover or any(current[k] for k in ('generation', 'id', 'route', 'error', 'flags')):
                raise ValueError('prior boot recovery requires an empty new controller')
            system.inhibit()
            system.unload()
            if system.call() != current:
                raise ValueError('controller changed during prior boot recovery')
            system.archive_journal(previous)
            record = dict(previous, boot=system.boot, session=current['session'],
                          request=str(uuid.uuid4()), observation=current,
                          phase='recovered-inhibited')
            system.write_journal(record)
            return current
        if previous['session'] != current['session']:
            raise ValueError('journal session mismatch')
        if observed['session'] != current['session']:
            raise ValueError('journal observation session mismatch')
        delta = current['generation'] - observed['generation']
        if delta not in (0, 1) or (delta == 1 and previous['phase'] not in ('apply-intent', 'remove-intent')):
            raise ValueError('unattributable controller generation')
        if delta == 0 and any(current[k] != observed[k] for k in ('id', 'route', 'error')):
            # Cleanup fault is a recorded consumer outcome, never permission for
            # a successor. Permit only explicit cleanup recovery of that fault.
            if not (recover and current['flags'] & FAULT and current['id'] == observed['id']):
                raise ValueError('controller changed outside the recorded effect')
        if delta == 1 and previous['phase'] == 'apply-intent' and current['id'] > 0 and current['route'] != previous['target']:
            raise ValueError('applied route differs from journal')
        if not recover and previous['phase'] not in ('complete-inhibited', 'recovered-inhibited'):
            raise ValueError('unfinished transaction requires explicit recovery')
    if recover and previous is None:
        raise ValueError('no attributable transaction')
    if not recover and route not in (1, 2):
        raise ValueError('route required')
    if previous is None and (current['id'] or current['flags']):
        raise ValueError('existing controller state has no attributable journal')
    if current['flags'] & FAULT and not recover:
        raise ValueError('controller fault; no successor permitted')
    record = previous.copy() if recover else dict(version=1, boot=system.boot,
        session=current['session'], binding=system.binding_hash, request=str(uuid.uuid4()), target=route,
        phase='inhibit-intent', observation=current)

    def journal(phase):
        record.update(phase=phase, observation=current)
        system.write_journal(record)

    journal('inhibit-intent')
    system.inhibit()
    journal('unload-intent')
    system.unload()
    before_unload = current
    current = system.call()
    if (any(current[k] != before_unload[k] for k in ('session', 'generation', 'id', 'route')) or
            current['flags'] & CONSUMER):
        raise ValueError('consumer exclusion/session lost')
    if current['id'] > 0:
        journal('remove-intent')
        system.check_inhibit()
        current = system.call(REMOVE, before=current)
        if current['error'] or current['id']:
            raise ValueError('overlay removal failed; preserve controller ID/error and inhibition')
    if current['flags'] & FAULT:
        raise ValueError('latched controller fault; no successor or inhibit release')
    if recover:
        journal('recovered-inhibited')
        return current
    journal('apply-intent')
    system.check_inhibit()
    current = system.call(APPLY, route, current)
    if current['error'] or current['flags'] & FAULT or current['route'] != route or current['id'] <= 0:
        raise ValueError('overlay apply failed; explicit recovery required')
    journal('load-intent')
    system.load()
    before_load = current
    current = system.call()
    if (any(current[k] != before_load[k] for k in ('session', 'generation', 'id', 'route')) or
            current['flags'] & FAULT or not current['flags'] & CONSUMER):
        raise ValueError('consumer binding not established')
    journal('complete-inhibited')
    return current


def main():
    if sys.argv[1:] not in (['switch', 'gpio4'], ['switch', 'gpio20'], ['recover'], ['status']):
        raise SystemExit('usage: runtime_controller_admin.py switch gpio4|gpio20 | recover | status')
    system = Linux()
    if sys.argv[1] == 'status':
        print(json.dumps({'state': system.call(), 'qualification': False}))
        return
    from runtime_application import mutation_lock
    with mutation_lock():
        result = execute(system, route={'gpio4': 1, 'gpio20': 2}.get(sys.argv[-1]),
                         recover=sys.argv[1] == 'recover')
    print(json.dumps({'state': result, 'applicationInhibited': True, 'qualification': False}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('STOP: ' + str(error) + '; do not release inhibition or assume an effect stopped')
