#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Keep target fault injection compile-time, identified, and complete."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
header = (ROOT / "include/rp1_gpclk/target_fault.h").read_text()
kbuild = (ROOT / "Kbuild").read_text()
main = (ROOT / "src/rp1_gpclk_main.c").read_text()
execution = (ROOT / "src/rp1_gpclk_execution.c").read_text()
client = (ROOT / "tests/development_fault_client.c").read_text()

stages = re.findall(r"RP1_GPCLK_TARGET_FAULT_([A-Z_]+) = ([0-9]+)", header)
if len(stages) != 15 or [int(number) for _, number in stages] != list(range(1, 16)):
    raise SystemExit("target fault stages are incomplete or non-canonical")
for name, _ in stages:
    token = f"RP1_GPCLK_TARGET_FAULT_{name}"
    if execution.count(token) != 1:
        raise SystemExit(f"target fault stage is not injected exactly once: {name}")

for token in ("ifneq ($(strip $(RP1_TARGET_FAULT_STAGE)),)",
              "-DRP1_GPCLK_TARGET_FAULT_STAGE=$(RP1_TARGET_FAULT_STAGE)"):
    if token not in kbuild:
        raise SystemExit("target fault Kbuild opt-in is missing")
for token in ("TEST-ONLY fault artifact stage=%u",
              "MODULE_INFO(rp1_target_fault_stage"):
    if token not in main:
        raise SystemExit("target fault artifact identity is missing")
if "module_param" in header + execution or "TARGET_FAULT" in (
        ROOT / "include/uapi/linux/rp1_gpclk.h").read_text():
    raise SystemExit("target fault injection escaped into a runtime interface")
for token in ("errno != EUCLEAN", "snapshots_equal(&first, &second)",
              "value->gpio_safe", "value->clock_quiescent",
              "value->dma_quiescent"):
    if token not in client:
        raise SystemExit("target fault client evidence check is incomplete")

print("target fault-injection contract: PASS (15 compile-time stages)")
