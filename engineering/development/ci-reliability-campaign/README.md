<!-- SPDX-License-Identifier: MIT -->

# CI reliability and efficiency campaign

This maintained phase list covers the selected RP1-GPCLK-DKMS CI work.
Reliability, safety, required coverage, and defect detection take priority over
speed and maintenance reductions. Reduction targets cannot waive assurance gates.

Current procedures and maintenance requirements belong in
[testing guidance](../../testing.md),
[package lifecycle operations](../../operations/package-lifecycle.md), and
[release candidate operations](../../operations/release-candidate.md).
Selected follow-on work belongs in [ROADMAP.md](../../../ROADMAP.md).

## Phase list

Status: ✅ done, ⏳ in progress, and ▧ not started.

| Phase | Batch | Work | Status |
| --- | --- | --- | --- |
| 01 | Trustworthy lifecycle execution | Require complete attributable lifecycle results | ✅ Done |
| 02 | Trustworthy lifecycle execution | Retain process and container ownership through cleanup | ✅ Done |
| 03 | Trustworthy lifecycle execution | Bound provisioning and preserve actionable diagnostics | ✅ Done |
| 04 | Coverage and deterministic evidence | Prove required dispatch and nonempty execution | ✅ Done |
| 05 | Coverage and deterministic evidence | Replace brittle process timing with observed state | ✅ Done |
| 06 | Coverage and deterministic evidence | Keep runtime bundle fixtures outside the checkout | ✅ Done |
| 07 | Coverage and deterministic evidence | Map lifecycle obligations to actual execution | ✅ Done |
| 08 | Coverage and deterministic evidence | Strengthen production-sensitive assertions and resolve fixture holds | ✅ Done |
| 09 | Measured efficiency | Measure and reduce repeated module metadata queries | ✅ Done |
| 10 | Measured efficiency | Batch authenticated Git blob reads without weakening validation | ✅ Done |
| 11 | Measured efficiency | Establish integrated assurance and honest reduction verdicts | ✅ Done |
