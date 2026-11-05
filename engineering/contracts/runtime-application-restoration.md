<!-- SPDX-License-Identifier: MIT -->

# Runtime application restoration

The runtime manager completes application restoration after successful route
switching. The low-level overlay transaction ends at `complete-inhibited`;
it does not itself start an application.

An explicit `remove` operation composes exact route recovery with neutral
application restoration. It is distinct from `recover`, whose fail-closed
contract continues to end route-neutral with application inhibition retained.

## Ownership and sequence

DKMS owns overlay/consumer lifecycle, its transaction journals, and temporary
service inhibition. WsprryPi supplies the installed companion
`/usr/local/lib/wsprrypi/route_application.py`, configuration semantics, idle
startup handling, and application readiness acknowledgement. The kernel UAPI,
compatibility checks, and release/qualification status are unchanged.

The privileged manager captures prior service state and a unique startup token
in `application.json` before stopping anything. A workflow lock excludes other
mutating manager requests throughout restoration. The existing controller lock
is released before starting WsprryPi so startup queries can acquire it.

Filesystem deployment also captures the pre-inhibition service state and exact
companion observation in its reviewed version-2 deployment plan. The neutral
activation transaction reuses the same owned inhibitor, service observation,
companion validation and administrator-mask rules. It never calls the
route-specific configuration operation, creates an idle-route token or invents
GPIO4/GPIO20. Neutral restoration is admitted only when `Operation.Transmit` was
already false. A previously active service is started and must be active with a
nonzero PID; a stopped service remains stopped, and an administrator mask remains
masked. The companion is rechecked and must still report `transmit=false`.

The route-specific `application-ready` acknowledgement is intentionally not
forged for neutral activation: there is no consumer or selected route to
reconcile. Neutral readiness instead proves controller route zero, consumer and
endpoint absence, exact service intent, and the companion's disabled application
configuration. A later explicit route transaction creates the existing
route-specific token and acknowledgement.

The owned `90-rp1-route-inhibit.conf` service drop-in adds an unsatisfiable
`ConditionPathExists` below `/dev/null`. It prevents normal starts/restarts
without replacing `/etc/systemd/system/wsprrypi.service`. An existing service
unit or administrator mask is never overwritten. This is cooperative systemd
inhibition, not isolation from privileged processes or alternative units.

After normal consumer unload and controller-owned overlay removal/application,
the consumer is loaded with default `output_inhibit=0`. A passive snapshot must confirm
the selected route is idle. Only then does the companion atomically update
`GPIO.Transmit Pin` and `Operation.Transmit=false`. It preserves other settings,
including `Enable on Boot`, comments and file mode. The canonical installed
service command/configuration is checked before effects. Missing services,
unsupported commands and old application builds require installation repair;
they are not silently replaced.

An owned `91-rp1-route-idle.conf` supplies the startup-only
`WSPRRYPI_ROUTE_RESTORE_IDLE` token. WsprryPi overrides automatic transmission
for that startup, leaving its saved boot preference unchanged. The manager
removes its inhibition, reloads systemd, closes the controller lock, then starts
only a previously active service. Startup reconciliation and application loop
setup, startup quiescence and network reconciliation must succeed, and any
configured HTTP listener must be bound, before WsprryPi sends `application-ready` with the selected
route, token, PID and `transmit=false`. The manager checks the current service
PID, controller identity and idle snapshot before recording completion.

The normal operator transmission controls remain available after restoration;
no prior transmission or scheduler request is resumed by this workflow. Existing
RP1 operation authorization and cleanup behavior remain unchanged.

## Durable outcomes and recovery

`query` includes the durable application transaction alongside the current
controller observation. Application phases distinguish:

- `restored`: the application acknowledged idle readiness, including a later
  explicit first start of a previously stopped application.
- `stopped`: the application was stopped and was not started.
- `administrator-masked`: an existing administrator mask was preserved.
- `restoration-failed`: the route transaction completed, but application
  configuration, startup or readiness failed.
- `route-failed`: the route transaction failed; its original errno and overlay
  ownership remain available separately from any subsequent inhibition error.
- `route-recovered`: explicit recovery reached a neutral route; a new switch is
  needed before restoring application availability.
- `neutral-restored`: explicit removal reached an exact neutral controller and
  restored a service that was running before removal.
- `neutral-stopped` and `neutral-administrator-masked`: removal reached neutral
  state while preserving a previously stopped service or administrator mask.
- `neutral-restoration-failed`: route recovery succeeded, but neutral service
  restoration failed and the owned inhibitor was retained.

Completed records describe the last transaction, not a promise that the service
cannot subsequently stop. A stopped/masked application's idle startup override
remains until its first later startup acknowledges readiness. This avoids an
`Always` boot preference unexpectedly transmitting on that first start.

`runtime_route_client.py restore --execute` retries only application completion
on the same boot, deployment and successfully installed route. It does not
repeat overlay effects. Interrupted route changes require `recover --execute`,
then a new explicit switch. Recovery preserves the original service intent on
the same boot. Prior-boot route records never establish live ownership or authorize historical
service intent. Ordinary reboot reconciliation uses the distinct neutral
activation workflow below; interrupted routes require explicit recovery.

