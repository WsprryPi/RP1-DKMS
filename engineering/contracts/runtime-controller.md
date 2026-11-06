<!-- SPDX-License-Identifier: MIT -->

# Runtime route controller

The runtime manager completes application restoration as specified in
[Runtime application restoration](runtime-application-restoration.md). Its successful switch path
restores a previously running application in idle mode. The low-level controller
transaction ends inhibited; the runtime manager performs the application
handshake afterward. `restore --execute` retries that application completion.

This opt-in development implementation uses exported stock-kernel OF APIs.
It is separate from the packaged boot-route manager. Clock-disabled tests load
the consumer with `output_inhibit=1`; production runtime administration loads
the output-capable consumer only behind application inhibition. The controller
itself exposes no transmission command.
Deployment, binding and hardware validation require explicit authorization;
software tests do not establish product or RF qualification.

## Build and identity

Run `python3 scripts/build_runtime_controller.py`, then build with
`make KERNEL_BUILD=/path/to/headers RP1_RUNTIME_CONTROLLER=1`. The Make target
regenerates the embedded overlays before compilation. The generated header and
identity JSON under `build/runtime-controller` come only from the two canonical
DTS files, through the existing deterministic overlay builder. Neither controller
ioctl nor userspace administration accepts an arbitrary overlay or path.

The runtime-controller build produces `rp1_route_controller.ko` (version specified in the
[development identity contract](development-identity.md)) plus `rp1_gpclk_dkms.ko` with the `rp1_runtime_controller=1` modinfo marker
and a link-time dependency on the controller. There is no OF autoload alias in
this opt-in build: the administrator explicitly
loads it after APPLY, avoiding an automatic load racing that step. Its driver
retains the OF match table for explicit binding. The default build retains its
autoload alias. The consumer version follows the same development identity contract;
changed bytes do not inherit qualification. The interlock constrains overlay
ownership and consumer lifetime, not output policy. Ordinary direct builds do not link
the controller or change their administration interface. The canonical package selects this interlocked profile for both modules.
Direct source builds retain the explicit opt-in flag and ordinary one-module default. Exact-source orchestration may explicitly select
the `runtime-controller` DKMS profile; that one DKMS instance builds, installs,
tracks, and rolls back both modules. The runtime bundle binds those installed
module artifacts as external prerequisites and never installs a second copy.
Changing build modes requires clean isolated build
directories; never reuse an opt-in object as a default artifact.

The controller requires exactly one available `raspberrypi,rp1` device-tree
identity and a neutral live tree at initialization. Kernel, architecture, board,
firmware, and compiled-module identities remain bound by the reviewed runtime
deployment rather than compiled into a board-model allowlist.
Existing compatible endpoints or canonical endpoint/pinctrl node names reject
admission, including disabled/foreign nodes. It never adopts a firmware overlay.
These checks do not replace coherent deployment or target firmware/resource
validation. Module signing/loading remains an independent prerequisite.

## Kernel ownership and admission

The root-only `/dev/rp1-route-admin` endpoint has the separate 64-byte interface in
`include/uapi/linux/rp1_route_admin.h`. It is separate from the transmission UAPI.
STATUS takes zero session/generation and returns a random controller-instance
session, monotonic generation, owned overlay ID, active route, last kernel error
and flags for fault, consumer presence and lifetime pinning. APPLY permits only
route 1 (`GPIO4`) or 2 (`GPIO20`); REMOVE accepts no route or arbitrary ID. Effects
require the exact session/generation and one controller mutex. Busy operations
reject immediately; status is not an electrical observation.

Every accepted effect advances generation exactly once. The handler records the
actual return code and mutated ID from `of_overlay_fdt_apply` or
`of_overlay_remove`. The ioctl return code indicates delivery or request
rejection; **a delivered response with last_error != 0 is a failed effect**.
The result survives caller death and copy-to-user failure. There is no fabricated
whole-system atomic snapshot or prediction substituted for a syscall result.

An apply failure may retain an ID for explicit cleanup. A removal failure may
retain its ID or clear it after a notification error; both cases latch a fault.
An error never permits another apply. Explicit removal of a retained overlay ID
is allowed after an overlay error, but successful cleanup does not clear the
fault. A no-ID fault remains pinned and requires separately reviewed recovery,
possibly reboot. Never force unload to erase this evidence.

A self-reference retains the controller while an overlay or fault is held,
including after every userspace descriptor closes. Ordinary module exit occurs
only without that ownership; its void callback never tries to remove an overlay
or discard an error. Open controller files and the linked consumer also retain
module references.

The consumer attaches before topology discovery/driver registration and detaches
only after complete device/driver/notifier teardown, including init failures.
Controller mutations reject while attached; consumer admission uses trylock to
avoid a recursive wait from synchronous OF work. Admission refuses no route,
an existing consumer, or a fault. Open transmission files already pin the
consumer, so ordinary non-forced removal cannot outrun their lifetime.

