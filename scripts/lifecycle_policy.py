#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pure fail-closed lifecycle planning and acceptance policy."""

from __future__ import annotations

import argparse
import json
import pathlib
import re

CHECKPOINTS = (
    "preflight", "stage", "verify-staged-hashes", "dkms-add", "dkms-build",
    "verify-dkms-signature", "verify-module", "dkms-install",
    "install-overlay-inactive", "install-policy", "verify-output-disabled",
    "commit-state",
)

ABSENT_FIELDS = (
    "moduleLoaded", "platformDeviceBound", "endpointOpen", "ownerPresent",
    "workActive", "callbackPending", "dmaActive", "productionOverlayActive",
    "packageBootMarkerPresent", "dkmsRegistered", "dkmsBuiltVersionsPresent",
    "moduleFilesPresent", "packageUdevFilesPresent", "packageSystemdFilesPresent",
    "packageManifestFilesPresent", "packageConfigurationFilesPresent",
    "packageDiagnosticFilesPresent", "packageOtherResiduePresent",
    "exclusivePrivateSigningMaterialPresent",
)
TRUE_FIELDS = (
    "selectedPinSafe", "clockPrepareCountRestored", "clockEnableCountRestored",
    "clockParentRestored", "dependencyMetadataCurrent",
    "initramfsCurrentOrNotApplicable", "unrelatedBytesPreserved",
    "ownershipFullyClassified",
)


def _exact(snapshot: dict, fields: tuple[str, ...], label: str) -> None:
    if set(snapshot) != set(fields):
        raise ValueError(f"{label} fields are incomplete or unknown")
    if any(type(snapshot[field]) is not bool for field in fields):
        raise ValueError(f"{label} fields must be known booleans")


def evaluate_complete_removal(snapshot: dict) -> dict:
    """Accept only complete, explicit post-removal and preservation evidence."""
    fields = ABSENT_FIELDS + TRUE_FIELDS
    _exact(snapshot, fields, "complete-removal evidence")
    failures = [field for field in ABSENT_FIELDS if snapshot[field]]
    failures += [field for field in TRUE_FIELDS if not snapshot[field]]
    return {"operation": "complete-removal", "accepted": not failures,
            "failClosed": bool(failures), "failures": failures,
            "repeatedRemovalSafe": not failures, "readOnly": True}


def rollback_plan(state: dict) -> dict:
    required = ("operation", "status", "outputActive", "cleanupProven",
                "successorOwnershipKnown", "predecessorComplete",
                "rollbackTargetsUnchanged", "administratorBytesUnchanged",
                "predecessorRelease", "successorRelease")
    _exact_booleans = required[2:8]
    if set(state) != set(required):
        raise ValueError("rollback state fields are incomplete or unknown")
    if any(type(state[field]) is not bool for field in _exact_booleans):
        raise ValueError("rollback safety fields must be known booleans")
    if state["operation"] != "upgrade" or state["status"] != "inactive-failed":
        raise ValueError("rollback requires one failed inactive successor")
    if state["outputActive"] or not all(state[field] for field in _exact_booleans[1:]):
        raise ValueError("rollback safety or freshness is unproven")
    for field in ("predecessorRelease", "successorRelease"):
        if not isinstance(state[field], str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", state[field]):
            raise ValueError("invalid rollback release identity")
    if state["predecessorRelease"] == state["successorRelease"]:
        raise ValueError("rollback requires distinct releases")
    return {"operation": "rollback", "from": state["successorRelease"],
            "to": state["predecessorRelease"],
            "steps": ["verify-successor-output-inhibited", "verify-successor-inactive",
                      "remove-exact-successor-owned-state", "restore-recorded-predecessor-bytes",
                      "verify-output-disabled", "audit-predecessor-and-preserved-bytes"],
            "outputActive": False, "automatic": False, "readOnly": True}


def recovery_plan(state: dict) -> dict:
    required = ("operation", "status", "checkpoint", "outputActive",
                "ownershipKnown", "cleanupLatch", "hardwareActivityAbsent")
    if set(state) != set(required):
        raise ValueError("recovery state fields are incomplete or unknown")
    for field in required[3:]:
        if type(state[field]) is not bool:
            raise ValueError("recovery safety fields must be known booleans")
    if state["operation"] not in {"install", "upgrade", "downgrade", "rollback", "complete-removal"}:
        raise ValueError("unrecognized lifecycle operation")
    if state["status"] != "inactive-recovery-required" or state["checkpoint"] not in CHECKPOINTS:
        raise ValueError("transaction is not at a recognized recoverable checkpoint")
    if state["outputActive"] or not state["ownershipKnown"] or state["cleanupLatch"] or not state["hardwareActivityAbsent"]:
        raise ValueError("recovery requires known inactive cleanup-safe state")
    return {"operation": "recovery", "interruptedOperation": state["operation"],
            "checkpoint": state["checkpoint"],
            "choices": ["resume-next-proven-checkpoint", "converge-to-documented-inactive-state"],
            "automatic": False, "clearCleanupLatch": False, "readOnly": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="read-only lifecycle policy")
    parser.add_argument("action", choices=("rollback-plan", "recovery-plan", "removal-audit"))
    parser.add_argument("snapshot", type=pathlib.Path)
    args = parser.parse_args()
    if args.snapshot.is_symlink() or not args.snapshot.is_file():
        raise SystemExit("snapshot must be a real file")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    functions = {"rollback-plan": rollback_plan, "recovery-plan": recovery_plan,
                 "removal-audit": evaluate_complete_removal}
    print(json.dumps(functions[args.action](snapshot), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
