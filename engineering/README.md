<!-- SPDX-License-Identifier: MIT -->

# Engineering reference

The published [operator handbook](../docs/index.md) covers WsprryPi-managed
installation, route control, status and recovery. This directory holds the
technical contracts and procedures needed to maintain the provider.

## Start with the management profile

Read the [module contract](contracts/rp1-gpclk-dkms-module-contract.md) first.
Identify the installed profile before choosing tools: the shared socket name
does not make their protocols or recovery records interchangeable.

| Profile | Entry point and evidence | Administration boundary |
| --- | --- | --- |
| Packaged boot-route executor | `/usr/sbin/rp1-gpclk-route-manager`; contract `rp1-gpclk-route-manager` | Owns a delimited boot block and reboot/reconciliation transactions. It is not the runtime switching protocol. |
| Passive source-development manager | `development-route-manager`; exact source/module binding and current-boot adoption | Its socket accepts passive `query` only. Installing, adopting or rolling back that binding are separate administrator mutations. Adoption does not make firmware overlays removable. |
| Runtime manager | `runtime_provider.py` facade and `runtime_route_client.py`; the current binding, readiness and runtime socket contracts | Deploys and activates neutral administration separately from route selection. Switching, removal and recovery have different application outcomes. |

The Debian package installs source and inactive administration files. It does
not deploy or activate the runtime profile. WsprryPi normally orchestrates that
profile; standalone maintainers need the complete
[runtime workflow](operations/runtime-manager-workflow.md), not individual copied
scripts. Package ownership, source-development enrollment and runtime binding
are separate records.

For hardware-free work, start with [testing](testing.md#run-the-offline-checks).
For an existing WsprryPi installation, use the operator handbook before reaching
for lower-level tools. Command examples with mutation are alternatives for a
reviewed state, not a script to execute in sequence.

[Source provenance](source-provenance.md) identifies imported source and adapted fixtures.

## Contracts

- [Module ownership, safety, compatibility and distribution](contracts/rp1-gpclk-dkms-module-contract.md)
- [Canonical userspace interface](contracts/uapi.md)
- [Route manager](contracts/route-manager.md)
- [Runtime controller](contracts/runtime-controller.md)
- [Application restoration](contracts/runtime-application-restoration.md)
- [Runtime output reconciliation](contracts/runtime-output.md)
- [Runtime updates](contracts/runtime-update.md)
- [Exact development identity](contracts/development-identity.md)
- [External qualification harness integration](contracts/qualification-harness-integration.md)

## Development and administration

- [Testing and maintained inventory](testing.md)
- [Exact-source development](operations/source-development.md)
- [Runtime deployment and route workflow](operations/runtime-manager-workflow.md)
- [Debian packaging](operations/debian-packaging.md)
- [Package transitions, recovery and rollback](operations/package-lifecycle.md)
- [Module lifecycle](operations/lifecycle.md)
- [Signing and trust](operations/signing.md)
- [Diagnostics implementation and limits](operations/diagnostics.md)
- [Release build and publication](operations/release-candidate.md)
- [Route qualification evidence](operations/qualification-metadata.md)
- [Documentation maintenance and publication](documentation.md)
- [Reusable repository cleanup instructions](development/repository-cleanup-prompt.md)

These procedures do not grant installation, module/overlay, GPIO, transmission
or RF authorization. Follow the applicable ownership and safety contract.
