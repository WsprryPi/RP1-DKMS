<!-- SPDX-License-Identifier: MIT -->

# Testing

## Run the offline checks

Run commands from the repository root after inspecting the selected runner.
Use a provisioned Linux build environment for the full suite. CI uses Ubuntu
24.04, Python 3 with `jsonschema`, C/C++ compilers, Git, make, device-tree-compiler
(`dtc` and `fdtput`), ShellCheck, Debian package tools, debhelper, dh-dkms and
zstd. The [release-builder recipe](../tools/release-builder.Containerfile)
provides a maintained dependency inventory; provisioning that environment can
use the network, while ordinary checks need no network, privilege or hardware.

```sh
make check
make package-check
```

Require each command's final exit status, not just an intermediate `PASS` line.
`make check` includes C++ compilation and Linux-only real package-build fixtures.
On macOS those Linux fixtures are skipped; the full result belongs to Linux CI.
For documentation-only edits, the link/SPDX/whitespace checks below are sufficient
locally; CI still runs the complete Linux suite:

```sh
python3 tests/check_doc_links.py
python3 tests/check_spdx.py
git diff --check
```

The link checker verifies relative destinations, not heading fragments or
external URLs. Check changed fragments and command examples separately.
Documentation regressions and Sphinx exports are a separate target, described
below. None of these commands runs the disposable package-install harness.

## CI assurance and measurement

The push and pull-request workflows retain four separate jobs: Ubuntu AMD64
`offline`, Ubuntu ARM64 `lifecycle`, Ubuntu `documentation`, and native Windows
`windows-documentation`. Language, header, profile, route, artifact, and platform
contexts retain their independent obligations. Workflow success and required
merge-check enforcement are separate properties.

Reliability, safety, required coverage, and defect detection take priority over
speed and maintenance targets. Readiness requires observed state. A finite
watchdog detects failure; elapsed time or a fixed sleep cannot establish
readiness. Preserve the initiating error and secondary cleanup diagnostics.
Unknown ownership, incomplete results, and unresolved cleanup block acceptance.

Before changing or retiring an oracle, demonstrate its actual sensitivity and
the replacement's detection of deliberate defects in disposable source/fixture
copies. Retain independent expected values, real subprocess and cryptographic
boundaries, source/artifact identities, and required no-write and recovery cases.
A model or source-shape check supports its stated scope without establishing
kernel concurrency or hardware behavior.

Compare exact source, environment, coverage, and cold/warm conditions. Account
for all replacement helpers, regressions, dependencies, and newly activated
coverage. Separate code, physical files, process and compiler/linker invocations,
contexts, and elapsed time. Allocate mixed fixture/assertion roles before claiming
orchestration reductions. Unused fixtures and retired execution prompts receive
no orchestration-saving credit. Local launch-count reductions cannot establish
whole-CI savings. Record failed attempts, retries, queue delay, and overlapping
job spans separately; aggregate spans are not billed cost.

Parallel scenario execution requires a separately reviewed resource/ownership
plan and an equivalent serial reference. Preserve per-scenario isolation, finite
budgets, source/artifact attribution, full aggregation, failure propagation, and
verified cleanup. Contention or lost defect detection invalidates a speed gain.

## Representative kernel builds

Build in a separate disposable source tree on an identified Linux host with
the exact representative headers. The direct default is the ordinary consumer;
`RP1_RUNTIME_CONTROLLER=1` is the alternative interlocked two-module profile:

```sh
make KERNEL_BUILD=/absolute/representative/headers
python3 tests/check_built_module.py rp1_gpclk_dkms.ko \
  --kernel-release EXACT_KERNEL_RELEASE --machine AArch64
```

For the runtime profile, use a fresh tree and add `RP1_RUNTIME_CONTROLLER=1`
to the build. Validate both `rp1_gpclk_dkms.ko` and `rp1_route_controller.ko`;
check the consumer's interlock marker, dependency and absence of an OF autoload
alias. The parameterized validator checks ELF architecture, version, license
and vermagic only. It does not verify signing trust, complete binding identity
or loaded memory. Record compiler, configuration, source/UAPI/artifact hashes
and the selected profile separately. No command here loads either module.

## Documentation scaffold

`make docs-check DOCS_PYTHON=/path/to/docs-environment/bin/python` runs the
documentation-only `tests/test_documentation*.py` regressions and strict builds
for the scaffold's supported output formats. It also validates repository links,
licensing and whitespace. Sphinx dependencies belong to the selected documentation
environment; ordinary module tests remain independent of them. See
[documentation maintenance](documentation.md) for entry points and output paths.

## Maintained inventory

