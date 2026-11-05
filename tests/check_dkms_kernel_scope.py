#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
text = (ROOT / "dkms.conf").read_text()
match = re.search(r'^BUILD_EXCLUSIVE_KERNEL="([^"]+)"$', text, re.MULTILINE)
assert match
pattern = re.compile(match.group(1))

allowed = (
    "6.12.75+rpt-rpi-2712",
    "6.12.75+rpt-rpi-v8",
    "6.18.34+rpt-rpi-2712",
    "6.18.34+rpt-rpi-v8",
)
excluded = (
    "6.18.44-v8-16k+",
    "6.18.44+rpt-rpi-2712-local",
    "6.18.44-2712",
    "6.18.44+rpt-rpi-2712-rt",
    "not-a-kernel",
)

for kernel in allowed:
    assert pattern.fullmatch(kernel), kernel
for kernel in excluded:
    assert not pattern.fullmatch(kernel), kernel

print("DKMS kernel scope: PASS")
