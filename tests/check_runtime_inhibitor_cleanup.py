#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline tests for exact orphaned runtime inhibitor cleanup."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/runtime_inhibitor_cleanup.py"
SPEC = importlib.util.spec_from_file_location("runtime_inhibitor_cleanup", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.uid = os.geteuid()
        self.inhibitor = MODULE.rooted(self.root, MODULE.INHIBITOR)
        self.inhibitor.parent.mkdir(parents=True)
        self.inhibitor.write_bytes(MODULE.INHIBIT_BYTES)
        self.inhibitor.chmod(0o644)

    def plan(self):
        return MODULE.inspect(self.root, self.uid)

    def test_exact_orphan_is_removed_with_reviewed_digest(self):
        plan = self.plan()
        self.assertTrue(plan["orphanCleanupEligible"])
        result = MODULE.cleanup(
            MODULE.digest(plan), root=self.root, expected_uid=self.uid,
            reload_systemd=False,
        )
        self.assertEqual(result["inhibitorState"], "absent")
        self.assertFalse(self.inhibitor.parent.exists())

    def test_foreign_content_mode_and_symlink_are_preserved(self):
        for mutation in ("content", "mode", "symlink"):
            with self.subTest(mutation=mutation):
                self.inhibitor.unlink(missing_ok=True)
                if mutation == "content":
                    self.inhibitor.write_bytes(b"foreign\n")
                    self.inhibitor.chmod(0o644)
                elif mutation == "mode":
                    self.inhibitor.write_bytes(MODULE.INHIBIT_BYTES)
                    self.inhibitor.chmod(0o666)
                else:
                    self.inhibitor.symlink_to("/dev/null")
                plan = self.plan()
                self.assertEqual(plan["inhibitorState"], "foreign")
                self.assertFalse(plan["orphanCleanupEligible"])
                with self.assertRaisesRegex(ValueError, "not a proven orphan"):
                    MODULE.cleanup(
                        MODULE.digest(plan), root=self.root,
                        expected_uid=self.uid, reload_systemd=False,
                    )
                self.assertTrue(self.inhibitor.exists() or self.inhibitor.is_symlink())

    def test_symlinked_parent_and_hard_link_are_preserved(self):
        outside = self.root / "outside"
        outside.mkdir()
        redirected = outside / self.inhibitor.name
        redirected.write_bytes(MODULE.INHIBIT_BYTES)
        redirected.chmod(0o644)
        self.inhibitor.unlink()
        self.inhibitor.parent.rmdir()
        self.inhibitor.parent.symlink_to(outside)
        plan = self.plan()
        self.assertEqual(plan["inhibitorState"], "foreign")
        self.assertFalse(plan["orphanCleanupEligible"])
        with self.assertRaisesRegex(ValueError, "not a proven orphan"):
            MODULE.cleanup(
                MODULE.digest(plan), root=self.root,
                expected_uid=self.uid, reload_systemd=False,
            )
        self.assertEqual(redirected.read_bytes(), MODULE.INHIBIT_BYTES)

        self.inhibitor.parent.unlink()
        self.inhibitor.parent.mkdir()
        os.link(redirected, self.inhibitor)
        plan = self.plan()
        self.assertEqual(plan["inhibitorState"], "foreign")
        self.assertFalse(plan["orphanCleanupEligible"])
        with self.assertRaisesRegex(ValueError, "not a proven orphan"):
            MODULE.cleanup(
                MODULE.digest(plan), root=self.root,
                expected_uid=self.uid, reload_systemd=False,
            )
        self.assertTrue(self.inhibitor.exists())

    def test_service_or_any_runtime_artifact_blocks_cleanup(self):
        candidates = (
            MODULE.SERVICE_UNITS[0],
            MODULE.SERVICE_UNITS[1],
            MODULE.RUNTIME_ARTIFACTS[0],
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                path = MODULE.rooted(self.root, candidate)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"present")
                plan = self.plan()
                self.assertFalse(plan["orphanCleanupEligible"])
                with self.assertRaisesRegex(ValueError, "not a proven orphan"):
                    MODULE.cleanup(
                        MODULE.digest(plan), root=self.root,
                        expected_uid=self.uid, reload_systemd=False,
                    )
                path.unlink()

    def test_dkms_owned_modules_are_not_runtime_inhibitor_residue(self):
        module = MODULE.rooted(
            self.root, "/lib/modules/fixture/updates/dkms/rp1_route_controller.ko.xz")
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_bytes(b"provider-owned")
        plan = self.plan()
        self.assertTrue(plan["orphanCleanupEligible"])
        self.assertNotIn(str(module), plan["runtimeArtifacts"])

    def test_state_change_after_review_is_rejected(self):
        approved = MODULE.digest(self.plan())
        runtime = MODULE.rooted(self.root, MODULE.RUNTIME_ARTIFACTS[1])
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b"appeared")
        with self.assertRaisesRegex(ValueError, "digest differs"):
            MODULE.cleanup(
                approved, root=self.root, expected_uid=self.uid,
                reload_systemd=False,
            )
        self.assertTrue(self.inhibitor.exists())

    def test_daemon_reload_failure_restores_owned_inhibitor(self):
        plan = self.plan()
        completed = type("Completed", (), {"returncode": 1})()
        with mock.patch.object(
            MODULE.subprocess,
            "run",
            side_effect=(MODULE.subprocess.CalledProcessError(1, "systemctl"), completed),
        ):
            with self.assertRaises(MODULE.subprocess.CalledProcessError):
                MODULE.cleanup(
                    MODULE.digest(plan), root=self.root,
                    expected_uid=self.uid, reload_systemd=True,
                )
        self.assertEqual(self.inhibitor.read_bytes(), MODULE.INHIBIT_BYTES)
        self.assertEqual(self.inhibitor.stat().st_mode & 0o777, 0o644)


if __name__ == "__main__":
    __import__("nonempty_unittest").main()
