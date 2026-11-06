#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline attribution and status regressions; no device, process or network use."""
import sys as _identity_sys
from pathlib import Path as _IdentityPath
_identity_sys.path.insert(0, str(_IdentityPath(__file__).resolve().parents[1]/'scripts'))
from version_identity import VERSION, DEBIAN, COMPATIBILITY, expand
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import qualification_status as status


def fixture():
    software = json.loads((ROOT / 'tests/fixtures/qualification/software.json').read_text())
    evidence = json.loads((ROOT / 'tests/fixtures/qualification/evidence.json').read_text())
    for entry in evidence['routes']:
        entry['overlaySha256'] = software['overlaySha256'][entry['route']]
    value = {'SPDX-License-Identifier': 'MIT', 'schema': 'rp1-qualification-v1',
             'schemaVersion': 1, 'metadataTag': 'qualification-v1.0.0-r1', 'revision': 1,
             'metadataSource': {'commit': 'a'*40, 'tree': 'b'*40, 'inputSha256': 'c'*64},
             'software': software, 'evidence': evidence,
             'runtimeFiles': {'/usr/lib/rp1-gpclk-dkms/runtime-overlays/'+e['route']+'.dtbo':
                              e['runtimeOverlaySha256'] for e in evidence['routes']}}
    return value


def report(value, route='gpio4'):
    software = value['software']
    entry = next(e for e in value['evidence']['routes'] if e['route'] == route)
    result = {'contract': 'rp1-gpclk-runtime-readiness-v1', 'schemaVersion': 1,
        'identities': {'installedBinding': {'status': 'valid', 'value': {
            'sourceCommit': software['sourceCommit'], 'productVersion': '1.0.0',
            'uapiSha256': software['uapiSha256'], 'compatibilityIdentities': software['compatibilityIdentities'],
            'consumerNoteSha256': 'a'*64, 'controllerNoteSha256': 'b'*64,
            'files': value['runtimeFiles'], 'externalFiles': {'/companion': 'e'*64},
            'kernel': 'observed-kernel',
            'modules': {n: {'path': '/modules/'+n, 'installedFileSha256': d*64,
                           'buildNoteSha256': note*64, 'version': '1.0.0', 'kernel': 'observed-kernel'}
                        for n, d, note in [('rp1_gpclk_dkms', '1', 'a'), ('rp1_route_controller', '2', 'b')]}}}},
        'artifacts': {'fixture': {'status': 'exact'}}, 'routes': {'active': route},
        'modules': {n: {'status': 'loaded', 'version': '1.0.0', 'buildNoteSha256': d*64}
                    for n, d in [('rp1_gpclk_dkms', 'a'), ('rp1_route_controller', 'b')]},
        'manager': {'idle': {'state': {'outputLifecycle': {'snapshot': {
            'route': 1 if route == 'gpio4' else 2, 'compatibility': 3}}}}},
        'safety': {'operationalReady': True, 'outputInhibited': False}}
    binding = result['identities']['installedBinding']['value']
    binding['artifactSetSha256'] = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    expected = {**binding['files'], **binding['externalFiles'],
                **{m['path']: m['installedFileSha256'] for m in binding['modules'].values()}}
    result['artifacts'] = {p: {'status': 'exact', 'expectedSha256': h, 'actualSha256': h}
                           for p, h in expected.items()}
    return result


