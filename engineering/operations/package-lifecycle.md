<!-- SPDX-License-Identifier: MIT -->

# Package transitions and recovery

The maintained [lifecycle matrix](../../release/package-lifecycle-matrix-v1.json)
defines supported states and results. It separates real Debian/DKMS operations,
controlled command failures and offline ownership fixtures. It is a test contract,
not a target or application qualification record.

## Identities and ownership

The maintained predecessor is a synthetic `0.9.0-1` lifecycle fixture. Its
[record](../../release/lifecycle-predecessor-v1.json) binds licensed legacy
packaging templates and their exact checksums. The builder uses current module
source with a fixture version and an ordinary single-consumer DKMS profile.
It exercises legacy overlay copies, service helper attempts, native package
operations, cleanup refusal, rollback, and retry behavior in restricted containers.
It is not the historical package, preserves no old Git object dependency, and
establishes no historical or target qualification. Template provenance is retained.
The successor owns both interlocked modules in one DKMS instance. Equal UAPI
bytes do not establish package or runtime migration compatibility.

The current package owns its complete dpkg-listed data: versioned `/usr/src`
closure, inactive `/usr/lib/rp1-gpclk-dkms/overlays`, route executors under
`/usr/sbin` and `/usr/libexec`, versioned schema under `/usr/share`, documentation
and inactive systemd unit fragments. Native DKMS owns generated source links,
kernel links, build caches and the two modules in each kernel's `updates/dkms`.
Their ownership must agree with the exact package source. Orphan kernel links,
unexpected cache entries, changed cached source copies and unsafe cache types or
ownership are refused before native DKMS can recursively remove them. Missing installed
modules may be rebuilt; changed bytes, changed modes, duplicate compressed
artifacts, unlisted descendants and foreign registrations are refused.

The package creates the route group if absent and deliberately retains it on
removal and purge: an administrator may have enrolled other accounts. It creates
no runtime/development/application ownership record. Signing keys, certificates,
trust enrollment, DKMS-global configuration, boot configuration, foreign overlay
files, unrelated DKMS instances and application state remain outside package
ownership. Runtime state, source-development installations, manager drop-ins and
WsprryPi's default `/var/lib/wsprrypi/rp1-gpclk-dkms-installation.json` record block
replacement/removal until their owning workflow retires them. A nonstandard
application record path must also be checked by its owning orchestrator; the
package does not search arbitrary application files or infer their ownership.

## Preflight before the package manager

Verify the exact [candidate assets](release-candidate.md) and retain the previous
package before any change. From the incoming reviewed source, run the read-only
guard **before** invoking dpkg or APT:

```sh
sudo python3 -I /absolute/reviewed/source/scripts/package_preflight.py unpack
sudo dpkg -i /absolute/candidate/rp1-gpclk-dkms_0.99.0-1_all.deb
```

Run those as separate reviewed steps. Proceed to dpkg only after a `permitted`
result and exit 0 from the guard, with the authorized inactive state unchanged.
Do not paste an effect after a refused preflight and rely on the shell to stop.
The guard does not reserve the host against another privileged actor.

The guard emits `rp1-gpclk-package-preflight-v1` JSON, exits 0 for `permitted`,
and exits 1 for `refused`, retaining the underlying diagnostic. It does not open
either endpoint. The incoming preinst embeds those exact guard bytes and runs
Python in isolated mode. It does not trust an older installed helper. Configure and removal repeat the
appropriate checks before native DKMS effects.

Debian invokes the outgoing prerm before the incoming preinst. Consequently a
new package cannot prevent an old script's earlier effects. Direct `0.9.0` to
`0.99.0` replacement is unsupported and refused; do not bypass the external
preflight by running dpkg first. The approved path is owning runtime/development
cleanup, owning predecessor removal, then a clean successor installation.
The old scripts copy inactive overlays into `/boot` and contain debhelper
systemd integration. Their cleanup has historical boot/service effects and needs
its own authorization on an actual host. It is not covered by the current
package's passive guarantees. Never delete their evidence to admit the successor.

Packages from the predecessor repository are different software identities,
including versions `1.0.0-1`, `1.0.1-1`, and `1.0.2-1`. Direct replacement is
refused: use owning cleanup and removal before a clean installation. No fixture
result establishes target acceptance for those original packages.

The same rule applies to downgrade: never submit a predecessor archive over an
installed successor. Version ordering is not rollback. The predecessor preinst
also refuses an in-place downgrade, but that check is later than the successor
prerm. Verify successor absence before submitting the retained old archive.

## Repeat, kernels, compression and signing

