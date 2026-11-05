#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pure, deny-by-default module-signing evaluator."""

from __future__ import annotations

import argparse
import json
import re

ENFORCEMENT = {"not-enforced", "accepts-trusted-local", "enforced"}
SIG = {"unsigned", "valid", "corrupt"}
TRUST = {"not-required", "trusted", "untrusted", "revoked", "unknown"}


def evaluate(value: dict) -> dict:
    required = {"targetKernel", "moduleVersion", "vermagicKernel", "moduleSha256",
                "enforcement", "signatureStatus", "signer", "signatureKeyId",
                "signatureAlgorithm", "signatureHashAlgorithm",
                "certificateFingerprint", "expectedCertificateFingerprint",
                "certificateValidity", "certificateTrust", "privateKeyState",
                "dkmsPerBuildSigningConfigured", "configuredIdentityReplacement"}
    if set(value) != required:
        raise ValueError("signing snapshot fields are incomplete or unknown")
    if value["enforcement"] not in ENFORCEMENT or value["signatureStatus"] not in SIG:
        raise ValueError("unknown enforcement or signature state")
    if value["certificateTrust"] not in TRUST:
        raise ValueError("unknown certificate trust state")
    if value["certificateValidity"] not in {"valid", "expired", "not-yet-valid", "unknown"}:
        raise ValueError("unknown certificate validity")
    if value["privateKeyState"] not in {"available-secure", "missing", "unsafe-permissions", "not-required"}:
        raise ValueError("unknown private-key state")
    if value["configuredIdentityReplacement"] not in {"none", "silent-replacement-detected"}:
        raise ValueError("unknown key replacement state")
    if not isinstance(value["dkmsPerBuildSigningConfigured"], bool):
        raise ValueError("invalid DKMS signing configuration state")
    if not re.fullmatch(r"[0-9a-f]{64}", value["moduleSha256"]):
        raise ValueError("invalid module hash")
    strings = required - {"dkmsPerBuildSigningConfigured"}
    if any(not isinstance(value[name], str) or not value[name] for name in strings):
        raise ValueError("empty signing identity field")

    signed_policy = value["enforcement"] != "not-enforced"
    signed_identity = signed_policy or value["signatureStatus"] != "unsigned"
    reason = "signature-policy-accepted"
    accepted = True
    if value["targetKernel"] != value["vermagicKernel"]:
        accepted, reason = False, "wrong-kernel-vermagic"
    elif value["configuredIdentityReplacement"] != "none":
        accepted, reason = False, "configured-signing-identity-replaced"
    elif signed_identity and not value["dkmsPerBuildSigningConfigured"]:
        accepted, reason = False, "dkms-per-build-signing-not-configured"
    elif signed_identity and value["privateKeyState"] in {"missing", "unsafe-permissions"}:
        accepted, reason = False, f"private-key-{value['privateKeyState']}"
    elif value["signatureStatus"] == "corrupt":
        accepted, reason = False, "signature-corrupt"
    elif signed_policy and value["signatureStatus"] != "valid":
        accepted, reason = False, "required-signature-absent"
    elif signed_identity and value["certificateValidity"] != "valid":
        accepted, reason = False, f"certificate-{value['certificateValidity']}"
    elif signed_identity and value["certificateTrust"] != "trusted":
        accepted, reason = False, f"certificate-{value['certificateTrust']}"
    elif signed_identity and value["certificateFingerprint"] != value["expectedCertificateFingerprint"]:
        accepted, reason = False, "certificate-fingerprint-mismatch"
    elif signed_identity and any(value[name] == "none" for name in
                               ("signer", "signatureKeyId", "signatureAlgorithm", "signatureHashAlgorithm")):
        accepted, reason = False, "signature-metadata-incomplete"
    elif not signed_policy and value["signatureStatus"] == "unsigned":
        reason = "unsigned-accepted-by-nonenforcing-kernel-policy"
    return {"state": "Compatible-unqualified" if accepted else "Unavailable",
            "signaturePolicyAccepted": accepted, "loadPermittedBySigningPolicy": accepted,
            "operationalReady": False, "reason": reason, "fallbackPermitted": False,
            "readOnly": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot")
    args = parser.parse_args()
    with open(args.snapshot, encoding="utf-8") as source:
        print(json.dumps(evaluate(json.load(source)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
