<!-- SPDX-License-Identifier: MIT -->

# Use an installed system

Start here when WsprryPi is already installed on your Pi 5-family system.
You normally manage RP1 from the WsprryPi web interface; a terminal is only
needed for administrator inspection or a reviewed recovery action.

## Open WsprryPi

1. Open the configuration URL printed by the WsprryPi installer. A typical
   address is `http://YOUR-PI-HOSTNAME.local/wsprrypi/`; replace
   `YOUR-PI-HOSTNAME` with your Pi's hostname. Use the installer's IP-address
   URL if hostname lookup fails.
2. Connect from the Pi's directly connected Ethernet or Wi-Fi network.
   A page can load while protected controls are unavailable from another
   network. Use [connection troubleshooting](troubleshooting.md#web-interface-or-connection-problems)
   if status or controls do not work.
3. Open **Setup > Transmitter**. For direct GPIO output, **RF Output Path**
   should read **GPIO** (the Si5351 switch is off). If another output path is
   selected, [make the transmitter idle](#make-the-transmitter-idle) before
   changing it to GPIO. On a supported Pi 5-family system,
   WsprryPi uses the RP1 provider for that path. There is no separate RP1
   backend choice to find in this control.
4. Check **Transmit Pin** and the adjacent route status. If the intended route
   is already selected and status confirms it, leave it selected. If there is
   no route, follow [route selection](routes.md). A fresh installation with no
   route is normal. Si5351 or Pico operation does not require an RP1 route.

If RP1 controls are absent, unavailable or ask for a reboot, first identify
your installed WsprryPi/provider version and deployment profile. Use
[installation](installation.md) or request support; do not enable a developer
setting or install another provider just to expose a control. A `--no-web`
installation has no web workflow; its administrator can use the
[command-line inspection tools](command-line.md).

## Make the transmitter idle

Use this procedure before a route change, update or other maintenance.

1. On **Operations**, turn **Transmit enabled** off. This prevents future
   scheduled transmissions; an already committed transmission can continue.
2. If you need to cancel active output, choose **Stop transmission** and wait
   for the controller's response and cleanup. Otherwise, let the current
   transmission finish with **Transmit enabled** still off.
3. Include any manual **Test tone** in that check. **Stop transmission** stops
   work and prevents later tone restoration from restarting it. The tone
   dialog's **End** can restore earlier scheduling or an earlier direct tone,
   so **End** or **Close** alone is not an all-output-off check. Read any tone
   cleanup/restoration result before proceeding. If the tone has an uncertain
   start/end result, reconnect and follow its recovery **End** feedback once;
   do not start another tone or treat uncertainty as a completed stop.
4. Confirm that **Current state** reports no active or pending work (normally
   **Transmit paused** with transmission disabled), **Transmit enabled** remains
   off, and no cancellation, cleanup error or route transaction is outstanding.
   A disconnected browser, disabled Stop button or old status display does
   not establish the current state. If you cannot confirm it, follow
   [troubleshooting](troubleshooting.md) and keep the RF setup safe.

An idle application is ready for the next software check. Before touching
wiring, also follow the [electrical precautions](safety.md); software status
does not establish that every connected part of a transmitter is safe to handle.

## Check readiness before operating

1. Confirm that the selected GPIO matches the physical signal connection.
   If a change is needed, keep the transmitter idle and follow
   [select or remove a route](routes.md).
2. Wait for **Route selected**, with the intended GPIO. A selected route is a
   prepared output path, not a transmission in progress. **Route Unsaved**,
   **Reconnecting** or a queued change is not completion.
3. Review WsprryPi's band, mode, frequency and drive settings, its accepted
   [band qualification guidance](https://wsprry-pi.readthedocs.io/en/devel/About_Wsprry_Pi/index.html#band-qualification),
   and your actual RF path. Resolve any application readiness or operation
   confirmation message before enabling transmission. Development RP1
   operations can require an explicit bounded-operation confirmation; a route
   selection or qualification label does not supply it.
4. When you intend to operate, use WsprryPi's normal
   [Operations controls](https://wsprry-pi.readthedocs.io/en/devel/User_Interface/Operations/index.html).
   **Transmit enabled** enables the configured schedule and can lead to output
   immediately or at its next slot. Keep it off while investigating a problem.

Routine status inspection does not require a test transmission. See
[read provider status](status.md) if the route or readiness message is unclear.