Exact repeated dpkg installation and APT reinstall replace the attributable
same-version DKMS instance and rebuild all eligible installed header trees.
They do not promise a build-free no-op. Dpkg's database lock refuses a concurrent
same-version request; independent privileged DKMS work must be excluded by its
owning orchestrator. A native `dkms install` or `autoinstall`
for an already installed exact kernel may be a no-op. Guard and audit those
operations; native DKMS registration alone does not prove installed-file identity.

For a separately approved kernel addition or native DKMS operation:

```sh
sudo python3 -I /usr/libexec/rp1-gpclk-dkms/package_preflight.py configure
sudo dkms autoinstall -k EXACT_KERNEL_RELEASE
sudo python3 -I /usr/libexec/rp1-gpclk-dkms/package_preflight.py configure
dkms status -m rp1-gpclk-dkms
```

Every eligible installed kernel must have usable headers. A missing configuration
refuses mutation. Excluded kernels remain outside the build filter and acquire
no qualification. A non-running kernel can be built/installed without loading.
Native removal for one kernel retains the others; package removal retires the
named package version across all kernels. Kernel hooks and privileged DKMS
commands are distribution-owned entry points: their orchestration must retain
the same preflight and post-operation audit. Changing global configuration or
running them outside this procedure invalidates the passive-state assumptions;
the package does not isolate arbitrary root activity.

Native installed `.ko`, `.ko.gz`, `.ko.xz` and `.ko.zst` are separate file
identities when the installed libkmod supports their compression. A `-ZLIB`
libkmod cannot inspect gzip modules: the guard refuses that state before native
DKMS effects. Unsupported bzip2 lifecycle is likewise refused. Record installed bytes and decompressed ELF hashes, version,
vermagic, signature and controller interlock for every kernel. Never conflate a
signed cache with another installed file or accept two suffixes for one module.
The bounded ELF decoder also recognizes `.ko.bz2` for identity inspection;
native creation/removal of that format is not claimed. Compression/signing fixture variants do not qualify
a kernel's signature enforcement or certificate trust.

Signing checks use DKMS's effective `include/config/auto.conf`, falling back to
`.config`. For signing-capable Debian/Raspberry Pi OS headers, a secure existing
administrator key/certificate and the canonical target signing command are
required. Dynamic framework configuration, unreviewed compression arguments,
module overrides and non-passive hooks are refused, including before removal.
Other signing distributions/mechanisms require a separate review. See
[signing](signing.md). No package operation generates a key or enrolls trust.

## Failure, removal, purge and rollback

Retain dpkg's exact state, DKMS status, failing command/stage/exit, full bounded
log and per-kernel module identities outside the checkout. After repairing only
the proven prerequisite, retry configuration:

```sh
sudo dpkg --configure rp1-gpclk-dkms
```

A missing payload file needs reinstall from the verified exact archive. Changed
or foreign files require ownership review; a retry cannot overwrite them. A
DKMS add/build/install/depmod failure leaves an attributable native prefix.
Retry removes/rebuilds that named version without duplicating registrations.
For signing-capable header configurations, the package verifies each installed
PKCS#7 signature cryptographically against only the selected public certificate
and checks that certificate's validity period. Native DKMS signing warnings do
not establish success: missing, corrupt or wrong-certificate signatures refuse
configuration. This never reads private key bytes or establishes kernel trust.

The package explicitly checks the installed module set and runs `depmod` after
native DKMS configure/removal. Its `rp1-gpclk-package-indices-v1` result preserves
the command, stage, underlying exit status, signature results and diagnostic; it does not trust
DKMS's `do_depmod` success message, which can mask an index-command failure.
If removal fails, repair its prerequisite and repeat removal. Never force-remove
an unknown registration or clear a runtime journal to make recovery succeed.

After owning runtime recovery and verified module/endpoint absence:

```sh
sudo python3 -I /usr/libexec/rp1-gpclk-dkms/package_preflight.py remove
sudo dpkg --remove rp1-gpclk-dkms
sudo dpkg --purge rp1-gpclk-dkms
```

Run each selected operation separately and stop on failure. Removal and purge
are different requested outcomes; purge is not a workaround for failed removal.
Use the owning runtime update preparation API before package removal on a
WsprryPi-managed installation, and retire the application's installation record
through its installer rather than deleting it to satisfy the package guard.

Remove and purge delete attributable package data and native DKMS artifacts;
there is no package-owned active configuration or postrm cleanup. Administrator
keys, trust, shared configuration, unrelated modules and the route group remain.
Missing files may permit finishing interrupted removal. Modified present files
are preserved through refusal. Reinstall is a clean installation after removal.

