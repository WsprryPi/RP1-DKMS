<!-- SPDX-License-Identifier: MIT -->

# Qualification boundaries

RP1-GPIO-CLK-DKMS development source has no inherited release, hardware, or RF qualification.
Build compatibility, structural compatibility, operational readiness, external
scoped qualification, and WsprryPi application eligibility are separate facts.
GPIO4 evidence does not qualify GPIO20, nor does a finite conducted tone result
establish every band, mode, kernel, board, timing, or spectral property.

WsprryPi owns its previously accepted local evidence bundles and their exact
source bindings. They remain with that application and must not be relabeled as
qualification for this repository. This source tree does not reconstruct bundles
from old release tags or download historical release assets.

## Diagnostics

`scripts/qualification_status.py` interprets explicit, verified local evidence
and a separately supplied runtime-provider report. It does not collect target
state, operate hardware, publish artifacts, or authorize output. Missing or
mismatched evidence does not create a new provider enrollment or permission gate.
Synthetic interpreter fixtures exercise attribution and refusal behavior; they
are not accepted physical evidence. Applications retain their own accepted data.
