#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage the fixed passive package payload; never install on a host."""
from pathlib import Path
import shutil
import sys
import hashlib
import json
from version_identity import VERSION, DEBIAN, REPOSITORY, LIFECYCLE

ROOT = Path(__file__).resolve().parents[1]


def payload_sources(root=ROOT):
    prefix = f'usr/src/rp1-gpclk-dkms-{VERSION}/'
    names = ['Kbuild', 'Makefile', 'include/uapi/linux/rp1_gpclk.h',
             'include/uapi/linux/rp1_route_admin.h', 'controller/main.c',
             'controller/consumer.h', 'controller/state.h',
             'scripts/build_runtime_controller.py', 'scripts/overlay_builder.py',
             'overlays/rp1-gpclk-gpio4.dts', 'overlays/rp1-gpclk-gpio20.dts']
    names += [p.relative_to(root).as_posix() for pattern in
              ('src/*.c', 'include/rp1_gpclk/*.h')
              for p in sorted(root.glob(pattern))]
    result = {prefix+name: name for name in names}
    result.update({
        'usr/libexec/rp1-gpclk-dkms/version_identity.py': 'scripts/version_identity.py',
        'usr/libexec/rp1-gpclk-dkms/version.h': 'include/rp1_gpclk/version.h',
        'usr/libexec/rp1-gpclk-dkms/package_preflight.py': 'scripts/package_preflight.py',
        'usr/libexec/rp1-gpclk-dkms/package_indices.py': 'scripts/package_indices.py',
        'usr/libexec/rp1-gpclk-dkms/package_signatures.py': 'scripts/package_signatures.py',
        'usr/libexec/rp1-gpclk-dkms/rp1-gpclk-route-manager': 'scripts/rp1-gpclk-route-manager.py',
        'usr/sbin/rp1-gpclk-route-manager': 'scripts/rp1-gpclk-route-manager.py',
        f'usr/share/rp1-gpclk-dkms/{VERSION}/rp1-gpclk-route-manager.schema.json': 'schema/rp1-gpclk-route-manager.schema.json',
        'usr/share/doc/rp1-gpclk-dkms/route-manager.md': 'engineering/contracts/route-manager.md',
    })
    for name in ('rp1-gpclk-route-manager.socket', 'rp1-gpclk-route-manager@.service'):
        result['usr/lib/systemd/system/'+name] = 'systemd/'+name
    for route in ('gpio4', 'gpio20'):
        name = 'rp1-gpclk-'+route+'.dtbo'
        result['usr/lib/rp1-gpclk-dkms/overlays/'+name] = 'debian/build/'+name
    return result


def render_dkms(text):
    if text.count('PACKAGE_VERSION="#MODULE_VERSION#"') != 1:
        raise ValueError('DKMS version placeholder differs')
    if (text.count('MAKE[0]="make KERNEL_BUILD=${kernel_source_dir}"') != 1 or
            'BUILT_MODULE_NAME[1]' in text):
        raise ValueError('DKMS build profile differs')
    text = text.replace('#MODULE_VERSION#', VERSION)
    text = text.replace('MAKE[0]="make KERNEL_BUILD=${kernel_source_dir}"',
                        'MAKE[0]="make KERNEL_BUILD=${kernel_source_dir} RP1_RUNTIME_CONTROLLER=1"')
    text += ('\nBUILT_MODULE_NAME[1]="rp1_route_controller"\n'
             'BUILT_MODULE_LOCATION[1]="."\nDEST_MODULE_LOCATION[1]="/updates/dkms"\n')
    return text


def stage(destination):
    for target, source in payload_sources().items():
        path = destination/target
        path.parent.mkdir(parents=True, exist_ok=True)
        if (ROOT/source).is_symlink():
            raise ValueError('package source symlink')
        shutil.copyfile(ROOT/source, path)
        path.chmod(0o644 if target.endswith('/version.h') else 0o755 if target.endswith('/rp1-gpclk-route-manager') or
                   target.startswith('usr/libexec/rp1-gpclk-dkms/') else 0o644)
    dkms = destination/f'usr/src/rp1-gpclk-dkms-{VERSION}/dkms.conf'
    dkms.write_text(render_dkms((ROOT/'dkms.conf').read_text()))
    dkms.chmod(0o644)
    staged = set(payload_sources()) | {f'usr/src/rp1-gpclk-dkms-{VERSION}/dkms.conf'}
    payload = {name: hashlib.sha256((destination/name).read_bytes()).hexdigest()
               for name in sorted(staged)}
    receipt = {'repository': REPOSITORY, 'lifecycle': LIFECYCLE, 'productVersion': VERSION,
               'debianVersion': DEBIAN, 'payload': payload,
               'scripts': {n: hashlib.sha256((ROOT/'debian'/('rp1-gpclk-dkms.'+n)).read_bytes()).hexdigest()
                           for n in ('preinst', 'postinst', 'prerm')},
               'uapi': {n: hashlib.sha256((ROOT/'include/uapi/linux'/n).read_bytes()).hexdigest()
                        for n in ('rp1_gpclk.h', 'rp1_route_admin.h')}}
    path = destination/'usr/libexec/rp1-gpclk-dkms/package-identity.json'
    path.write_text(json.dumps(receipt, sort_keys=True, separators=(',', ':'))+'\n')
    path.chmod(0o644)


def incoming_guard(root, receipt):
    receipt = json.loads(json.dumps(receipt, sort_keys=True))
    helper = (root/'scripts/version_identity.py').read_text()
    header = (root/'include/rp1_gpclk/version.h').read_text()
    # Embedded literal is generated from the authoritative declaration.
    helper = helper.replace('VERSION, DEBIAN = identity()',
                            'VERSION, DEBIAN = from_header('+repr(header)+')')
    bootstrap = ('import sys, types\n_version = types.ModuleType("version_identity")\n'
                 'sys.modules["version_identity"] = _version\n'
                 'exec('+repr(helper)+', _version.__dict__)\n')
    guard = (root/'scripts/package_preflight.py').read_text()
    return bootstrap + guard.replace('INCOMING = None', 'INCOMING = '+repr(receipt))


def preinst(destination):
    """Embed the incoming read-only guard before unpack; trust no old helper."""
    path = destination/'DEBIAN/preinst'
    marker = '# RP1_INCOMING_PREFLIGHT\n'
    text = path.read_text()
    if text.count(marker) != 1:
        raise ValueError('incoming package guard marker differs')
    receipt_path = destination/'usr/libexec/rp1-gpclk-dkms/package-identity.json'
    receipt = json.loads(receipt_path.read_text())
    for name in ('postinst', 'prerm'):
        control = destination/'DEBIAN'/name
        control.write_text(control.read_text().replace('@DEBIAN_VERSION@', DEBIAN))
    receipt['scripts'] = {name: hashlib.sha256((destination/'DEBIAN'/name).read_bytes()).hexdigest()
                          for name in ('preinst', 'postinst', 'prerm')}
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(',', ':'))+'\n')
    guard = incoming_guard(ROOT, receipt)
    text = text.replace(marker, "python3 -I - unpack <<'RP1_INCOMING_PREFLIGHT'\n"+
                        guard+"RP1_INCOMING_PREFLIGHT\n")
    path.write_text(text)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--preinst':
        preinst(Path(sys.argv[2]))
    else:
        stage(Path(sys.argv[1]))
