#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage the fixed passive package payload; never install on a host."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def payload_sources(root=ROOT):
    prefix = 'usr/src/rp1-gpclk-dkms-0.99.0/'
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
        'usr/libexec/rp1-gpclk-dkms/package_preflight.py': 'scripts/package_preflight.py',
        'usr/libexec/rp1-gpclk-dkms/package_indices.py': 'scripts/package_indices.py',
        'usr/libexec/rp1-gpclk-dkms/package_signatures.py': 'scripts/package_signatures.py',
        'usr/libexec/rp1-gpclk-dkms/rp1-gpclk-route-manager': 'scripts/rp1-gpclk-route-manager.py',
        'usr/sbin/rp1-gpclk-route-manager': 'scripts/rp1-gpclk-route-manager.py',
        'usr/share/rp1-gpclk-dkms/0.99.0/rp1-gpclk-route-manager.schema.json': 'schema/rp1-gpclk-route-manager.schema.json',
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
    text = text.replace('#MODULE_VERSION#', '0.99.0')
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
        path.chmod(0o755 if target.endswith('/rp1-gpclk-route-manager') or
                   target.startswith('usr/libexec/rp1-gpclk-dkms/') else 0o644)
    dkms = destination/'usr/src/rp1-gpclk-dkms-0.99.0/dkms.conf'
    dkms.write_text(render_dkms((ROOT/'dkms.conf').read_text()))
    dkms.chmod(0o644)


def preinst(destination):
    """Embed the incoming read-only guard before unpack; trust no old helper."""
    path = destination/'DEBIAN/preinst'
    marker = '# RP1_INCOMING_PREFLIGHT\n'
    text = path.read_text()
    if text.count(marker) != 1:
        raise ValueError('incoming package guard marker differs')
    guard = (ROOT/'scripts/package_preflight.py').read_text()
    text = text.replace(marker, "python3 -I - unpack <<'RP1_INCOMING_PREFLIGHT'\n"+
                        guard+"RP1_INCOMING_PREFLIGHT\n")
    path.write_text(text)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--preinst':
        preinst(Path(sys.argv[2]))
    else:
        stage(Path(sys.argv[1]))
