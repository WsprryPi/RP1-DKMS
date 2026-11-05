<!-- SPDX-License-Identifier: MIT -->

# Troubleshooting

Keep transmission disabled while investigating an installation or route
failure. Record the exact message, the action that produced it and whether
output state is confirmed. [Make the transmitter idle](getting-started.md#make-the-transmitter-idle)
when the connected application can confirm it. Start with WsprryPi status and the
[read-only inventory](command-line.md); do not try successive module or overlay
commands to make an error disappear.

## Web interface or connection problems

1. Use the configuration URL from the installer. If the hostname does not
   resolve, try its IP-address URL from the same local network. A `--no-web`
   installation does not supply this web interface.
2. If the page opens but status is disconnected or protected controls report
   **Forbidden**/HTTP 403, check that you are on the Pi's directly connected
   Ethernet or Wi-Fi network. VPNs, routed networks and custom proxies can be
   outside the application's allowed network. Use the normal `/wsprrypi/`
   browser URL, not a direct backend port. Ask the network administrator to
   review the reported restriction; disabling network safety is not an RP1 fix.
3. If the disconnect started during a route change, keep the status dialog
   open. **Retry status** after automatic checks pause; this does not repeat
   the change. If the application does not return, collect the
   [read-only client query and service logs](command-line.md).
4. If neither the browser nor a Pi terminal is available, make the physical
   RF setup safe and request help restoring access. Do not treat lost contact
   as a confirmed stop or assume that rebooting will repair the transaction.

## Route, installation and output problems

| Symptom | Likely checks and next action |
| --- | --- |
| `/dev/rp1-gpclk` is missing | This is expected with no route. If a route should be active, check route status, installer result and the manager. Never create the device node by hand. |
| Provider files exist but no route can be selected | Check for `activation_required` or incomplete runtime deployment. Package installation alone is insufficient. Use the owning installer/startup workflow. |
| Requested and Active differ | Wait for the current transaction. If it failed, preserve the response and investigate before another switch. |
| **Route Unsaved** or disabled **Switch route** | A draft has not changed the Pi. If the desired GPIO is already active, no switch is needed. Otherwise check idle state and the reported readiness/error before applying; see [route selection](routes.md). |
| Kernel update left no usable module | Compare `uname -r`, headers, DKMS status and kernel-specific module metadata. Repair the exact prerequisite through the owning installer. |
| Signing or trust was rejected | Review the certificate and target kernel policy with the administrator. A nonempty signer name does not prove trust. Do not disable enforcement. |
| Permission denied | Execution and administrative tools require the installed ownership and access policy. Use administrator inspection when appropriate; do not broaden device permissions. |
| Manager socket is unavailable | Collect service/socket state and installer diagnostics. Do not start an unrelated service profile or apply a second overlay. |
| No RP1 control, or **Apply route and reboot** appears | Confirm the application version and manager profile. This handbook's normal **Switch route** procedure uses the managed runtime profile; do not mix it with a boot-configured installation. |
| `recovery_required` or an incomplete transaction | Preserve journals and installation records. Use owning recovery after reviewing the cause. |
| `conflict`, mixed identity or changed files | Stop. Identify who owns the files and current runtime. A reinstall must not overwrite foreign or modified state. |
| Route removed but service unavailable | Keep output disabled, fix the service error, then retry the same removal. See [maintenance](maintenance.md#when-service-restoration-fails). |
| Cleanup fault, owner/lease still present or output unknown | Do not resume or force unload. Make the physical RF setup safe and request reviewed recovery. |
| Evidence missing, invalid or unverified | Check the matching application helper/cache and exact identity. Evidence state is separate from runtime readiness and application band policy. |
| **Route selected** but an operation is refused | Keep the specific application refusal. Check the band/mode, frequency, requested operation and any required bounded-operation confirmation. Re-selecting a route does not satisfy these checks. |
| No received signal despite healthy software status | Check the selected physical route, RF path, filtering, load, receiver settings and WsprryPi's band/mode limits. A build or status result does not establish RF performance. |

A cleanup fault, unknown output, unexplained ownership conflict or unresolved
transaction is a stop condition. Do not try a test tone, increase drive, change
routes repeatedly or clear records to see whether the symptom goes away.

## Collect a useful failure report

1. Note whether the failure followed installation, an update, reboot, route
   switch, removal or a transmission request.
2. Record the WsprryPi version, provider source/release, kernel and selected
   GPIO. Distinguish requested, saved and active routes where available.
3. Preserve the complete error and its exit code. `inspect` exit codes
   10 through 14 describe classified states; [status](status.md) explains them.
4. Collect a WsprryPi support bundle if the application is available, or
   retain read-only command results if it is not.
5. Review logs and archives before sharing. Use the [support procedure](support.md).

If a command or file is absent or inaccessible, report that fact. Do not
install another tool, clear evidence or perform a test transmission just to
complete a diagnostic report.
