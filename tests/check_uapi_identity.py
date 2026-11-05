#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the canonical UAPI digest and optional consumer byte identity."""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
canonical = ROOT / "include/uapi/linux/rp1_gpclk.h"
lock = json.loads((ROOT / "uapi-identity.json").read_text(encoding="utf-8"))
digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
if digest != lock["sha256"]:
    raise SystemExit(f"canonical UAPI digest drift: {digest}")
if set(lock) != {"SPDX-License-Identifier", "path", "sha256"} or \
        lock["path"] != "include/uapi/linux/rp1_gpclk.h":
    raise SystemExit("UAPI identity metadata is inconsistent")
if len(sys.argv) == 2 and canonical.read_bytes() != Path(sys.argv[1]).read_bytes():
    raise SystemExit("consumer UAPI is not byte-identical")
print("UAPI identity: PASS")
