#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline generation of fixed embedded DTBOs; never installs or loads."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from overlay_builder import build_dtbo

ROOT = Path(__file__).resolve().parents[1]


def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    dtc = shutil.which('dtc')
    fdtput = shutil.which('fdtput')
    if not dtc or not fdtput:
        raise SystemExit('dtc and fdtput required')
    header = ['/* SPDX-License-Identifier: GPL-2.0-only OR MIT */']
    identities = {}
    for route in ('gpio4', 'gpio20'):
        source = ROOT / 'overlays' / f'rp1-gpclk-{route}.dts'
        output = destination / f'{route}.dtbo'
        build_dtbo(source, output, dtc)
        # Runtime routes have no downstream overlay consumers. Exported labels
        # would add properties to the base /__symbols__ node, whose property
        # allocations the kernel warns cannot be reclaimed on removal. Keep
        # every overlay node/phandle and both fixup tables unchanged.
        subprocess.run([fdtput, '-r', str(output), '/__symbols__'], check=True,
                       capture_output=True, timeout=10)
        data = output.read_bytes()
        if not 40 < len(data) < 65536:
            raise ValueError('overlay bounds')
        identities[route] = {'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                             'dtboSha256': hashlib.sha256(data).hexdigest()}
        header.append(f'static const unsigned char {route}_dtbo[] __aligned(8) = {{')
        for start in range(0, len(data), 16):
            header.append('\t' + ', '.join(f'0x{x:02x}' for x in data[start:start+16]) + ',')
        header.append('};')
    (destination / 'overlays.h').write_text('\n'.join(header) + '\n')
    (destination / 'identity.json').write_text(json.dumps(identities, indent=2) + '\n')
    return identities


if __name__ == '__main__':
    generate(ROOT / 'build/runtime-controller')
