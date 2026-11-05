#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile maintained RP1 GPCLK overlays deterministically without installing them."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile


def build_dtbo(source: pathlib.Path, destination: pathlib.Path, dtc: str) -> None:
    text = source.read_text()
    text = re.sub(r"^#include <dt-bindings/clock/rp1.h>$", "", text, flags=re.M)
    text = re.sub(r"^#include <dt-bindings/mfd/rp1.h>$", "", text, flags=re.M)
    text = (text.replace("RP1_CLK_GP0", "33")
                .replace("RP1_PLL_SYS", "3")
                .replace("RP1_DMA_DMA_TICK_TICK0", "0x30"))
    if "#include" in text:
        raise SystemExit(f"unresolved overlay include in {source.name}")
    with tempfile.NamedTemporaryFile("w", suffix=".dts", delete=False) as preprocessed:
        preprocessed.write(text)
        temporary = pathlib.Path(preprocessed.name)
    try:
        warning_policy = ["-Wno-reg_format", "-Wno-unit_address_vs_reg", "-Wno-pci_device_reg",
                          "-Wno-pci_device_bus_num", "-Wno-simple_bus_reg", "-Wno-i2c_bus_reg",
                          "-Wno-spi_bus_reg", "-Wno-avoid_default_addr_size", "-Wno-avoid_unnecessary_addr_size",
                          "-Wno-unique_unit_address"]
        result = subprocess.run(
            [dtc, *warning_policy, "-@", "-I", "dts", "-O", "dtb", "-o", str(destination), str(temporary)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode or "warning" in result.stderr.lower():
            raise SystemExit(f"dtc failed or warned for {source.name}: {result.stderr.strip()}")
    finally:
        temporary.unlink(missing_ok=True)
