#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Durable application restoration around the existing route transaction.

The workflow lock excludes competing mutations while the controller lock is
released for application startup queries. No output authorization is granted.
"""
import contextlib
import fcntl
import json
import os
import re
from pathlib import Path
import time
import tempfile
import stat
import uuid
import runtime_controller_admin as admin
import runtime_output as output

HELPER = Path('/usr/local/lib/wsprrypi/route_application.py')
DROPIN = '90-rp1-route-inhibit.conf'
IDLE_DROPIN = '91-rp1-route-idle.conf'
INHIBIT = b'# Owned by rp1-gpclk runtime administration\n[Unit]\nConditionPathExists=/dev/null/rp1-route-inhibited\n'
TERMINAL = ('restored', 'stopped', 'administrator-masked')
REMOVAL_TERMINAL = ('neutral-restored', 'neutral-stopped',
                    'neutral-administrator-masked')


def neutral_capture():
    """Capture installer restoration intent without selecting a GPIO route."""
    observed = service()
    if observed['ActiveState'] not in ('active', 'inactive', 'failed'):
        raise ValueError('service is transitioning')
    masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in (
        'masked', 'masked-runtime')
    if observed['LoadState'] not in ('loaded', 'masked'):
        raise ValueError('service is not installed; repair installation before deployment')
    if masked and observed['ActiveState'] == 'active':
        raise ValueError('active administrator-masked service cannot be restored automatically')
    companion = helper('inspect-stopped' if masked else 'inspect')
    if companion.get('transmit') is not False:
        raise ValueError('neutral deployment requires Operation.Transmit=false')
    return {'version': 1, 'wasActive': observed['ActiveState'] == 'active',
            'administratorMasked': masked,
            'service': observed, 'companion': companion}


def validate_neutral_capture(record):
    required = {'version', 'wasActive', 'administratorMasked', 'service', 'companion'}
    if (not isinstance(record, dict) or set(record) != required or
            type(record.get('version')) is not int or record['version'] != 1 or
            type(record.get('wasActive')) is not bool or
            type(record.get('administratorMasked')) is not bool or
            not isinstance(record.get('service'), dict) or
            set(record['service']) != {'LoadState', 'ActiveState', 'UnitFileState', 'MainPID'} or
            not isinstance(record.get('companion'), dict) or
            set(record['companion']) != {'contract', 'route', 'transmit', 'config'} or
            record['companion'].get('contract') != 'wsprrypi-route-application-v1' or
            record['companion'].get('route') not in ('gpio4', 'gpio20') or
            record['companion'].get('config') != '/usr/local/etc/wsprrypi.ini' or
            record['companion'].get('transmit') is not False):
        raise ValueError('invalid neutral application capture')
    service = record['service']
    masked = service['LoadState'] == 'masked' or service['UnitFileState'] in (
        'masked', 'masked-runtime')
    if (service['LoadState'] not in ('loaded', 'masked') or
            service['ActiveState'] not in ('active', 'inactive', 'failed') or
            not isinstance(service['MainPID'], str) or not service['MainPID'].isdigit() or
            record['wasActive'] != (service['ActiveState'] == 'active') or
            record['administratorMasked'] != masked or
            (record['wasActive'] and service['MainPID'] == '0') or
            (not record['wasActive'] and service['MainPID'] != '0')):
        raise ValueError('inconsistent neutral application capture')
    return record


def neutral_restore(record):
    """Release only the owned inhibitor and restore the captured service intent."""
    validate_neutral_capture(record)
    current = neutral_capture()
    if (current['administratorMasked'] != record['administratorMasked'] or
            current['companion'] != record['companion'] or
            (current['wasActive'] and not record['wasActive'])):
        raise ValueError('application intent changed before neutral restoration')
    remove_owned(unit_file(DROPIN), INHIBIT)
    admin.run(('/usr/bin/systemctl', 'daemon-reload'))
    if record['wasActive']:
        admin.run(('/usr/bin/systemctl', 'start', 'wsprrypi.service'))
    observed = service()
    masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in (
        'masked', 'masked-runtime')
    if masked != record['administratorMasked']:
        raise ValueError('administrator service mask changed during neutral restoration')
    if record['wasActive']:
        if observed['ActiveState'] != 'active' or observed['MainPID'] == '0':
            raise ValueError('previously active application did not restart')
        phase = 'restored'
    else:
        if observed['ActiveState'] not in ('inactive', 'failed'):
            raise ValueError('previously stopped application unexpectedly started')
        phase = 'administrator-masked' if record['administratorMasked'] else 'stopped'
    companion = helper('inspect-stopped' if masked else 'inspect')
    if companion.get('transmit') is not False:
        raise ValueError('application is not neutral after restoration')
    return {'phase': phase, 'service': observed, 'companion': companion}


def neutral_inhibit():
    """Re-establish the owned safety barrier after a neutral restoration fault."""
    write_owned(unit_file(DROPIN), INHIBIT)
    admin.run(('/usr/bin/systemctl', 'daemon-reload'))
    admin.run(('/usr/bin/systemctl', 'stop', 'wsprrypi.service'))
    observed = service()
    if observed['ActiveState'] not in ('inactive', 'failed'):
        raise ValueError('application still active after neutral inhibition')


def validate_journal(record):
    """Validate one already-read application restoration journal."""
    required = {'version', 'boot', 'binding', 'requestId', 'fingerprint', 'route',
                'token', 'wasActive', 'administratorMasked', 'phase', 'controller',
                'ready', 'previousIdle'}
    if (not isinstance(record, dict) or not required <= set(record) or
            set(record)-required-{'operation', 'error', 'inhibitionError', 'routeError'} or
            type(record['version']) is not int or record['version'] != 1 or
            type(record['wasActive']) is not bool or type(record['administratorMasked']) is not bool or
            record['route'] not in ('gpio4', 'gpio20') or
            record['phase'] not in (*TERMINAL, *REMOVAL_TERMINAL, 'captured',
                                   'configure-intent', 'start-intent', 'route-failed',
                                   'restoration-failed', 'route-recovered',
                                   'neutral-start-intent', 'neutral-restoration-failed')):
        raise ValueError('invalid application journal; preserve service state')
    if ('operation' in record and record['operation'] not in ('switch', 'remove')):
        raise ValueError('invalid application operation; preserve service state')
    for name in ('token', 'boot', 'previousIdle'):
        value = record[name]
        if name == 'previousIdle' and value is None:
            continue
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError('invalid application journal UUID')
    for name in ('binding', 'fingerprint'):
        if not isinstance(record[name], str) or not re.fullmatch('[0-9a-f]{64}', record[name]):
            raise ValueError('invalid application journal identity')
    if not isinstance(record['requestId'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{7,63}', record['requestId']):
        raise ValueError('invalid application request identity')
    if record['controller'] is not None:
        admin.validate_observation(record['controller'])
    ready = record['ready']
    if ready is not None and (not isinstance(ready, dict) or set(ready) != {'pid', 'route'} or
            type(ready['pid']) is not int or ready['pid'] <= 0 or ready['route'] != record['route']):
        raise ValueError('invalid application readiness journal')
    return record


def load(system):
    record = system.read_record('application.json')
    return None if record is None else validate_journal(record)


def unit_file(name):
    return admin.UNIT_DIR / 'wsprrypi.service.d' / name


def write_owned(path, data):
    admin.safe_directory(path.parent.parent)
    path.parent.mkdir(mode=0o755, exist_ok=True)
    admin.safe_directory(path.parent)
    try:
        if admin.read_regular(path) != data:
            raise ValueError('foreign restoration drop-in: '+str(path))
        return
    except FileNotFoundError:
        pass
    fd, temporary = tempfile.mkstemp(prefix='.route-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish complete bytes exclusively: never replace an administrator file.
        os.link(temporary, path)
        admin.fsync_dir(path.parent)
    finally:
        os.unlink(temporary)



def remove_owned(path, data):
    try:
        admin.safe_directory(path.parent)
        if admin.read_regular(path) != data:
            raise ValueError('foreign restoration drop-in: '+str(path))
    except FileNotFoundError:
        return
    path.unlink()
    admin.fsync_dir(path.parent)


def idle_bytes(record):
    return ('# Owned by rp1-gpclk runtime administration\n[Service]\n'
            'Environment=WSPRRYPI_ROUTE_RESTORE_IDLE='+record['token']+'\n').encode()


def remove_idle(record):
    try:
        installed = admin.read_regular(unit_file(IDLE_DROPIN))
    except FileNotFoundError:
        return
    owners = [idle_bytes(record)]
    if record.get('previousIdle'):
        owners.append(idle_bytes(dict(record, token=record['previousIdle'])))
    if installed not in owners:
        raise ValueError('foreign idle override; preserve it')
    remove_owned(unit_file(IDLE_DROPIN), installed)


def service():
    text = admin.run(('/usr/bin/systemctl', 'show', 'wsprrypi.service',
        '--property=LoadState,ActiveState,UnitFileState,MainPID'))
    result = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    if set(result) != {'LoadState', 'ActiveState', 'UnitFileState', 'MainPID'}:
        raise ValueError('incomplete service observation')
    return result


def helper(*args):
    admin.safe_directory(HELPER.parent)
    admin.read_regular(HELPER)
    value = admin.strict_json(admin.run(('/usr/bin/python3', str(HELPER), *args)))
    if value.get('contract') != 'wsprrypi-route-application-v1':
        raise ValueError('application companion contract mismatch')
    return value


@contextlib.contextmanager
def mutation_lock():
    admin.safe_directory(admin.STATE)
    fd = os.open(admin.STATE/'application-lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode & 0o077:
            raise ValueError('application lock ownership')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def capture(system, request):
    previous = load(system)
    if previous and previous.get('phase') not in (*TERMINAL, *REMOVAL_TERMINAL,
                                                   'route-recovered'):
        raise ValueError('application restoration pending; use restore --execute')
    observed = service()
    if observed['ActiveState'] not in ('active', 'inactive', 'failed'):
        raise ValueError('service is transitioning')
    masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in ('masked', 'masked-runtime')
    if observed['LoadState'] not in ('loaded', 'masked'):
        raise ValueError('service is not installed; repair installation before switching')
    if masked and observed['ActiveState'] == 'active':
        raise ValueError('active administrator-masked service cannot be restored automatically')
    helper('inspect-stopped' if masked else 'inspect')
    for name in (DROPIN, IDLE_DROPIN):
        if unit_file(name).exists() or unit_file(name).is_symlink():
            if name == DROPIN and (previous is None or previous.get('phase') == 'route-recovered') and admin.read_regular(unit_file(name)) == INHIBIT:
                continue
            if name == IDLE_DROPIN and previous and previous.get('phase') in TERMINAL and admin.read_regular(unit_file(name)) == idle_bytes(previous):
                continue
            raise ValueError('existing workflow inhibition requires explicit recovery')
    was_active = observed['ActiveState'] == 'active'
    if previous and previous.get('phase') == 'route-recovered' and previous['boot'] == system.boot:
        was_active = previous['wasActive']
    record = dict(version=1, boot=system.boot, binding=system.binding_hash,
        requestId=request['requestId'], fingerprint=admin.digest(json.dumps(request, sort_keys=True).encode()), route=request['route'], token=str(uuid.uuid4()),
        operation=request['operation'],
        wasActive=was_active, administratorMasked=masked,
        phase='captured', controller=None, ready=None,
        previousIdle=previous['token'] if previous and previous.get('phase') in TERMINAL else None)
    system.write_record('application.json', record)
    return record


def save(system, record, phase):
    record['phase'] = phase
    system.write_record('application.json', record)


def prepare(system, record, state):
    record['ready'] = None
    record['controller'] = state
    save(system, record, 'configure-intent')
    output.ready(system, state, {'gpio4':1, 'gpio20':2}[record['route']])
    configured = helper('configure', record['route'])
    if configured.get('route') != record['route'] or configured.get('transmit') is not False:
        raise ValueError('application configuration did not converge')
    save(system, record, 'start-intent')
    if record.get('previousIdle'):
        old = dict(record, token=record['previousIdle'])
        try:
            installed = admin.read_regular(unit_file(IDLE_DROPIN))
        except FileNotFoundError:
            installed = None
        if installed == idle_bytes(old):
            remove_owned(unit_file(IDLE_DROPIN), idle_bytes(old))
    write_owned(unit_file(IDLE_DROPIN), idle_bytes(record))
    remove_owned(unit_file(DROPIN), INHIBIT)
    admin.run(('/usr/bin/systemctl', 'daemon-reload'))


def finish(factory, record):
    # Called after closing the controller lock. The systemd manager owns this
    # process independently of the requesting WsprryPi service/socket client.
    if record['wasActive']:
        admin.run(('/usr/bin/systemctl', 'start', 'wsprrypi.service'))
        deadline = time.monotonic()+30
        while True:
            observed = service()
            with factory() as system:
                current = load(system)
                if current['token'] != record['token'] or current['boot'] != system.boot:
                    raise ValueError('restoration identity changed')
                ready = current.get('ready')
                if ready and str(ready['pid']) == observed['MainPID'] and observed['ActiveState'] == 'active':
                    output.ready(system, system.call(), {'gpio4':1, 'gpio20':2}[record['route']])
                    record = current
                    break
            if time.monotonic() >= deadline or observed['ActiveState'] == 'failed':
                raise ValueError('application did not acknowledge idle readiness; use restore --execute')
            time.sleep(0.1)
    with factory() as system:
        if system.boot != record['boot'] or system.binding_hash != record['binding'] or system.call() != record['controller']:
            raise ValueError('route identity changed during restoration')
        observed = service()
        if record['wasActive']:
            if observed['ActiveState'] != 'active' or str(record['ready']['pid']) != observed['MainPID']:
                raise ValueError('acknowledged application process is no longer active')
        elif observed['ActiveState'] not in ('inactive', 'failed'):
            raise ValueError('application unexpectedly started during a stopped-service switch')
        masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in ('masked', 'masked-runtime')
        if masked != record['administratorMasked']:
            raise ValueError('administrator service mask changed during restoration')
        # Keep idle startup for stopped/masked services until their first startup
        # acknowledgement. Otherwise Always could transmit on that first start.
        if record['wasActive']:
            remove_owned(unit_file(IDLE_DROPIN), idle_bytes(record))
            admin.run(('/usr/bin/systemctl', 'daemon-reload'))
        phase = 'restored' if record['wasActive'] else ('administrator-masked' if record['administratorMasked'] else 'stopped')
        save(system, record, phase)
        return record


def acknowledge(system, request, state):
    record = load(system)
    if (not record or record.get('phase') not in ('start-intent', 'stopped', 'administrator-masked') or
            record['token'] != request['token'] or record['route'] != request['route'] or
            record['boot'] != system.boot or record['binding'] != system.binding_hash or
            record['controller'] != state or request['transmit'] is not False):
        raise ValueError('stale or mismatched application startup acknowledgement')
    if str(request['pid']) != service()['MainPID']:
        raise ValueError('startup acknowledgement is not the current service process')
    output.ready(system, state, {'gpio4':1, 'gpio20':2}[record['route']])
    record['ready'] = {'pid': request['pid'], 'route': request['route']}
    if record['phase'] in ('stopped', 'administrator-masked'):
        remove_owned(unit_file(IDLE_DROPIN), idle_bytes(record))
        admin.run(('/usr/bin/systemctl', 'daemon-reload'))
        record['phase'] = 'restored'
    system.write_record('application.json', record)


def failed(system, record, error):
    record['error'] = str(error)
    try:
        system.inhibit()
    except (OSError, ValueError) as cleanup:
        record['inhibitionError'] = str(cleanup)
    save(system, record, 'restoration-failed')


def finish_removal(factory, record):
    """Restore captured service intent only after exact neutral recovery."""
    validate_journal(record)
    with factory() as system:
        state = system.call()
        journal = system.read_journal()
        if (record['boot'] != system.boot or record['binding'] != system.binding_hash or
                any(state[name] for name in ('id', 'route', 'error', 'flags')) or
                not journal or journal.get('phase') != 'recovered-inhibited' or
                journal.get('observation') != state):
            raise ValueError('neutral recovery identity is not exact')
        validate_removal_capture(record, system.read_manager_record(), journal,
                                 state, system.boot, system.binding_hash)
        observed = service()
        resuming = record['phase'] == 'neutral-start-intent'
        if not resuming and (not system.inhibited() or
                observed['ActiveState'] not in ('inactive', 'failed') or
                observed['MainPID'] != '0'):
            raise ValueError('application is not stopped behind the owned inhibitor')
        masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in (
            'masked', 'masked-runtime')
        if (masked != record['administratorMasked'] or
                observed['LoadState'] not in ('loaded', 'masked') or
                observed['ActiveState'] not in ('active', 'inactive', 'failed') or
                (not record['wasActive'] and observed['ActiveState'] == 'active')):
            raise ValueError('service intent changed during removal restoration')
        if helper('inspect-stopped' if masked else 'inspect').get('transmit') is not False:
            raise ValueError('application is not idle before removal restoration')
        save(system, record, 'neutral-start-intent')
        remove_owned(unit_file(DROPIN), INHIBIT)
        admin.run(('/usr/bin/systemctl', 'daemon-reload'))
    if record['wasActive'] and observed['ActiveState'] != 'active':
        admin.run(('/usr/bin/systemctl', 'start', 'wsprrypi.service'))
    with factory() as system:
        state = system.call()
        if (record['boot'] != system.boot or record['binding'] != system.binding_hash or
                any(state[name] for name in ('id', 'route', 'error', 'flags'))):
            raise ValueError('neutral controller changed during application restoration')
        observed = service()
        masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in (
            'masked', 'masked-runtime')
        if masked != record['administratorMasked']:
            raise ValueError('administrator service mask changed during route removal')
        if record['wasActive']:
            if observed['ActiveState'] != 'active' or observed['MainPID'] == '0':
                raise ValueError('previously active application did not restart after route removal')
            phase = 'neutral-restored'
        else:
            if observed['ActiveState'] not in ('inactive', 'failed') or observed['MainPID'] != '0':
                raise ValueError('previously stopped application unexpectedly started after route removal')
            phase = ('neutral-administrator-masked' if record['administratorMasked']
                     else 'neutral-stopped')
        companion = helper('inspect-stopped' if masked else 'inspect')
        if companion.get('transmit') is not False:
            raise ValueError('application is not idle after route removal')
        save(system, record, phase)
        return record


def validate_removal_capture(record, manager, route, state, boot, binding):
    """Bind removal restoration to its exact captured intent and neutral result."""
    import runtime_activation as activation
    validate_journal(record)
    activation._validate_prior_route_transaction(route, boot, binding)
    activation._validate_prior_manager(manager, route, boot, binding)
    captured = manager['response']['state'].get('application')
    validate_journal(captured)
    # Error text is retained diagnostic evidence, not mutable service intent.
    diagnostics = {'error', 'inhibitionError'}
    terminal = ('neutral-restored' if record['wasActive'] else
        'neutral-administrator-masked' if record['administratorMasked'] else 'neutral-stopped')
    if (route['phase'] != 'recovered-inhibited' or route['observation'] != state or
            record.get('operation') != 'remove' or captured.get('operation') != 'remove' or
            captured['phase'] != 'captured' or
            record['controller'] is not None or record['ready'] is not None or
            (record['phase'] in REMOVAL_TERMINAL and record['phase'] != terminal) or
            record['boot'] != boot or record['binding'] != binding or
            record['route'] != {1:'gpio4', 2:'gpio20'}[route['target']] or
            any(record.get(key) != captured.get(key)
                for key in set(record) | set(captured) if key not in {'phase'} | diagnostics) or
            any(key in record and not isinstance(record[key], str) for key in diagnostics)):
        raise ValueError('application removal terminal differs from its capture')


def verify_removal_terminal(system, record):
    """Prove that a completed removal remains neutral and service-consistent."""
    validate_journal(record)
    state = system.call()
    journal = system.read_journal()
    if (record['phase'] not in REMOVAL_TERMINAL or
            record['boot'] != system.boot or record['binding'] != system.binding_hash or
            any(state[name] for name in ('id', 'route', 'error', 'flags')) or
            not journal or journal.get('phase') != 'recovered-inhibited' or
            journal.get('observation') != state or system.inhibited()):
        raise ValueError('completed neutral removal identity changed')
    validate_removal_capture(record, system.read_manager_record(), journal,
                             state, system.boot, system.binding_hash)
    observed = service()
    expected_active = record['phase'] == 'neutral-restored'
    masked = observed['LoadState'] == 'masked' or observed['UnitFileState'] in (
        'masked', 'masked-runtime')
    if ((expected_active and (observed['ActiveState'] != 'active' or observed['MainPID'] == '0')) or
            (not expected_active and (observed['ActiveState'] not in ('inactive', 'failed') or observed['MainPID'] != '0')) or
            masked != (record['phase'] == 'neutral-administrator-masked')):
        raise ValueError('completed neutral removal service state changed')
    companion = helper('inspect-stopped' if masked else 'inspect')
    if companion.get('transmit') is not False:
        raise ValueError('application is not idle after completed route removal')
    return record


def failed_removal(system, record, error):
    record['error'] = str(error)
    try:
        neutral_inhibit()
    except (OSError, ValueError) as cleanup:
        record['inhibitionError'] = str(cleanup)
    save(system, record, 'neutral-restoration-failed')
