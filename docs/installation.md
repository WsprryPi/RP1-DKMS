<!-- SPDX-License-Identifier: MIT -->

# Install with WsprryPi

This repository contains unreleased development source. The production WsprryPi
installer does not select it. The procedures below describe the managed provider
interfaces; installation requires separately selected, accepted source.

Use a WsprryPi version with RP1 support and its normal installer. It obtains
the independently maintained provider, checks identities and prerequisites,
and establishes managed route administration. Installing a second copy by hand
can conflict with the ownership information needed for updates and recovery.

## Before you begin

You need:

- a Raspberry Pi 5 or Compute Module 5 system with an identified RP1 topology;
- a stock Raspberry Pi kernel and matching kernel headers;
- administrator access, Internet access, and space for the kernel-module build;
- a supported operating system for your selected WsprryPi version; and
- an inactive RF setup while installing or changing wiring.

WsprryPi's installer requests the exact running-kernel header package and
required build tools when RP1 installation is selected. Provider packaging
requires a DKMS installation accepted by its package preflight. Unsupported DKMS configurations,
missing headers, and unknown signing policies are refused. Do not disable
signature enforcement to make a build load.

Being able to run WsprryPi with another backend does not establish that the
same OS has the RP1 build prerequisites. If the installer reports an unsupported
DKMS version or unavailable matching headers, retain that message and resolve
the supported OS/package combination before retrying. Do not substitute a
nearby kernel's headers or bypass the provider's checks.

## Follow the managed installation

1. Prepare the Pi and install WsprryPi using its
   [installation guide](https://wsprry-pi.readthedocs.io/en/devel/Install/index.html).
   Select the manual version that matches your application channel.
2. Let the complete installer finish. An individual successful DKMS/build step
   is not overall installation success. Retain the final result, reported
   configuration URLs, and any error details. Follow an explicit installer
   reboot request before checking the installed application.
3. Open the URL it reports from the Pi's local network. Keep transmission
   disabled and go to **Setup > Transmitter**. See
   [use an installed system](getting-started.md) for the exact output-path
   control and idle checks.
4. For a fresh setup, expect neutral administration with **no route selected**.
   An explicitly saved RP1 GPIO4/GPIO20 route may be restored during a repeat
   installation, with transmission still disabled.
5. If installation succeeds, follow [route selection](routes.md). If it fails,
   use [troubleshooting](troubleshooting.md) before making further changes.

**Setup is complete** when the installer reports overall success, the web
interface reconnects with current status, and the managed route state is
explained: neutral for a fresh installation, or the confirmed saved RP1 route
after an eligible repeat installation. There must be no pending recovery or
restoration error. A missing execution endpoint is expected in the neutral case.

The package installs two modules and inactive GPIO4/GPIO20 overlays. WsprryPi
separately deploys and activates the runtime manager. Package installation
alone does not mean that the manager or an execution endpoint is ready.

## Release and development selection

WsprryPi owns provider selection. Its `auto` policy uses an eligible published
provider for production/main application installations and an exact resolved
development source for named development branches. Explicit release selection
is available to administrators through `RP1_GPCLK_DKMS_SOURCE=release`.
`INSTALL_RP1_GPCLK_DKMS=false` deliberately skips provider installation.

These are administrator installer settings, not Read the Docs version-selector
options or settings required for ordinary route selection. Keep your existing
application channel during maintenance unless you intend a reviewed migration.

These installer settings belong to WsprryPi. Use its
[provider installation reference](https://github.com/WsprryPi/WsprryPi/blob/devel/docs/rp1-gpclk-dkms-installation.md)
for exact selectors and migration prerequisites. A missing or corrupt release
stops installation; no alternate hardware backend is substituted.

## Standalone administration

Standalone package installation is intended for administrators maintaining an
explicit deployment. The source package alone does not provide a complete
WsprryPi runtime setup. Before using that path, review the repository's
[package lifecycle procedure](https://github.com/WsprryPi/RP1-DKMS/blob/devel/engineering/operations/package-lifecycle.md),
[packaging prerequisites](https://github.com/WsprryPi/RP1-DKMS/blob/devel/engineering/operations/debian-packaging.md),
and [signing policy](https://github.com/WsprryPi/RP1-DKMS/blob/devel/engineering/operations/signing.md).

Do not apply firmware overlays, force-load modules, or edit boot configuration
over a WsprryPi-managed runtime to work around an installer refusal. Preserve
the reported state and use its owning recovery procedure.
