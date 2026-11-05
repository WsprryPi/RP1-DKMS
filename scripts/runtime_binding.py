#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Canonical validation for the exact runtime-profile binding."""
import hashlib
import json
import re

from runtime_layout import INVENTORY, MODULES

CONTRACT = 'rp1-gpclk-runtime-binding-v3'
PRODUCT_VERSION = '0.99.0'
COMPATIBILITY = {'gpio4': 'v0.99.0-rp1-gpio4', 'gpio20': 'v0.99.0-rp1-gpio20'}
APPLICATION = '/usr/local/lib/wsprrypi/route_application.py'
EXTERNAL_PATHS = {APPLICATION}


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def validate(binding):
    fields = {'schemaVersion', 'contract', 'productVersion',
        'compatibilityIdentities', 'sourceCommit', 'kernel', 'files', 'modules',
        'externalFiles', 'uapiSha256', 'controllerNoteSha256',
        'consumerNoteSha256', 'artifactSetSha256'}
    if (not isinstance(binding, dict) or set(binding) != fields or
            type(binding.get('schemaVersion')) is not int or binding['schemaVersion'] != 3 or
            binding.get('contract') != CONTRACT or binding.get('productVersion') != PRODUCT_VERSION or
            not isinstance(binding.get('kernel'), str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}', binding['kernel']) or
            binding.get('compatibilityIdentities') != COMPATIBILITY or
            not isinstance(binding.get('sourceCommit'), str) or
            not re.fullmatch('[0-9a-f]{40}', binding['sourceCommit']) or
            not isinstance(binding.get('files'), dict) or set(binding['files']) != set(INVENTORY) or
            not isinstance(binding.get('modules'), dict) or set(binding['modules']) != set(MODULES) or
            not isinstance(binding.get('externalFiles'), dict) or set(binding['externalFiles']) != EXTERNAL_PATHS or
            not isinstance(binding.get('uapiSha256'), dict) or
            set(binding['uapiSha256']) != {'consumer', 'controller'}):
        raise ValueError('runtime binding schema/identity mismatch')
    module_fields = {'name', 'path', 'installedFileSha256', 'decompressedElfSha256',
                     'compression', 'buildNoteSha256', 'version', 'kernel'}
    kernel = binding['kernel']
    for name, module in binding['modules'].items():
        suffix = r'\.ko(?:\.(?:xz|gz|zst|bz2))?'
        if (not isinstance(module, dict) or set(module) != module_fields or
                module.get('name') != name or module.get('kernel') != kernel or
                module.get('version') != PRODUCT_VERSION or
                module.get('compression') not in {'none', 'xz', 'gz', 'zst', 'bz2'} or
                not re.fullmatch(rf'/lib/modules/{re.escape(kernel)}/updates/dkms/{re.escape(name)}{suffix}',
                                 module.get('path', ''))):
            raise ValueError('runtime binding module identity mismatch')
        expected_compression = ('none' if module['path'].endswith('.ko')
                                else module['path'].rsplit('.', 1)[1])
        if module['compression'] != expected_compression:
            raise ValueError('runtime binding module compression mismatch')
    digests = (list(binding['files'].values()) + list(binding['externalFiles'].values()) +
               [module[field] for module in binding['modules'].values()
                for field in ('installedFileSha256', 'decompressedElfSha256', 'buildNoteSha256')] +
               list(binding['uapiSha256'].values()) + [binding['controllerNoteSha256'],
               binding['consumerNoteSha256'], binding['artifactSetSha256']])
    if any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
           for value in digests):
        raise ValueError('runtime binding digest schema')
    if (binding['uapiSha256']['consumer'] != binding['files'][
            '/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_gpclk.h'] or
            binding['uapiSha256']['controller'] != binding['files'][
            '/usr/lib/rp1-gpclk-dkms/runtime-uapi/rp1_route_admin.h']):
        raise ValueError('runtime binding UAPI identity mismatch')
    if (binding['controllerNoteSha256'] != binding['modules']['rp1_route_controller']['buildNoteSha256'] or
            binding['consumerNoteSha256'] != binding['modules']['rp1_gpclk_dkms']['buildNoteSha256']):
        raise ValueError('runtime binding module note identity mismatch')
    identity = dict(binding)
    identity.pop('artifactSetSha256')
    if canonical_digest(identity) != binding['artifactSetSha256']:
        raise ValueError('runtime binding artifact-set digest mismatch')
    return binding
