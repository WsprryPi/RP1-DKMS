#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline tests for runtime reconciliation; no target effects."""
import copy
import json
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_output as output
import runtime_manager as manager
import runtime_controller_admin as admin
from check_runtime_manager import System

class Machine(System):
    def __init__(self):
        super().__init__()
        admin.execute(self, 2)
        self.snapshot = dict(route=2, compatibility=3, reason=0, operation=0,
            terminal=0, event=0, flags=0, fault=1, owner=1, lease=1,
            outputInhibited=1, operationalReady=2, drain=0, gpio=2,
            clock=2, dma=2, stable=2, reserved=0)
    def output_snapshot(self): return self.snapshot.copy()
    def output_resume(self): self.check_inhibit(); self.mask = False

class Tests(unittest.TestCase):
    def request(self, machine, operation='idle', **extra):
        return manager._dispatch(dict(schemaVersion=3, operation=operation, route='gpio20', **extra), lambda:machine)
    def test_idle_and_operation_reconcile_do_not_authorize_or_change_route(self):
        machine = Machine()
        before = copy.deepcopy(machine.value)
        for operation in ('idle','reconcile-output'):
            result = self.request(machine, operation)['state']['outputLifecycle']
            self.assertTrue(result['ready'])
            self.assertIs(result['executionAuthorized'], False)
            self.assertIs(type(result['executionAuthorized']), bool)
            self.assertEqual(result['productionAuthority'], 'root-owned-endpoint')
            self.assertEqual(machine.value, before)
            self.assertTrue(machine.mask)
    def test_active_authorization_is_reported_without_claiming_idle_readiness(self):
        machine = Machine()
        machine.snapshot.update(owner=2, lease=2, operation=1, stable=1,
                                gpio=1, clock=1, dma=1)
        result = self.request(machine)['state']['outputLifecycle']
        self.assertIs(result['executionAuthorized'], True)
        self.assertIs(result['ready'], False)
        self.assertTrue(machine.mask)
        with self.assertRaises(ValueError):
            self.request(machine, 'resume', execute=True)
    def test_authorization_evidence_is_strict_and_coherent(self):
        changes = (
            {'owner': 2}, {'lease': 2}, {'owner': 0, 'lease': 0},
            {'owner': True, 'lease': True}, {'owner': '1', 'lease': '1'},
            {'owner': None, 'lease': None}, {'operation': 1},
            {'operation': 0, 'terminal': 1}, {'operation': 3, 'terminal': 0},
            {'operation': 3, 'terminal': 5}, {'operation': 4, 'terminal': 1},
            {'operation': 5})
        for change in changes:
            with self.subTest(change=change):
                machine = Machine(); machine.snapshot.update(change)
                with self.assertRaises(ValueError): self.request(machine)
    def test_active_authorization_requires_current_route_and_compatibility(self):
        for change in ({'route': 1}, {'route': '2'}, {'compatibility': 0},
                       {'compatibility': '3'}):
            with self.subTest(change=change):
                machine = Machine()
                machine.snapshot.update(owner=2, lease=2, operation=1, **change)
                with self.assertRaises(ValueError): self.request(machine)
    def test_lifecycle_serialization_preserves_required_boolean(self):
        lifecycle = self.request(Machine())['state']['outputLifecycle']
        decoded = json.loads(json.dumps(lifecycle))
        self.assertIn('executionAuthorized', decoded)
        self.assertIs(type(decoded['executionAuthorized']), bool)
        self.assertIs(output.validate_lifecycle(decoded), decoded)
        for value in (None, 0, 1, 'false', 'true'):
            changed = copy.deepcopy(decoded)
            changed['executionAuthorized'] = value
            with self.assertRaises(ValueError): output.validate_lifecycle(changed)
    def test_busy_fault_unknown_and_route_mismatch(self):
        for key in ('fault','owner','lease','outputInhibited','operationalReady',
                    'gpio','clock','dma','stable','route','compatibility'):
            machine = Machine(); machine.snapshot[key] = 0
            with self.assertRaises(ValueError, msg=key): self.request(machine)
    def test_journal_identity_and_pending_effects(self):
        for key, value in [('boot','stale'),('session',0),('binding','stale'),('phase','remove-intent'),('observation',{})]:
            machine = Machine(); machine.journal[key] = value
            with self.assertRaises(ValueError, msg=key): self.request(machine)
    def test_explicit_resume_only_releases_mask(self):
        machine = Machine(); before = machine.value.copy()
        with self.assertRaises(ValueError): self.request(machine, 'resume')
        result = self.request(machine, 'resume', execute=True)
        self.assertFalse(result['state']['applicationInhibited'])
        self.assertIs(result['state']['outputLifecycle']['executionAuthorized'], False)
        self.assertEqual(result['state']['outputLifecycle']['productionAuthority'],
                         'root-owned-endpoint')
        self.assertEqual(machine.value, before)
    def test_snapshot_layout_and_reserved_fields_are_strict(self):
        fields = [2, 3, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 0, 2, 2, 2, 2, 0]
        data = output.SNAPSHOT.pack(output.SNAPSHOT.size, 0, 0, *fields,
            *([0] * 6), b'module', b'build', b'compat', *([0] * 8))
        self.assertEqual(output.SNAPSHOT.size, 384)
        parsed = output.parse_snapshot(data)
        self.assertEqual(parsed['route'], 2)
        self.assertEqual(parsed['compatibility'], 3)
        self.assertEqual(parsed['outputInhibited'], 1)
        self.assertEqual(parsed['operationalReady'], 2)
        for offset in (2, 4 + 17 * 4, output.SNAPSHOT.size - 8):
            changed = bytearray(data)
            if offset == 2:
                struct.pack_into('=H', changed, offset, 1)
            elif offset == 4 + 17 * 4:
                struct.pack_into('=I', changed, 8 + 17 * 4, 1)
            else:
                struct.pack_into('=Q', changed, offset, 1)
            with self.assertRaises(ValueError):
                output.parse_snapshot(changed)
    def test_no_legacy_mutation_translation_or_extra_fields(self):
        for value in (dict(schemaVersion=1,operation='idle',route='gpio20'),
                      dict(schemaVersion=3,operation='idle',route='gpio20',execute=True)):
            with self.assertRaises(ValueError): manager._dispatch(value, Machine)

if __name__ == '__main__': __import__("nonempty_unittest").main()
