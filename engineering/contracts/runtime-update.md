<!-- SPDX-License-Identifier: MIT -->

# Application update preparation

The provider owns interpretation of controller sessions, generations, activation
ancestry, route journals, deployment recovery and provider service state.
Applications own version selection, their configuration and installation
provenance. An application must not reconstruct provider recovery decisions.

## Public interface

`runtime_provider.py capabilities` advertises
`rp1-gpclk-runtime-update-v1`. `update-plan` is read-only and returns the next
bounded step toward removal of the runtime deployment. `update-execute` accepts
only its reviewed SHA-256. Both accept `--source-commit` and optional paired
`--binding-sha256` / `--artifact-set-sha256` from application installation
provenance. `--deployment-sha256` binds interrupted inverse deployment recovery.

The public envelope contains the contract/version, operation, installation
identity, plan digest, status and postconditions. The plan payload is opaque
to applications: its contents are provider-private evidence. Execution
reconstructs it under application mutation exclusion and rejects drift before
effects. Existing primitives retain their deployment/controller locks and
revalidation. Each effect has its own reviewed step; failed execution is never
automatically retried. A new plan observes the completed or interrupted state.
An interrupted inverse may already have removed the installed binding and its
helpers. Recovery uses the digest-bound retained inverse and verifies that the
activation and dependent route journals are absent before resuming file
restoration. A remaining or changed journal is a refusal; missing removed
prerequisites never justify reconstructing or discarding journal ownership.

Successful preparation removes only the exact runtime deployment. The inverse
may restore the application service intent captured before deployment; success
does not promise that the application remains stopped. DKMS package
or source rollback remains the predecessor's lifecycle operation. Preparation
never selects a route or enables transmission. The application may replace its
files only after `prepared` with verified runtime absence. It subsequently
deploys and activates the new provider through the existing public facade. The
standalone bundle includes the manager used by update execution and the complete
local import dependencies of every bootstrap helper, including imports inside
functions. Each helper is byte-identical to its digest-bound deployment payload;
predeployment validation must not rely on an installed helper or source checkout.

On a Debian-package installation, inverse deployment restores the passive
package-owned route-manager unit fragments. The inactive firmware overlays
remain package data throughout. Runtime absence permits only these attributable
package files after complete payload verification against the root-owned dpkg
inventory and the exact installed package version. Missing, changed, foreign,
or additional files remain refusals. The shared library directory is retained
only when its remaining descendants are exactly the two verified package
overlays and their directory. Preparation does not remove the package, its
DKMS instance, or its inactive overlays. Source-development has no such package
baseline. The bundle includes the checksummed package-inventory helper needed
to verify this distinction even during inverse deployment.

## Response contract

All successful responses use integer `schemaVersion: 1`, string `contract:
rp1-gpclk-runtime-update-v1`, and the requested `operation`.

- `capabilities` lists `update-plan`, `update-execute`, and
  `installation-status`; it performs no host observations or effects.
- `update-plan` and `update-execute` echo `identity` with `sourceCommit`,
  `bindingSha256`, `artifactSetSha256`, and `deploymentPlanSha256`. Unprovided
  optional digests are JSON null. The source is the installed predecessor's
  40-character lowercase hexadecimal commit, not the candidate's commit.
- `status` is `planned` or `prepared`. `postconditions.runtimeAbsent` is true
  only for `prepared`; `postconditions.transmissionAuthorized` is always false.
- `update-plan` includes `plan` and `planSha256`, the SHA-256 of UTF-8 JSON
  with sorted keys and compact separators. Consumers may verify the hash but
  must not branch on private payload fields. `update-execute` echoes the
  approved digest and returns newly observed status and postconditions.
- `installation-status` returns `status: neutral_ready` and a `receipt` with
  the readiness contract, binding/artifact/source/product/kernel/compatibility
  identities, deployment and activation digests, original activation request
  and controller session, `controllerGeneration: 0`, `state: neutral_ready`,
  `route: null`, and `output: disabled`. Generation zero describes the original
  installation, not a later live controller. The provider validates later
  generations independently.

