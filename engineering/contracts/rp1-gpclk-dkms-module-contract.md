<!-- SPDX-License-Identifier: MIT -->

# RP1 GPCLK DKMS module contract

## Purpose and authority

This document defines the engineering, ownership, safety, compatibility,
packaging, and release contract for `WsprryPi/RP1-DKMS`.

This repository is authoritative for the kernel module, canonical UAPI,
device-tree overlays, DKMS packaging, module lifecycle tooling, compatibility
metadata, and module-specific releases. WsprryPi remains authoritative for
application behavior, operator policy, scheduling, integration, and product
qualification. Conflicting contracts require an explicit coordinated change;
neither repository silently overrides the other.

Nothing in this contract authorizes installation, module loading, binding,
system configuration, GPIO operation, transmission, or RF activity.

## Product

The product is source for an out-of-tree Linux module built by DKMS against the
operator's installed stock Raspberry Pi kernel. It supplements the stock
`clk-rp1` provider and does not acquire a private provider lease.

The Debian package contains the versioned module source, Kbuild and DKMS
configuration, canonical UAPI, and inactive `GPIO4` and `GPIO20` overlays. Package
installation does not select a route, edit boot configuration, apply an
overlay, load the module, enable output, or authorize use.

Release checksums and compatibility metadata are functional machine inputs.
They identify artifacts and detect substitution; they are not signatures,
authorization, or qualification by themselves.

## Repository boundaries

### This repository owns

- loadable kernel-module source and kernel-facing lifecycle behavior;
- Kbuild and DKMS configuration;
- route-specific device-tree overlays;
- the bounded canonical userspace API;
- compatibility identities and release metadata;
- package installation, update, rollback, removal, signing, and diagnostics
  behavior; and
- module-specific tests, releases, and security reporting.

### WSPR-Transmitter owns

- its userspace provider adapter;
- conversion of application plans into the UAPI;
- application-side state and terminal-reason handling; and
- adapter tests using fakes or mocks rather than embedded kernel source.

### WsprryPi owns

- physical-backend selection and fail-closed product policy;
- persisted `GPIO4` or `GPIO20` selection;
- scheduling and application integration;
- installation orchestration for explicitly compatible tagged releases;
- operator warnings, diagnostics, authorization workflow, and recovery; and
- product qualification and release decisions.

The repositories coordinate only through tagged artifacts, the canonical UAPI,
compatibility metadata, and explicit cross-repository validation. This complete
module source tree is not vendored into WsprryPi.

## Licensing

- Original module and kernel-facing source uses
  `GPL-2.0-only OR MIT`.
- The module declares `MODULE_LICENSE("Dual MIT/GPL")`.
- Original userspace-visible UAPI headers use
  `(GPL-2.0-only WITH Linux-syscall-note) OR MIT`.
- Independent original tools, tests, documentation, schemas, and metadata use
  `MIT`.
- Original device-tree sources use `GPL-2.0-only OR MIT` unless their actual
  derivation requires a narrower license.
- Imported or adapted material retains its upstream license, copyright, and
  provenance.

The SPDX identifier in each file is authoritative. Kernel loader metadata does
not replace source licensing or resolve derivation questions.

## Kernel and resource model

The module targets stock Raspberry Pi kernels. It must not introduce a custom
kernel dependency or fall back to `/dev/mem`, raw userspace MMIO, unexported
kernel internals, arbitrary physical addresses, or another transmitter backend.

The stock `clk-rp1` provider remains authoritative for ordinary clock
operations. Resources are derived from device tree and exported kernel APIs.
Provider identity, resource layout, DMA translation, pinctrl state, clock state,
and route must pass runtime validation before the endpoint becomes operational.