Failed consumer initialization or observed cleanup faults latch a separate
consumer fault. That fault blocks **all** overlay effects, including cleanup
removal, because resource quiescence is not established. No GPIO/clock/DMA
operation is introduced by the controller; consumer binding still selects safe
pinctrl and acquires resources, which is why it requires target authorization.
A userspace timeout cannot bound a blocked kernel teardown.

## Concrete userspace transaction and recovery

`scripts/runtime_controller_admin.py` is a separate opt-in root CLI with only
`switch gpio4`, `switch gpio20`, `recover`, and `status`. STATUS reads the
controller without a route or service effect; it still opens the admin endpoint
and may create the private lock file. It does not claim application inhibition.
The runtime manager adapter now exposes this transaction on the existing socket
under its own explicit profile; the packaged manager is unchanged. WsprryPi supplies the companion application/browser protocol support. The digest-approved
deployment supplies the exact root-owned binding at
`/etc/rp1-gpclk-dkms/runtime-controller.json` and creates the fixed root-owned
private state directory at `/var/lib/rp1-gpclk-dkms/runtime-admin` only when
execution begins. Read-only inspection and planning do not create it. The local-only
`build_runtime_binding.py` renders a review candidate from compiled modules and
the exact installed WsprryPi application companion;
it is not an installer or a claim about loaded target memory.

The runtime binding fixes the source commit, product and route compatibility
identities, kernel, and the unique DKMS-installed path for each module. Each module
record includes its installed-file digest, decompressed-ELF digest, compression,
version, kernel, and build-note digest. `.ko`, `.ko.xz`, `.ko.gz`, `.ko.zst`, and
`.ko.bz2` are accepted only when exactly one artifact exists for each module and
`modinfo -F filename` resolves to that exact path. It also binds both UAPIs, both transformed overlays, every runtime
tool and schema, the base socket/service units, the runtime drop-in, and the exact
WsprryPi application companion. `artifactSetSha256` binds that complete canonical
record. The tool checks module resolution, the consumer interlock marker, loaded
controller note and character-device identity before effects. Build-note agreement
corroborates identity; it is not a full hash of executing memory. Only a coherent
controlled deployment may enroll those observations.

A private nonblocking flock serializes cooperating tool instances. A durable
journal is written with file fsync, atomic replacement and directory fsync before
each effect. It binds boot, controller session, exact binding digest, request UUID,
target route, phase and observed state. A malformed, foreign, stale-session or
cross-boot journal stops administration. Existing controller ownership without a
journal is not silently adopted. Recovery never authorizes a successor.

Before route or consumer effects, the tool persists owned service inhibition,
reloads systemd, stops the service and verifies inactivity. The current owned
`90-rp1-route-inhibit.conf` drop-in and idle restoration handshake are specified
in the [application restoration contract](runtime-application-restoration.md).
Foreign unit files and administrator masks are preserved. Failures and crashes
retain inhibition. The low-level transaction never starts the application; the
runtime manager restores it only after successful route completion. This covers the named service only, not arbitrary root-launched
processes, alternate units or other applications. Operators must exclude those
entry points. Production loads the consumer with its default
`output_inhibit=0`; the root-only endpoint is then the execution authority, as
clarified in [runtime output reconciliation](runtime-output.md).

The tool unloads only the exact checked consumer with non-forced rmmod, checks
absence and controller detachment, removes the owned overlay, then applies the
new fixed overlay and loads the checked consumer with default `output_inhibit=0` using its
exact DKMS module name after verifying that `modinfo` resolves it to the bound
path. No modprobe install/remove hook or dependency removal is used for effects.
Each stage rechecks inhibition and boot identity. Completion
requires actual controller readback and successful consumer initialization;
the application remains inhibited even on success.

After a crash, ordinary switch refuses a pending journal. Explicit `recover`
accepts only the same boot/session/binding and an attributable generation (the
recorded generation or the single pending overlay effect). It inhibits again,
unloads the matching consumer and attempts only removal of a retained ID. A
clean recovery ends route-neutral and inhibited. Latched faults, ambiguous state,
identity mismatches and failures stop without restart, automatic reboot or
rollback to an unproven route. Interrupted kernel calls may still be pending;
busy status stops recovery instead of assuming completion.

The higher-level runtime-manager `remove` operation does not weaken this
low-level recovery boundary. It first completes the same neutral inhibited
transaction, verifies its exact journal and controller observation, and only
then releases the owned application inhibitor to restore captured service
intent. Any ambiguous controller, journal, application, or systemd state keeps
the service inhibited.

## Boundaries and validation

Cooperative privileged administration is a requirement. Root can load a consumer
without the controller interlock, edit device tree, alter a mask, or force-remove
modules; this design does not isolate itself from unrestricted root. Do not operate
configfs/dtoverlay, install alternate modules, bind other drivers or load dependent
overlays during a transaction. Such interference invalidates the campaign.

The source-development manager remains query-only. No compatibility or release
identity is promoted.
Kernel/controller code uses `GPL-2.0-only OR MIT`, declares Dual MIT/GPL, and uses
exported GPL-compatible APIs. Independent tooling and tests use MIT; the separate
administrative UAPI uses the project's syscall-note dual license. No upstream
implementation is vendored.

