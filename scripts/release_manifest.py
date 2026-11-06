#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Canonical candidate metadata, derived from actual package bytes."""
import ast
from datetime import datetime, timezone
import re
from release_contract import (BEHAVIOR, COMPATIBILITY, DEB, DEBIAN,
    MANIFEST, METADATA, MODULES, PACKAGE, RESULT, SOURCE, VERSION, canonical,
    command, inventory, package_members, read_json, require, sha, tools)


def validate_source(files):
    def text(name):
        return files[name][1].decode()
    require(f'#define RP1_GPCLK_MODULE_VERSION "{VERSION}"' in text('include/rp1_gpclk/version.h'),
            'canonical module version mismatch')
    require('MODULE_VERSION(RP1_GPCLK_MODULE_VERSION);' in text('controller/main.c'),
            'controller version mismatch')
    for token, name in [(f'MODULE_VERSION := {VERSION}', 'debian/rules'),
                        (f'({DEBIAN}) UNRELEASED;', 'debian/changelog'),
                        (f'VERSION="{VERSION}"; DEBIAN_VERSION="{DEBIAN}"', 'scripts/rp1-gpclk-route-manager.py')]:
        require(token in text(name), 'package version mismatch: '+name)
    for name, token in (
        ('include/rp1_gpclk/compatibility.h', '#define RP1_GPCLK_COMPATIBILITY_VERSION "0.0.1"'),
        ('scripts/development_route_manager.py', 'value.get("renderedVersion")!="0.0.1"'),
        ('scripts/rp1-gpclk-diagnostics.py', '"rp1_gpclk_dkms", "0.0.1"')):
        require(token in text(name), 'current version source mismatch: '+name)
    binding = ast.parse(text('scripts/runtime_binding.py'))
    constants = {n.targets[0].id: ast.literal_eval(n.value) for n in binding.body
                 if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id in ('CONTRACT', 'PRODUCT_VERSION', 'COMPATIBILITY')}
    require(constants == {'CONTRACT': 'rp1-gpclk-runtime-binding-v1', 'PRODUCT_VERSION': VERSION,
                          'COMPATIBILITY': {r: f'v{VERSION}-rp1-{r}' for r in ('gpio4', 'gpio20')}},
            'runtime binding identity mismatch')
    for route in ('gpio4', 'gpio20'):
        require(f'"v{VERSION}-rp1-{route}"' in text('include/rp1_gpclk/compatibility.h'),
                'compatibility identity mismatch')
        overlay = text('overlays/rp1-gpclk-'+route+'.dts')
        require(f'pins = "{route}"' in overlay and f'rp1-gpclk-dkms-{route}' in overlay,
                'overlay route substitution')
    consumer = read_json(files['release/wsprrypi-consumer-contract.json'][1])
    require(consumer['requiredAssets'] == ['SHA256SUMS', MANIFEST, DEB],
            'consumer required assets differ from current package identity')
    uapi = read_json(files['uapi-identity.json'][1])
    require(uapi['sha256'] == sha(files['include/uapi/linux/rp1_gpclk.h'][1]), 'canonical UAPI mismatch')
    dkms = text('dkms.conf')
    require(dkms.count('#MODULE_VERSION#') == 1 and
            'PACKAGE_VERSION="#MODULE_VERSION#"' in dkms, 'DKMS template identity mismatch')
    for name, (_, data) in files.items():
        if name.startswith(('src/', 'controller/', 'include/', 'overlays/')):
            require(not re.search(br'@(?:VERSION|COMMIT|SHA256)@|#(?:VERSION|COMMIT|SHA256)#', data),
                    'unresolved placeholder in '+name)


