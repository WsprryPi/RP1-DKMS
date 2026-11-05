#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify installed signatures and module indices after native DKMS transactions.

DKMS 3.2's do_depmod can lose depmod's failure status. Never infer current
indices from its success message. This helper never loads or unloads anything.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_preflight import KERNEL, check, framework, kernel_configuration, module_elf
from package_signatures import SignatureFailure, verify


class IndexFailure(Exception):
    def __init__(self, result):
        self.result = result


def update(root=Path('/'), operation='configure'):
    check(root, operation)
    results = []
    signatures = []
    configuration = framework(root)
    for directory in sorted((root/'lib/modules').glob('*')):
        if not KERNEL.fullmatch(directory.name):
            continue
        for name in ('rp1_gpclk_dkms', 'rp1_route_controller'):
            paths = list((directory/'updates/dkms').glob(name+'.ko*'))
            if len(paths) != (1 if operation == 'configure' else 0):
                raise ValueError('installed module set differs before depmod: '+directory.name)
            if operation == 'configure' and re.search(r'^CONFIG_MODULE_SIG_HASH=', kernel_configuration(directory), re.M):
                certificate = root/configuration.get('mok_certificate', '/var/lib/dkms/mok.pub').lstrip('/')
                try:
                    signatures.append(verify(module_elf(paths[0].resolve()), certificate, paths[0]))
                except SignatureFailure as error:
                    raise IndexFailure(error.result) from error
        command = ['/usr/sbin/depmod', '-a', directory.name]
        if root != Path('/'):
            command = ['/usr/sbin/depmod', '-b', str(root), '-a', directory.name]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise IndexFailure({'stage': 'depmod', 'command': command, 'exitStatus': 124,
                                'diagnostic': 'module-index update timed out'})
        except OSError as error:
            raise IndexFailure({'stage': 'depmod', 'command': command, 'exitStatus': 127,
                                'diagnostic': str(error)[:4096]}) from error
        result = {'stage': 'depmod', 'command': command, 'exitStatus': completed.returncode,
                  'diagnostic': (completed.stdout+completed.stderr)[-8192:]}
        results.append(result)
        if completed.returncode:
            raise IndexFailure(result)
    return {'contract': 'rp1-gpclk-package-indices-v1', 'operation': operation,
            'status': 'complete', 'results': results, 'signatures': signatures, 'executionAuthorized': False}


if __name__ == '__main__':
    try:
        if sys.argv[1:] not in ([], ['remove']):
            raise ValueError('expected no arguments or remove')
        print(json.dumps(update(operation='remove' if sys.argv[1:] else 'configure')))
    except IndexFailure as error:
        print(json.dumps({'contract': 'rp1-gpclk-package-indices-v1', 'status': 'failed',
                          'executionAuthorized': False,
                          **error.result}), file=sys.stderr)
        raise SystemExit(error.result['exitStatus'] if error.result['exitStatus'] > 0 else 1)
    except (OSError, ValueError) as error:
        print(json.dumps({'contract': 'rp1-gpclk-package-indices-v1', 'status': 'failed',
                          'stage': 'inventory', 'exitStatus': 1,
                          'executionAuthorized': False, 'diagnostic': str(error)[:4096]}), file=sys.stderr)
        raise SystemExit(1)