Offline tests exercise the real controller ioctl handler with mocked Linux APIs,
not the rejected synthetic transaction adapter. Fault injection covers partial
apply, both removal-error ID outcomes, retained module references, stale requests,
consumer exclusion, cleanup faults and response-copy failure. Userspace tests
cover actual transaction logic, command construction, persistent inhibition and
journal crash boundaries. These do not prove OF notification, kernel scheduling,
pinctrl state, timing, cleanup, coexistence, rebootless switching or RF safety.

## Runtime manager integration

The explicit runtime profile now has an implementation on the existing manager
socket, a bounded operator client, and journaled filesystem deployment tooling.
See [the workflow and its remaining target gates](../operations/runtime-manager-workflow.md).
The runtime profile is distinct from the packaged and source-development
protocols. Exact bindings include the entire runtime software inventory;
incomplete bindings must be regenerated and reviewed. Deployment and
administration share one lock,
and an unfinished deployment blocks administration. The [output reconciliation extension](runtime-output.md) connects application
startup to the root-owned consumer endpoint and adds explicit mask resumption.
Route switching never submits output. Application restoration releases only
owned inhibition after the required idle-state checks.

`runtime_provider.py` is the single installer facade over these components. Its
read-only `inspect` operation aggregates binding, deployment, controller, route,
application, service, endpoint and passive-output evidence. Its `plan`/`ensure`
and `route-plan`/`route-ensure` pairs require unchanged SHA-256 plan digests.
The intervening `activation-plan`/`activation-ensure` pair loads only the exact
bound controller, activates the exact manager socket, confirms controller route
zero through the manager and restores the captured application service intent.
The controller has no OF autoload alias, and activation verifies that loading it
did not load the consumer. The consumer endpoint must remain absent.
The latter delegates to the existing preflight-token transaction; it does not
add another overlay or module mutation path. Stable output and exit statuses are
defined in the operator workflow.

Neutral activation owns `activation.json`, its exact controller load, and a
socket start only when the socket was previously inactive. The DKMS deployment
owns its installed files and inhibitor. Systemd owns unit runtime state;
WsprryPi owns its service, configuration and companion; administrator masks are
preserved. `activation-recover-plan`/`activation-recover` restore the provable
post-deployment inhibited state without removing foreign objects. A non-neutral
controller, changed boot, substituted endpoint or failed unload remains a durable
recovery fault. A neutral controller with a nonzero generation is unloadable
only when the same-boot terminal route, manager, and optional application
journals form an exact recovery chain to that controller observation. The
recovery plan binds the controller state and every retained
route-recovery journal digest; missing or changed evidence remains a fault.

A terminal `complete-neutral` journal may seed a new current-boot activation
only after a clean reboot has removed both modules, both endpoints and the
manager socket. The prior journal must validate completely and bind the same
binding, artifact set and deployment record. Any prior route must have its full
terminal route/manager/application chain, including an attributable idle override
when present. Partial, failed, same-boot divergent or identity-drifted history
does not admit reboot activation.

All activation plans use one current format. The explicit `activationContext`
distinguishes initial, recovered, idempotent and post-reboot operations.
Post-reboot plans additionally require the full historical chain, current
disabled application capture and current boot. Reboot evidence is rejected in
other contexts. `reboot-prepare` durably records current intent before
establishing the inhibitor and retiring dependent journals in order. An exact
interrupted suffix can be retried without reusing the old boot's service or
transmission intent. A fresh controller session establishes route zero and
restores the captured current service intent. Retired formats are rejected;
there is no historical-format fallback. WsprryPi separately orchestrates its
saved route through the public facade.

For replacement of an exact owned deployment, current candidate code may retire
that same prior-boot terminal journal without first reactivating the controller.
A coherent terminal route, manager and application journal set from the same
prior boot and binding may be retired with it. `activation-retire-plan` binds the
installed binding, artifact set, retained deployment, current boot, exact
digest of every present journal, and any application-owned idle override.
`activation-retire` repeats the complete
inactive-state observation under the shared mutation lock and removes the exact
owned idle override while the application journal proves ownership, then
removes application, manager and route journals before the activation journal after the
owning updater has preserved it. This order leaves every interrupted prefix
eligible for an exact retry and creates no dynamic residue inside the deployment
being removed.
It does not load a module, start a socket, select a route, change application
intent or authorize output. The operation is unavailable for same-boot,
nonterminal, incomplete, active or identity-drifted state.

### Runtime overlay export policy

Exporting runtime overlay labels adds properties to the base `/__symbols__`
node, whose allocations can leak on removal. Runtime generation uses `fdtput` to
remove only the compiled `/__symbols__` subtree before embedding. The canonical
packaged DTS/DTBO pipeline is unchanged. All route nodes, properties, phandles,
external `__fixups__` and `__local_fixups__` remain byte-for-byte equal as decoded
properties; deterministic regression tests compare both trees. Runtime routes do
not support downstream overlays referencing their labels. This changes controller
and runtime DTBO identities and requires a fresh coherent deployment binding.
