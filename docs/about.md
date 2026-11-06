<!-- SPDX-License-Identifier: MIT -->

# How RP1 support works

RP1 is the I/O controller used on Pi 5-family systems. GPCLK is a general-purpose
clock output, used here as the signal source for the transmitter's RF interface.
WsprryPi prepares the signal and schedules transmissions. RP1-DKMS
controls the Pi's RP1 GPCLK0 output using the stock Raspberry Pi clock driver.
The module accepts finite tone and gap sequences and permits one execution
owner at a time. Cancellation prevents further chunks and drains bounded
work before cleanup.

## The parts you may see

| Part | Purpose |
| --- | --- |
| WsprryPi | Installation, setup, scheduling, signal planning and operator controls |
| DKMS | Builds the modules for eligible installed Raspberry Pi kernel headers |
| `rp1_gpclk_dkms` | Executes bounded signal sequences on the selected route |
| `rp1_route_controller` | Manages the route's device-tree lifecycle |
| Route manager | Coordinates route changes and WsprryPi service restoration |
| `/dev/rp1-gpclk` | Root-only execution endpoint, normally present when a route is selected |

The stock `clk-rp1` driver remains the clock provider. No custom kernel is
required. Unknown resource identity, conflicting ownership or an uncertain
cleanup result blocks operation.

## Installation, route selection and transmission

These are separate operations:

1. **Package installation** places source and inactive overlays on the system
   and builds modules. It does not load a module or select a GPIO route.
2. **Neutral activation** establishes managed administration without a
   transmission route. The execution endpoint is absent.
3. **Route selection** connects one managed GPIO route. A saved RP1 route can
   also be restored by the owning WsprryPi installer or startup workflow.
4. **Transmission** requires WsprryPi's separate readiness, ownership and
   operation checks and the operator's deliberate request.

A route is the selected signal path, not an antenna connection or proof of
RF suitability. GPIO4 and GPIO20 need separate wiring and support evidence.

For everyday use, open WsprryPi, check the selected route and leave it in place
when it matches your wiring. You do not need to load a module or run an
engineering test client. Start with [use an installed system](getting-started.md).

## Software and support limits

This is development source, not a published release.
Neutral activation creates the route-manager group if absent, including when
Debian package configuration has not run. Existing group membership and numeric
identity are preserved. This source has distinct package, module, and route identities. Evidence for
another repository or source does not qualify it.
WsprryPi verifies exact source and artifact identities;
matching a version string alone is insufficient.

WsprryPi includes verified scoped evidence for each route with its application.
No separate evidence-release download or refresh is needed. That evidence
applies to specific systems and operating conditions; it does not establish
support for every kernel, board, frequency, mode or RF setup. A successful
DKMS build establishes build compatibility only.

Use [WsprryPi's band qualification guidance](https://wsprry-pi.readthedocs.io/en/devel/About_Wsprry_Pi/index.html#band-qualification)
for application band and mode choices. The provider's structural compatibility,
current readiness and externally established qualification are separate facts;
[status](status.md) explains how to read them.
