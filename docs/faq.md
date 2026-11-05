<!-- SPDX-License-Identifier: MIT -->

# Frequently asked questions

## Do I install this separately from WsprryPi?

Normally, no. WsprryPi installs and validates RP1 support on identified Pi 5-family
systems. Use [managed installation](installation.md) to preserve the ownership
and recovery information needed for later maintenance.

## WsprryPi is installed. What should I do first?

Open its configuration URL and [check the installed system](getting-started.md).
For direct GPIO output, check that **RF Output Path** reads **GPIO**, then check
**Transmit Pin** and its route status. Make the transmitter idle before
changing an output path or route. You do not need to switch an already
correct route or run a test transmission to inspect it.

## Why is there no execution device after installation?

Fresh setup is route-neutral. `/dev/rp1-gpclk` normally appears after you select
GPIO4 or GPIO20 through WsprryPi. Package installation, neutral activation and
route selection are separate steps.

## Does selecting a route start transmitting?

No. Selection establishes the managed path. WsprryPi separately checks the
requested operation, ownership and readiness before submitting output.

## Is switching transmission off the same as Stop or End?

No. **Transmit enabled** off prevents future scheduled work while committed
work can finish. **Stop transmission** cancels active work and disables future
transmission. The Test Tone dialog's **End** can restore previous work; closing
the dialog is not an all-output-off check. Use
[make the transmitter idle](getting-started.md#make-the-transmitter-idle)
before maintenance or a route change.

## The browser disconnected while switching. Should I try again?

Retry **status**, not the route action. A running application normally stops
and restarts idle during switching. Keep its dialog open, use **Retry status**
if automatic checks pause, or collect a read-only query from the Pi if the
application does not return. See [connection recovery](routes.md#if-the-browser-disconnects).

## Can I use GPIO4 and GPIO20 at the same time?

No. Only one managed route can be active. They share GPCLK0 and have separate
wiring, overlay identities and qualification. Use the route that matches the
physical connection.

## Does switching require a reboot?

The WsprryPi-managed runtime workflow switches in the current boot. An older
boot-configured profile follows a different reboot/reconciliation procedure.
Do not mix profiles to work around a failure.

## Does a successful DKMS build prove my transmitter works?

It proves build compatibility for the identified headers and toolchain.
Runtime state, cleanup, frequency accuracy, timing and RF suitability require
their own checks. Consult the WsprryPi band/mode limits for your application.

## Does removing a route uninstall the software?

No. It returns the controller to neutral administration and removes the
transmission endpoint while retaining installed software. Successful normal
removal can restore WsprryPi online and idle. Recovery deliberately retains
application inhibition.

## Route selected is shown, but why is transmission still disabled?

Route selection deliberately leaves WsprryPi idle. Application band/mode
eligibility, frequency settings, current ownership/cleanup state and any
required bounded-operation confirmation remain separate checks. Keep the
specific refusal message and use [status](status.md) or
[troubleshooting](troubleshooting.md); changing a module parameter is not an
eligibility override.

## Does choosing main or devel in this handbook update the Pi?

No. It changes the documentation you read. WsprryPi's application channel and
installer select the provider software. See
[installation selection](installation.md#release-and-development-selection)
before changing software channels.

## Where do I set frequency, drive and frequency correction?

Use WsprryPi's Setup controls and its
[timing and calibration guide](https://wsprry-pi.readthedocs.io/en/devel/Advanced_Operations/timing_calibration.html).
The RP1 provider executes the signal plan supplied by the application. A route
change does not calibrate the clock, and a drive setting in mA is not a measured
RF power level. Check the complete RF path rather than changing module load
parameters or increasing drive to compensate for an unexplained problem.

## Can I fix a refusal by deleting the journal or forcing a module load?

No. Those records are needed to establish ownership and safe recovery.
Preserve the failure and follow [maintenance and recovery](maintenance.md).

## Where are the developer documents?

Technical contracts, API details, builds, packaging and maintainer procedures
are in the repository's
[engineering directory](https://github.com/WsprryPi/RP1-DKMS/tree/devel/engineering).
They are kept separately from this operator handbook.