def documents(files, commit, tree, timestamp, directory, release=False):
    members, controls = package_members(directory/DEB)
    member_map = {m['path']: m for m in members}
    inv = inventory(members)
    prefix = f'usr/src/{PACKAGE}-{VERSION}/'
    uapi_path = prefix+'include/uapi/linux/rp1_gpclk.h'
    manifest = {'schema': 'rp1-gpclk-dkms-installation-manifest-v1', 'schemaVersion': 1,
        'repository': 'WsprryPi/RP1-DKMS', 'releaseTag': 'v'+VERSION, 'sourceCommit': commit,
        'productVersion': VERSION, 'debianVersion': DEBIAN,
        'package': {'name': PACKAGE, 'filename': DEB, 'sha256': sha((directory/DEB).read_bytes())},
        'dkmsModule': PACKAGE, 'kernelModule': MODULES[0],
        'uapi': {'path': uapi_path, 'sha256': member_map[uapi_path]['sha256']},
        'administrationProtocol': 'rp1-gpclk-route-manager', 'packageInventory': inv,
        'packageInventorySha256': sha(canonical(inv)), 'installationBehavior': BEHAVIOR,
        'releaseChannel': 'release'}
    routes = {}
    for route, number in (('gpio4', 1), ('gpio20', 2)):
        source = 'overlays/rp1-gpclk-'+route+'.dts'
        installed = f'usr/lib/{PACKAGE}/overlays/rp1-gpclk-{route}.dtbo'
        routes[route] = {'routeId': number, 'compatibilityId': f'v{VERSION}-rp1-{route}',
            'sourcePath': source, 'sourceSha256': sha(files[source][1]),
            'packagePath': installed, 'dtboSha256': member_map[installed]['sha256']}
    classification = 'release' if release else 'candidate'
    metadata = {'schema': f'rp1-gpclk-{classification}-provenance-v1', 'schemaVersion': 1,
        'SPDX-License-Identifier': 'MIT', 'classification': classification, 'published': False,
        'productVersion': VERSION, 'debianVersion': DEBIAN, 'intendedTag': 'v'+VERSION,
        'releaseTag': 'v'+VERSION if release else None,
        'releaseUrl': 'https://github.com/WsprryPi/RP1-DKMS/releases/tag/v'+VERSION if release else None,
        'githubAssetDigest': None,
        'sourceCommit': commit, 'sourceTree': tree,
        'sourceArchive': {'filename': SOURCE, 'sha256': sha((directory/SOURCE).read_bytes())},
        'package': {'filename': DEB, 'sha256': sha((directory/DEB).read_bytes()),
                    'controlSha256': sha(command(['dpkg-deb', '-f', str(directory/DEB)])),
                    'name': PACKAGE, 'version': DEBIAN, 'architecture': 'all'},
        'installationManifestSha256': sha(canonical(manifest)+b'\n'),
        'packageOwnership': {'uid': 0, 'gid': 0},
        'controlInventory': inventory(controls),
        'dkms': {'name': PACKAGE, 'version': VERSION, 'profile': 'runtime-controller',
                 'configurationPath': prefix+'dkms.conf',
                 'configurationSha256': member_map[prefix+'dkms.conf']['sha256']},
        'modules': [{'name': name, 'version': VERSION, 'origin': 'target-generated-by-dkms',
                     'packagedElf': False, 'installedFileSha256': None,
                     'decompressedElfSha256': None, 'compression': None,
                     'vermagic': None, 'buildNoteSha256': None} for name in MODULES],
        'uapi': {name: {'sourcePath': 'include/uapi/linux/'+name,
                       'installedPath': prefix+'include/uapi/linux/'+name,
                       'sha256': sha(files['include/uapi/linux/'+name][1])}
                 for name in ('rp1_gpclk.h', 'rp1_route_admin.h')},
        'routes': routes,
        'runtime': {'binding': 'rp1-gpclk-runtime-binding-v1',
                    'readiness': 'rp1-gpclk-runtime-readiness-v1',
                    'update': 'rp1-gpclk-runtime-update-v1',
                    'tools': {name: sha(data) for name, (_, data) in files.items()
                              if name.startswith('scripts/runtime_') and name.endswith('.py')},
                    'schemas': {name: sha(data) for name, (_, data) in files.items()
                                if name.startswith('schema/') and name.endswith('.json')}},
        'signing': {'package': 'unsigned', 'source': 'unsigned', 'privateKeyIncluded': False,
                    'targetModules': 'administrator-existing-identity-required-when-signing',
                    'trustEnrollment': 'separate-administrator-operation'},
        'build': {'sourceDateEpoch': timestamp, 'locale': 'C', 'timezone': 'UTC',
                  'umask': '0022', 'compression': 'gzip-mtime-zero-source;dpkg-gzip-level9-single-thread',
                  'tools': tools()},
        'qualification': {'hardware': False, 'rf': False, 'product': False,
                          'wsprrypiAcceptance': False, 'lifecycle': False},
        'consumerContract': read_json(files['release/wsprrypi-consumer-contract.json'][1])}
    compatibility = {'SPDX-License-Identifier': 'MIT', 'schemaVersion': 1,
        'manifestId': f'v{VERSION}-'+('' if release else 'candidate-')+commit,
        'generatedAt': datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace('+00:00', 'Z'),
        'module': {'name': MODULES[0], 'release': VERSION, 'sourceCommit': commit,
                   'sourceArchiveSha256': metadata['sourceArchive']['sha256'],
                   'uapiHeaderSha256': manifest['uapi']['sha256']},
        'defaultState': 'Unavailable', 'entries': []}
    result = {'SPDX-License-Identifier': 'MIT', 'schema': 'rp1-gpclk-candidate-validation-v1',
        'sourceCommit': commit, 'sourceTree': tree, 'classification': classification,
        'reproducibility': {'independentCleanBuilds': 2, 'byteIdentical': True},
        'sourceSha256': metadata['sourceArchive']['sha256'],
        'packageSha256': manifest['package']['sha256'], 'published': False,
        'qualification': False}
    return {MANIFEST: manifest, METADATA: metadata, COMPATIBILITY: compatibility, RESULT: result}


def encode_documents(directory, values):
    for name, value in values.items():
        (directory/name).write_bytes(canonical(value)+b'\n')
