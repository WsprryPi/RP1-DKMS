#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the real sweep renderer using a hardware-blocked offline binary."""

import csv
from fractions import Fraction
import io
from pathlib import Path
import subprocess
import sys
import tempfile

BINARY = str(Path(sys.argv[1]).resolve())
PARENT = 200_000_000


def run(*arguments):
    with tempfile.TemporaryDirectory() as temporary:
        return subprocess.run([BINARY, *arguments], cwd=temporary,
                              capture_output=True, text=True,
                              timeout=15, check=False)


def render(*arguments):
    result = run("--render-only", *arguments)
    assert result.returncode == 0, result.stderr
    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    assert rows and all(row["status"] == "planned" for row in rows), rows
    return rows


def check_row(row, parent=PARENT, maximum_direct=100_000_000):
    requested = Fraction(row["requested_rf_hz"])
    harmonic = 3 if requested > maximum_direct else 1
    lower = int(row["lower_divider_q16"])
    upper = int(row["upper_divider_q16"])
    low_count = int(row["lower_count"])
    high_count = int(row["upper_count"])
    assert int(row["harmonic"]) == harmonic
    assert 65536 <= lower < upper <= 0xffffffff
    assert upper == lower + 1 and lower >> 16 == upper >> 16
    assert low_count > 0 and high_count > 0
    assert low_count + high_count == 66792
    mean = parent * 65536 * (
        Fraction(low_count, lower) + Fraction(high_count, upper)
    ) / (low_count + high_count) * harmonic
    assert abs(mean - requested) < Fraction(1, 20), (row, float(mean))
    assert abs(mean - Fraction(row["planned_rf_hz"])) < Fraction(1, 1_000_000)


rows = render("--repeats", "2")
assert len(rows) == 32
for row in rows:
    check_row(row)
assert rows[0]["requested_rf_hz"] == "135700.000000"
assert rows[15]["requested_rf_hz"] == "148000000.000000"

fixed = render("--frequency-hz", "10140200")[0]
assert [int(fixed[key]) for key in (
    "lower_divider_q16", "upper_divider_q16", "lower_count", "upper_count"
)] == [1292597, 1292598, 14752, 52040]
assert render("--parent-hz", "200000000", "--frequency-hz", "10140200")[0] == fixed
assert render("--receiver-ppm", "200", "--frequency-hz", "10140200")[0] == fixed

frequencies = ("135700", "10140200", "9999999.9999", "10000000.0001",
               "60000000", "100000000", "100000000.001", "148000000")
arguments = [item for frequency in frequencies
             for item in ("--frequency-hz", frequency)]
for ppm in (-200, 0, 200):
    for row in render("--source-rate-ppm", str(ppm), *arguments):
        check_row(row, PARENT * (1 + Fraction(ppm, 1_000_000)))

# Alternate parents remain available for explicit offline modelling only.
for row in render("--parent-hz", "50000000", "--maximum-direct-hz", "25000000",
                  "--frequency-hz", "10140200"):
    check_row(row, 50_000_000, 25_000_000)

# These execute only the mocked CLI. A missed guard aborts in the SDR stub.
for parent in ("49997248", "50000000", "199999999", "200000001", "1000000000"):
    result = run("--live", "--parent-hz", parent,
                 "--maximum-direct-hz", "25000000")
    assert result.returncode == 2, (parent, result.returncode, result.stderr)
    assert "200 MHz" in result.stderr, result.stderr
    assert not result.stdout

result = run("--render-only", "--parent-hz", "50000000",
             "--maximum-direct-hz", "25000000", "--live")
assert result.returncode == 2 and "200 MHz" in result.stderr
assert render("--live", "--parent-hz", "50000000",
              "--maximum-direct-hz", "25000000", "--render-only")

with tempfile.TemporaryDirectory() as temporary:
    output = Path(temporary) / "existing.csv"
    output.write_text("preserve existing output\n")
    result = run("--live", "--parent-hz", "50000000",
                 "--maximum-direct-hz", "25000000", "--output", str(output))
    assert result.returncode == 2
    assert output.read_text() == "preserve existing output\n"

print("sweep clock-parent planning and live-parent rejection: PASS")