Rollback is explicitly remove/reinstall, using the retained exact predecessor
archive and its manifest. First recover/remove any successor runtime, remove or
purge the inactive failed successor, verify its DKMS/source/modules absent, then
install the retained predecessor through its owning policy. This restores the
predecessor's package/module profile across installed kernels; it does not
restore runtime-controller sessions, routes, WsprryPi ownership/configuration,
services, a transmission or qualification. A failed predecessor configure is
retried with that exact package's own `dpkg --configure` path. Legacy effects
remain separately scoped, including during rollback.

## Disposable integration harness

Use ARM64 Linux/Docker. The [image recipe](../../tools/package-lifecycle.Containerfile)
pins its base, Raspberry Pi archive key and representative header versions.
APT tools may receive distribution updates at image construction; retain the
immutable image ID and recorded tool versions. Package tests run without a
network. They require no host boot/module/service/device mounts and no module,
reboot or hardware capabilities. Only filesystem ownership and APT user-switch
capabilities are retained. Each scenario is removed with its container; results
and logs stay in the new external output directory. Its mode is `0700`;
individual scenario bind-mount directories use `0777` beneath it so both users
can record results without `CAP_DAC_OVERRIDE`.

```sh
docker build -t rp1-package-lifecycle -f tools/package-lifecycle.Containerfile .
./scripts/build-lifecycle-predecessor \
  --source-commit "$(git rev-parse HEAD)" \
  --output /absolute/new/predecessor
python3 tools/run-package-lifecycle.py --image rp1-package-lifecycle \
  --candidate /absolute/verified/candidate \
  --predecessor /absolute/new/predecessor --output /absolute/new/results
```

The predecessor builder runs in the provisioned Linux build environment, not on
macOS. Use the current exact clean source commit; no historical tag or Git object is required.
Use `--scenario` for a focused rerun. The harness records distribution,
architecture, package manager, DKMS/compiler/compression tools, header configs,
candidate/predecessor digests and every before/after transition. Legacy service
attempts are separately logged and interlocked; candidate service/module-loader
attempts fail the test. Native DKMS is real; command faults and signing/compression
header variants are explicitly controlled test inputs.

The `packaged-runtime-baseline` scenario checks runtime directory pruning and
absence detection against a real installed package's passive units and overlays.
It substitutes inactive service/module/endpoint observations and does not deploy
or activate a runtime. It also checks refusal and preservation of changed or
foreign overlay files. These filesystem checks do not establish target runtime
removal or service correctness. Actual service-manager,
signing trust, target binding, GPIO, WsprryPi and RF validation remain separate.
WsprryPi owns application acceptance of exact provider identities. The existing
target rollback exclusion remains in force; these procedures and offline
regressions do not establish target rollback qualification.

## Attributable scenario results

The disposable runner requires a nonempty explicit scenario selection and one
accepted result per requested scenario. Single-scenario execution is not full
lifecycle acceptance. The `rp1-gpclk-package-lifecycle-v2` result binds a fresh
host run ID, scenario, source commit, candidate and predecessor package SHA-256,
and immutable container image ID. The container verifies source/package inputs
before and after scenario execution; the host rechecks them before final success.
Source checks compare tracked bytes and executable modes with Git objects,
including changes hidden by index flags.

Acceptance requires a bounded stable single-linked regular result file, unique
JSON keys, exact envelope fields and integer version, matching attribution,
zero container exit, PASS without an error, nonempty completed steps, and
explicit absent endpoints/unloaded modules in each step observation. Hardware
and RF qualification remain false. Expected refusal steps can have nonzero
command exits; scenario success requires their existing independent oracles.
Missing, stale, malformed, contradictory or substituted results fail aggregation.
The result envelope establishes attribution and basic completed work; the
lifecycle matrix and scenario assertions retain ownership of behavioral coverage.

Both entry points restart with isolated Python and use a fresh temporary cache
before importing local helpers. Ignored bytecode and `PYTHONPATH` cannot supply
those imports. Cache output stays outside the source tree.

## Owned cleanup

Each scenario has fresh run/scenario labels and a host-owned, bounded CID file
outside the container-writable result directory. Docker output logs also stay
outside that directory, preventing substituted container paths from redirecting
host diagnostic reads. Cleanup inspects matching
containers and their image/labels before removal. A fresh successful engine
query must prove their absence; daemon errors and ambiguous ownership fail
acceptance. An auto-removal race can succeed only with this absence evidence.
The aggregate keeps the initiating error separate from cleanup diagnostics.