The module supplies GPCLK0 and the RP1 200 MHz `pll_sys` output as distinct
named clock resources. An output operation explicitly selects the
independently identified provider clock with the common clock framework,
verifies parent and nominal-rate readback, and restores the preceding parent
and rate during bounded cleanup. It does not authorize automatic substitution
of another GPCLK0 source. Consumers must plan divider words from the contracted
200 MHz nominal parent; a consumer that still assumes 50 MHz is incompatible.
Divider plans use the provider's 16-bit integer and 16-bit fractional GPCLK0
field: integer values 1 through 65,535 are valid, while the complete Q16 word
remains bounded by `0xffffffff`.

All frequencies and execution modes share this parent-selection path. Rate
selection can reparent GPCLK0, so checking the parent only before setting a
rate is insufficient. While output is inactive, setup makes at most four
attempts using the observed parent and verifies the planned integer
divider against the provider's whole-Hz readback and Q16 divider bounds.
Every unsuccessful attempt moves the next seed request inward by one more Hz,
including after a parent switch. Keeping that bias across parent switches
prevents repeating an identical nearest-rate parent-selection cycle.
The operation's fractional DMA sequence remains unchanged. Setup selects the
contracted parent after the final rate request and verifies the parent,
200 MHz nominal rate, and integer divider before activation. Preparation
rechecks the parent and nominal rate. No band-specific 50 MHz exception exists.

Cleanup disables output and restores safe pinctrl before restoring the saved
parent and nominal output rate. Restoration also selects the saved parent
after rate requests and checks both identities; it is bounded to four attempts.
When a requested rate equals the common-clock cached rate, an inactive
intermediate rate forces a provider update before the final request, preventing
fractional DMA's last value from surviving a cached no-op.
Each attempt therefore makes at most two provider rate requests.
Unverifiable restoration faults the endpoint, including when startup cleanup
is followed by a second cleanup call. This changes neither the shared PLL's
frequency nor other consumers' clocks. A different future parent contract must
update the module identity and userspace divider planning together.

Only `GPIO4` and `GPIO20` are supported. They are separate administrative routes
with distinct overlays and qualification. The module accepts no arbitrary GPIO
parameter, combined overlay, or automatic route substitution.

## Endpoint discovery and platform-device ownership

Each route overlay owns one route-specific enabled endpoint node beneath the existing `rp1`
bus. The node carries the canonical compatible, route, pin, clock, DMA,
register, and pinctrl identities. Keeping that ancestry is mandatory: resource
translation continues through the stock RP1 device-tree ranges and providers.
`GPIO4` and `GPIO20` use distinct node names. Consequently, applying both overlays
produces two matching nodes and module initialization rejects the ambiguous
topology before publishing an endpoint. With neither overlay there are zero
matching nodes and no endpoint; with exactly one overlay there is exactly one
candidate node. Overlay order can never silently select a last-applied route.

The module owns bounded discovery of that endpoint. Initialization requires
exactly one matching node and rejects zero, duplicate, disabled, malformed,
ambiguous, conflicting, or inconsistently populated nodes. A platform device
already created by the kernel is preferred and must be bound to this driver.
Probe validation requires the endpoint, clock provider, and DMA provider to be
children of the same RP1 node; supplier phandles alone do not establish valid
ancestry.
The module never replaces, unregisters, or otherwise assumes ownership of a
kernel-created platform device.

Some stock Raspberry Pi boot paths do not instantiate a newly overlaid child
of the RP1 node. When the single valid endpoint has no platform device, the
module may create only that exact device with exported OF platform APIs. The
module walks upward from the endpoint and uses the nearest instantiated
platform ancestor as the Linux device parent. On stock Raspberry Pi 5 kernels
the intermediate `rp1` firmware node need not have its own platform device, so
the nearest instantiated ancestor can be the PCIe platform device while the
endpoint's firmware ancestry still passes through `rp1`. Absence of any
instantiated platform ancestor rejects creation. The module records this
ownership and may unregister only the device it created and still owns.
Synchronous creation must also produce a successful bind;
deferred or failed binding rejects module initialization and removes the
module-created device. Owned-device teardown holds the endpoint OF-node
reference across unregister and clears only that node's populated flag after
unregister completes, permitting a later bounded fallback creation without
exposing a duplicate-device window.

