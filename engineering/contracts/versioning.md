<!-- SPDX-License-Identifier: MIT -->

# Version identity and package transitions

`include/rp1_gpclk/version.h` is the authoritative declaration of the product
SemVer and the independent Debian packaging revision. `scripts/version_identity.py`
parses it strictly and derives module, DKMS, route compatibility, package, tag,
filename, and metadata identities. Change that declaration when preparing a new
product version or packaging revision. Tooling contains no current-version
allowlist. UAPI, JSON schema, protocol, dependency, and kernel versions are
independent contracts and do not follow product numbering.

The Debian changelog is a maintained template. Candidate builds render its version
in their disposable source trees. For a direct Debian build, copy the source to a
new disposable directory, run `python3 scripts/version_identity.py prepare-debian`
there, then run `dpkg-buildpackage --no-sign -b`. Do not render the template in the
maintained checkout. Generated packages, source trees, receipts, and manifests
contain resolved identities. Installed helpers and retained runtime bundles carry
their own exact canonical header and helper, independent of a newer checkout.

SemVer compares numeric components and prerelease identifiers; build metadata
has no precedence. Debian versions map prereleases to `~` and retain an independent
packaging revision. Native comparisons use `dpkg --compare-versions`. An upgrade
must have nondecreasing SemVer precedence and increasing Debian order. Ordering disagreement is reported explicitly. Different build metadata at equal
SemVer precedence identifies a replacement, subject to native Debian downgrade
ordering. Build metadata is never treated as a SemVer precedence component.

Published Debian package filenames replace the native version's `~` with `.`
because GitHub normalizes that character in release asset names. Package control
metadata retains `~` and its Debian ordering. The builder verifies the native
filename before copying the unchanged bytes to the public filename; manifests,
checksums, and consumers use that public name. Stable filenames are unchanged.

Before dpkg or APT, run the incoming reviewed source's read-only package guard
with `unpack --package /absolute/verified/PACKAGE.deb`. It authenticates outgoing
ownership, inactivity, module/cache agreement, repository, passive lifecycle,
canonical UAPI hashes, and the incoming package's own identity receipt. The
incoming preinst repeats this check without trusting installed executable code.
An outgoing prerm runs before an incoming preinst, so the external check is
required. Exclude concurrent privileged package/DKMS/runtime administration.

- Clean installation requires no foreign provider state.
- Same product and Debian version with identical payload and scripts is an
  idempotent repeat. It retains installed modules; native DKMS converges without a
  forced removal. Missing attributable payload can be restored by exact reinstall.
  Deliberately supplied different payload under the same identity replaces the
  old build through native DKMS cleanup before unpack, then rebuilds. Changed
  present installed files require explicit preservation and owning repair.
- A newer compatible package retires the old native DKMS registration and module
  artifacts through its owning scripts. dpkg removes superseded versioned source
  and schema paths. The new package configures every eligible installed kernel.
- Packaging revision upgrades may retain the upstream module version; they still
  replace the attributable instance through the native package lifecycle.
- Downgrades require an explicit reviewed owning removal and exact retained
  package reinstall. There is no silent in-place downgrade or force flag.
- Unknown repository/lifecycle and legacy-effects fixtures,
  active runtime/module state, and changed or foreign data require their specific
  owning recovery or migration. Numeric ordering alone grants no ownership.

An interrupted upgrade can leave an attributable partially configured successor.
Repair the proven prerequisite and retry that exact package's configuration.
Retain recovery inputs before replacing a version. No transition restores an
application session, route, qualification, or RF authorization.

Source-development uses the same strict product ordering. An inactive exact owned
source from this repository may be replaced or upgraded with the same build profile.
Changed source under an identical version is supported after owned backup and replacement. An exact inactive source repeat with matching recorded module hashes retains
the installed artifacts and original removal receipt. Missing module evidence
requires verified native rebuilding. Explicit load requests retain their separate
administrative path. Retained enrollment/runtime state, other-kernel source
instances, and foreign origins require their owning cleanup first.

The restricted `tests/package_upgrade_linux.py` harness builds two distinct
passive package versions and exercises native install, repeat, upgrade, failure
retry, remove, and purge with independent obsolete-artifact checks. Its container
has no networking, host system/device mounts, module/service/GPIO privileges, or
hardware access. These checks establish package behavior only.
