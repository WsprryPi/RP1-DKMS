#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the one current runtime format and reject retired formats."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_route_client as client
import runtime_activation as activation
import runtime_binding as binding
import runtime_deployment as deployment
import runtime_manager as manager
import runtime_output as output
from check_runtime_activation import System, lock
from check_runtime_manager import Files, deployment_values
from check_runtime_provider import exact_binding


class Tests(unittest.TestCase):
    def test_binding_rejects_retired_contracts_and_schema_numbers(self):
        current = exact_binding()
        self.assertEqual(binding.validate(current), current)
        self.assertEqual(current['schemaVersion'], 1)
        self.assertEqual(current['contract'], 'rp1-gpclk-runtime-binding-v1')
        for version in (0, 2, 3, True, 1.0):
            changed = copy.deepcopy(current)
            changed['schemaVersion'] = version
            changed['artifactSetSha256'] = binding.canonical_digest(
                {k: v for k, v in changed.items() if k != 'artifactSetSha256'})
            with self.subTest(version=version), self.assertRaises(ValueError):
                binding.validate(changed)
        for contract in ('rp1-gpclk-runtime-binding-v2', 'rp1-gpclk-runtime-binding-v3'):
            changed = copy.deepcopy(current)
            changed['contract'] = contract
            changed['artifactSetSha256'] = binding.canonical_digest(
                {k: v for k, v in changed.items() if k != 'artifactSetSha256'})
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                binding.validate(changed)

    def test_manager_and_output_refuse_old_requests_before_host_access(self):
        def forbidden():
            self.fail('invalid format reached the administrative host')
        self.assertEqual(manager.parse({'schemaVersion': 1, 'operation': 'query'})['schemaVersion'], 1)
        output.parse({'schemaVersion': 1, 'operation': 'idle', 'route': 'gpio4'})
        for version in (0, 2, 3, True, 1.0):
            with self.subTest(version=version), self.assertRaises(ValueError):
                manager.dispatch({'schemaVersion': version, 'operation': 'query'}, forbidden)
            with self.subTest(output=version), self.assertRaises(ValueError):
                manager.dispatch({'schemaVersion': version, 'operation': 'idle', 'route': 'gpio4'}, forbidden)
            with self.subTest(restore=version), self.assertRaises(ValueError):
                manager.dispatch({'schemaVersion': version, 'operation': 'restore', 'execute': True}, forbidden)

    def test_route_client_rejects_noninteger_and_retired_response_formats(self):
        for version in (0, 2, 3, True, 1.0):
            reply = {'schemaVersion': version, 'contract': client.CONTRACT}
            stream = MagicMock()
            stream.recv.side_effect = [json.dumps(reply).encode(), b'']
            socket = MagicMock()
            socket.__enter__.return_value = stream
            with self.subTest(version=version), patch.object(client.socket, 'socket', return_value=socket), self.assertRaises(ValueError):
                client.exchange({'schemaVersion': 1, 'operation': 'query'})

    def test_activation_contexts_share_one_strict_plan_format(self):
        system = System()
        initial = activation.activation_plan(system)
        self.assertEqual(initial['version'], 1)
        self.assertEqual(initial['activationContext'], 'initial')
        activation.ensure(system, initial, activation.plan_digest(initial), lock)
        repeated = activation.activation_plan(system)
        self.assertEqual(repeated['version'], 1)
        self.assertEqual(repeated['activationContext'], 'idempotent')
        system.boot_id = '00000000-0000-0000-0000-000000000002'
        system.controller = False
        system.socket_active = False
        system.state['session'] = 8
        reboot = activation.activation_plan(system)
        self.assertEqual(reboot['version'], 1)
        self.assertEqual(reboot['activationContext'], 'post-reboot')
        self.assertIn('rebootEvidence', reboot)
        for current in (initial, repeated, reboot):
            self.assertEqual(activation.validate_plan(current), current)
            for version in (0, 2, 3, True, 1.0):
                changed = copy.deepcopy(current)
                changed['version'] = version
                with self.subTest(context=current['activationContext'], version=version), self.assertRaises(ValueError):
                    activation.validate_plan(changed)
        without_reboot_proof = copy.deepcopy(reboot)
        without_reboot_proof.pop('rebootEvidence')
        with self.assertRaises(ValueError): activation.validate_plan(without_reboot_proof)
        extra_reboot_proof = copy.deepcopy(initial)
        extra_reboot_proof['rebootEvidence'] = reboot['rebootEvidence']
        with self.assertRaises(ValueError): activation.validate_plan(extra_reboot_proof)

    def test_deployment_rejects_old_plan_numbers(self):
        current = deployment.plan(Files(), deployment_values())
        self.assertEqual(current['version'], 1)
        self.assertIsInstance(deployment.journal_bytes(current), bytes)
        for version in (0, 2, 3, True, 1.0):
            changed = copy.deepcopy(current)
            changed['version'] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                deployment.journal_bytes(changed)


if __name__ == '__main__': __import__("nonempty_unittest").main()