`runtime_route_client.py remove gpio4|gpio20 --execute` requires the requested
route to match the active route, captures service intent, performs the existing
recovery transaction, and restores that intent only after route zero, an exact
`recovered-inhibited` journal, disabled output, and the owned inhibitor are
verified. Repeating removal is idempotent only while boot, binding, controller,
journal, companion configuration, and service outcome still match. A changed or
foreign state fails closed.

Removal retries retain the captured intent and validate it against the manager's
recorded recovery response. `neutral-start-intent` permits restoration to resume
after the owned inhibitor has been removed or the service has already started;
it does not repeat overlay effects. Current masks and disabled application
configuration are checked before restoration. Error text from failed attempts
remains diagnostic evidence in the terminal record and does not replace the
captured service intent or controller identity. A new removal request after
explicit recovery records its own removal intent before completing restoration.

Failures retain owned inhibition where possible and report inhibition failure
separately. Foreign drop-ins are preserved and reported. Requester disconnects
do not kill the independently systemd-owned manager worker; durable results
remain queryable. No successful application restoration is reported merely
because systemd accepted a start request.

Neutral activation failures retain `activation.json` and re-establish the same
owned inhibitor. Recovery requires its reviewed journal digest. A recovered
transaction remains inhibited but retains the original application intent for a
subsequent reviewed activation or coherent deployment. Prior activation evidence
is archived before a recovered transaction is restarted.

After a clean reboot, an exact completed neutral activation and a full terminal
route/manager/application chain may be superseded through a fresh version-3
neutral activation plan. The plan binds the historical records and current
application capture. A stopped or masked route that subsequently acknowledged
an explicit start is terminal `restored` history; its original service capture
is preserved as evidence and does not determine the new boot's service intent.
`reboot-prepare` durably stores that capture before changing
the owned inhibitor or retiring any dependent journal. Retries accept only an
exact ordered suffix of the saved records behind that inhibitor. Historical
records are retained as evidence in the plan and activation archive; their
controller session, service state and transmission intent are never reused.
Current masks and disabled companion configuration are rechecked before service
restoration. A stopped service remains stopped. Reconciliation selects no route;
WsprryPi separately owns startup orchestration and its persisted route decision.

The installer-facing runtime-provider contract classifies a failed restoration
as `recovery_required` and directs the caller to `restore --execute`; it never
converts a route-only success into application readiness.

Runtime-controller removal must reconcile the owned application inhibitor
before discarding the runtime inventory or journals. If an interrupted or older
removal has already left only the exact owned inhibitor, use
`scripts/runtime_inhibitor_cleanup.py inspect` to obtain a reviewed plan. The
cleanup operation is eligible only when the canonical WsprryPi service and all
fixed runtime-controller bindings, tools, journals, loaded modules, and endpoints
are absent. DKMS-installed module files are provider-owned prerequisites rather
than runtime-deployment residue and do not block this orphan-inhibitor cleanup.
Execution requires the unchanged plan digest and
removes only the exact root-owned regular file with the canonical bytes and
mode. Foreign overrides or any ambiguous runtime state remain untouched.

Review and execute the cleanup as two separate operations:

```sh
sudo python3 scripts/runtime_inhibitor_cleanup.py inspect
sudo python3 scripts/runtime_inhibitor_cleanup.py cleanup --execute \
  --plan-sha256 REVIEWED_PLAN_SHA256
```

The second operation re-inspects the machine and refuses cleanup if the
reviewed plan digest no longer describes the current state. It reloads systemd
after removal and restores the exact inhibitor if that reload fails.

## Deployment and validation boundary

Install the companion and matching WsprryPi executable using the application's
installer or its own `scripts/copy_exe.py` in the **WsprryPi repository**. There
is no application installer at that path in this repository. Deploy a newly
bound complete DKMS runtime
bundle: the inventory includes `runtime_application.py` and the manager's
sandbox permits the canonical application configuration directory. Do not swap
individual scripts under an incomplete binding. The application requires
`applicationRestoration: true` from the manager before offering a successful
runtime preflight.

Bundle construction also requires the exact WsprryPi companion path as an input.
The companion remains application-owned and is not installed by DKMS, but its
bytes are bound and reverified before runtime effects. This makes a companion
update a new deployment identity rather than an in-place script substitution.

An old `/dev/null` service mask is not automatically adopted as workflow-owned.
Restore the canonical service installation and intentionally clear that legacy
mask during coherent deployment. The software cannot infer whether that mask
is now an administrator's desired state.

Offline tests exercise public manager dispatch, real temporary journals and
drop-ins, fake systemd/kernel effects, interruption at durable journal boundaries,
error retention, startup lock ordering, stale acknowledgements, configuration
preservation and startup policy. They do not qualify systemd behavior, kernel
overlay removal, GPIO, RF or exact-target deployment.

Separately authorized target validation starts with coherent identities, the
explicitly authorized physical route and output disabled. A two-route round trip
requires verified wiring/ownership and authorization for both GPIO4 and GPIO20.
Check running/stopped/masked service restoration, switching with no output,
deliberate restart failure and explicit restoration, service/unit preservation,
and restoration of the agreed final route in idle state. Record route,
service PID/readiness, configuration, clock/DMA quiescence and both journals.
Do not resume transmission or infer RF qualification from these tests.