`make check` runs every standalone `tests/check_*.py` program except
`check_built_module.py`. The latter is a parameterized build validator: it
requires a caller-supplied `.ko` and exact kernel release and never loads the
module. `tests/offline_checks.py` owns the ordered Python registry and directly launches
each standalone check in its own process. `check_test_inventory.py` compares this
registry with the filesystem, validates active C/C++ compiler and execution
commands, and requires both real client planners. Comments do not register tests.
The module validator and compiled sweep validator retain parameterized callers.
Missing ShellCheck fails in CI; local absence is reported as a skip.

Unittest entry points use `tests/nonempty_unittest.py`: an empty discovered suite
or zero executed cases fails. Documentation discovery additionally requires every
matching module to contribute cases. Standalone programs retain their own
assertion and exit contracts; their launches are reported individually. No
lexical assertion count is presented as a case count.

`make package-check` repeats the package-specific subset. Repetition there is
intentional because package validation is also a separately usable gate.

The C programs executed by `tests/run-offline-checks.sh` are hardware-free
host tests. `development_tone_client.c` and `development_fault_client.c` are
target development clients that can open the endpoint and request output.
Their standalone entry points require separate, route-specific hardware
authorization and are never invoked by an ordinary test target.

On Linux, the offline runner compiles `development_client_tones.c` separately
against each client's actual divider-planning function. This wrapper replaces
endpoint opens and ioctls with aborting stubs and calls only the pure planner.
It checks parent agreement with the provider, exact Q16 divider/count fixtures,
UAPI divider constraints and the calculated mean frequency. Other hosts skip
this wrapper because it requires Linux userspace headers.

The same Linux runner compiles the sweep client's real CLI and renderer through
`development_sweep_plan.cpp`, using aborting endpoint and SoapySDR stubs instead
of an SDR library. `check_development_sweep.py` checks the default frequency
vector, fixed-tone dividers, source PPM, direct/third-harmonic selection,
integer-divider boundaries, alternate offline models, and rejection of live
parent mismatches before any hardware call.

GPCLK divider planning uses a 200 MHz parent; DMA pacing uses a 50 MHz reference.
Execution-policy tests retain the one-write minimum duration and 97,847 writes
for a fresh one-second event with tick divider 511. Clock-setup tests model a 50 MHz
alternate parent so they can verify reparenting and restoration; that model is
not the current output-parent contract.

The tone client's `finite` operation submits one one-second event. The
`cancel-start`, `cancel-middle`, and `cancel-boundary` operations each submit one
maximum-duration logical event, then request cancellation immediately, halfway
through the first one-second DMA chunk, or at its boundary. Each operation
requires the opened endpoint to be a root-owned mode-`0600` character device,
then requires a stable `COMPLETE/STOPPED` result with no cleanup fault. It polls
passive snapshots to prove the module reports GPIO safety and clock/DMA
quiescence and a completed bounded drain before release, and that owner and
lease are absent afterward. A
target campaign must additionally use independent physical observation to
prove endpoint closure, absence of a successor, GPIO safety, clock and DMA
quiescence, and terminal silence; the client result alone is not that proof.

### Fixed C-client tone planning

Both `development_tone_client.c` and `development_fault_client.c` calculate
their fixed nominal **10,140,200 Hz** tone from the provider's nominal
**200 MHz** `pll_sys` parent. They default to GPIO20;
`RP1_GPCLK_TEST_ROUTE=4` selects GPIO4 and `20` selects GPIO20. These are
fixed-frequency lifecycle/fault fixtures, not general frequency planners.

Correct divider arithmetic does not establish actual frequency accuracy,
timing, cleanup or RF qualification. A target plan must separately identify
the exact client/provider artifacts, route and frequency and obtain hardware
authorization. Output-inhibited submission is refused and cannot exercise
their execution/cancellation cases.

## Cancellation and fault evidence

The ordinary host suite injects every core transaction fault and every
execution-machine setup/cleanup operation. It proves lease and generation
rollback, one terminal publication, one plan release, stage-specific failure
reasons, cleanup-failure precedence, the persistent cleanup latch, and complete
cleanup attempts after an earlier failure. Those mocks do not prove RP1
hardware state.

A target evidence campaign therefore repeats the three maximum-duration
cancellation positions and injects failures at clock setup/enable, active and
safe pinctrl selection, DMA preparation/submission/completion, divider readback,
and cleanup restoration. Fault injection must be compiled into a separately
identified test artifact or supplied by reviewed kernel fault facilities; it is
not a production module parameter or UAPI command. After every case, capture
the lease-scoped terminal reason followed by a passive snapshot proving stable
terminal state, the expected owner/lease disposition, GPIO safety, clock and DMA
quiescence, and cleanup-latch state. The authority observation is the immutable
root-owned mode-`0600` endpoint; there is no kernel authorization credential to
restore or clear.

