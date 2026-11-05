<!-- SPDX-License-Identifier: MIT -->

# Select or remove a route

WsprryPi manages one RP1 GPIO route at a time. Use its **Setup > Transmitter**
controls for normal changes. Keep the physical wiring consistent with the
route you select.

| Selection | GPIO number | Standard 40-pin header pin | Result |
| --- | --- | --- | --- |
| GPIO4 | 4 | 7 | Uses the GPIO4 output path |
| GPIO20 | 20 | 38 | Uses the GPIO20 output path |
| None | No output GPIO | No output pin | Returns the controller to neutral administration |

Both GPIO routes use GPCLK0 and have separate overlays and compatibility
identities. There is no arbitrary-pin selection or automatic substitution.
For a carrier board or custom connector, use its documented pin mapping.

## Choose or change the route

1. [Make the transmitter idle](getting-started.md#make-the-transmitter-idle).
   Keep **Transmit enabled** off and wait for cleanup and any previous route
   transaction to finish.
2. Verify the RF setup and the header connection. Follow the
   [electrical precautions](safety.md) before moving wiring.
3. Open **Setup > Transmitter**. Set **RF Output Path** to **GPIO** if needed
   (Si5351 off), then find **Transmit Pin**. On Pi 5-family systems this selects
   the RP1 GPIO path. There is no separate RP1 option in that switch.
4. Choose **GPIO4** or **GPIO20** in **Transmit Pin**. **Route Unsaved** means
   you have a draft; the Pi has not switched. Choose **Switch route**, review
   the confirmation's GPIO and idle/restart behavior, then confirm only if
   those match your intention. To discard a draft, choose the active GPIO
   again. The detailed panel's **Cancel** control, when visible, also discards it.
5. Keep the status dialog open. WsprryPi may briefly disconnect while the
   manager performs the change and restores the application service.
6. Wait for **Route selected** for the intended GPIO and **Status check
   complete**. Close the completed dialog, check **Transmit Pin** again, and
   confirm no recovery or cleanup error remains. Where detailed route facts
   are available, saved, configured and active routes must agree. Keep
   transmission disabled until you deliberately start an eligible operation.

Runtime switching occurs in the current boot and does not require a reboot.
Saving a selection alone is not evidence that the route became active. If the
chosen route is already active, the action can be disabled because no switch
is needed. A disabled action while status is checking, unavailable or in error
does not establish that the route is ready; read its accompanying status.

## If the browser disconnects

The status dialog checks completion without repeating the route change.
**Route switch queued**, **Restoring application** and **Reconnecting** are
progress states, not success.

- If it reports **Automatic checks paused**, choose **Retry status**. This
  reads current status; it does not submit the switch or removal again.
- If the web interface does not return, use the installed client's
  [read-only query](command-line.md#managed-runtime-inspection) from an existing
  Pi terminal/SSH session. Retain its complete result and any service error.
- Do not repeat **Switch route**, reboot, or choose recovery solely because
  the browser lost contact. Follow the
  [reported outcome](status.md#route-control-messages) before another action.

Closing a paused dialog does not cancel a transaction already submitted to the Pi.

## Remove the route

1. [Make the transmitter idle](getting-started.md#make-the-transmitter-idle).
2. In **Setup > Transmitter > Transmit Pin**, select **None**, choose
   **Remove route**, and review the confirmation before proceeding.
3. Wait for **Route removed** and **Status check complete**. The controller remains available for
   administration, but `/dev/rp1-gpclk` is absent and output is disabled.

If WsprryPi was running, successful removal restores it online and idle.
A service that was already stopped or administrator-masked remains in that
state. Removing a route does not uninstall the provider.

**Route removed; service stopped** describes that retained service intent.
It is different from a failed restoration. **Recover to no route** is an
exceptional recovery action, not the button to use for normal removal.

**Route removed; service unavailable** means the route reached neutral but
application restoration failed. Keep transmission disabled and follow
[service restoration](maintenance.md#when-service-restoration-fails).

## After a reboot

The owning WsprryPi startup workflow must validate the new boot and restore
managed administration before a saved RP1 route can be used. A saved setting
or a previous boot's successful status is insufficient. If startup reports
recovery required, preserve the records and follow the reported procedure.

Wait for the web interface to reconnect, confirm the intended GPIO and **Route
selected** status, and check that transmission remains disabled. RP1 startup
restoration stays idle even when a general saved reboot preference would allow
transmission; that preference is retained, not silently rewritten. After normal
removal or a neutral installation, a reboot does not invent a GPIO selection.

An older packaged route manager can instead use boot-selected overlays and
reboot/reconciliation. Do not mix that profile with the managed runtime
workflow described here. Ask for support if you cannot identify which profile
owns an existing installation.
