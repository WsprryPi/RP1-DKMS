#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline overlay identity and deterministic-build checks."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

builder = load("rp1_builder_overlay", ROOT / "scripts/overlay_builder.py")
contract = json.loads((ROOT / "release/overlay-contract-v1.json").read_text())
assert contract["selection"] == {"exactlyOne": True, "arbitraryGpioParameter": False,
                                  "automaticSubstitution": False, "hotMutation": False}
assert all(contract["evidenceIndependence"].values())
assert set(contract["routes"]) == {"gpio4", "gpio20"}
dtc = shutil.which("dtc")
if not dtc:
    raise SystemExit("dtc is required for deterministic overlay validation")
shared = contract["sharedIdentity"]
compiled = {}
endpoint_names = set()
with tempfile.TemporaryDirectory() as temporary:
    out = pathlib.Path(temporary)
    for route, identity in contract["routes"].items():
        source = ROOT / identity["source"]
        text = source.read_text()
        endpoint_names.add(identity["endpointName"])
        other = "gpio20" if route == "gpio4" else "gpio4"
        required = (f'{identity["endpointLabel"]}: {identity["endpointName"]}',
                    f'compatible = "{shared["compatible"]}"',
                    f'wsprrypi,route = <{identity["routeId"]}>',
                    f'wsprrypi,pin = <{identity["pin"]}>',
                    f'clocks = <&{shared["clockProvider"]} {shared["clockId"]}>, '
                    f'<&{shared["parentClockProvider"]} {shared["parentClockId"]}>',
                    f'clock-names = "{shared["clockName"]}", '
                    f'"{shared["parentClockName"]}"',
                    f'dmas = <&{shared["dmaProvider"]} {shared["dmaId"]}>',
                    'reg-names = "tick-dma0", "dma-tick0"',
                    'pinctrl-names = "default", "active", "safe"',
                    'function = "gpio"', 'input-enable;', 'bias-disable;',
                    'function = "gpclk0"', 'drive-strength = <2>')
        assert all(token in text for token in required)
        assert f'pins = "{route}"' in text and f'pins = "{other}"' not in text
        assert "__overrides__" not in text
        first, second = out / f"{route}-1.dtbo", out / f"{route}-2.dtbo"
        builder.build_dtbo(source, first, dtc)
        builder.build_dtbo(source, second, dtc)
        assert first.read_bytes() == second.read_bytes()
        decompiled = subprocess.check_output([dtc, "-I", "dtb", "-O", "dts", str(first)],
                                             text=True, stderr=subprocess.DEVNULL)
        for token in (shared["compatible"], identity["endpointName"], "tick-dma0",
                      "dma-tick0", "gpclk", "parent", "default", "active", "safe", route):
            assert token in decompiled
        numeric = {"gpio4": ("0x01", "0x04"), "gpio20": ("0x02", "0x14")}[route]
        for token in (f"wsprrypi,route = <{numeric[0]}>", f"wsprrypi,pin = <{numeric[1]}>",
                      "reg = <0xc0 0x40174024 0x00 0x08 0xc0 0x40158000 0x00 0x08>"):
            assert token in decompiled
        # dtc 1.8 may retain symbolic external phandles while dtc 1.7 emits
        # the canonical unresolved value and records the provider in
        # __fixups__. Accept both renderings, but always require the exact
        # provider/property fixup so a numeric placeholder cannot pass alone.
        assert ("dmas = <&rp1_dma>, <0x30>" in decompiled or
                "dmas = <0xffffffff 0x30>" in decompiled)
        assert ("clocks = <&rp1_clocks>, <0x21>, <&rp1_clocks>, <0x03>" in decompiled or
                "clocks = <&rp1_clocks 0x21>, <&rp1_clocks 0x03>" in decompiled or
                "clocks = <0xffffffff 0x21 0xffffffff 0x03>" in decompiled)
        for token in ("rp1_dma =", f'{identity["endpointName"]}:dmas:0',
                      "rp1_clocks =", f'{identity["endpointName"]}:clocks:0',
                      f'{identity["endpointName"]}:clocks:8'):
            assert token in decompiled
        compiled[route] = (hashlib.sha256(source.read_bytes()).hexdigest(),
                           hashlib.sha256(first.read_bytes()).hexdigest())
assert compiled["gpio4"] != compiled["gpio20"]
assert endpoint_names == {"rp1-gpclk-dkms-gpio4", "rp1-gpclk-dkms-gpio20"}
combined = "\n".join((ROOT / contract["routes"][route]["source"]).read_text()
                     for route in ("gpio4", "gpio20"))
assert combined.count('compatible = "wsprrypi,rp1-gpclk-dkms-v1"') == 2

print("overlay contract: PASS")