Consumers must reject missing required fields, unknown contracts/versions,
identity or digest mismatch, contradictory postconditions, and nonzero exit
status. Additional envelope fields are additive. Only the two postcondition
booleans above are defined in version 1. A failure does not authorize a retry or
prove absence. Current CLI failures use the readiness-v1 diagnostic envelope
and a nonzero status; they are never successful update responses.

## Prepare an update or uninstall

Run from the exact reviewed installed provider, or the explicitly supported
predecessor adapter described below, in an authorized administrator window.
First disable transmission, establish current idle/cleanup state and retain the
installation provenance. `INSTALLED_SOURCE_COMMIT` names the **installed
predecessor**, not the selected replacement's HEAD.
Keep a complete verified bootstrap bundle outside the installation being removed:
inverse deployment can remove the installed facade and imports, including after
an interruption. When the supported source adapter is needed, invoke its
reviewed entry point and complete import closure instead of replacing an installed
script or borrowing arbitrary helpers from another version.

```sh
python3 /usr/lib/rp1-gpclk-dkms/runtime_provider.py update-plan \
  --source-commit INSTALLED_SOURCE_COMMIT
```

Supply the paired `--binding-sha256` and `--artifact-set-sha256` from the owning
application record when available, and retain them unchanged on execution.
Interrupted inverse deployment additionally needs its exact
`--deployment-sha256`; do not invent it if the record is missing.
Validate the public contract, identity, booleans and complete plan digest. If
`status` is `planned`, review that one bounded step before executing:

```sh
python3 /usr/lib/rp1-gpclk-dkms/runtime_provider.py update-execute \
  --source-commit INSTALLED_SOURCE_COMMIT --plan-sha256 REVIEWED_UPDATE_SHA256
```

Repeat the same identity options used for planning. There is no additional
`--execute` flag on this facade verb: the unchanged approved digest is required.
Check its exit status and response. After a successful step that remains
`planned`, obtain and review a **new** `update-plan`; do not reuse the old digest
or implement an automatic retry loop. A failure stops preparation and preserves
the error and recovery inputs.

Only `prepared` with `runtimeAbsent=true` and
`transmissionAuthorized=false` permits the owning installer to proceed with its
next separately controlled file/package operation. This is runtime absence,
not package absence or a promise that WsprryPi remains stopped. Preserve the
predecessor package/source recovery inputs until the new managed installation
has passed its own checks.

## Compatibility and recovery

Use the installed provider when it supports this contract. Otherwise an exact,
reviewed provider source may supply the adapter. The adapter explicitly supports
the binding-v3/readiness-v1 predecessor protocol, validates its complete installed
artifact inventory and identities, and uses existing provider-owned lifecycle
primitives. Unknown binding versions, changed artifacts, foreign state, unsafe
output or unproven recovery are refused before mutation.

The selected source must advertise the contract during source resolution,
before package/application mutation, even when no provider is installed. An
older installed provider may be migrated by the selected compatible source;
this does not make older sources or release packages implement the new API.
The same interface applies to uninstall preparation. Application ownership
records remain application-owned. No provider API reads or rewrites WsprryPi's
INI or its installation record directly; existing application companion calls
continue to own idle/service integration policy.

## Acceptance boundary

Offline coverage must include initial neutral, GPIO4/20 selected and idle,
completed removal at later generations, stopped/masked service intent,
interrupted recovery/removal, post-reboot retirement, retries, stale plans,
concurrency, unknown contracts, foreign artifacts, unsafe endpoints and output.
Provider fixtures exercise the real classifier and lifecycle planners; consumer
tests verify the public envelope and delegation without interpreting private
plan contents. Offline tests do not qualify live installation, GPIO or RF.
