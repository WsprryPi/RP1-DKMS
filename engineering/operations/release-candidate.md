<!-- SPDX-License-Identifier: MIT -->

# Source and package preparation

The builder prepares unpublished artifacts from one exact clean Git commit in
an identified Linux Debian packaging environment. The independent validator
rebuilds the package and verifies source, control/payload inventories, checksums,
UAPI, overlays, compatibility, tool identities, and reproducibility. Outputs must
be outside every source checkout. No builder or validator publishes anything.

## Build environment

Use `tools/release-builder.Containerfile` for package tools or the reviewed
`tools/package-lifecycle.Containerfile` for representative-header container tests.
Keep dependency identities and compiler/header configuration with temporary
build results. No physical target or host module installation is part of a build.

```sh
module_version=$(sed -n 's/^#define RP1_GPCLK_MODULE_VERSION "\(.*\)"/\1/p' include/rp1_gpclk/version.h)
./scripts/build-release-candidate --version "$module_version" --source-commit "$(git rev-parse HEAD)" --output /absolute/new-candidate
./scripts/validate-release-candidate --candidate /absolute/new-candidate --source-commit "$(git rev-parse HEAD)"
```

The seven artifacts are the source archive, Debian package, installation manifest,
compatibility manifest, release metadata, candidate validation metadata, and
`SHA256SUMS`. Candidates declare `published: false`; compatibility defaults to
Unavailable without invented entries. Qualification fields remain false.

## Ordinary release profile

The explicit `--release` option prepares an ordinary release-shaped metadata
profile with the intended tag and URL. It still declares `published: false`:
intended identity is not observed publication. Candidate and release profiles
are distinguished and independently validated, but neither proves a GitHub
release exists. Source and package bytes remain reproducible in either profile.

Publication is a separate, explicitly authorized operation after readiness is
accepted. Use ordinary editable GitHub releases. Do not enable release immutability,
tag/asset locks, equivalent permanent restrictions, required signing, attestations,
or provenance enrollment as release gates. Preserve checksums and exact source
identities; verify downloaded assets against the reviewed package and metadata.
No GitHub settings changes are part of local release preparation.

The first stable release requires the user's readiness decision.
WsprryPi consumer acceptance and release decisions remain independently owned.
