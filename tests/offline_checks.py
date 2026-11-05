#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One ordered registry, consumed directly by the isolated offline dispatcher."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    'check_development_workflow.py',
    'check_development_identity.py',
    'check_spdx.py',
    'check_test_inventory.py',
    'check_uapi_identity.py',
    'check_uapi_static.py',
    'check_target_fault_contract.py',
    'check_clock_disabled_source_boundary.py',
    'check_pll_sys_parent_contract.py',
    'check_build_contract.py',
    'check_route_uapi_contract.py',
    'check_debian_packaging.py',
    'check_package_lifecycle.py',
    'check_release_candidate.py',
    'check_overlay_admin_contract.py',
    'check_signing_policy.py',
    'check_diagnostics_contract.py',
    'check_qualification_metadata.py',
    'check_qualification_harness_contract.py',
    'check_dkms_kernel_scope.py',
    'check_route_manager.py',
    'check_runtime_inventory.py',
    'check_runtime_controller.py',
    'check_runtime_manager.py',
    'check_runtime_provider.py',
    'check_runtime_activation.py',
    'check_runtime_output.py',
    'check_runtime_restoration.py',
    'check_runtime_inhibitor_cleanup.py',
    'check_development_route_manager.py',
    'check_doc_links.py',
)


def main():
    from check_test_inventory import validate
    validate()
    for name in CHECKS:
        subprocess.run([sys.executable, str(ROOT/'tests'/name)], cwd=ROOT, check=True)
        print('Completed standalone check: '+name, flush=True)


if __name__ == '__main__':
    main()
