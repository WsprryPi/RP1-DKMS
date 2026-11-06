<!-- SPDX-License-Identifier: MIT -->

# RP1 DKMS

RP1-DKMS provides Linux kernel modules and managed GPIO route administration for
RP1 on Raspberry Pi 5 and Compute Module 5 systems. DKMS builds the modules for
the installed stock Raspberry Pi kernel. The stock `clk-rp1` driver remains the
clock provider; no custom kernel is required.

Version `1.0.0-rc.1` is a prerelease for evaluation. WsprryPi independently
controls production provider selection. Build results do not
establish hardware, timing, waveform, spectral, or RF qualification.

## Capabilities and use

The module supports finite tone/gap sequences, exclusive ownership, passive
status queries, and bounded cancellation. GPIO4 (standard header pin 7) and
GPIO20 (pin 38) are separate administrative routes; only one may be active.
Unknown identity, conflicting ownership, or uncertain cleanup blocks operation.
Use the carrier mapping for custom connectors.

The source package contains both modules, canonical userspace interfaces,
inactive route overlays, and route management tools. Package installation does
not load modules, select a route, edit boot configuration, operate services, or
authorize output. Runtime deployment, neutral activation, route selection, and
transmission are separate operations. A GPIO clock signal requires suitable RF
interfacing, termination, and filtering.

The local operator handbook explains [setup](docs/getting-started.md),
[installation boundaries](docs/installation.md), [route administration](docs/routes.md),
[status](docs/status.md), [maintenance](docs/maintenance.md), and
[safety](docs/safety.md). WsprryPi owns production provider selection,
configuration, scheduling, operator workflow, and application qualification.

## Development

Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the
[module contract](engineering/contracts/rp1-gpclk-dkms-module-contract.md).
[Engineering references](engineering/README.md) cover APIs, lifecycle,
packaging, tests, and release preparation. Run offline hardware-free checks with:

```sh
make check
make package-check
```

Use [documentation maintenance](engineering/documentation.md) for local handbook
builds. Target installation, module/overlay administration, GPIO, and RF work
require their own authorization. Releases use ordinary GitHub releases;
release/tag/asset locking and release immutability are not project requirements.
The first stable release is reserved for an explicit readiness decision.

## Ownership and licensing

This repository owns the modules, canonical UAPI, overlays, DKMS packaging,
lifecycle tools, compatibility metadata, and module releases. WSPR-Transmitter
owns its userspace adapter; WsprryPi owns application and product policy.
Independent tools, tests, and documentation use MIT. Original kernel-facing
and device-tree source uses `GPL-2.0-only OR MIT`; canonical UAPI uses
`(GPL-2.0-only WITH Linux-syscall-note) OR MIT`. Reused scaffold assets retain
their notices. See [LICENSE.md](LICENSE.md).