Docker clients and package-lock children use dedicated process groups. Their
owner reaps them on exit, exceptions, or cancellation, escalating only within
that group. File-backed output avoids pipe backpressure. Package-lock holds
are released on every exit. SIGINT/SIGTERM cancel execution; signals received
during cleanup are deferred until cleanup finishes. This proves harness resource
cleanup only, without establishing kernel, hardware, or RF safety.

## Failure budgets and diagnostics

The driver uses one monotonic one-hour deadline and a 15-minute guard per
scenario. Command output never renews those deadlines. Cleanup runs after the
execution guard and uses 30-second Docker control guards and ten-second process
reaping guards. Container commands have ten-minute guards; package-lock release
has a three-minute completion guard. These generous hang guards exceed the
observed eight-minute complete serial run and are not readiness or product timing
requirements. Different runner provisioning can still require investigation.

Workflow provisioning, input preparation, and lifecycle steps have separate
20-, 15-, and 65-minute guards within a 105-minute job guard. Ordinary offline
and documentation jobs have 45- and 20-minute guards. APT acquisition uses two
retries and 30-second I/O guards; the pinned key and exact header-archive downloads also have three-minute
whole-transfer limits. Pip uses two retries and a 30-second socket guard. The job
and step guards bound continued slow progress across individual acquisitions.
Missing tools or exhausted acquisition budgets remain failures.

Owned command output is file-backed, checked during execution, and rejected if
it exceeds its byte budget (64 MiB for Docker, 4 MiB for container commands).
The polling interval limits detection delay, not a strict disk quota: a burst can
exceed that size before termination. Only bounded tails enter failure summaries.
The harness copies at most eight 64-KiB DKMS logs per recorded step; it does not
recursively retain the container filesystem. Private signing keys are excluded.
The always-run workflow summary reads only the bounded aggregate result and
prints scenario names, statuses, and exit codes. Empty, duplicated, rejected,
or unresolved summaries fail; complete-matrix summaries require all scenarios
and case IDs. Selected subsets are identified explicitly. Missing or invalid
results fail. Original failing steps retain their failure status. No artifact-upload
action is installed: temporary runner files expire with the runner, and bounded
job-log summaries provide diagnostics subject to the service's log retention.
Cancellation before summary execution can still prevent its publication; it
cannot establish successful validation.

## Obligation attribution

The lifecycle matrix owns expected transition states and evidence classes.
`tools/lifecycle_coverage.py` maps each case to a scenario and required stages.
The host driver derives attribution from actual completed commands, exit codes,
and before/after observations; the container cannot add case IDs to certify its
own completeness. Missing or duplicated stages, wrong commands, states, or
contexts fail acceptance. Every selected scenario must retain its final cleanup
stage. Both exact headers and both build profiles have separate required stages.
The aggregate distinguishes a selected subset from complete matrix coverage.
Shared transitions can exercise several obligations without becoming multiple
independent fault executions.

Controlled Python-boundary failures exercise incoming pre-install and configure
interruptions. Inventory failure injects a foreign DKMS-cache member immediately
before the real inventory validator; the helper must refuse it, retain its
evidence, and converge only after the fixture removes that exact member.
Filesystem-only passive-runtime checks have explicit in-process observations,
not invented external command executions. Their service/endpoint observations
remain stubs, and they do not qualify live runtime retirement.

## Snapshot metadata

Each installed module is queried once with native `modinfo --null`. The bounded
parser accepts raw `key=value` and generated `key: value` records, preserves
repeated alias ordering, requires one nonempty version and vermagic, rejects
duplicate scalar fields, and permits absent optional signing/interlock fields.
Multiline signature material is outside the projected field set; projected
scalar fields cannot contain line breaks. Nonzero status, malformed framing,
missing identity, and oversized output fail the snapshot.

Snapshots retain installed-file and decompressed-ELF digests. Regular-file,
link-count, size, inode, mode, and timestamp checks bracket metadata collection,
and file digests must remain equal. Native compression and independent PKCS#7
verification remain separate checks; metadata is not cryptographic evidence.
Before/after observation frequency and all header/profile contexts are retained.

## Exact header provisioning

The lifecycle image downloads the exact ten representative header/base/kbuild
archives listed in `tools/lifecycle-headers.sha256` from the official Raspberry Pi
package pool. It verifies every SHA-256 before installing local archives, then
checks both header metapackage versions. The selected kernels and their matching
dependencies remain pinned even when the moving APT index omits older versions.
Download size, retries, connection, and total-transfer guards are finite; missing
or substituted archives fail provisioning. Replacing a pin requires review of
the actual archive identity and dependency closure. Header archives are build
inputs only and confer no target or RF qualification.