The module must not populate or depopulate the RP1 bus generally, create
unrelated children, move the endpoint to an unrelated bus, manufacture
resources, hard-code translated CPU physical addresses, or bypass normal
device-tree address, clock, DMA, or pinctrl translation. Boot-time firmware
overlays and dynamic overlay notification are distinct validation cases and
neither result transfers qualification to the other.

## UAPI

The canonical header is `include/uapi/linux/rp1_gpclk.h`. The UAPI is bounded,
exact, and route-neutral. It does not expose physical addresses,
DMA channels, unrestricted programs, or arbitrary register access.

Requests use fixed-size structures, checked arithmetic, bounded counts and
durations, zero reserved fields, and explicit capability checks. Userspace
pointers are copied once into bounded kernel-owned storage. Unknown commands,
flags, values, routes, capabilities, or structure variants fail closed.

One open file may own one opaque lease. The only submission primitive is a
finite sequence of generic tone/gap events; the module contains no product-mode
or band semantics. Every submission has a strictly increasing generation. A
logical request may span signed 64-bit nanoseconds, but execution materializes
at most one fixed one-second coherent DMA chunk. Timing remainders and dither
state carry across chunk boundaries. Cancellation prevents every successor and
drains at most the current chunk before cleanup. Stale callbacks are rejected.
Owner close retains authority for the bounded drain; on that close path,
successful cleanup and terminal publication revoke both owner and lease.
Ordinary completion with the owner still open retains its lease until release
or close. After authority is released, passive inspection retains the
completed generation and terminal reason without retaining that authority.
Terminal outcomes are stable and specific. A cleanup fault remains latched and
cannot be cleared by releasing a lease.

### Stable UAPI and endpoint identity

The canonical endpoint is `/dev/rp1-gpclk`. The byte-authoritative current
interface is `include/uapi/linux/rp1_gpclk.h`; `uapi-identity.json` records its
SHA-256. The current interface has one set of ioctl identities,
sizes, routes, lease semantics, submission semantics, terminal states, and
cleanup meanings. No legacy layouts or compatibility commands are retained.
The root-owned, root-only mode-`0600` endpoint is production execution
authority. There is no authorization flag, digest, enrollment credential, or
mode-specific admission in the module. The immutable `output_inhibit=1` load
option is reserved for clock-disabled development and lifecycle tests and
rejects submission while retaining administrative and cleanup paths.

Changing the endpoint or canonical UAPI requires coordinated updates to the
module, consumers, diagnostics, tests, and exact header digest. The complete
contract is [RP1 GPCLK userspace interface](uapi.md).

## Lifetime and cleanup

Open-file, platform-device, DMA callback, unbind, overlay, and module lifetimes
are explicit. Managed allocation does not replace reference counting or a
dead-state transition.

Module initialization registers platform-device removal observation before
the platform driver, discovers or creates the endpoint, and publishes success
only after the device is bound. Failure unwinds in strict reverse order.
Module exit detaches its ownership record, unregisters any still-owned created
device so `remove()` can quiesce it, unregisters the driver, and finally
unregisters removal observation. External removal of a created device clears
the ownership record before its storage can be released. Creation holds a
temporary device reference and observes removal across the interval between
device registration and ownership publication. These rules prevent duplicate
creation, stale ownership, double removal, and destruction of a kernel-created
device.

Removal or unbind first prevents new work, rejects stale callbacks, drains or
cancels bounded work, restores only state owned by this module, and proves
resource quiescence before freeing state. The module never restores another
consumer's state from a stale snapshot and never releases a resource it did not
acquire.

