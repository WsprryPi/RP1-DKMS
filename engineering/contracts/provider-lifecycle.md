<!-- SPDX-License-Identifier: MIT -->

# Provider installation lifecycle

`scripts/provider_lifecycle.py` is the public installation facade. It owns
provider source/package verification, installation, repeat/replacement/upgrade
classification, predecessor recovery retention, native lifecycle operations,
runtime preparation, neutral activation, removal, and provider absence checks.
It composes the existing development, package, and runtime implementations.

The application selects a source channel or exact source/artifact and supplies
its interface requirements. It owns its configuration, executable, services,
web integration, application companions, and application file retirement.
Neither side reconstructs the other's private recovery plans.

## Public identity

`identity` returns one bounded JSON envelope with integer `schemaVersion: 1`,
`contract: rp1-gpclk-provider-lifecycle-v1`, the operation, and `status: ok`.
Its `providerIdentity` has the `rp1-gpclk-provider-identity-v1` contract and
reports repository/module, product and Debian versions, runtime/lifecycle
interfaces, lifecycle capabilities, both route compatibility identities, and
canonical consumer/controller UAPI hashes. The canonical version header is the
only product-version declaration. Python assignment syntax is not an interface.

Consumer requirements contain an integer schema version, required interface
contracts, canonical UAPI hashes, and lifecycle capabilities. Product numbers
do not select a consumer implementation. A later or prerelease product can be
accepted only while its declared interfaces satisfy the consumer. Kernel query
sizes, limits, capabilities, resource identities, and safety state remain
independent runtime requirements; metadata does not grant execution authority.

## Planning and effects

Commands use `--client CLIENT_ID` before the operation. The provider receipt
records that client separately from provider ownership. A client cannot replace
or remove another client's instance. The default receipt is
`/var/lib/rp1-gpclk-dkms/provider-installation.json`.

1. `prepare --state-dir PRIVATE_DIRECTORY --install auto|true|false
   --source SELECTOR --source-policy development|production|explicit-source
   --requirements REQUIREMENTS_JSON` resolves a source once, validates identity,
   requirements, existing ownership and semantic/native ordering, and writes
   only caller-selected private staging data. It returns the installation
   decision, transition classification, and opaque `planSha256`.
2. `plan-status --state-dir PRIVATE_DIRECTORY` reads the staged plan. The caller
   must retain the digest acknowledged by `prepare` or the preceding successful
   effect and reject an unexpected digest change.
3. `prepare-runtime-update --state-dir PRIVATE_DIRECTORY --plan-sha256 DIGEST`
   prepares the installed runtime through its public update contract before
   application/provider replacement.
4. `apply --state-dir PRIVATE_DIRECTORY --plan-sha256 DIGEST` invokes native
   provider installation or owning predecessor removal and replacement. It
   loads neither module. The application can then install its own companions,
   configuration and executable.
5. `activate-runtime --state-dir PRIVATE_DIRECTORY --plan-sha256 DIGEST`
   establishes the exact neutral runtime through the existing runtime facade.
   It selects no route and grants no output authority.

Each successful effect returns the newly acknowledged plan digest. Plans bind
the frozen candidate and predecessor receipt digest; effects reject stale
receipts and revalidate exact source/package/runtime inputs. The global
`/run/lock/rp1-gpclk-provider-lifecycle.lock` serializes provider effects. This
empty coordination file is retained until reboot so another waiter cannot
acquire a replacement lock inode. Native DKMS/package/runtime locks and guarded
recovery remain authoritative for their respective effects.

Identical source/artifact inputs retain attributable installed modules and the
original native removal receipt. A changed source or release payload at equal
SemVer precedence is a replacement. Increasing SemVer is an upgrade; release
transitions also require nondecreasing native Debian order and reject ordering
disagreement. Build metadata has no SemVer precedence. Downgrades require
explicit owning removal and reinstall. None of these classifications permits
overwriting unexplained changed installed files or adopting foreign state.

There is no automatic retry of a failed effect. Preserve the staged plan,
receipt, and recovery inputs. A fresh installation request observes the actual
interrupted state and uses the existing attributable recovery workflow.

## Removal and retained tools

`status` validates and returns the provider receipt. `removal-plan` supplies an
opaque digest for the current receipt. Use `prepare-runtime-removal` with its
reviewed digest before application teardown, obtain a fresh `removal-plan`, then
use `remove --plan-sha256 DIGEST`. A successful removal proves
`postconditions.providerAbsent: true` and
`postconditions.transmissionAuthorized: false`. Nonzero exit status, malformed
JSON, unknown contracts, or contradictory postconditions are failures.

The provider retains a content-addressed complete facade closure under
`/var/lib/rp1-gpclk-dkms/facade`, independent of runtime inverse deployment.
`active.json` identifies its exact entry point and file hashes. Clients verify
the root-owned, non-writable, no-symlink closure before execution. Owning removal
retires only verified facade copies after native absence is established. The
receipt also records dedicated configuration/drop-in directories absent before
installation; removal retires those only when still owned and empty. Existing
or nonempty directories are preserved.
Completed development evidence and immutable predecessor recovery inputs remain
attributable recovery material rather than installed provider payload. They may
be retired separately only after terminal rollback and absence of live references.

The explicit `adopt --receipt EXPORTED_RECEIPT` adapter accepts the prior
WsprryPi ownership schema from a client-supplied, protected export. It verifies
the existing native/runtime evidence before creating the provider-owned receipt.
The client retires its unchanged old receipt only after successful adoption.
The provider does not discover or rewrite application configuration or records.

Production source selection requires actual eligible published artifacts.
Development selection can use exact authoritative commits or explicitly selected
clean local development checkouts with canonical origin and complete provenance.
Local fixture commits remain unpublished development evidence. Installation,
neutral administration, native lifecycle tests, and RF qualification are separate.

## Non-installing release acceptance

`verify-release --state-dir PRIVATE_DIRECTORY --requirements REQUIREMENTS_JSON`
verifies a published release through the provider's artifact/source parser. The
optional `--tag TAG` selects one eligible published release; otherwise selection
uses the latest eligible published release, including prereleases, by SemVer
precedence. `--compare-candidate DIRECTORY` requires
the independent local candidate's complete asset inventory and hashes to match
the publication. The `release-audit` capability advertises this interface.

The operation writes only private caller staging data. It performs no installed
inventory, runtime, package installation/removal, service, overlay, or module
operation. Its public result reports source commit/tree, provider identity,
publication verification, candidate comparison, and `installationPerformed: false`.
A release-profile rebuild alone never establishes publication or qualification.
