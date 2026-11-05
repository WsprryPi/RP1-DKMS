#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Enforce route injection and the canonical interface freeze."""

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GPIO4 = (ROOT / "overlays/rp1-gpclk-gpio4.dts").read_text(encoding="utf-8")
GPIO20 = (ROOT / "overlays/rp1-gpclk-gpio20.dts").read_text(encoding="utf-8")
SOURCE = "\n".join(
    p.read_text(encoding="utf-8") for p in (ROOT / "src").glob("*.c")
    if p.name != "rp1_gpclk_execution.c"
)
HEADER_PATH = ROOT / "include/uapi/linux/rp1_gpclk.h"
HEADER = HEADER_PATH.read_text(encoding="utf-8")
IDENTITY = json.loads((ROOT / "uapi-identity.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "schema/rp1-gpclk-compatibility-manifest-v1.schema.json").read_text(encoding="utf-8"))


def require(text: str, tokens: tuple[str, ...], label: str) -> None:
    for token in tokens:
        if token not in text:
            raise SystemExit(f"{label} missing {token}")


shared = (
    'compatible = "wsprrypi,rp1-gpclk-dkms-v1"',
    'clocks = <&rp1_clocks RP1_CLK_GP0>, <&rp1_clocks RP1_PLL_SYS>',
    'clock-names = "gpclk", "parent"',
    'pinctrl-names = "default", "active", "safe"',
    'dmas = <&rp1_dma RP1_DMA_DMA_TICK_TICK0>',
    'dma-names = "tx"',
)
require(GPIO4, shared + ('wsprrypi,route = <1>', 'wsprrypi,pin = <4>',
                         'pins = "gpio4"'), "GPIO4 overlay")
require(GPIO20, shared + ('wsprrypi,route = <2>', 'wsprrypi,pin = <20>',
                          'pins = "gpio20"'), "GPIO20 overlay")
if 'pins = "gpio20"' in GPIO4 or 'pins = "gpio4"' in GPIO20:
    raise SystemExit("a production overlay mentions the other route")

for pin, overlay in ((4, GPIO4), (20, GPIO20)):
    safe = f"rp1_gpclk_gpio{pin}_safe"
    active = f"rp1_gpclk_gpio{pin}_active"
    require(overlay, ('function = "gpio"', 'input-enable;', 'bias-disable;',
                      'function = "gpclk0"', 'drive-strength = <2>',
                      f'pinctrl-0 = <&{safe}>', f'pinctrl-1 = <&{active}>',
                      f'pinctrl-2 = <&{safe}>'), f"GPIO{pin} safe-state contract")
    if re.search(rf"pinctrl-[02]\s*=\s*<&{active}>", overlay):
        raise SystemExit(f"GPIO{pin} active state is selected as default/safe")

normalized4 = GPIO4.replace("gpio4", "gpioX").replace("GPIO4", "GPIOX") \
    .replace("wsprrypi,route = <1>", "wsprrypi,route = <ROUTE>") \
    .replace("wsprrypi,pin = <4>", "wsprrypi,pin = <PIN>")
normalized20 = GPIO20.replace("gpio20", "gpioX").replace("GPIO20", "GPIOX") \
    .replace("wsprrypi,route = <2>", "wsprrypi,route = <ROUTE>") \
    .replace("wsprrypi,pin = <20>", "wsprrypi,pin = <PIN>")
if normalized4 != normalized20:
    raise SystemExit("production overlays differ outside route-specific fields")

require(SOURCE, ("rp1_gpclk_route_pin_validate(route, pin)",
                 "atomic_set_release(&rp1_gpclk_endpoint_owner, 0)"),
        "route-neutral implementation")
for pattern in (r"\bclk_(?:prepare|enable|prepare_enable|set_rate|set_parent)\s*\(",
                r"\bpinctrl_select_state\s*\(",
                r"\b(?:dmaengine_prep|dmaengine_submit|dma_async_issue_pending)\b"):
    if re.search(pattern, SOURCE):
        raise SystemExit("route/UAPI contract crossed the clock-disabled boundary")

fixtures = {p.name: p.read_text(encoding="utf-8")
            for p in (ROOT / "overlays/fixtures").glob("*.dts")}
for name in ("rp1-gpclk-route-invalid.dts",
             "rp1-gpclk-gpio20-route-mismatch.dts"):
    if name not in fixtures:
        raise SystemExit(f"missing route/UAPI fixture {name}")
require(fixtures["rp1-gpclk-route-invalid.dts"],
        ('wsprrypi,route = <3>',), "invalid-route fixture")
require(fixtures["rp1-gpclk-gpio20-route-mismatch.dts"],
        ('wsprrypi,route = <1>', 'wsprrypi,pin = <20>'), "mismatch fixture")

digest = hashlib.sha256(HEADER_PATH.read_bytes()).hexdigest()
if IDENTITY != {"SPDX-License-Identifier": "MIT",
                "path": "include/uapi/linux/rp1_gpclk.h", "sha256": digest}:
    raise SystemExit("current UAPI identity does not match canonical header")
require(HEADER, ("RP1_GPCLK_IOC_MAGIC 0xb8",
                 "RP1_GPCLK_ROUTE_GPIO4 = 1", "RP1_GPCLK_ROUTE_GPIO20 = 2"),
        "canonical UAPI")
for legacy in ("UAPI_ABI_V", "_v1", "_v2", "_v3", "_v4",
               "IOC_QUERY_V", "IOC_ACQUIRE_V", "IOC_RELEASE_V"):
    if legacy in HEADER:
        raise SystemExit(f"legacy UAPI token remains: {legacy}")

if SCHEMA["properties"]["defaultState"]["const"] != "Unavailable":
    raise SystemExit("manifest default is not fail-closed")
if SCHEMA["properties"]["schemaVersion"]["const"] != 1:
    raise SystemExit("manifest schema version changed")
if SCHEMA["$defs"]["route"]["enum"] != ["GPIO4", "GPIO20"]:
    raise SystemExit("manifest route vocabulary changed")

# Behavioral ownership is exercised by lifecycle_core.c and the controller's
# compiled ioctl harness. This program enforces source/format boundaries only.

print("route injection and interface freeze: PASS")