The maintained target cancellation client measures latency from issuance of
`STOP` to observation of terminal state. It rejects latency above one fixed DMA
chunk plus 500 ms of cleanup, scheduler, and polling allowance; total execution
elapsed time is recorded separately because a boundary-race winner may have
committed the next chunk immediately before `STOP` obtained the commit lock.

The maintained compile-time target injector has stages 1 through 15 for clock
rate setup, clock preparation, active pinctrl, clock enable, DMA preparation,
DMA submission, DMA completion, readback, and each ordered cleanup operation. Build exactly one
stage into an otherwise exact source tree with:

```sh
make KERNEL_BUILD="/lib/modules/$(uname -r)/build" \
  RP1_TARGET_FAULT_STAGE=STAGE
modinfo rp1_gpclk_dkms.ko | grep rp1_target_fault_stage
```

An injected artifact emits a prominent `TEST-ONLY` kernel warning and carries
the `rp1_target_fault_stage` module-information field. The setting is a build
variable only: it creates no module parameter and no UAPI control. Clean or use
a separate build tree between stages and retain every artifact hash. The fixed
C-client tone-planning and target-authorization requirements above also apply
to fault validation. A reviewed fault client requires the expected
terminal reason and whether a cleanup latch is expected. It verifies retained
terminal state twice, GPIO/clock/DMA quiescence, normal lease release for setup
or execution failures, and deliberate `EUCLEAN` release refusal for cleanup
faults. The administrator must unload each cleanup-latched test artifact and
verify endpoint, lease authority, route, clock, DMA, and GPIO teardown before
continuing.

Build the standalone `development_frequency_sweep.cpp` client explicitly with
`make development-frequency-sweep-client` on a Linux host with SoapySDR
development headers. Its default, hardware-free `--render-only` run requests
16 uniformly spaced RF frequencies, inclusive, from 135.7 kHz through 148.0
MHz. It uses finite two-second generic `GPIO20` events at 2 mA only with explicit `--live`,
and measures them with SDRplay serial `2404058C60`. With the selected
`pll_sys` parent, frequencies through the provider's 100 MHz GPCLK0 output
limit use the fundamental; higher requested frequencies measure the third
harmonic.
Source-clock and receiver PPM values are separate explicit inputs; both default
to zero. The CSV includes the divider plan, raw SDR estimate,
receiver-corrected estimate, carrier level, worst spur outside a roughly 200 Hz
carrier exclusion, median in-band noise, and rejected points. This diagnostic
does not itself authorize target or RF work. `make check` exercises only its
hardware-blocked offline wrapper described above.
Repeat `--frequency-hz` for a repeatable selected-frequency comparison within
the same range; otherwise the uniformly spaced vector is retained. Explicit
`--parent-hz` and `--maximum-direct-hz` inputs change userspace planning only;
they do not change the provider's clock source or output contract. Alternate
parents are accepted only for offline rendering. Live mode requires the nominal
200 MHz parent and rejects other parent values before opening the output file,
endpoint or SDR. Use `--source-rate-ppm` for source calibration. Changing the
provider's parent contract requires a separately reviewed provider and client.
When an ideal pair straddles an integer-divider boundary, the renderer selects the
nearest legal same-integer pair and clamps its weighting instead of rejecting
the requested frequency.

Render a plan without touching hardware:

```sh
./build/development-frequency-sweep --render-only --points 16 --repeats 2 \
  --source-rate-ppm 0 --receiver-ppm 0 \
  --output /tmp/rp1-gpclk-plan.csv
```

Run the same vector live only in an authorized `GPIO20`/SDRplay window:

```sh
./build/development-frequency-sweep --live --points 16 --repeats 3 \
  --source-rate-ppm 0 --receiver-ppm 0 \
  --output /tmp/rp1-gpclk-live.csv
```

The transmitter PPM describes the selected source (`negative` means slow) and
changes divider planning through `corrected_parent = parent_hz * (1 + ppm/1e6)`
(the current default parent is 200 MHz).
The receiver PPM corrects the SDR estimate by division by `(1 + ppm/1e6)`.
Replace the example zero corrections only with values calibrated for the
actual source and receiver. They are not interchangeable.

## Interface checks

UAPI tests protect the current canonical header, ioctl layouts, exact digest,
and absence of legacy layouts or commands. Route-manager tests retain only the
minimal deterministic fixtures needed to verify current ownership and recovery
behavior.

Generated test output belongs in temporary directories. Qualification captures,
run results and deployment inventories belong outside this source checkout.
Release format/adversarial checks run through `check_release_candidate.py`.
Its portable cases check version convergence, deterministic source encoding,
unsafe archive members and duplicate JSON keys. On Linux its unprivileged
fixtures build an exact temporary Git commit, exercise the real builder and
independent validator, test dirty/untracked and index-hidden source changes,
rebuild package/source bytes, and reject malformed, substituted and incorrectly
classified assets. Linux requires the complete Debian build dependencies;
macOS reports the Linux-only cases as skipped. CI runs the full Linux suite.
No fixture installs a package or executes target/module/overlay effects.

