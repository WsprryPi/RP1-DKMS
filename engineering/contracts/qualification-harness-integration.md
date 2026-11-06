<!-- SPDX-License-Identifier: MIT -->

# Qualification Harness integration contract

## Scope

This contract defines the evidence boundary between an external WsprryPi
Qualification Harness, WsprryPi, and the `RP1-GPIO-CLK-DKMS` development
module. These are integration/evidence requirements, not a claim that every
Harness or application version implements the complete path. Resolve actual
version capabilities and readiness before selecting a plan. This contract does not
authorize installation, target access, module or overlay changes, endpoint
operation, GPIO output, receiver access, transmission, or RF activity.

The Harness is an external installable package. Consumers use only its console
script, `python -m` entry point, published schemas, maintained semantic
validators, supported replay/fixture interfaces, and machine-readable result
bundles. No WsprryPi or DKMS code may import undocumented Harness internals.

The module reports structural `Compatible-unqualified` independently of external
qualification. Exact-source development remains an `Experimental` consumer
classification. `GPIO4` and `GPIO20` have independent attributable evidence;
identity, authorization, results and retained evidence never transfer between them.
The [local evidence contract](../operations/qualification-metadata.md)
keeps scoped evidence attribution separate from provider compatibility. WsprryPi installs the pinned bundle with its application; there is
no separate qualification-release dependency. Application band/mode policy remains
in WsprryPi.

## Identity record

Every resolved plan and result binds these values without relying on version
ordering or implicit defaults.

### Module source and artifact

- repository URL and absolute checkout path used for development evidence;
- exact 40-hex source revision and whether tracked or untracked bytes differ;
- module, DKMS, and intended Debian versions;
- canonical UAPI header path and SHA-256;
- module ID, build ID, and route-specific compatibility ID from `QUERY`;
- compatibility metadata path, ID, SHA-256, selected entry, state, reason, and
  `operationalReady` value;
- source and installed module hashes, transform, vermagic, signer, signing
  policy, and actual installed module-file hash when an artifact exists; and
- route overlay source, compiled DTBO, and installed DTBO hashes.

Source-development labels alone are not a final package, tag, inventory,
compatibility manifest or consumer identity. Release inputs require the exact
exact source identity and verified assets. An absent package identity remains an
explicit blocker rather than a fabricated value.

### Target and route

- authorized transmitter host alias; model, revision, architecture, kernel,
  headers/configuration, firmware, base device-tree hash, and boot ID;
- clock and DMA provider identity and ancestry, GPCLK0 clock ID, DMA request and
  translation, pinctrl identity, resource layout, and signing policy;
- requested, persisted, configured, active-overlay, module-reported, and
  reconciled routes as separate values;
- exactly one enabled `rp1-gpclk-dkms-gpio4` or
  `rp1-gpclk-dkms-gpio20` endpoint, with the matching `wsprrypi,route`
  property;
- exact source-derived GPIO4 or GPIO20 compatibility ID and
  structural compatibility state, separately from external qualification; and
- management profile and its contract/schema identity; transaction ID, status,
  boot IDs, configuration hashes, attribution and reconciliation result; and
- for the runtime profile, exact binding/artifact-set identity, controller
  session/generation, overlay ownership, and terminal route/application journals.
  Runtime and packaged boot-route records are not interchangeable.

The route manager supplies configured and active route state. WsprryPi supplies
requested and persisted state. `QUERY` supplies the module-reported route
and compatibility identity. The DKMS diagnostics report independently records
the live endpoint topology and agreement; none of these observations may be
substituted for another.

### Endpoint and operation

- canonical endpoint `/dev/rp1-gpclk`, file identity and availability;
- capability mask including generic events and bounded DMA chunks, duration bounds, compatibility
  state/reason, and cleanup-fault latch;
- WsprryPi parent revision, executable path, SHA-256, build metadata, component
  tree identity, backend, mode, band, exact output frequencies, route, drive,
  request and plan identities, and authorized plan digest;
- endpoint ownership check before launch; acquired nonzero lease and strictly
  increasing generation; `RUNNING`/`DRAINING`/terminal state and reason; current
  event; elapsed/remaining time; cancellation outcome; cleanup result; and
- process exit, endpoint closure, lease release, GPIO-safe state, clock/DMA
  quiescence, cleanup latch, and terminal-silence observation.

DKMS diagnostics are passive and do not acquire a lease. WsprryPi must retain
the operation-scoped lease, generation, state, terminal reason, and cleanup
evidence returned through its provider adapter.

### Receiver and physical path

- receiver host/local identity, SDR serial/device and driver, sample format,
  rate, bandwidth, center frequency, gain, AGC and bias-tee state;
- calibration policy (`required`, `optional`, or `disabled`), complete profile
  identity, validity domain, application request/result identities, and
  qualification-usability decision;
- physical connection, attenuation and tolerances, load/antenna state, filter,
  safe-input basis, and current operator confirmation; and
- RF-off pre-roll, RF-on duration, post-roll, exact sample count, launch and
  capture timeouts, capture start evidence, and terminal-silence interval.

Receiver calibration preserves indicated measurements and may add
estimated-true frequency and uncertainty. It does not change requested RF,
transmitter arguments or PPM, transmitter identity, output power, harmonic
claims, or product eligibility.

## Mode readiness

The common readiness labels are `externally consumable`,
`hardware-free exercised`, `live-plan ready`, `not ready`, and
`not applicable`. Hardware-free results are not labelled qualified.

