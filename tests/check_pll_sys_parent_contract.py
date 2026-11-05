#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Enforce deterministic PLL_SYS identity, selection, and cleanup ordering."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "src/rp1_gpclk_kernel_api.c").read_text()
EXECUTION = (ROOT / "src/rp1_gpclk_execution.c").read_text()
MACHINE = (ROOT / "src/rp1_gpclk_execution_machine.c").read_text()
POLICY = (ROOT / "include/rp1_gpclk/resource_policy.h").read_text()
SWEEP = (ROOT / "tests/development_frequency_sweep.cpp").read_text()
OVERLAY_IDENTITY = json.loads(
    (ROOT / "release/overlay-contract-v1.json").read_text()
)["sharedIdentity"]

# Packaged metadata must describe the same parent as the kernel and consumers.
assert OVERLAY_IDENTITY["parentClockRateHz"] == 200_000_000, \
    "overlay metadata must describe the 200 MHz parent"
assert OVERLAY_IDENTITY["parentClockId"] == "RP1_PLL_SYS"
assert OVERLAY_IDENTITY["parentClockProvider"] == "rp1_clocks"

for token in (
    '#define RP1_GPCLK_PARENT_PROVIDER_COMPATIBLE "raspberrypi,rp1-clocks"',
    "#define RP1_GPCLK_PARENT_CLOCK_ID 3U",
    "#define RP1_GPCLK_PARENT_RATE_HZ 200000000U",
):
    assert token in POLICY, token

for token in (
    'of_property_count_strings(device->dev->of_node, "clock-names") != 2',
    "parent_spec.np != clock_spec.np",
    "parent_spec.args[0] != RP1_GPCLK_PARENT_CLOCK_ID",
    'clk_get(device->dev, "parent")',
    "clk_put(device->parent_clock)",
):
    assert token in API, token

selection = EXECUTION[EXECUTION.index("static int rp1_gpclk_machine_set_rate") :]
selection = selection[: selection.index("static int rp1_gpclk_machine_prepare")]
ordered = [
    selection.index("device->initial_parent = clk_get_parent"),
    selection.index("clk_set_parent(device->clock, device->parent_clock)"),
    selection.index("clk_is_match(clk_get_parent(device->clock), device->parent_clock)"),
    selection.index("parent_rate = clk_get_rate(device->parent_clock)"),
    selection.index("rp1_gpclk_clock_setup(&rp1_gpclk_setup_ops"),
]
assert ordered == sorted(ordered)

setup = (ROOT / "src/rp1_gpclk_clock_setup.c").read_text()
for name in ("rp1_gpclk_clock_setup", "rp1_gpclk_clock_restore"):
    body = setup[setup.index("int " + name):].split("\nint ", 1)[0]
    assert body.index("ops->set_rate(context,") < body.index("ops->select_parent(context)")
    assert "ops->parent_rate(context) != " in body
assert "rp1_gpclk_clock_restore(&ops, device, initial_rate" in EXECUTION
assert "clk_set_rate(device->clock, rate > 1 ? rate / 2 : 2)" in EXECUTION
assert EXECUTION.count("return ret ?: device->clock_cleanup_error;") == 2
assert "return device->clock_cleanup_error;" not in EXECUTION
prepare = EXECUTION[EXECUTION.index("static int rp1_gpclk_machine_prepare"):]
prepare = prepare[:prepare.index("static int rp1_gpclk_machine_select_active")]
assert "rp1_gpclk_setup_parent_rate(device) != RP1_GPCLK_PARENT_RATE_HZ" in prepare

finish = MACHINE[MACHINE.index("int rp1_gpclk_execution_machine_finish") :]
cleanup = [
    finish.index("ops->disable_clock"),
    finish.index("ops->unprepare_clock"),
    finish.index("ops->select_safe"),
    finish.index("ops->restore_parent"),
    finish.index("ops->restore_rate"),
]
assert cleanup == sorted(cleanup)

for route in ("gpio4", "gpio20"):
    overlay = (ROOT / f"overlays/rp1-gpclk-{route}.dts").read_text()
    assert ('clocks = <&rp1_clocks RP1_CLK_GP0>, '
            '<&rp1_clocks RP1_PLL_SYS>;' in overlay)
    assert 'clock-names = "gpclk", "parent";' in overlay

for token in (
    "if ((lower >> 16) != ((lower + 1) >> 16))",
    "const uint64_t nearest = static_cast<uint64_t>(llroundl(ideal))",
    "std::clamp(ratio, 0.0L, 1.0L)",
):
    assert token in SWEEP, token

print("deterministic PLL_SYS parent contract: PASS")
