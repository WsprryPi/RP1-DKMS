#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Parameterized container-only dpkg/DKMS integration tests, never ordinary tests.

Real package operations use the unmodified supplied archives. Fault wrappers
replace only one command's result and retain native commands for all other work.
"""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    import os
    os.execv(sys.executable, [sys.executable, '-I', __file__, *sys.argv[1:]])
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import time
import tempfile

if __name__ == '__main__':
    _cache = tempfile.TemporaryDirectory(prefix='rp1-lifecycle-import-', dir='/tmp')
    sys.pycache_prefix = _cache.name
    sys.dont_write_bytecode = True
sys.path.insert(0, '/source/scripts')
sys.path.insert(0, '/source/tools')
from lifecycle_results import (context, decode, envelope, input_identity,
                               source_identity)
from lifecycle_process import owned_process, run_owned
from lifecycle_metadata import metadata, module_stamp
from package_preflight import module_elf
from release_contract import inventory, package_members
import jsonschema

PACKAGE = 'rp1-gpclk-dkms'
VERSION = '0.99.0'
NAMES = ('rp1_gpclk_dkms', 'rp1_route_controller')
OUT = Path('/results')
DEB = Path('/candidate/rp1-gpclk-dkms_0.99.0-1_all.deb')
OLD = Path('/predecessor/rp1-gpclk-dkms_0.9.0-1_all.deb')
KERNELS = ('6.18.50+rpt-rpi-2712', '6.18.50+rpt-rpi-v8')
STEPS = []
FOREIGN_MODULES = {}
MATRIX = json.loads(Path('/source/release/package-lifecycle-matrix-v1.json').read_text())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def raw(command):
    with tempfile.TemporaryFile() as stream:
        try:
            result = run_owned(command, stream, timeout=600, output_limit=4*1024*1024,
                               env={**os.environ, 'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive'})
        except Exception as error:
            stream.seek(max(0, stream.seek(0, 2)-8192))
            raise RuntimeError(str(error)+'; command tail: '+stream.read(8192).decode(errors='replace')) from error
        stream.seek(0)
        result.stdout, result.stderr = stream.read(4*1024*1024).decode(errors='replace'), ''
        return result


def observe(stage, action, expected=0):
    """Record a real in-process filesystem oracle without inventing a CLI call."""
    before = snapshot()
    try:
        action()
    except ValueError as error:
        require(expected == 1, stage+': '+str(error))
        diagnostic = str(error)
    else:
        require(expected == 0, stage+' accepted an invalid fixture')
        diagnostic = ''
    STEPS.append({'stage': stage, 'command': ['in-process', 'runtime_deployment.Files.prune_removed_directories'],
                  'exitStatus': expected, 'before': before, 'after': snapshot(), 'diagnosticTail': diagnostic})
    neutral()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    modules = []
    for path in sorted(Path('/lib/modules').rglob('rp1*.ko*')):
        if path.name.split('.ko')[0] not in NAMES:
            continue
        stamp_before = module_stamp(path)
        identity_before = sha(path)
        fields = metadata(raw(['modinfo', '--null', str(path)]))
        version = fields['version']
        modules.append({'path': str(path), 'installedFileSha256': sha(path),
                        **fields,
                        'decompressedElfSha256': hashlib.sha256(module_elf(path.resolve(), version)).hexdigest(),
                        })
        require(module_stamp(path) == stamp_before
                and sha(path) == identity_before == modules[-1]['installedFileSha256'],
                'module changed during snapshot')
    package = raw(['dpkg-query', '-W', '-f=${db:Status-Abbrev} ${Version}', PACKAGE])
    dkms = raw(['dkms', 'status', '-m', PACKAGE])
    return {'packageManager': package.stdout.strip(), 'packageQueryExit': package.returncode,
            'dkms': dkms.stdout.strip(), 'dkmsExit': dkms.returncode, 'modules': modules,
            'sourceTrees': sorted(str(p) for p in Path('/usr/src').glob(PACKAGE+'-*')),
            'endpointsAbsent': all(not Path('/dev', n).exists() for n in ('rp1-gpclk', 'rp1-route-admin')),
            'modulesUnloaded': all(not Path('/sys/module', n).exists() for n in NAMES),
            'bootSha256': sha(Path('/boot/firmware/config.txt'))}


def run(stage, command, expected=0):
    before = snapshot()
    result = raw([str(p) for p in command])
    for line in (result.stdout+result.stderr).splitlines():
        if line.startswith('{'):
            value = json.loads(line)
            contract = value.get('contract')
            if contract in ('rp1-gpclk-package-preflight-v1', 'rp1-gpclk-package-indices-v1'):
                schema = json.loads(Path('/source/schema', contract+'.schema.json').read_text())
                jsonschema.Draft202012Validator(schema).validate(value)
    number = len(STEPS)
    (OUT/f'{number:03d}-{stage}.log').write_text(result.stdout+result.stderr)
    for index, log in enumerate(sorted(Path('/var/lib/dkms', PACKAGE).rglob('make.log'))[:8]):
        if log.is_file() and not log.is_symlink():
            with log.open('rb') as stream:
                data = stream.read(65537)
            (OUT/f'{number:03d}-dkms-{index}.log').write_bytes(data[:65536])
    after = snapshot()
    STEPS.append({'stage': stage, 'command': [str(p) for p in command],
                  'exitStatus': result.returncode, 'before': before, 'after': after,
                  'diagnosticTail': (result.stdout+result.stderr)[-8192:]})
    require(result.returncode == expected, stage+' exit differs: '+str(result.returncode)+'\n'+
            (result.stdout+result.stderr)[-4096:])
    require(after['endpointsAbsent'] and after['modulesUnloaded'], 'provider activation detected')
    neutral()
    return after


def neutral():
    require(not Path('/tmp/forbidden-calls').exists(), 'forbidden command called')
    require(Path('/boot/firmware/config.txt').read_bytes() == b'# administrator configuration\n', 'boot config changed')
    require(Path('/boot/firmware/overlays/foreign.dtbo').read_bytes() == b'foreign overlay', 'foreign overlay changed')
    require(Path('/var/lib/dkms/unrelated/7/source').is_symlink(), 'unrelated DKMS registration lost')
    require(Path('/etc/systemd/system/foreign.service').read_bytes() == b'# administrator unit\n', 'foreign service file changed')
    for path, digest in FOREIGN_MODULES.items():
        require(path.exists() and sha(path) == digest, 'foreign module artifact changed')


def installed(state):
    require(state['packageManager'] == 'ii  0.99.0-1', 'package is not configured')
    require(len(state['modules']) == 2*len(KERNELS), 'module/kernel set differs')
    require(state['dkms'].count(': installed') == len(KERNELS), 'DKMS kernel set differs')
    for module in state['modules']:
        if Path(module['path']).name.startswith('rp1_gpclk_dkms.'):
            require(module['controllerInterlock'] == '1' and module['depends'] == 'rp1_route_controller' and
                    not module['aliases'], 'consumer/controller build profile differs')
    neutral()


def absent(state):
    require(not state['modules'] and not state['sourceTrees'] and not state['dkms'], 'provider residue after removal')
    base = Path('/var/lib/dkms', PACKAGE)
    require(not base.exists() or not any(base.iterdir()), 'stale DKMS objects after removal')
    manifest = json.loads(Path('/candidate/rp1-gpclk-dkms-installation-manifest-v1.json').read_text())
    for member in manifest['packageInventory']:
        if member['type'] == 'file':
            require(not (Path('/')/member['path']).exists(), 'package data retained after removal: '+member['path'])
    neutral()


def replace_command(name, program):
    path = Path(shutil.which(name))
    # GCC locates cc1 relative to its executable prefix. Keep its real driver
    # beside the original, rather than silently changing the toolchain search.
    backup = path.with_name(path.name+'.lifecycle-real') if 'gcc' in name else Path('/tmp/lifecycle-real')/name
    backup.parent.mkdir(exist_ok=True)
    shutil.copyfile(path.resolve(), backup)
    backup.chmod(0o755)
    path.unlink()
    path.write_text(program.replace('@REAL@', str(backup)))
    path.chmod(0o755)


def setup():
    require(Path('/.dockerenv').is_file() and os.geteuid() == 0, 'restricted disposable Docker container required')
    status = Path('/proc/self/status').read_text()
    capabilities = int(next(line.split()[1] for line in status.splitlines() if line.startswith('CapEff:')), 16)
    require(capabilities & ~0xc9 == 0, 'only package filesystem/user-switch capabilities are permitted')
    mounts = Path('/proc/self/mountinfo').read_text().splitlines()
    for path in ('/boot', '/lib/modules', '/usr', '/etc', '/var/lib/dkms'):
        require(not any(line.split()[4] == path for line in mounts), 'host/system bind mount refused')
    require(not any(line.split()[1] == '00000000' for line in Path('/proc/net/route').read_text().splitlines()[1:]),
            'container network must have no default route')
    require(DEB.is_file() and OLD.is_file(), 'exact candidate and predecessor inputs required')
    manifest = json.loads(Path('/candidate/rp1-gpclk-dkms-installation-manifest-v1.json').read_text())
    members, _ = package_members(DEB)
    require(sha(DEB) == manifest['package']['sha256'] and inventory(members) == manifest['packageInventory'],
            'candidate hash/inventory mismatch')
    Path('/boot/firmware/overlays').mkdir(parents=True, exist_ok=True)
    Path('/boot/firmware/config.txt').write_bytes(b'# administrator configuration\n')
    Path('/boot/firmware/overlays/foreign.dtbo').write_bytes(b'foreign overlay')
    Path('/etc/systemd/system').mkdir(parents=True, exist_ok=True)
    Path('/etc/systemd/system/foreign.service').write_bytes(b'# administrator unit\n')
    source = Path('/usr/src/unrelated-7')
    source.mkdir()
    (source/'dkms.conf').write_text('PACKAGE_NAME="unrelated"\nPACKAGE_VERSION="7"\nBUILT_MODULE_NAME[0]="unrelated"\nDEST_MODULE_LOCATION[0]="/updates/dkms"\nAUTOINSTALL="no"\n')
    require(raw(['dkms', 'add', '-m', 'unrelated', '-v', '7']).returncode == 0, 'unrelated fixture setup failed')
    for name in ('modprobe', 'insmod', 'rmmod', 'systemctl', 'deb-systemd-invoke',
                 'deb-systemd-helper', 'reboot', 'shutdown'):
        if shutil.which(name):
            legacy = ''
            if name in ('systemctl', 'deb-systemd-invoke', 'deb-systemd-helper'):
                legacy = ('if [ -f /tmp/legacy-phase ]; then\n'+
                    ' printf "%s\\n" "'+name+' $*" >> /results/legacy-service-calls.log\n'+
                    (' exit 99\n' if name == 'systemctl' else ' exec @REAL@ "$@"\n')+'fi\n')
            replace_command(name, '#!/bin/sh\n'+legacy+'printf "%s\\n" "'+name+' $*" >> /tmp/forbidden-calls\nexit 99\n')
    for name in ('dkms', 'depmod', 'gcc', 'aarch64-linux-gnu-gcc-14'):
        stage = '"${1:-}"' if name == 'dkms' else ('gcc' if 'gcc' in name else name)
        match = ''
        if name == 'depmod':
            match = 'case " $* " in *" -a "*) ;; *) exec @REAL@ "$@";; esac\n'
        elif 'gcc' in name:
            match = 'case " $* " in *" -c "*) ;; *) exec @REAL@ "$@";; esac\n'
        replace_command(name, '#!/bin/sh\nset -eu\n'+
            match+
            ('if [ "${1:-}" = build ] && [ -f /tmp/lifecycle-hold ]; then\n'+
             ' touch /tmp/lifecycle-ready\n while [ -f /tmp/lifecycle-hold ]; do sleep 0.05; done\nfi\n'
             if name == 'dkms' else '')+
            'if [ -f /tmp/lifecycle-fault ] && [ "$(cat /tmp/lifecycle-fault)" = '+stage+' ]; then\n'+
            ('' if name == 'depmod' or 'gcc' in name else ' rm /tmp/lifecycle-fault\n')+
            ' echo "injected '+name+' failure (exit 64): $*" >&2\n exit 64\nfi\nexec @REAL@ "$@"\n')
    for kernel in KERNELS:
        for name in ('modules.order', 'modules.builtin', 'modules.builtin.modinfo'):
            Path('/lib/modules', kernel, name).touch()
        require(raw(['depmod', '-a', kernel]).returncode == 0, 'module index setup failed')
    versions = raw(['dpkg-query', '-W', '-f=${Package}=${Version}\n', 'dpkg', 'apt', 'dkms', 'dh-dkms',
                    'debhelper', 'gcc', 'binutils', 'kmod', 'openssl', 'gzip', 'xz-utils', 'zstd', 'bzip2']).stdout
    (OUT/'environment.json').write_text(json.dumps({'osRelease': Path('/etc/os-release').read_text(),
        'architecture': raw(['dpkg', '--print-architecture']).stdout.strip(), 'packages': versions,
        'compiler': raw(['gcc', '--version']).stdout.splitlines()[0],
        'hostKernel': raw(['uname', '-r']).stdout.strip(),
        'headerConfigurations': {k: sha(Path('/lib/modules', k, 'build/.config')) for k in KERNELS},
        'candidateCommit': manifest['sourceCommit'], 'candidatePackageSha256': sha(DEB),
        'predecessorPackageSha256': sha(OLD)}, indent=2)+'\n')


def clean_cycle():
    run('extract-incoming-control', ['dpkg-deb', '-e', DEB, '/tmp/incoming-control'])
    hostile = Path('/tmp/foreign-python')
    hostile.mkdir()
    (hostile/'pathlib.py').write_text(
        'open("/tmp/forbidden-calls", "w").write("foreign Python module imported")\n'
        'raise RuntimeError("foreign Python module imported")\n')
    run('isolated-incoming-preflight', ['env', 'PYTHONPATH='+str(hostile),
        'sh', '-c', 'cd /tmp/foreign-python && exec /tmp/incoming-control/preinst install'])
    installed(run('clean-install', ['dpkg', '-i', DEB]))
    installed(run('repeat-install', ['dpkg', '-i', DEB]))
    installed(run('apt-reinstall', ['apt-get', '-o', 'Acquire::Retries=0', '--reinstall', '-y', 'install', DEB]))
    missing = Path('/lib/modules', KERNELS[0], 'updates/dkms/rp1_gpclk_dkms.ko')
    missing.unlink()
    installed(run('missing-module-reinstall', ['dpkg', '-i', DEB]))
    absent(run('remove', ['dpkg', '--remove', PACKAGE]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))
    installed(run('reinstall-after-removal', ['dpkg', '-i', DEB]))
    absent(run('final-purge', ['dpkg', '--purge', PACKAGE]))


def packaged_runtime_baseline():
    """Real passive package data plus a filesystem-only runtime inverse.

    No controller, service, endpoint or hardware operation is performed.
    """
    installed(run('clean-install', ['dpkg', '-i', DEB]))
    sys.path[:0] = ['/source/scripts', '/source/tests']
    import runtime_deployment as deployment
    import runtime_provider as provider
    baseline = deployment.Files().packaged_baseline()
    require(len(baseline) == 4, 'exact passive package baseline required')
    files = deployment.Files()
    # Reproduce the inverse's final filesystem phase against real package
    # inventory. Earlier administrative effects are outside this test class.
    observe('preserve-passive-baseline', files.prune_removed_directories)
    for name, expected in baseline.items():
        require(Path(name).exists() and sha(Path(name)) == expected,
                'runtime pruning changed passive package data')
    host = provider.Host.__new__(provider.Host)
    host.files = files
    host.services = lambda: {name: {'load': 'loaded', 'active': 'inactive'} for name in
        ('rp1-gpclk-route-manager.socket', 'rp1-gpclk-route-manager@.service')}
    host.module = lambda name: {'status': 'absent'}
    host.endpoint = lambda name: {'status': 'absent'}
    host.socket = lambda: {'status': 'absent'}
    require(host.update_absent(), 'verified passive package units prevent runtime absence')
    overlay = Path('/usr/lib/rp1-gpclk-dkms/overlays/rp1-gpclk-gpio4.dtbo')
    original = overlay.read_bytes()
    overlay.write_bytes(b'changed overlay')
    try:
        observe('refuse-changed-passive-baseline', files.prune_removed_directories, 1)
        require(overlay.read_bytes() == b'changed overlay', 'changed overlay was removed')
    finally: overlay.write_bytes(original)
    foreign = overlay.parent/'foreign.dtbo'; foreign.write_bytes(b'preserve')
    try:
        observe('refuse-foreign-passive-baseline', files.prune_removed_directories, 1)
        require(foreign.read_bytes() == b'preserve', 'foreign member was removed')
    finally: foreign.unlink()
    absent(run('purge-after-runtime-retirement', ['dpkg', '--purge', PACKAGE]))


def dependency_recovery():
    packages = list(Path('/opt/lifecycle-inputs').glob('adduser_*.deb'))
    require(len(packages) == 1, 'official dependency repair archive required')
    run('remove-test-dependency', ['dpkg', '--remove', 'adduser'])
    state = run('dependency-configure-refusal', ['dpkg', '-i', DEB], 1)
    require('depends on adduser' in STEPS[-1]['diagnosticTail'] and not state['dkms'] and not state['modules'],
            'dependency failure was not before DKMS effects')
    run('restore-exact-dependency', ['dpkg', '-i', packages[0]])
    installed(run('retry-after-dependency-repair', ['dpkg', '--configure', PACKAGE]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def missing_payload():
    installed(run('initial-install', ['dpkg', '-i', DEB]))
    for name in ('/usr/libexec/rp1-gpclk-dkms/package_preflight.py',
                 '/usr/src/rp1-gpclk-dkms-0.99.0/dkms.conf'):
        Path(name).unlink()
        installed(run('repair-missing-'+Path(name).name, ['dpkg', '-i', DEB]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def package_lock():
    installed(run('initial-install', ['dpkg', '-i', DEB]))
    hold = Path('/tmp/lifecycle-hold')
    hold.touch()
    try:
        with (OUT/'first-replacement.log').open('w') as stream, \
                owned_process(['dpkg', '-i', str(DEB)], stream) as process:
            try:
                deadline = time.monotonic()+30
                while not Path('/tmp/lifecycle-ready').exists() and time.monotonic() < deadline:
                    require(process.poll() is None, 'first replacement exited before lock boundary')
                    time.sleep(0.05)
                require(Path('/tmp/lifecycle-ready').exists(), 'package lock synchronization timed out')
                before = snapshot()
                state = run('refuse-concurrent-same-version', ['dpkg', '-i', DEB], 2)
                require(state == before and 'lock' in STEPS[-1]['diagnosticTail'], 'concurrent operation changed state')
            finally:
                hold.unlink(missing_ok=True)
            require(process.wait(timeout=180) == 0, 'first same-version replacement did not finish')
    finally:
        hold.unlink(missing_ok=True)
    installed(snapshot())
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def python_boundary_fault(stage):
    marker = Path('/tmp/python-boundary-fault')
    marker.write_text(stage)
    cache_fault = Path('/var/lib/dkms', PACKAGE, VERSION, 'foreign-inventory-fault')
    replace_command('python3', '''#!/bin/sh
set -eu
if [ -f /tmp/python-boundary-fault ]; then
    boundary=$(cat /tmp/python-boundary-fault)
    case "$boundary:$*" in
    'preinstall:-I - unpack'|'configure:-I /usr/libexec/rp1-gpclk-dkms/package_preflight.py configure')
        rm /tmp/python-boundary-fault
        echo "injected $boundary Python boundary failure (exit 64)" >&2
        exit 64 ;;
    'inventory:-I /usr/libexec/rp1-gpclk-dkms/package_indices.py')
        rm /tmp/python-boundary-fault
        printf '%s' 'injected inventory fault' > /var/lib/dkms/rp1-gpclk-dkms/0.99.0/foreign-inventory-fault ;;
    esac
fi
exec @REAL@ "$@"
''')
    if stage == 'configure':
        run('unpack-before-configure-fault', ['dpkg', '--unpack', DEB])
        command = ['dpkg', '--configure', PACKAGE]
    else:
        command = ['dpkg', '-i', DEB]
    state = run('interrupted-'+stage, command, 1)
    require(not marker.exists(), 'Python boundary injection was not reached')
    if stage == 'inventory':
        require('"stage": "inventory"' in STEPS[-1]['diagnosticTail'] and len(state['modules']) == 4,
                'native installed inventory failure was not diagnosed')
        require(cache_fault.read_bytes() == b'injected inventory fault', 'inventory fault evidence changed')
        cache_fault.unlink()
    else:
        require('injected '+stage+' Python boundary failure' in STEPS[-1]['diagnosticTail']
                and not state['modules'] and not state['dkms'], 'boundary fault had unexpected effects')
    retry = 'retry-configure' if stage == 'configure' else 'retry-'+stage
    installed(run(retry, ['dpkg', '--configure', PACKAGE] if stage != 'preinstall' else ['dpkg', '-i', DEB]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def fault(stage):
    if stage in ('preinstall', 'inventory', 'configure'):
        return python_boundary_fault(stage)
    if stage == 'signature':
        return signature_failure()
    removing = stage in ('remove', 'purge', 'remove-depmod')
    if stage == 'unpack':
        return unpack_fault()
    if removing:
        installed(run('install-before-remove-fault', ['dpkg', '-i', DEB]))
    else:
        run('unpack', ['dpkg', '--unpack', DEB])
    injected = 'depmod' if stage == 'remove-depmod' else ('remove' if stage == 'purge' else stage)
    Path('/tmp/lifecycle-fault').write_text(injected)
    command = (['dpkg', '--purge' if stage == 'purge' else '--remove', PACKAGE]
               if removing else ['dpkg', '--configure', PACKAGE])
    run('injected-'+stage, command, 1)
    if injected == 'depmod':
        require('injected depmod failure' in STEPS[-1]['diagnosticTail'], 'depmod failure was not diagnosed')
        Path('/tmp/lifecycle-fault').unlink()
    elif injected == 'gcc':
        require(any('injected aarch64-linux-gnu-gcc-14 failure (exit 64)' in p.read_text()
                    for p in OUT.glob('*-dkms-*.log')), 'compiler failure was not captured')
        Path('/tmp/lifecycle-fault').unlink()
    else:
        require(not Path('/tmp/lifecycle-fault').exists(), 'injection point was not reached')
    state_name, registrations, modules = {
        'add': ('failed-add', 0, 0), 'build': ('failed-build', 1, 0),
        'gcc': ('failed-build', 1, 0), 'install': ('failed-install', 1, 0),
        'depmod': ('failed-index', 2, 4), 'remove': ('failed-remove', 2, 4),
        'purge': ('failed-purge', 2, 4), 'remove-depmod': ('failed-remove-index', 0, 0)}[stage]
    expected = (MATRIX['states'][state_name]['packageManager'], registrations, modules)
    state = STEPS[-1]['after']
    require((state['packageManager'], len(state['dkms'].splitlines()), len(state['modules'])) == expected,
            'failure state differs from the lifecycle matrix: '+stage)
    if removing:
        absent(run('retry-remove', command))
    else:
        installed(run('retry-configure', command))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def unpack_fault():
    # The archive is unchanged. Fault only the actual dpkg-deb tar stream at
    # the GPIO20 data member, proving dpkg's interrupted-unpack recovery.
    replace_command('dpkg-deb', '''#!/usr/bin/python3
import io, os, pathlib, subprocess, sys, tarfile
marker = pathlib.Path('/tmp/unpack-fault')
if '--fsys-tarfile' in sys.argv and marker.exists():
    raw = subprocess.check_output(['@REAL@', *sys.argv[1:]])
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        member = next(m for m in archive if m.name.endswith('/rp1-gpclk-gpio20.dtbo'))
        cut = member.offset_data + 20
    print('injected overlay payload unpack failure: exit 64', file=sys.stderr, flush=True)
    sys.stdout.buffer.write(raw[:cut])
    sys.stdout.buffer.flush()
    raise SystemExit(64)
os.execv('@REAL@', ['@REAL@', *sys.argv[1:]])
''')
    marker = Path('/tmp/unpack-fault')
    marker.touch()
    run('interrupted-overlay-unpack', ['dpkg', '-i', DEB], 1)
    require('injected overlay payload' in STEPS[-1]['diagnosticTail'], 'unpack fault was not reached')
    marker.unlink()
    installed(run('retry-exact-unpack-configure', ['dpkg', '-i', DEB]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def foreign_state():
    for name in ('var/lib/wsprrypi/rp1-gpclk-dkms-installation.json',
                 'etc/rp1-gpclk-dkms/runtime-controller.json',
                 'var/lib/rp1-gpclk-dkms/route-transactions/foreign.json',
                 'usr/src/rp1-gpclk-dkms-0.99.0/DEVELOPMENT_MANIFEST.json'):
        path = Path('/')/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'foreign ownership evidence')
        run('refuse-'+path.stem, ['dpkg', '-i', DEB], 1)
        require(path.read_bytes() == b'foreign ownership evidence', 'ownership record changed')
        path.unlink()
        parent = path.parent
        while str(parent) not in ('/var/lib', '/etc', '/'):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    for version in ('0.99.0', '9.9.9'):
        path = Path('/var/lib/dkms', PACKAGE, version)
        path.mkdir(parents=True)
        run('foreign-dkms-'+version, ['dpkg', '-i', DEB], 1)
        require(path.exists(), 'foreign DKMS state deleted')
        path.rmdir()
    hook = Path('/etc/dkms/rp1-gpclk-dkms.conf')
    hook.write_text('PRE_BUILD="foreign-hook"\n')
    run('refuse-unknown-hook', ['dpkg', '-i', DEB], 1)
    require(hook.read_text() == 'PRE_BUILD="foreign-hook"\n', 'foreign hook changed')
    hook.unlink()
    installed(run('install-after-foreign-cleanup', ['dpkg', '-i', DEB]))
    module = Path('/lib/modules', KERNELS[0], 'updates/dkms/rp1_gpclk_dkms.ko')
    duplicate = module.with_suffix('.ko.xz')
    duplicate.write_bytes(lzma.compress(module.read_bytes()))
    run('refuse-duplicate-module', ['dpkg', '-i', DEB], 1)
    require(lzma.decompress(duplicate.read_bytes()) == module.read_bytes(), 'duplicate changed')
    duplicate.unlink()
    for name in ('foreign.txt', KERNELS[0]+'/aarch64/module/foreign.txt'):
        foreign = Path('/var/lib/dkms', PACKAGE, VERSION, name)
        foreign.write_bytes(b'foreign cache evidence')
        run('refuse-foreign-cache-removal', ['dpkg', '--remove', PACKAGE], 1)
        run('refuse-foreign-cache-reinstall', ['dpkg', '-i', DEB], 1)
        require(foreign.read_bytes() == b'foreign cache evidence', 'foreign cache file deleted')
        foreign.unlink()  # Retire only the injected test object.
    path = Path('/usr/src/rp1-gpclk-dkms-0.99.0/Kbuild')
    saved = path.read_bytes()
    path.write_bytes(saved+b'\n# administrator change\n')
    run('refuse-drifted-removal', ['dpkg', '--remove', PACKAGE], 1)
    run('refuse-drifted-reinstall', ['dpkg', '-i', DEB], 1)
    require(path.read_bytes() == saved+b'\n# administrator change\n', 'drift overwritten')
    path.write_bytes(saved)  # Explicit fixture restoration, never an operator repair.
    absent(run('purge-restored-fixture', ['dpkg', '--purge', PACKAGE]))


def multi_kernel():
    second = Path('/lib/modules', KERNELS[1])
    shutil.move(str(second), '/tmp/held-kernel')
    state = run('install-nonrunning-kernel', ['dpkg', '-i', DEB])
    require(len(state['modules']) == 2, 'one-kernel module set differs')
    absent(run('one-kernel-purge', ['dpkg', '--purge', PACKAGE]))
    state = run('reinstall-one-kernel', ['dpkg', '-i', DEB])
    require(len(state['modules']) == 2, 'one-kernel reinstall set differs')
    shutil.move('/tmp/held-kernel', str(second))
    installed(run('new-kernel-autoinstall', ['dkms', 'autoinstall', '-k', KERNELS[1]]))
    installed(run('exact-autoinstall-noop', ['dkms', 'autoinstall', '-k', KERNELS[1]]))
    state = run('kernel-removal', ['dkms', 'remove', '-m', PACKAGE, '-v', VERSION, '-k', KERNELS[1]])
    require(len(state['modules']) == 2, 'kernel removal damaged retained kernel')
    installed(run('kernel-readdition', ['dkms', 'autoinstall', '-k', KERNELS[1]]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def unpack_recovery():
    run('interrupted-before-configure', ['dpkg', '--unpack', DEB])
    installed(run('recover-configure', ['dpkg', '--configure', PACKAGE]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def header_profiles():
    run('extract-build-inputs', ['dpkg-deb', '-x', DEB, '/tmp/profile-payload'])
    source = Path('/tmp/profile-payload/usr/src/rp1-gpclk-dkms-0.99.0')
    builds = []
    for kernel in KERNELS:
        for profile in (0, 1):
            directory = Path('/tmp/profile-'+kernel+'-'+str(profile))
            shutil.copytree(source, directory)
            run('build-'+kernel+'-'+str(profile), ['make', '-C', directory,
                'KERNEL_BUILD=/lib/modules/'+kernel+'/build', 'RP1_RUNTIME_CONTROLLER='+str(profile)])
            names = NAMES if profile else NAMES[:1]
            for name in names:
                module = directory/(name+'.ko')
                run('validate-'+kernel+'-'+name+'-'+str(profile), ['python3',
                    '/source/tests/check_built_module.py', module, '--kernel-release', kernel])
                builds.append({'kernel': kernel, 'profile': profile, 'module': name,
                               'sha256': sha(module), 'consumerUapiSha256': sha(directory/'include/uapi/linux/rp1_gpclk.h')})
            consumer = directory/'rp1_gpclk_dkms.ko'
            require(bool(raw(['modinfo', '-F', 'alias', str(consumer)]).stdout.strip()) == (not profile),
                    'profile OF autoload alias differs')
    (OUT/'header-builds.json').write_text(json.dumps(builds, indent=2)+'\n')


def missing_headers():
    path = Path('/lib/modules', KERNELS[0], 'build')
    saved = path.readlink()
    path.unlink()
    state = run('refuse-missing-headers', ['dpkg', '-i', DEB], 1)
    require(not state['dkms'] and not state['modules'], 'effects before missing-header refusal')
    path.symlink_to(saved)
    installed(run('install-after-header-repair', ['dpkg', '-i', DEB]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def compression_signing():
    # Explicit header-config fixtures select native DKMS signing/compression.
    # Header code and generated compile configuration remain the stock inputs;
    # these variants exercise packaging transforms, not a qualified kernel.
    key, cert = Path('/var/lib/dkms/mok.key'), Path('/var/lib/dkms/mok.pub')
    generated = raw(['openssl', 'req', '-new', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '1',
                     '-subj', '/CN=Disposable-lifecycle-test/', '-keyout', str(key),
                     '-outform', 'DER', '-out', str(cert)])
    require(generated.returncode == 0, 'explicit test administrator key setup failed')
    key.chmod(0o600)
    key_digest, cert_digest = sha(key), sha(cert)
    originals = {k: Path('/lib/modules', k, 'build/.config').read_text() for k in KERNELS}
    references = {}
    for kernel in KERNELS:
        directory = Path('/tmp/foreign-module-'+kernel)
        directory.mkdir()
        (directory/'Makefile').write_text('# SPDX-License-Identifier: MIT\nobj-m += lifecycle_foreign.o\n')
        (directory/'lifecycle_foreign.c').write_text(
            '/* SPDX-License-Identifier: GPL-2.0-only OR MIT */\n#include <linux/module.h>\n'
            'static int __init start(void) { return 0; }\nstatic void __exit stop(void) {}\n'
            'module_init(start); module_exit(stop); MODULE_LICENSE("Dual MIT/GPL"); MODULE_VERSION("7");\n')
        run('build-foreign-fixture-'+kernel, ['make', '-C', '/lib/modules/'+kernel+'/build',
                                            'M='+str(directory), 'modules'])
        references[kernel] = (directory/'lifecycle_foreign.ko').read_bytes()
    for suffix, symbol in (('.ko', None), ('.ko.gz', 'GZIP'), ('.ko.xz', 'XZ'), ('.ko.zst', 'ZSTD')):
        for path in FOREIGN_MODULES:
            path.unlink()
        FOREIGN_MODULES.clear()
        for kernel in KERNELS:
            text = '\n'.join(line for line in originals[kernel].splitlines()
                             if not line.startswith(('CONFIG_MODULE_COMPRESS', '# CONFIG_MODULE_COMPRESS',
                                                     'CONFIG_MODULE_SIG_HASH=')))+'\n'
            text += 'CONFIG_MODULE_SIG_HASH="sha256"\n'
            if symbol:
                text += 'CONFIG_MODULE_COMPRESS=y\nCONFIG_MODULE_COMPRESS_'+symbol+'=y\n'
            Path('/lib/modules', kernel, 'build/.config').write_text(text)
            effective = Path('/lib/modules', kernel, 'build/include/config/auto.conf')
            configured = effective.read_text()
            configured = '\n'.join(line for line in configured.splitlines()
                                   if not line.startswith('CONFIG_MODULE_SIG_HASH='))+'\nCONFIG_MODULE_SIG_HASH="sha256"\n'
            effective.write_text(configured)
            path = Path('/lib/modules', kernel, 'kernel/lifecycle_foreign'+suffix)
            path.parent.mkdir(exist_ok=True)
            data = references[kernel]
            if suffix == '.ko.gz':
                data = gzip.compress(data)
            elif suffix == '.ko.xz':
                data = lzma.compress(data)
            elif suffix == '.ko.zst':
                data = subprocess.check_output(['zstd', '-q', '-c'], input=data)
            path.write_bytes(data)
            FOREIGN_MODULES[path] = sha(path)
        if suffix == '.ko.gz' and '+ZLIB' not in raw(['modinfo', '--version']).stdout.split():
            state = run('refuse-native-gzip-without-zlib', ['dpkg', '-i', DEB], 1)
            require(not state['modules'] and not state['dkms'], 'unsupported gzip caused DKMS effects')
            continue
        state = run('signed-install-'+suffix, ['dpkg', '-i', DEB])
        installed(state)
        require(all(m['path'].endswith(suffix) and m['signer'] for m in state['modules']),
                'native signing/compression identity differs')
        if suffix == '.ko':
            installed_path = Path('/lib/modules', KERNELS[0], 'updates/dkms/rp1_gpclk_dkms.ko')
            cached_path = Path('/var/lib/dkms', PACKAGE, VERSION, KERNELS[0], 'aarch64/module/rp1_gpclk_dkms.ko')
            original = installed_path.read_bytes()
            changed = bytearray(original)
            changed[64] ^= 1
            installed_path.write_bytes(changed)
            cached_path.write_bytes(changed)
            run('refuse-corrupt-signature', ['python3', '-I', '/usr/libexec/rp1-gpclk-dkms/package_indices.py'], 4)
            require('CMS Verification failure' in STEPS[-1]['diagnosticTail'] or
                    'CMS Verification failure'.lower() in STEPS[-1]['diagnosticTail'].lower(),
                    'corrupt signature was not rejected cryptographically')
            installed_path.write_bytes(original)
            cached_path.write_bytes(original)
        installed(run('exact-dkms-noop-'+suffix, ['dkms', 'install', '-m', PACKAGE, '-v', VERSION, '-k', KERNELS[0]]))
        absent(run('remove-'+suffix, ['dpkg', '--purge', PACKAGE]))
        require(sha(key) == key_digest and sha(cert) == cert_digest, 'administrator signing material changed')


def signature_failure():
    key, cert = Path('/var/lib/dkms/mok.key'), Path('/var/lib/dkms/mok.pub')
    result = raw(['openssl', 'req', '-new', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '1',
                  '-subj', '/CN=Disposable-signing-failure/', '-keyout', str(key), '-outform', 'DER', '-out', str(cert)])
    require(result.returncode == 0, 'explicit signing identity setup failed')
    key.chmod(0o600)
    good_certificate = cert.read_bytes()
    for kernel in KERNELS:
        for name in ('.config', 'include/config/auto.conf'):
            path = Path('/lib/modules', kernel, 'build', name)
            path.write_text(path.read_text()+'\nCONFIG_MODULE_SIG_HASH="sha256"\n')
    cert.write_bytes(b'controlled invalid public certificate')
    run('refuse-native-signing-warning', ['dpkg', '-i', DEB], 1)
    require('"stage": "signature"' in STEPS[-1]['diagnosticTail'], 'native signing failure was concealed')
    cert.write_bytes(good_certificate)
    installed(run('retry-after-signing-repair', ['dpkg', '--configure', PACKAGE]))
    absent(run('purge', ['dpkg', '--purge', PACKAGE]))


def predecessor():
    # Legacy-effects fixture scripts execute in this disposable root. Only service
    # effects are interlocked; their attempts are recorded separately.
    legacy = Path('/tmp/legacy-phase')
    legacy.touch()
    state = run('legacy-fixture-install', ['dpkg', '-i', OLD])
    require(state['packageManager'] == 'ii  0.9.0-1', 'predecessor is not configured')
    require(len(state['modules']) == len(KERNELS) and all(m['version'] == '0.9.0' for m in state['modules']),
            'predecessor ordinary module profile differs')
    require(Path('/boot/firmware/overlays/rp1-gpclk-gpio4.dtbo').exists(), 'legacy fixture overlay effect missing')
    legacy.unlink()
    before = snapshot()
    run('refuse-direct-upgrade-before-dpkg', ['python3', '/source/scripts/package_preflight.py', 'unpack'], 1)
    require(snapshot() == before, 'refused upgrade changed predecessor')
    # Actual old/new package transitions follow the approved owning removal
    # recipe. The predecessor is a synthetic effects fixture, not historical software.
    legacy.touch()
    Path('/tmp/lifecycle-fault').write_text('remove')
    state = run('failed-owning-predecessor-removal', ['dpkg', '--purge', PACKAGE], 1)
    require(state['packageManager'] == 'pi  0.9.0-1' and len(state['modules']) == len(KERNELS),
            'failed predecessor removal did not preserve its attributable modules')
    state = run('owning-predecessor-removal', ['dpkg', '--purge', PACKAGE])
    legacy.unlink()
    absent(state)
    require(not Path('/boot/firmware/overlays/rp1-gpclk-gpio4.dtbo').exists(), 'owned legacy overlay not retired')
    installed(run('successor-clean-install', ['dpkg', '-i', DEB]))
    # The retained predecessor refuses in-place downgrade; call its exact
    # preinst before dpkg could invoke the installed candidate's prerm.
    require(raw(['dpkg-deb', '-e', str(OLD), '/tmp/old-control']).returncode == 0, 'old control extraction failed')
    run('refuse-direct-downgrade-before-dpkg', ['sh', '/tmp/old-control/preinst', 'upgrade', '0.99.0-1'], 1)
    absent(run('rollback-remove-successor', ['dpkg', '--purge', PACKAGE]))
    legacy.touch()
    state = run('rollback-install-retained-predecessor', ['dpkg', '-i', OLD])
    require(state['packageManager'] == 'ii  0.9.0-1' and len(state['modules']) == len(KERNELS), 'rollback did not converge')
    state = run('rollback-cleanup-predecessor', ['dpkg', '--purge', PACKAGE])
    legacy.unlink()
    absent(state)
    run('failed-successor-unpack', ['dpkg', '--unpack', DEB])
    Path('/tmp/lifecycle-fault').write_text('build')
    run('failed-successor-configure', ['dpkg', '--configure', PACKAGE], 1)
    absent(run('failed-successor-removal', ['dpkg', '--purge', PACKAGE]))
    legacy.touch()
    Path('/tmp/lifecycle-fault').write_text('build')
    run('failed-rollback', ['dpkg', '-i', OLD], 1)
    state = run('retry-exact-rollback-configure', ['dpkg', '--configure', PACKAGE])
    require(state['packageManager'] == 'ii  0.9.0-1' and len(state['modules']) == len(KERNELS), 'rollback retry did not converge')
    state = run('final-predecessor-cleanup', ['dpkg', '--purge', PACKAGE])
    legacy.unlink()
    absent(state)


def main():
    setup()
    scenario = sys.argv[1]
    if scenario.startswith('fault-'):
        fault(scenario.removeprefix('fault-'))
    else:
        {'clean-cycle': clean_cycle, 'foreign-state': foreign_state,
         'packaged-runtime-baseline': packaged_runtime_baseline,
         'missing-payload': missing_payload,
         'package-lock': package_lock,
         'multi-kernel': multi_kernel, 'unpack-recovery': unpack_recovery,
         'header-profiles': header_profiles,
         'dependency-recovery': dependency_recovery,
         'missing-headers': missing_headers, 'compression-signing': compression_signing,
         'predecessor': predecessor}[scenario]()
    neutral()


if __name__ == '__main__':
    status, error = 'PASS', None
    expected = None
    try:
        supplied = decode(os.environ['RP1_LIFECYCLE_CONTEXT'])
        require(set(supplied) == {'runId', 'scenario', 'identity'}, 'context fields differ')
        expected = context(supplied['runId'], sys.argv[1], input_identity(
            Path('/candidate'), Path('/predecessor'), supplied['identity']['imageId'],
            source_identity(Path('/source'))))
        require(supplied == expected, 'container input identity differs')
        main()
        require(input_identity(Path('/candidate'), Path('/predecessor'),
                supplied['identity']['imageId'], source_identity(Path('/source')))
                == expected['identity'], 'inputs changed during scenario')
    except Exception as exception:
        status, error = 'FAIL', str(exception)
    finally:
        if expected is not None:
            (OUT/'result.json').write_text(json.dumps(envelope(expected, status, error, STEPS),
                                                    indent=2)+'\n')
    print(json.dumps({'status': status, 'error': error}), flush=True)
    raise SystemExit(0 if status == 'PASS' else 1)