For each of `WSPR`, `TONE`, `QRSS`, `FSKCW`, and `DFCW`, a readiness record covers:

1. application-plan construction;
2. explicit mode parameters with no device defaults;
3. source and executable identity;
4. backend, output, band, route, and frequency binding;
5. receiver and physical-path inputs;
6. receiver-calibration policy;
7. exact plan digest and authorization;
8. bounded transmitter and capture timing;
9. cleanup and backend quiescence;
10. schema and maintained semantic validation;
11. digest-verified artifact/index/manifest handling; and
12. a passing hardware-free rehearsal.

Harness support alone does not make a WsprryPi mode `live-plan ready`. That
label additionally requires an exact integrated WsprryPi execution path for the selected DKMS source,
final artifact identities, operator window, receiver configuration, physical
path, and cleanup contract.

## Control and capture sequence

1. Create a new output and work directory. Reject an existing run destination.
2. Resolve the typed request through the supported Harness CLI. Validate every
   request and resolved document using both JSON Schema and its maintained
   semantic validator.
3. Bind exact Harness, DKMS, WsprryPi, target, route, receiver, calibration,
   helper, service, and RF-path identities. Unknown required values block live
   authorization.
4. Compute the canonical plan digest. Record a short-lived operator approval
   for exactly that digest, route, frequency, duration, connection, receiver,
   abort procedure, and window. Never embed approval in a reusable profile.
5. Install cleanup before receiver or transmitter access. Verify WsprryPi and
   provider idleness, exactly-one route topology, reconciliation, endpoint
   closure, no cleanup fault, and pre-test RF silence.
6. Start exact-count capture and complete the RF-off preamble before launching
   WsprryPi through the plan-bound structured argument vector and authenticated
   helper. A pre-launch capture failure prevents output.
7. Prove launch from authenticated process evidence plus a nonzero lease,
   matching generation, and `RUNNING` state. A process start alone is
   insufficient.
8. Enforce the kernel/request duration and Harness deadline. Cancellation
   names the exact generation, permits only bounded drain, and admits no
   successor.
9. On success, failure, timeout, or interruption, stop owned processes, observe
   a stable terminal state, release the lease, close the endpoint, verify GPIO,
   clock and DMA quiescence, restore only owned service state, and capture the
   post-run silence interval.
10. Classify capture failure after proven launch as receiver/fixture blockage,
    not transmitter unqualification. Remove incomplete or rejected IQ from the
    valid artifact index while retaining bounded authenticated diagnostics.
11. Semantically validate every result, artifact index, and manifest; seal the
    digest-verified bundle; and publish/index only accepted evidence.

Automated checks cover typed validation, identity equality, exact counts and
hashes, deadlines, process/endpoint/lease state, terminal reason, cleanup
precedence, artifact membership, and digest-verified destination use. Manual review
covers physical topology, safe-level basis, current operator authorization,
calibration applicability, spectral interpretation, and claim scope.

## First live-plan template

An external full-mode campaign can contain five separate test definitions:

1. finite carrier expressed as one generic output-enabled event;
2. `WSPR`;
3. `QRSS`;
4. `FSKCW`; and
5. `DFCW`.

`QRSS`, `FSKCW`, and `DFCW` are the three required QRSS-family modes. Each has its
own explicit mode parameters, plan identity, lifecycle result, capture and
analysis evidence, cleanup result, and semantic validation. A passing carrier
does not replace any mode test, and one keyed-mode result does not satisfy another.

A finite carrier test uses one generic event and a kernel-enforced duration.
The Harness and WsprryPi own campaign ordering and mode selection; DKMS adds no
product-mode approval list. Resolve these run-specific values before execution:

- WsprryPi revision/executable: `REQUIRED-BEFORE-LIVE`;
- DKMS revision/module/artifact/manifest: `REQUIRED-BEFORE-LIVE`;
- route: one of `GPIO4` or `GPIO20`, independently authorized;
- transmitter host alias and current target identities: `REQUIRED-BEFORE-LIVE`;
- receiver, calibration binding, connection, attenuation, load/antenna state,
  center/analysis frequency, sample rate, bandwidth, and gain:
  `REQUIRED-BEFORE-LIVE`;
- duration, pre-roll, post-roll, capture/launch/cancel/cleanup/silence bounds:
  `REQUIRED-BEFORE-LIVE`; and
- new artifact destination, operator window, abort method, and exact approval
  digest: `REQUIRED-BEFORE-LIVE`.

The template is not authorization and is not executable while any placeholder
remains.

## Evidence boundaries

Hardware-free plan validation, simulation, synthetic IQ, replay, mock
lifecycle, and sealed coordinator rehearsal establish software-contract
evidence only. Read-only actual-host preflight remains actual-host evidence.
Module build, load, binding, output, receiver capture, waveform, decode,
WsprryPi product-path, packaging, SDR, and RF qualification are separate
classes and never inherit from one another.

Existing artifacts are accepted only through supported authenticated replay or
intake. Missing, altered, partial, unauthenticated, unrelated, or wrong-route
sources are rejected and never indexed. Retained evidence is not a new run.

WsprryPi owns finite carrier, `WSPR`, `QRSS`, `FSKCW`, and `DFCW` product policy.
The DKMS adapter enforces capability, resource, lease, generation and cleanup
contracts. No automatic fallback, `/dev/mem` access or alternate transmitter
is permitted. A full-mode campaign does not convert those application modes
into a DKMS approval list. This contract does not authorize target execution.
