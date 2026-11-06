#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only public provider identity, derived from canonical source inputs."""
import hashlib
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
from version_identity import from_header, parse, debian_version

CONTRACT = 'rp1-gpclk-provider-identity-v1'
LIFECYCLE = 'rp1-gpclk-provider-lifecycle-v1'
INTERFACES = {
    'binding': 'rp1-gpclk-runtime-binding-v1',
    'readiness': 'rp1-gpclk-runtime-readiness-v1',
    'update': 'rp1-gpclk-runtime-update-v1',
    'lifecycle': LIFECYCLE,
}
CAPABILITIES = ['route-neutral-install', 'identical-repeat', 'same-version-replace',
                'semantic-upgrade', 'owned-remove', 'runtime-update', 'neutral-activation', 'release-audit']


def read(path, maximum=1024*1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('missing, substituted or oversized identity input: '+str(path))
    return path.read_bytes()


def describe(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    version, debian = from_header(read(root/'include/rp1_gpclk/version.h',4096).decode())
    return {
        'schemaVersion': 1, 'contract': CONTRACT,
        'repository': 'WsprryPi/RP1-DKMS', 'module': 'rp1-gpclk-dkms',
        'productVersion': version, 'debianVersion': debian,
        'interfaces': dict(INTERFACES), 'capabilities': list(CAPABILITIES),
        'compatibilityIdentities': {route: 'v'+version+'-rp1-'+route for route in ('gpio4','gpio20')},
        'uapiSha256': {name: hashlib.sha256(read(root/'include/uapi/linux'/header)).hexdigest()
                       for name,header in [('consumer','rp1_gpclk.h'),('controller','rp1_route_admin.h')]},
    }


def validate(value, requirements=None):
    fields = {'schemaVersion','contract','repository','module','productVersion','debianVersion',
              'interfaces','capabilities','compatibilityIdentities','uapiSha256'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['schemaVersion']) is not int
            or value['schemaVersion']!=1 or value['contract']!=CONTRACT
            or value['repository']!='WsprryPi/RP1-DKMS' or value['module']!='rp1-gpclk-dkms'):
        raise ValueError('provider identity contract differs')
    parse(value['productVersion'])
    if len(value['productVersion'])>48:raise ValueError('provider version exceeds UAPI identity capacity')
    if (not isinstance(value['debianVersion'],str) or len(value['debianVersion'])>128
            or not re.fullmatch(r'[0-9][0-9A-Za-z.+:~\-]*',value['debianVersion'])):
        raise ValueError('invalid native provider version')
    revision=value['debianVersion'].rsplit('-',1)[-1]
    if value['debianVersion']!=debian_version(value['productVersion'],revision):
        raise ValueError('native provider version contradicts product identity')
    if value['interfaces']!=INTERFACES:
        raise ValueError('provider lifecycle/runtime interface differs')
    caps=value['capabilities']
    if (not isinstance(caps,list) or any(not isinstance(x,str) for x in caps)
            or len(caps)!=len(set(caps)) or not set(CAPABILITIES)<=set(caps)):
        raise ValueError('provider lifecycle capabilities differ')
    identities=value['compatibilityIdentities']
    if identities!={route:'v'+value['productVersion']+'-rp1-'+route for route in ('gpio4','gpio20')}:
        raise ValueError('provider route identities differ')
    digests=value['uapiSha256']
    if (not isinstance(digests,dict) or set(digests)!={'consumer','controller'}
            or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in digests.values())):
        raise ValueError('provider UAPI identity differs')
    if requirements is not None:
        if (not isinstance(requirements,dict) or set(requirements)!={'schemaVersion','interfaces','uapiSha256','capabilities'}
                or type(requirements['schemaVersion']) is not int or requirements['schemaVersion']!=1
                or requirements['interfaces']!=value['interfaces']
                or requirements['uapiSha256']!=digests
                or not isinstance(requirements['capabilities'],list)
                or any(not isinstance(x,str) for x in requirements['capabilities'])
                or not set(requirements['capabilities'])<=set(caps)):
            raise ValueError('consumer interface/UAPI/capability requirements are not satisfied')
    return value


if __name__=='__main__':
    try:
        if len(sys.argv)!=1: raise ValueError('identity accepts no arguments')
        print(json.dumps(validate(describe()),sort_keys=True))
    except (OSError,ValueError,TypeError) as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)