Process death, interruption, timeout, unbind, and cleanup failure must converge
to a safe terminal state or an explicit fault that prevents further use.
Worker publication, wakeup, retirement, and completion are serialized. A
self-exiting worker retires its task and plan pointers and publishes completion
before a successor can be admitted; forced-stop fallback pins the task while it
acts on that worker.
`STOP` and close cancellation do not synthesize DMA completion or force-abort an
active RP1 paced descriptor. They reject every successor and allow only the
current kernel-bounded descriptor to drain before cleanup. Cancellation and the
worker's final descriptor check-and-issue boundary are serialized: a descriptor
committed first is the permitted current drain, while cancellation committed
first prevents that descriptor from being issued. No successor can be issued
after `STOP` returns.

On the validated Pi 5 firmware baseline, TICK_DMA0 may be enabled and running
at 50 reference cycles while the downstream DMA_TICK0 handshake is disabled.
After exclusive acquisition of both MMIO resources, development execution may
temporarily stop and later restore only that exact `CTRL=3`, `CYCLES=50`,
`DMA_TICK_EN=0`, `DMA_TICK_CTRL=0` baseline. All other nonzero combinations
remain ownership conflicts. This exception does not permit takeover of an
active DMA handshake or a different tick configuration.

The read-only DMA_TICK DREQ pulse is excluded from configuration ownership and
restoration comparisons. It is not an enable bit. Runtime DMA uses word-aligned
scatterlist entries, keeps pacing enabled across linked blocks, and stops pacing
when the entire descriptor completes. A DMA deadline remains a failure even when
`STOP` was requested; cancellation cannot relabel a failed drain as success.

## Compatibility

Compatibility is deny-by-default for unsupported UAPI/resource contracts, architectures,
routes, UAPI contracts, resources, ownership, and cleanup state. Hardware
eligibility is structural rather than a marketing-model allowlist: the active
endpoint, clock provider, DMA provider, and their ancestry must identify one RP1
instance and expose the exact required resources. This permits Raspberry Pi 5
and future Pi-5-like systems that retain the contracted RP1 topology, while
rejecting lookalike names, missing resources, ambiguous routes, and non-RP1
platforms.

The compatibility ID binds module version, RP1 route, and resource contract. It
does not encode a board model or kernel release and is not an authorization
credential. Exact kernel, configuration, firmware, device tree, and board model
remain build, diagnostic, and evidence observations.

A successful module build establishes build compatibility only. Structural
acceptance is a prerequisite for a bounded experiment, not operator authorization;
it does not qualify timing, cleanup,
coexistence, transmission, waveform, spectral, or RF behavior. `Qualified`
claims remain tied to the exact systems and evidence on which they were
established. Product policy and operator authorization remain in WsprryPi.

The module contains independent `GPIO4` and `GPIO20` compatibility identities.
The unique active device-tree route selects one; zero routes provides no
endpoint and both routes are ambiguous. Overlay order never selects a route.
There is no fallback, substitution, or evidence transfer between routes.
Hostname, board model, and kernel release are retained in evidence and are not
compatibility-ID components.

## Packaging and administration

The [public provider lifecycle](provider-lifecycle.md) owns provider identity,
installation transitions, native lifecycle orchestration, recovery, and removal.
Applications select authenticated inputs, declare consumer interfaces, invoke
opaque provider plans, and retain their own application policy and file ownership.
Product SemVer is data derived from the canonical header; accepted UAPI hashes,
capabilities, limits, and authenticated provenance govern consumer compatibility.

The Debian package owns its declared source for both modules, inactive overlay
files, passive package guard, packaged route executor, schema and disabled units. Standard `dpkg`, `dh-dkms`, and DKMS mechanisms own package lifecycle.
Installation refuses to overwrite foreign files. Removal deletes only files
whose identity and ownership remain attributable to the package.

The package also owns a versioned application-facing
route executor, its JSON schema, and consumer documentation. The executor owns
only its delimited managed route block and attributable journals below
`/var/lib/rp1-gpclk-dkms/route-transactions`. It keeps saved/configured and
post-boot active routes separate, rejects ambiguous ownership, and exposes no
qualification-plan interface. Package installation remains route-neutral and
does not create runtime state.

