# SPDX-License-Identifier: MIT
"""Fixed runtime deployment destinations; kernel identity is binding-specific."""
LIB = '/usr/lib/rp1-gpclk-dkms/'
MODULES = ('rp1_route_controller', 'rp1_gpclk_dkms')
INVENTORY = {LIB+name: 'scripts/'+name for name in (
    'runtime_controller_admin.py', 'runtime_manager.py', 'runtime_route_client.py',
    'runtime_layout.py', 'runtime_deployment.py', 'runtime_output.py',
    'runtime_application.py', 'runtime_activation.py', 'runtime_provider.py',
    'runtime_binding.py')}
INVENTORY[LIB+'package_preflight.py'] = 'scripts/package_preflight.py'
INVENTORY['/usr/lib/systemd/system/rp1-gpclk-route-manager.socket'] = 'systemd/rp1-gpclk-route-manager.socket'
INVENTORY['/usr/lib/systemd/system/rp1-gpclk-route-manager@.service'] = 'systemd/rp1-gpclk-route-manager@.service'
INVENTORY['/etc/systemd/system/rp1-gpclk-route-manager@.service.d/95-runtime-controller.conf'] = 'systemd/95-runtime-controller.conf'
INVENTORY[LIB+'schema/rp1-gpclk-runtime-readiness-v1.schema.json'] = 'schema/rp1-gpclk-runtime-readiness-v1.schema.json'

for name in ('rp1_gpclk.h', 'rp1_route_admin.h'):
    INVENTORY[LIB+'runtime-uapi/'+name] = 'include/uapi/linux/'+name
for route in ('gpio4', 'gpio20'):
    INVENTORY[LIB+'runtime-overlays/'+route+'.dtbo'] = 'build/runtime-controller/'+route+'.dtbo'
