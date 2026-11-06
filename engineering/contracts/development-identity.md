<!-- SPDX-License-Identifier: MIT -->

# Development identity and installation transitions

The source supports finite
generic events, fixed-memory DMA chunking, exact `GPIO4`/`GPIO20` selection,
runtime switching through none, bounded cancellation/drain, and application restoration.
WsprryPi owns present/future modes and product policy; DKMS enforces resource,
ownership, capability and cleanup contracts without a product-mode allowlist.

| Identity | Current development contract |
| --- | --- |
| Product/upstream, consumer module, DKMS identity | Canonical version header and generated manifests |
| Debian identity and filename | Debian changelog and generated package metadata |
| Package/DKMS name | `rp1-gpclk-dkms` |
| Consumer module / endpoint | `rp1_gpclk_dkms` / `/dev/rp1-gpclk` |
| Controller module | `rp1_route_controller`; part of the same candidate DKMS package |
| Source and schema destinations | Versioned paths recorded by the installation manifest |
| Transmission UAPI | Exact `include/uapi/linux/rp1_gpclk.h` bytes and SHA-256 |
| Administrative UAPI | Exact `include/uapi/linux/rp1_route_admin.h` bytes |
| Development manifest | `rp1-gpclk-source-development-manifest` |
| Route-manager protocols | Packaged/source and runtime profiles |
| Route compatibility identities | Canonical `scripts/runtime_binding.py` mapping for GPIO4 and GPIO20 |
| Classification | `source-development` / `Experimental`; not release-qualified |

Current identity values come from machine-readable source and generated
metadata, not duplicated version claims in documentation.

Product, Debian, DKMS, UAPI, and schema identities are distinct. Current
compatibility IDs identify the RP1 resource contract and route. `Experimental`
is reported separately through the UAPI and development record. Kernel release is
recorded in build manifests, diagnostics and enrollment records, but is not part
of the compatibility ID and is not a per-release permission list. Exact hashes
identify each build. Canonical route overlay names and endpoint nodes are stable
and carry no product-version suffix.

An operator may build the selected source through DKMS for another stock Raspberry Pi kernel
on a structurally compatible RP1 system without defining a new compatibility
ID. The running kernel must still be identified, the module must be built for
it, and all route, resource, ownership, signing, and cleanup checks still apply.
Such use establishes no support or qualification claim. A kernel change can
change module bytes and therefore requires the normal DKMS rebuild and artifact
identity checks.

The supported development paths remain `development-*` and the explicit runtime
manager. Source-development renders the same version with separate Experimental
identity and no release metadata. The [candidate pipeline](../operations/release-candidate.md)
produces the unpublished package and release-shaped consumer metadata from a
clean exact commit. Candidate preparation does not freeze or publish the provider.
The package-transition tests use a normalized synthetic predecessor;
the synthetic fixture tests legacy lifecycle effects only. No predecessor has
a direct in-place upgrade path into this candidate. Owning removal precedes
a clean installation; version ordering alone does not establish migration safety.

## Maintainer transition policy

1. **Clean install:** external orchestration uses
   `development-install --route-neutral --output-inhibit 1 --install` from a clean
   exact commit. It installs the DKMS source and module for the named kernel but
   does not select a route, install or apply an overlay, enroll, load, edit boot
   configuration, operate a service, or enable output. Its manifest records
   `route: null` and exact installed identities. A route-specific maintainer may
   instead render the exact selected checkout with
   `scripts/render-development-tree --source SOURCE --output NEW_TREE`.
   The renderer derives the version from the canonical source header and changes
   only the DKMS placeholder and explicit development kernel filter.
   `development-install` needs no release package or tag.
2. **Same-version replacement:** the source installer requires the complete
   recorded inventory to match the existing development tree. Foreign files,
   changed bytes, symlinks, package ownership, other kernel instances and stale
   enrollment/manager/runtime state block replacement. It retains `prior-source`
   and original installed/compressed module files in the new evidence directory,
   with hashes and DKMS status in `ROLLBACK.json`, before removing the instance.
3. **Package transitions:** same-version reinstall is supported only for exact
   attributable inactive package state. The synthetic predecessor exercises legacy effects without original Git history. Direct upgrades
   from it and in-place downgrades are refused. Use owning predecessor cleanup
   and removal before successor installation. Exact rollback removes the
   successor before reinstalling retained predecessor bytes; it does not restore
   runtime or application state. An external read-only preflight precedes dpkg/APT
   because Debian invokes the outgoing prerm first. See the current
   [package transition procedure](../operations/package-lifecycle.md).
4. **Source-development non-current installation:** no general compatibility,
   adoption or automated migration is claimed. Installer transitions refuse non-current or foreign
   DKMS, source, module, overlay, enrollment, manager, or runtime state. A
   maintainer must separately inventory ownership, quiesce the application,
   prove output/clock/DMA/GPIO cleanup, preserve a recovery point, and use the
   owning workflow to remove only attributable state before a clean install.
   The candidate-provider retirement of an exact prior-boot terminal activation
   journal is one bounded WsprryPi-owned runtime migration, not a general
   exception. There is no force flag or version-normalization bypass.

No transition command grants host, system, GPIO, transmission, or RF authority.
Actual-host installation, removal, and recovery require a reviewed host-specific
plan and separate authorization. Offline fixtures establish only deterministic
workflow behavior.

The source installer's `--build-only` still registers source and builds through
DKMS with privilege; it is not the unprivileged direct Kbuild path. Its
`development-rollback` removes the recorded installation and does not restore
the retained predecessor automatically. Legacy firmware route/overlay helpers
also have narrower ownership checks than the runtime/package workflows; review
their [explicit limits](../operations/source-development.md#firmware-helper-limits)
before including them in a target plan.

## Identity and transitions

Product, package, module, route and interface identities are defined by their
canonical machine-readable sources. Development identity does not establish
publication. Installation from another repository requires manual removal
before the current source is installed; version comparison cannot authorize
adopting that state. Candidate/publication metadata stays unpublished and
unqualified until separately accepted publication and qualification decisions.