The [package transition contract](../operations/package-lifecycle.md) requires
read-only preflight before the package manager, exact inactive ownership, complete
payload identity and native DKMS/cache agreement. Exact package repeats converge
without forced module removal. Compatible passive packages support upgrades;
legacy-effects fixtures and unknown lifecycle state require owning removal first.
Downgrade recovery removes the successor before exact retained predecessor
reinstall. [Version identity](versioning.md) defines source-derived identities,
SemVer precedence, Debian ordering, payload conflicts, and upgrade eligibility. No package transition restores runtime sessions,
application state or qualification. Native kernel hooks remain distribution-owned;
external orchestration must retain the documented preflight and state audits.

Signing keys and trust enrollment are administrator-owned. No private key is
distributed or created as a silent installation side effect. Signing proves
provenance and possible load eligibility; it does not qualify behavior.

Diagnostics are bounded and read-only. They do not install, load, bind, repair,
select a route, change boot state, operate GPIO, or enable output.

Exact-source maintainer development is a separate, package-independent
administrative path. Its manifest binds the exact Git commit, explicitly
recorded source state, bounded rendering transformation, DKMS/module/kernel,
UAPI, overlays, route, installed artifact, tools, and removal evidence. Its
state is visibly `source-development` and at most `Experimental`; it cannot
create release metadata, satisfy release compatibility, or establish product
or RF qualification. The canonical module name remains `rp1_gpclk_dkms`.

The exact-source route-manager lifecycle is likewise package-independent. It
must preserve Debian-owned executables and unit fragments, use a reversible
administrator drop-in, bind userspace and module source identities separately,
and expose only passive query while active. Successful deployment or query is
not execution authorization or qualification.

Where `source-development` consumers require current boot ownership, deployment
alone is insufficient. A separate attributable adoption record must bind the
current boot and configuration digest to exact route, userspace, module,
kernel, UAPI, and compatibility identities. Package ownership and completed
journals do not establish that current proof.

While that exact-source binding is active, passive query also returns a nested
`state.safety` snapshot containing authenticated endpoint ownership, endpoint
open state, the observed immutable `output_inhibit` value, and bounded service
states. The snapshot remains observational and cannot acquire the endpoint,
change the module gate, or authorize an operation.

## Validation

The [runtime controller](runtime-controller.md) is a separate administrative
implementation using exported stock-kernel overlay APIs.
It owns overlay IDs and error results, interlocks the consumer's module lifetime,
and supplies concrete route administration and same-boot crash recovery. Test
workflows load the consumer with `output_inhibit=1`; production loads the default
output-capable module only while the application is inhibited and restores the
captured application state after the transition. Digest-bound route plans protect
the administrative transaction but are not kernel execution credentials. It
adds a separate administrative UAPI, not transmission commands. Offline tests
do not establish target qualification; applicable external evidence remains
separately identified and scoped. Deployment and hardware tests remain separately
authorized gates.

A bounded read-only inventory collector does not provide a write adapter or
deployment path. Snapshot observations and offline tests do not establish
exclusion, post-removal success, kernel lifetime safety, or hardware readiness.

The canonical [userspace interface](uapi.md) includes passive snapshots and
root-only execution authority. The passive snapshot exposes presence and tri-state
observations without granting ownership or disclosing lease tokens. Terminal
generation, reason, and completed-unit state remain observable after lease
release until the next successful acquire.

Ordinary checks are offline, unprivileged, network-free, hardware-free, and
safe to repeat. Implementation changes receive deterministic tests. Kernel
build results record the kernel, configuration, compiler, architecture, module
version, exact UAPI header digest, and outcome.

Binding validation records the firmware-applied device-tree node, platform
device, driver link, probe result, and canonical character device as separate
facts. A loaded module or matching OF modalias alone is not binding evidence.

Target tests require inspection of the exact test implementation and explicit
authorization for their system effects. Output-inhibited administration, live
GPIO behavior, timing, transmission, and RF are separate evidence classes and
must not be inferred from one another.