The maintained suite covers module behavior, current runtime ownership and
recovery, package transitions and reproducible artifact validation. Offline
checks retain canonical UAPI, output-inhibit and cleanup assertions.

Target waveform and mode qualification belongs in the external WsprryPi Harness.
No ordinary repository test authorizes installation, loading, GPIO, transmission,
SDR capture or RF operation.

## Debian lifecycle integration

`make package-check` includes offline ownership, migration-policy and predecessor
rendering regressions. The opt-in
[disposable Linux harness](operations/package-lifecycle.md) additionally runs real
Debian package/DKMS transitions. It is never launched by ordinary `make check`.
Its container-only driver refuses host execution and unapproved capabilities or
system bind mounts. Package operations are real; command faults and header
signing/compression variants are explicitly recorded. Generated results remain
outside the checkout. Source-development, package, target-loading, application
and RF evidence remain distinct.

## Process observation boundaries

Inventory process checks synchronize on a real child readiness record before
exercising the normal five-second timeout guard. They retain partial-I/O,
output-limit, nonzero-exit, EOF-before-exit, cancellation, and descendant-held
stdout cases. EOF is not an exit acknowledgement. Inventory owns its direct
child only; a descriptor-holding descendant causes unknown observation and is
separately released by its test fixture. Unresolved direct-child cleanup remains
explicit alongside the original observation failure.

The route client uses one 30-second monotonic transaction budget across connect,
send, and all response reads. Partial replies do not renew it. A client timeout
means state requires observation; it does not cancel server-side kernel work or
prove restoration. Server lock, fixed-command, service-acknowledgement, boot,
token, PID, and terminal readiness checks remain independent. The application
acknowledgement loop and its final PID/service acceptance check retain their
existing contract; a socket deadline does not replace those observations.

Runtime bundle fixtures copy explicit inventory inputs and canonical overlay
sources into temporary trees. Both real builders and embedded-overlay generation
use that tree, including lazy generation calls. Determinism checks poison prior
generated overlays and reject missing embedded overlay bytes before publication.
Synthetic ELF note/provenance identities exercise bundle formats only; they do
not establish real compiled module validity, signing, or target qualification.
The fixture checks content/mode identities for checkout files, including ignored
outputs, on successful and rejected builds. Bytecode is suppressed and bootstrap
imports run outside the checkout.

## Oracle scope and overlay fixtures

`check_route_uapi_contract.py` enforces source-shape, overlay-text, canonical
header identity, and schema vocabulary constraints. It does not simulate route
ownership. `lifecycle_core.c` executes the production core, including repeated
GPIO4/GPIO20 acquisition/release, foreign and same-owner refusal without writes,
cleanup latches, stale generations, and dead-state admission refusal.
The controller ioctl harness compiles actual controller code with aborting or
controlled host stubs. `resource_policy.c` executes production route/target
arithmetic; its unwind/reference/dead-lifetime section is an independent model.
These host oracles do not qualify Linux concurrency, device removal, DMA, or
physical GPIO/RF behavior.

All DTS fixtures are retained. Generic text discovery is not semantic probe or
resource-conflict execution. The invalid-route and GPIO20 route-mismatch fixtures
have named static assertions. The following fixtures require a separately
identified semantic target consumer and its expected refusal/cleanup oracle
before their qualification role or retirement can be resolved:

| Retained fixture | Intended challenge | Disposition |
| --- | --- | --- |
| `rp1-gpclk-gpio4-bad-dma.dts` | Missing GPIO4 DMA binding | HOLD |
| `rp1-gpclk-gpio20-bad-dma.dts` | Missing GPIO20 DMA binding | HOLD |
| `rp1-gpclk-gpio4-conflict.dts` | Second GPIO4 resource consumer | HOLD |
| `rp1-gpclk-gpio20-conflict.dts` | Second GPIO20 resource consumer | HOLD |
| `rp1-gpclk-gpio4-dma-conflict.dts` | GPIO4 composite ownership with empty safe states | HOLD |
| `rp1-gpclk-gpio20-dma-conflict.dts` | GPIO20 composite ownership with empty safe states | HOLD |
| `rp1-gpclk-gpio4-missing-active.dts` | Missing GPIO4 active pinctrl state | HOLD |
| `rp1-gpclk-gpio20-missing-active.dts` | Missing GPIO20 active pinctrl state | HOLD |

Neither text discovery nor absence of a named repository caller establishes that
these fixtures are unused. Target operations retain their separate authorization
and safety requirements.