class Tests(unittest.TestCase):
    def setUp(self):
        software = fixture()['software']
        self.ownership = {'channel': 'release', 'sourceCommit': software['sourceCommit'],
            'tag': 'v1.0.0', 'manifest': {'package': {'sha256':
                software['assets']['rp1-gpclk-dkms_1.0.0-1_all.deb']}}}

    def interpret(self, metadata, observed, route):
        return status.interpret(metadata, observed, route, self.ownership)

    def test_schema_and_independent_scopes(self):
        import jsonschema
        value = fixture()
        jsonschema.Draft202012Validator(json.loads((ROOT / 'tests/fixtures/qualification/schema.json').read_text())).validate(value)
        self.assertNotEqual(*[e['caseSelectionSha256'] for e in value['evidence']['routes']])
        for route in ('gpio4', 'gpio20'):
            result = self.interpret(value, report(value, route), route)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(result['structuralCompatibility'], 'Compatible-unqualified')
            self.assertEqual(result['scope']['frequencyHz'], 14097100)
            self.assertFalse(result['permissionGate'])

    def test_no_false_unavailability_or_gate(self):
        value = fixture(); observed = report(value)
        observed['safety']['operationalReady'] = False
        observed['safety']['outputInhibited'] = True
        result = self.interpret(value, observed, 'gpio4')
        self.assertEqual(result['status'], 'verified')
        self.assertFalse(result['operationalReady'])
        self.assertEqual(status.interpret(None, observed, 'gpio4')['state'], 'Evidence missing')
        self.assertEqual(status.interpret(value, observed, None)['state'], 'No active route')

    def test_patch_identity_does_not_inherit_release_evidence(self):
        value = fixture()
        observed = report(value)
        binding = observed['identities']['installedBinding']['value']
        binding['productVersion'] = VERSION
        binding['compatibilityIdentities'] = {
            route: ('v' + VERSION + '-rp1-') + route for route in ('gpio4', 'gpio20')}
        # Even identical source/UAPI observations cannot transfer versioned evidence.
        result = self.interpret(value, observed, 'gpio4')
        self.assertEqual(result['status'], 'unattributed')
        self.assertEqual(result['reason'], 'installed source/UAPI/release differs')
        self.assertFalse(result['permissionGate'])

    def test_exact_runtime_attribution(self):
        value = fixture()
        for path in [('sourceCommit', '0'*40), ('productVersion', '2.0.0'),
                     ('uapiSha256', {}), ('compatibilityIdentities', {}),
                     ('consumerNoteSha256', '0'*64), ('files', {})]:
            observed = report(value)
            observed['identities']['installedBinding']['value'][path[0]] = path[1]
            self.assertEqual(self.interpret(value, observed, 'gpio4')['status'], 'unattributed')
        self.assertEqual(self.interpret(value, report(value, 'gpio20'), 'gpio4')['status'], 'unattributed')
        observed = report(value); observed['artifacts']['/companion']['status'] = 'mismatch'
        self.assertEqual(self.interpret(value, observed, 'gpio4')['status'], 'unattributed')
        observed = report(value); observed['artifacts'].pop('/companion')
        self.assertEqual(self.interpret(value, observed, 'gpio4')['status'], 'unattributed')
        self.ownership['manifest']['package']['sha256'] = '0'*64
        self.assertEqual(self.interpret(value, report(value), 'gpio4')['status'], 'unattributed')

    def test_pinned_metadata_refusals(self):
        value = fixture()
        def check(value, lock_value=None):
            raw = json.dumps(value).encode()
            lock = copy.deepcopy(lock_value or value)
            lock['assets'] = {'rp1-qualification.json': hashlib.sha256(raw).hexdigest()}
            return status.validate(raw, lock)
        self.assertEqual(check(value), value)
        for field, bad in [('revision', 0), ('metadataTag', 'wrong'), ('metadataSource', {}), ('software', {})]:
            changed = copy.deepcopy(value); changed[field] = bad
            with self.assertRaises(ValueError): check(changed, value)
        for change in ('duplicate', 'wrong-overlay', 'wrong-route'):
            changed = copy.deepcopy(value)
            if change == 'duplicate': changed['evidence']['routes'][1] = changed['evidence']['routes'][0]
            if change == 'wrong-overlay': changed['evidence']['routes'][0]['overlaySha256'] = '0'*64
            if change == 'wrong-route': changed['evidence']['routes'][0]['routeId'] = 'v1.0.0-rp1-gpio20'
            with self.assertRaises(ValueError): check(changed)
        with self.assertRaises(ValueError): status.strict_json(b'{"revision":1,"revision":2}')
        with self.assertRaises(ValueError): status.validate(b'{}', {'assets': {'rp1-qualification.json': '0'*64}})



if __name__ == '__main__':
    __import__("nonempty_unittest").main()