For the current dual-route development identity, structural compatibility also requires
the route-specific endpoint node name emitted by the corresponding current
overlay: `rp1-gpclk-dkms-gpio4` for route `1` or
`rp1-gpclk-dkms-gpio20` for route `2`. Any other endpoint name is rejected even
when its remaining properties are otherwise valid.

The development build reports the route-specific identities in the
[development identity contract](development-identity.md). Its exact RP1
topology, kernel, architecture, module-version, resource, and route observations
apply together.
Only the current exact identities can satisfy this contract; immutable
module/UAPI/overlay hashes remain mandatory evidence.

Hardware-free validation and successful build, binding, or functional output
are separate evidence classes. None establishes waveform or spectral integrity, timing or frequency
accuracy, receiver capture or decode, WsprryPi product-path behavior, product
eligibility, transmitter-system qualification, SDR qualification, RF
qualification, packaging evidence, or release qualification.

## Releases

A release is tagged, checksummed, reproducible from source, and accompanied by
compatibility, provenance, licensing, and security metadata. The source
version, tag, Debian version, DKMS version, module version, UAPI, package, and
release metadata must agree according to the release policy.
Public package filenames use the GitHub-safe projection defined by the
[version identity contract](versioning.md); native Debian control versions
retain prerelease ordering.

Version `1.0.0-rc.1` is a prerelease for evaluation. The
[candidate procedure](../operations/release-candidate.md) defines exact clean-source
builds, inventories, checksums, and independent reconstruction. The package owns
both interlocked modules; neither is loaded at installation. Both route overlays
remain inactive under `/usr/lib`. Package operations do not modify boot routes
or operate services. Native helper compatibility is checked against the package preflight policy;
unknown signing mechanisms require review and fail closed.

Ordinary editable GitHub releases are supported. Release immutability, tag/asset
locks, required attestations, and equivalent permanent publication restrictions
must not be enabled or required. A local release-profile flag identifies intended
metadata only, with `published: false`; actual publication requires separate
user authorization and independent source/download verification. The first
stable `v1.0.0` release remains a separate readiness decision.

WsprryPi consumes only explicitly selected, compatible, verified provider source
or a separately published release, never the moving default branch for production.
Automatic release selection includes published prereleases and uses SemVer
precedence; a final version sorts above prereleases of the same version.
Module and application reviews, commits, releases, and acceptance remain separate.
No old release or externally owned qualification bundle qualifies changed source.
See [qualification boundaries](../operations/qualification-metadata.md).

### Opt-in runtime management integration

The [runtime manager workflow](../operations/runtime-manager-workflow.md) uses a
separate runtime profile on the existing privileged socket. It binds the complete
runtime inventory, serializes deployment and route effects, preserves removal
errors and ownership, and restores application availability after successful switching
through the [application restoration contract](runtime-application-restoration.md).
Failed or unresolved transactions retain owned inhibition. This development
profile does not change the packaged compatibility contract, transmission UAPI,
release status, or hardware qualification. Application/browser adaptation remains
owned and reviewed in WsprryPi.

The runtime profile distinguishes fail-closed `recover` from operator-intended
`remove`. Recovery always ends route-neutral and application-inhibited. Removal
may restore the captured service intent only after the same recovery transaction
proves an exact neutral controller, absent consumer route, disabled output, and
matching durable evidence. It never starts a service that was previously stopped
or administrator-masked.

Runtime-owned routes can use the canonical operation lease through the
[application reconciliation extension](runtime-output.md). Application output
stays inhibited during reconciliation; this does not add qualification or
change the kernel ownership contract.

