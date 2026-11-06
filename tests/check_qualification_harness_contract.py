#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the maintained external Harness integration boundaries."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
contract = (ROOT / "engineering/contracts/qualification-harness-integration.md").read_text()
plain = contract.replace("`", "")

for mode in ("WSPR", "QRSS", "FSKCW", "DFCW"):
    assert mode in plain
for label in ("externally consumable", "hardware-free exercised",
              "live-plan ready", "not ready", "not applicable"):
    assert label in plain
for state in ("requested", "persisted", "configured", "active-overlay",
              "module-reported", "reconciled", "operationalReady"):
    assert state in plain
for boundary in ("fixture blockage", "semantic validator", "exactly one",
                 "digest-verified", "terminal-silence", "REQUIRED-BEFORE-LIVE"):
    assert boundary in plain
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_binding
for route in ("gpio4", "gpio20"):
    assert runtime_binding.COMPATIBILITY[route] == f"v{runtime_binding.PRODUCT_VERSION}-rp1-{route}"
for prohibited in ("/dev/mem", "automatic fallback", "generic event"):
    assert prohibited in plain

assert "does not authorize target execution" in plain
assert "The template is not authorization" in plain
required_campaign = "finite carrier, WSPR, QRSS, FSKCW, and DFCW"
assert required_campaign in plain
assert "QRSS, FSKCW, and DFCW are the three required QRSS-family modes" in plain
assert "one keyed-mode result does not satisfy another" in plain
print("Qualification Harness integration contract: PASS")
