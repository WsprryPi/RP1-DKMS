#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Enforce the offline module build and DKMS contract."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
version_header = (ROOT / "include/rp1_gpclk/version.h").read_text(encoding="utf-8")
main = (ROOT / "src/rp1_gpclk_main.c").read_text(encoding="utf-8")
dkms = (ROOT / "dkms.conf").read_text(encoding="utf-8")
debian_rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
kbuild = (ROOT / "Kbuild").read_text(encoding="utf-8")
makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
offline = (ROOT / "tests/run-offline-checks.sh").read_text(encoding="utf-8")

header_match = re.search(r'^#define RP1_GPCLK_MODULE_VERSION "([^"]+)"$',
                         version_header, re.MULTILINE)
dkms_match = re.search(r'^PACKAGE_VERSION="([^"]+)"$', dkms, re.MULTILINE)
if not header_match or not dkms_match:
    raise SystemExit("module or DKMS version is missing")
dkms_version = dkms_match.group(1)
if dkms_version == "#MODULE_VERSION#":
    rules_match = re.search(r"^MODULE_VERSION := (\S+)$", debian_rules, re.MULTILINE)
    if not rules_match or rules_match.group(1) != header_match.group(1):
        raise SystemExit("module and Debian DKMS versions differ")
    if "dh_dkms -V $(MODULE_VERSION)" not in debian_rules:
        raise SystemExit("Debian DKMS template substitution is missing")
elif header_match.group(1) != dkms_version:
    raise SystemExit("module and DKMS versions differ")
if "MODULE_VERSION(RP1_GPCLK_MODULE_VERSION);" not in main:
    raise SystemExit("module version is not emitted")
if "RP1_GPCLK_TERMINAL_" in main:
    raise SystemExit("module source uses a stale terminal-reason namespace")
if ".llseek = no_llseek" in main:
    raise SystemExit("module source uses removed no_llseek helper")

required_dkms = {
    'PACKAGE_NAME="rp1-gpclk-dkms"',
    'BUILT_MODULE_NAME[0]="rp1_gpclk_dkms"',
    'BUILT_MODULE_LOCATION[0]="."',
    'DEST_MODULE_LOCATION[0]="/updates/dkms"',
    'MAKE[0]="make KERNEL_BUILD=${kernel_source_dir}"',
    'CLEAN="make KERNEL_BUILD=${kernel_source_dir} clean"',
    'AUTOINSTALL="yes"',
}
missing = sorted(required_dkms.difference(dkms.splitlines()))
if missing:
    raise SystemExit("missing DKMS settings: " + ", ".join(missing))
if "obj-m += rp1_gpclk_dkms.o" not in kbuild:
    raise SystemExit("Kbuild module identity differs from DKMS")
for token in ("ifneq ($(strip $(RP1_TARGET_FAULT_STAGE)),)",
              "-DRP1_GPCLK_TARGET_FAULT_STAGE=$(RP1_TARGET_FAULT_STAGE)"):
    if token not in kbuild:
        raise SystemExit("target fault build is not explicit and compile-time only")
kbuild_objects = set(re.findall(r"src/([a-z0-9_]+)\.o", kbuild))
source_objects = {path.stem for path in (ROOT / "src").glob("*.c")}
if kbuild_objects != source_objects:
    raise SystemExit(
        "Kbuild/source object mismatch: "
        f"missing={sorted(source_objects - kbuild_objects)}, "
        f"extra={sorted(kbuild_objects - source_objects)}")
if 'test -n "$(KERNEL_BUILD)"' not in makefile:
    raise SystemExit("external-module build does not require explicit headers")

forbidden = re.compile(r"\b(?:dkms\s+(?:add|build|install|remove)|insmod|modprobe|rmmod)\b")
if forbidden.search(offline):
    raise SystemExit("offline checks contain a module lifecycle operation")

print("build and DKMS configuration: PASS")
