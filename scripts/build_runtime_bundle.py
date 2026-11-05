#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a local reviewed runtime bundle; does not install or activate anything."""
import argparse
import json
from pathlib import Path
from build_runtime_binding import build, module_payload, ROOT
from runtime_controller_admin import digest
from runtime_layout import INVENTORY
from build_runtime_controller import generate


def bundle(modules, output, application_companion, kernel=None):
    generate(ROOT / "build/runtime-controller")
    binding = build(modules, application_companion, kernel)
    # Reject an ordinary consumer and mismatched kernel before producing a bundle.
    consumer = module_payload(modules / Path(
        binding['modules']['rp1_gpclk_dkms']['path']).name)[0]
    controller = module_payload(modules / Path(
        binding['modules']['rp1_route_controller']['path']).name)[0]
    if b'rp1_runtime_controller=1\0' not in consumer or b'rp1_route_controller' not in consumer:
        raise ValueError('interlocked consumer required')
    if b'alias=of:' in consumer:
        raise ValueError('runtime consumer must not autoload from OF aliases')
    for data in (consumer, controller):
        if (not data.startswith(b'\x7fELF\x02\x01') or
                b'vermagic='+binding['kernel'].encode()+b' ' not in data):
            raise ValueError('exact-kernel ELF64 module required')
    for route in ('gpio4', 'gpio20'):
        if (ROOT / 'build/runtime-controller' / (route+'.dtbo')).read_bytes() not in controller:
            raise ValueError('controller embedded overlay differs from canonical overlay')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for destination, source in INVENTORY.items():
        data = (ROOT / source).read_bytes()
        if digest(data) != binding['files'][destination]:
            raise ValueError('source changed during bundle creation')
        (output / (digest(destination.encode())+'.bin')).write_bytes(data)
    (output / 'binding.json').write_text(json.dumps(binding, sort_keys=True, indent=2)+'\n')
    # Standalone bootstrap tool, with its dependencies, for review before running.
    for name in ('runtime_deployment.py', 'runtime_controller_admin.py', 'runtime_layout.py',
                 'runtime_application.py', 'runtime_output.py', 'runtime_provider.py',
                 'runtime_binding.py', 'runtime_activation.py', 'runtime_route_client.py',
                 'runtime_manager.py', 'package_preflight.py'):
        (output / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    return binding


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('modules', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--application-companion', required=True, type=Path)
    parser.add_argument('--kernel')
    args = parser.parse_args()
    bundle(args.modules, args.output, args.application_companion, args.kernel)
