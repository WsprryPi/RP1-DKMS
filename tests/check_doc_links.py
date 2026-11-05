#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify repository-relative Markdown links without network access."""

from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
pattern = re.compile(r"\[[^]]*\]\(([^)]+)\)")
failures = []
for document in [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"),
                 *(ROOT / "engineering").rglob("*.md")]:
    for target in pattern.findall(document.read_text(encoding="utf-8")):
        target = target.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (document.parent / unquote(target)).resolve()
        if not resolved.exists():
            failures.append(f"{document.relative_to(ROOT)} -> {target}")
if failures:
    raise SystemExit("broken documentation links:\n" + "\n".join(failures))
versioned_contracts = sorted(
    path.name for path in (ROOT / "engineering" / "contracts").glob("*-v[0-9]*.md")
)
if versioned_contracts:
    raise SystemExit(
        "versioned development contract documents remain: " +
        ", ".join(versioned_contracts)
    )
for obsolete in (
    "engineering/contracts/runtime-route-v2.md",
    "schema/rp1-gpclk-runtime-binding-v2.schema.json",
    "schema/rp1-gpclk-runtime-route-v2.schema.json",
    "scripts/rp1-gpclk-runtime-route.py",
    "scripts/runtime_route.py",
    "tests/check_runtime_route.py",
):
    if (ROOT / obsolete).exists():
        raise SystemExit(f"obsolete synthetic runtime-route artifact remains: {obsolete}")
print("documentation links: PASS")
