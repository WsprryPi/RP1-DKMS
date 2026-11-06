<!-- SPDX-License-Identifier: MIT -->

# Module lifecycle

The Debian package, DKMS, module runtime, device-tree overlays, and signing
identity have separate ownership and lifecycle. Treat them separately and fail
closed when current state is incomplete or ambiguous.

## Installation behavior

Package installation registers the module source with DKMS and installs both
allowlisted overlays as inactive files. It does not:

- select `GPIO4` or `GPIO20`;
- edit boot configuration;
- apply a device-tree overlay;
- load or bind the module;
- create a signing identity;
- enable GPCLK or change GPIO state; or
- authorize transmission.

Exact-source development installation also provides a route-neutral mode. It
installs the selected commit through DKMS but installs no route overlay and
requires the module, endpoint, configured route, and active route to remain
absent. It emits exact module, kernel, UAPI, and rollback identities for an
external orchestrator. Later overlay, route-record, and load operations
are separate lifecycle steps.

Route selection is an administrative configuration decision. Exactly one of
the `GPIO4` or `GPIO20` overlays may be selected. There is no arbitrary GPIO
parameter, combined overlay or automatic substitution. A loaded consumer's
route never changes in place. The runtime profile can switch without reboot by
inhibiting the application, unloading the consumer, removing the owned overlay,
passing through neutral, then applying the selected overlay and restoring the
consumer/application. Firmware boot routes use a different lifecycle; see the
[profile selection](../README.md#start-with-the-management-profile).

## Compatibility and signing

Before loading the module, record the exact running kernel, hardware, firmware
and device tree; verify that DKMS built the module for that kernel; and validate
the RP1 ancestry, clock and DMA providers, resource layout, selected route,
module version, exact UAPI identity, and signing policy. Kernel and board names
are diagnostic provenance rather than compatibility-ID components.

The device endpoint remains root-owned and mode `0600`. Signing keys and trust
enrollment are administrator-owned and are not package content. See
[Module signing and key enrollment](signing.md).

## Loading and operation

The sole canonical transmission endpoint is `/dev/rp1-gpclk`. No alternate
endpoint spelling is a supported discovery fallback. A missing
endpoint does not authorize userspace to create or substitute one.

Production loads with the immutable default `output_inhibit=0`; the root-owned,
mode-`0600` endpoint is then the execution authority. Clock-disabled development
and lifecycle testing loads with `output_inhibit=1`, which retains query,
ownership, cancellation, cleanup, and lifecycle paths but rejects submission.
Either path still requires the recognized structural RP1 and route identities.

One open file may hold one lease. All submissions are finite generic event
sequences. Long logical events use fixed one-second coherent DMA chunks, so
memory and cancellation bounds do not scale with duration. `STOP`, `RELEASE`,
owner close, process death, unbind, and unload use the bounded cleanup path. A
cleanup fault is a stop condition and prevents further use until it is
investigated.

## Update and rollback

Retain exact predecessor packages and recovery inputs until the replacement has
passed its separately scoped checks. The [package transition procedure](package-lifecycle.md)
requires owning removal before any non-current version is replaced by the selected current source
and before exact remove/reinstall rollback. Direct upgrade/downgrade is refused.
Version ordering alone does not establish compatibility.

On failure, remove only state attributable to the failed replacement. Do not
weaken compatibility or signing policy, overwrite foreign files, or force an
unknown runtime state to make an update succeed.

## Removal

Unload before DKMS uninstall. Remove only module, overlay, and package state
owned by this package. An applied overlay, open endpoint, active owner, pending
work, cleanup fault, modified file, unknown clock state, or unproven resource
state blocks automatic removal.

After removal, verify that the module is unloaded, the device endpoint and
platform binding are absent, the package version is absent from DKMS, owned
overlay files are absent where safe to remove, and GPIO/clock state matches the
recorded inactive baseline. Administrator signing keys, certificates, trust
entries, shared configuration, and unrelated files are retained.

## Diagnostics

Use the source-tree [diagnostic collector](diagnostics.md) for bounded read-only
inspection. It does not load,
bind, repair, select a route, edit boot configuration, or operate hardware. See
[Read-only diagnostics](diagnostics.md).

There is no `/dev/mem`, raw userspace MMIO, arbitrary-route, or
alternate-transmitter fallback. Unknown hardware, kernel, device-tree,
resource, signing, route, UAPI, artifact, or cleanup state remains unavailable.
An identified stock-kernel RP1 combination may be classified `Experimental`
without asserting that it is qualified.
