#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate a completed representative module build without loading it."""

import argparse
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def output(*command: str) -> str:
    return subprocess.run(command, check=True, text=True,
                          stdout=subprocess.PIPE).stdout


parser = argparse.ArgumentParser()
parser.add_argument("module", type=Path)
parser.add_argument("--kernel-release", required=True)
parser.add_argument("--machine", default="AArch64")
args = parser.parse_args()

if not args.module.is_file():
    raise SystemExit(f"module not found: {args.module}")

header = output("readelf", "-h", str(args.module))
machine = re.search(r"^\s*Machine:\s*(.+)$", header, re.MULTILINE)
if not machine or machine.group(1).strip() != args.machine:
    raise SystemExit(f"unexpected ELF machine: {machine.group(1) if machine else 'missing'}")

modinfo = shutil.which("modinfo")
if not modinfo and Path("/sbin/modinfo").is_file():
    modinfo = "/sbin/modinfo"
if not modinfo:
    raise SystemExit("modinfo is unavailable")
metadata = output(modinfo, str(args.module))
fields = {}
for line in metadata.splitlines():
    if ":" in line:
        key, value = line.split(":", 1)
        fields.setdefault(key.strip(), value.strip())

version_header = (ROOT / "include/rp1_gpclk/version.h").read_text(encoding="utf-8")
expected_version = re.search(
    r'^#define RP1_GPCLK_MODULE_VERSION "([^"]+)"$',
    version_header, re.MULTILINE)
if not expected_version or fields.get("version") != expected_version.group(1):
    raise SystemExit("built module version differs from source")
if fields.get("license") != "Dual MIT/GPL":
    raise SystemExit("built module license differs from contract")
vermagic = fields.get("vermagic", "").split()
if not vermagic or vermagic[0] != args.kernel_release:
    raise SystemExit(
        f"vermagic release mismatch: expected {args.kernel_release}, "
        f"found {vermagic[0] if vermagic else 'missing'}")

print(f"built module: PASS ({args.kernel_release}, {args.machine}, "
      f"{expected_version.group(1)})")
