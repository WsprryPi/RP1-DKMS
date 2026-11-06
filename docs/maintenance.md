<!-- SPDX-License-Identifier: MIT -->

# Maintenance and recovery

Use WsprryPi's installer and update workflow for an installation it manages.
Keep the previous installer/source or release details and administrator recovery
backups until the update completes successfully. Do not install a package
or development tree over an unexplained provider state.

Before any change, [make the transmitter idle](getting-started.md#make-the-transmitter-idle).
If a route transaction is already unresolved, first
[read its status](routes.md#if-the-browser-disconnects). Starting a second change
can make the original failure harder to diagnose.

## Update WsprryPi or the provider

1. Confirm idle state, transmission disabled, and no outstanding route transaction.
2. Record the current application/provider versions and retain the previous
   installation inputs.
3. Follow your WsprryPi version's
   [installation/update procedure](https://wsprry-pi.readthedocs.io/en/devel/Install/index.html#install-wsprrypi),
   keeping the intended application channel. It verifies
   the owned state, prepares the runtime for replacement, then validates or
   installs the selected provider and restores neutral administration.
4. Check the complete installer result. An explicitly saved RP1 route may
   be restored with transmission disabled.
5. Reopen the configuration URL, confirm the intended route and
   [ready/neutral status](status.md), and check that **Transmit enabled** is off.
   Resume normal operation only after those checks and your RF-path checks.

Foreign or modified files and mixed ownership are preserved through refusal.
Direct package upgrade/downgrade is not a rollback procedure. Development-to-release migration and incompatible transitions require owning cleanup,
verified absence, then installation of the selected exact software.

## Standalone package updates

For an independently administered inactive package, an exact repeat verifies the
installed files and retains intact modules. Installing a deliberately changed
build under the same version retires the previous modules and rebuilds them.
A newer compatible package can upgrade
through Debian and DKMS. Before invoking the package manager, run the incoming
reviewed source's read-only preflight with the verified candidate package. Keep the
previous package for recovery, and check that obsolete source, DKMS, schema, and
module artifacts are gone after the update. Changed files, unknown ownership,
incompatible lifecycle state, or an active runtime require owning recovery first.
Follow the [standalone package procedure](https://github.com/WsprryPi/RP1-GPIO-CLK-DKMS/blob/devel/engineering/operations/package-lifecycle.md)
for commands, removal, and explicit downgrade recovery.

## After a kernel update

DKMS builds against eligible installed header trees. A module built for the
old kernel is not automatically usable with the new one.

1. Let the OS package update and its DKMS work finish. Retain any header,
   build, or signing error. If the OS update requests a reboot, arrange it with
   transmission stopped; a route change by itself does not require one.
2. Once the update has finished, and after any requested reboot, compare the
   running kernel with the installed module build using the
   [read-only inventory commands](command-line.md#system-and-module-inventory).
   `uname -r` reports the kernel running now, not a newly installed kernel
   that has not yet booted.
3. If headers or builds are missing, retain the install/build error and use
   the owning installation procedure to repair the exact prerequisite.
4. Wait for WsprryPi's startup workflow, then check the saved route and idle
   state through the web interface. An old journal alone does not prove
   current-boot ownership. If the failure persists, stop here and collect the result.

Do not manually load a mismatched module, bypass signing policy, or force a
route to restore output. Build success does not establish timing or RF quality.

## When service restoration fails

The route transaction and restoration of WsprryPi are separately verified.
A browser disconnect alone does not prove either failed. Use **Retry status**
or the [installed client's query](command-line.md#managed-runtime-inspection)
to establish the last result before choosing a recovery command.

1. Keep transmission disabled. Retain the route, full response, and
   [service logs](command-line.md#service-and-kernel-messages).
2. Have the administrator correct the reported service prerequisite. Do not
   remove a mask, rewrite a service, or reinstall the provider just to make the
   status disappear.
3. Choose the action matching the confirmed outcome:

   | Confirmed outcome | Recovery action |
   | --- | --- |
   | GPIO selection completed; application restoration failed | Retry `restore --execute`; it does not switch the overlay again. |
   | **Route removed; service unavailable** | Retry `remove gpio4 --execute` or `remove gpio20 --execute` for the GPIO that was removed. |
   | Transaction incomplete, route unclear, ownership conflict, or cleanup fault | Stop and request reviewed recovery; neither of the above retries establishes the missing proof. |

4. Run only the corresponding [administrative command](command-line.md#administrative-recovery),
   then query again. A selected route should be unchanged after restoration;
   successful normal removal should remain neutral. A previously running
   application returns idle. A previously stopped or administrator-masked
   service stays stopped or masked; that intent is not a restoration failure.
5. If the retry refuses or the expected state is not confirmed, retain that
   response and request support. Do not cycle through the other commands.

See the [administrative command reference](command-line.md#administrative-recovery)
for exact commands. A missing manager, ownership conflict, or cleanup fault
requires investigation before retrying an effect.

## Recover an interrupted transaction

Recovery is different from normal route removal. **Recovery returns to no
route and intentionally leaves WsprryPi inhibited.** It may stop the application
and does not automatically resume operation.

1. Preserve the failing response and collect a support bundle before making
   further changes when possible. If the web interface is unavailable, retain
   the [read-only command results](command-line.md) instead.
2. Have the administrator or support reviewer identify the interrupted
   transaction and confirm that the installed runtime owns it. A generic
   `recovery_required` classification can refer to deployment, activation,
   route, or application restoration; the route client's `recover` is not a
   universal repair for all of them.
3. Only for the reviewed route-transaction case, use **Recover to no route**
   if offered, or the installed client's
   [route recovery command](command-line.md#recover-an-interrupted-route-transaction).
   Read its confirmation: WsprryPi can stop and remain unavailable afterward.
4. Query and retain the result. Recovery must confirm no active route and
   retained application inhibition. A fault, refusal, or unknown state is a
   stop condition, not permission to attempt another effect.
5. Keep the recovered system inhibited for administrator review. Restoring
   administration/application availability and making a new explicit route
   selection are separate actions. Do not unmask/start the service by hand or
   delete records to skip that review. Return to the normal route procedure
   only after the administrator has restored the managed workflow.

## Uninstall

Use WsprryPi's normal uninstall workflow for installer-owned RP1 support. It
prepares the exact owned runtime for removal before application teardown.
A preparation failure stops the uninstall; keep its error and records.

Uninstall also removes the application and its configuration. If you only want
to stop using the GPIO output, use [Remove route](routes.md#remove-the-route)
instead. If you intend a full uninstall, use the
[WsprryPi uninstall instructions](https://wsprry-pi.readthedocs.io/en/devel/Install/index.html#uninstall-wsprrypi)
and check its overall result rather than deleting RP1 directories manually.

Standalone removal requires prior owning route/deployment cleanup and verified
absence of active modules and endpoints. Follow the
[package lifecycle procedure](https://github.com/WsprryPi/RP1-GPIO-CLK-DKMS/blob/devel/engineering/operations/package-lifecycle.md).
Administrator signing keys, trust entries, shared configuration, and unrelated
files are retained. Removing a GPIO route alone is sufficient if you
want to stop using that output while keeping the software installed.