The canonical installer-facing entry point for this profile is
`/usr/lib/rp1-gpclk-dkms/runtime_provider.py`. Its versioned JSON contract
classifies the aggregate state as `absent`, `deployment_required`,
`activation_required`, `neutral_ready`, `exact_ready`, `recovery_required`, or
`conflict`. Readiness binds the exact source commit,
product and route compatibility identities, kernel, both modules and build notes,
both UAPIs, both runtime overlays, runtime tools and schema, systemd units and
drop-in, WsprryPi application companion, deployment binding, journals, endpoints,
socket, selected route, application restoration, and passive output state.
`exact_ready` is unavailable unless the active route is singular and aligned,
the application restoration is terminal and safe, both endpoints and the socket
are attributable, the consumer endpoint is closed, and passive UAPI state proves
`output_inhibit=0`, `executionAuthorized=false` from matching absent owner and
lease observations, operational resource readiness, and stable clock/GPIO/DMA
quiescence. Unknown or mixed identity fails closed.

The facade composes the existing deployment and route-manager implementations;
it is not a competing manager. Filesystem deployment and route selection remain
separate digest-bound operations. Between them, `activation-plan` and
`activation-ensure` establish only the exact controller and manager socket in a
zero-route state, then restore the application according to its captured service
intent. The consumer remains unloaded and `/dev/rp1-gpclk` remains absent.

Neutral activation ensures the persistent `rp1-gpclk-route` system group exists before starting the manager socket, including installations performed without Debian package configuration. An existing group is reused without changing membership or its numeric identity. Inspection and planning do not create accounts. Recovery and removal retain the group, as with the Debian package lifecycle.

Activation completion verifies the captured application restoration intent.
Later passive neutral readiness accepts a stable start, stop, or restart of the
bound application service while retaining the exact neutral hardware and
activation evidence. Route preflight separately validates the current service
and application state before selecting a route.
Neutral activation is neither route selection nor transmission eligibility.
None of these operations authorizes output. Exact repeated execution is
idempotent. A same-boot completed route remains attributable to its neutral
activation only when the binding, boot, controller session, increasing
generation, route transaction, manager response, and restored application
journal form one exact chain. If that route is subsequently recovered to a
nonzero neutral controller generation, the facade reports `recovery_required`
instead of a generic conflict only when the digest-bound activation recovery
planner validates the complete same-boot route, manager, and application
journal chain. An exact operator-requested removal is the narrow exception:
after its matching neutral application restoration is terminal and the current
service state, controller, journals, endpoints, socket, artifacts, boot, and
binding still agree, the facade reports `neutral_ready` and permits a new
read-only route plan. The manager revalidates the completed removal and live
service state during preflight before a reviewed route digest can be produced.
A completed prior-boot neutral activation may be superseded only
after its exact evidence, any coherent terminal route journal set, and the
inactive current-boot state are validated and the application is inhibited.
Normal reboot activation requires the full terminal chain, not the partial
suffix permitted by explicit migration. Its reviewed digest binds prior-boot
route evidence and current application intent; a durable `reboot-prepare`
checkpoint precedes inhibition and dependency-ordered retirement. Exact retries
retain that intent, and the new controller session must differ from the prior
boot. WsprryPi must separately orchestrate activation and its persisted route
through the public facade. Provider readiness alone does not implement normal
application startup recovery.
Candidate-owned retirement binds every present journal and application-owned
idle override by digest, removes that override while ownership remains proven,
and removes dependent journals before activation evidence so interruption is retryable. A
pending deployment, activation, controller
fault, incomplete route journal, or failed application restoration is reported as `recovery_required`;
foreign, substituted, mixed, unsafe, open, or contradictory state is `conflict`.
During an exact inverse deployment, a same-boot `recovered-inhibited` route
journal chain may likewise be retired after the modules, endpoints, manager
socket, and application are all verified inactive and inhibited. This remains
retryable when the recovered activation journal is archived or an interrupted
retirement has removed only an ordered prefix of dependent journals.
Applications use the versioned [update preparation contract](runtime-update.md)
for provider recovery and inverse deployment. The provider interprets sessions,
generations, journals and interrupted removal; applications retain version
selection, installation provenance, configuration and service orchestration.
The update contract also exposes a provider-validated installation receipt.
The source-development manager remains passive-query-only.
