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
Package-transition tests use current passive packaging at synthetic versions.
They establish no publication or predecessor support. Compatible passive packages
support normal upgrades. Unknown lifecycle state confers no replacement authority.
See [versioning](versioning.md).

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
2. **Same-version repeat or repair:** exact source and installed module hashes,
   matching installation parameters, and an intact DKMS registration allow an
   inactive repeat to retain its artifacts and original removal receipt. Changed source under the same version is a supported replacement; installed
   edits require preservation and owning repair. Missing modules require
   verified rebuilding. A mutation retains `prior-source` and original installed
   artifacts in the external evidence directory before removing the instance.
3. **Package transitions:** exact repeated installation is convergent. Compatible
   passive packages upgrade through native dpkg/DKMS after an external incoming
   preflight. Legacy-effects fixtures and foreign origins remain cleanup-first.
   Explicit downgrade recovery removes the successor before reinstalling retained
   predecessor bytes. See [versioning](versioning.md) and the
   [package procedure](../operations/package-lifecycle.md).
4. **Source-development upgrades:** an inactive exact owned source from this
   repository may advance to a newer compatible version. Build profile must agree; exact new UAPI identity remains recorded. Same-version changed source can replace an owned build. Other kernels,
   foreign origins, enrollment, and runtime state require owning cleanup first.

No transition command grants host, system, GPIO, transmission, or RF authority.
Actual-host installation, removal, and recovery require a reviewed host-specific
plan and separate authorization. Offline fixtures establish only deterministic
workflow behavior.

The source installer's `--build-only` still registers source and builds through
DKMS with privilege; it is not the unprivileged direct Kbuild path. Its
`development-rollback` removes the recorded installation and does not restore
the retained predecessor automatically. The source-development firmware
route/overlay helpers also have narrower ownership checks than the
runtime/package workflows; review
their [explicit limits](../operations/source-development.md#firmware-helper-limits)
before including them in a target plan.

## Identity and transitions

Product, package, module, route and interface identities are defined by their
canonical machine-readable sources. Development identity does not establish
publication. Installation from another repository requires manual removal
before the current source is installed; version comparison cannot authorize
adopting that state. Candidate/publication metadata stays unpublished and
unqualified until separately accepted publication and qualification decisions.
