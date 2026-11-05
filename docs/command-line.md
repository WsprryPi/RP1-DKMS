<!-- SPDX-License-Identifier: MIT -->

# Command-line reference

The WsprryPi web interface is the normal route-control workflow. The commands
below help an administrator inspect an installed system or recover a known
managed transaction. Run them on the Pi; do not run developer test clients
or submit a signal merely to inspect status.

Use a console or an existing SSH session on the Pi being investigated. `sudo`
uses that Pi's administrator account. These paths refer to its installed
WsprryPi-managed runtime, not a source checkout on your workstation. If a tool
is missing or refuses a different manager profile, retain the error and stop;
do not copy a newer script onto the installation by itself.

Run inspection commands individually. An expected nonzero result should not
prevent you from collecting the next observation. Do not put the whole
inspection behind `&&`, and do not run the recovery commands as a batch.

## System and module inventory

These commands read system/package metadata. They do not load a module,
select a route or open the execution endpoint:

```sh
cat /etc/os-release
uname -r
uname -m
dpkg-query -W -f='${Status} ${Version}\n' rp1-gpclk-dkms
dpkg-query -W -f='${Status} ${Version}\n' dkms
dkms status -m rp1-gpclk-dkms
modinfo -k "$(uname -r)" -F filename rp1_gpclk_dkms
modinfo -k "$(uname -r)" -F version rp1_gpclk_dkms
modinfo -k "$(uname -r)" -F vermagic rp1_gpclk_dkms
modinfo -k "$(uname -r)" -F filename rp1_route_controller
modinfo -k "$(uname -r)" -F version rp1_route_controller
modinfo -k "$(uname -r)" -F vermagic rp1_route_controller
```

Source-development installations may have DKMS records without an installed
Debian package. `modinfo` describes an installed module file, not proof that
it is loaded or that the route is active. A missing result is useful evidence.

Read the results together:

- `uname -r` identifies the running kernel. DKMS needs an installed result for
  that kernel, not only a successful build listed for a different one.
- A Debian package result identifies package installation. It does not prove
  runtime deployment, route selection or the absence of a conflicting source
  installation.
- `filename` shows which installed module file is found for this kernel;
  `vermagic` includes its kernel identity. Retain both modules' results.
  Matching version strings alone do not establish exact source identity.
- A permission error, missing command or missing module should remain in the
  report. Do not load a module to make this inventory succeed.

## Managed runtime inspection

When WsprryPi has installed the runtime tools, inspect their state with:

```sh
sudo python3 /usr/lib/rp1-gpclk-dkms/runtime_provider.py inspect
printf 'inspect exit status: %s\n' "$?"
```

The `printf` must immediately follow `inspect` to record its exit status.
Then query the route manager separately:

```sh
sudo python3 /usr/lib/rp1-gpclk-dkms/runtime_route_client.py query
```

These are observational commands: they do not install, switch routes, submit
output or repair state. They can perform passive endpoint queries. Avoid
concurrent route changes while gathering a consistent report. `inspect`
prints one JSON document and returns the [classified exit code](status.md).
`query` returns the managed route service's response and exits 2 on a reported
service error. A missing client or socket can mean deployment is incomplete;
do not substitute a different manager profile.

`query` can report a connection/profile error without a JSON response; preserve
stderr too. Its process exit status is not the provider's 10–14 classification.
In a JSON response, examine `state.activeRoute`, `state.application.phase`,
`state.applicationInhibited` and any error details. A retained transaction
record can describe a completed change. A successful query or an
administrative `outputEnabled` field alone does not prove physical RF is off.
Use the [readiness interpretation](status.md) and the actual operation context.

For installed scoped evidence status, use WsprryPi's maintained helper:

```sh
sudo python3 /usr/local/lib/wsprrypi/rp1_qualification.py status --route gpio4
```

Use `gpio20` for that route. This checks the locally installed evidence bundle
and performs bounded passive inspection; it does not download evidence or authorize
output. Provider diagnostics report structural and runtime observations; an
aggregate compatibility result cannot establish qualification or output inhibition.

## Service and kernel messages

```sh
systemctl status --no-pager wsprrypi.service rp1-gpclk-route-manager.socket
sudo journalctl -b --no-pager -n 100 -u wsprrypi.service -u wsprrypi-rp1-reconcile.service -u 'rp1-gpclk-route-manager@*.service'
sudo journalctl -k -b --no-pager -n 100 -g 'rp1_gpclk|rp1-gpclk|rp1_route|rp1-route'
```

`status` can return nonzero for an inactive service. Retain that result and
the actual message. `journalctl -b` reads the current boot; retain the failed
boot's logs before a planned reboot when possible. A stopped or masked service
can reflect administrator intent rather than a fault. These commands do not
restart, unmask or enable it. Review logs before posting them publicly.

## Administrative recovery

The following commands **change the installed runtime or application service**.
Use them only for the described known state after transmission has stopped,
cleanup is complete and the owning runtime has been identified. Preserve the
failure response first. They are not a general repair script.

Choose **one** case from [maintenance and recovery](maintenance.md). Query
before it to confirm the case, and query afterward to verify the result.
If the preconditions are unclear, collect evidence and request support.

### Retry application restoration

Use only when route selection succeeded for the intended GPIO and application
restoration failed, after the reported service prerequisite has been corrected:

```sh
sudo python3 /usr/lib/rp1-gpclk-dkms/runtime_route_client.py restore --execute
```

The selected route must remain unchanged. A previously running application
should return online and idle; stopped/masked intent remains preserved. A
refusal about an unresolved route, boot or deployment is not a reason to force
the service to start.

### Retry normal removal

For an administrator performing normal GPIO4 removal, or retrying its confirmed
**Route removed; service unavailable** result after correcting the service error:

```sh
sudo python3 /usr/lib/rp1-gpclk-dkms/runtime_route_client.py remove gpio4 --execute
```

Use `gpio20` only when GPIO20 is the route being removed. Successful removal
returns to no route and restores a previously running application online and
idle. Previously stopped or administrator-masked services retain that intent.

### Recover an interrupted route transaction

Use only after the administrator/support reviewer identifies an owned
interrupted route transaction. A generic `recovery_required` result from
deployment or activation is not sufficient:

```sh
sudo python3 /usr/lib/rp1-gpclk-dkms/runtime_route_client.py recover --execute
```

Recovery returns to no route and **keeps the application inhibited**. It does
not resume transmission or complete every deployment/update recovery. If the
command refuses ownership, reports a cleanup fault or cannot prove completion,
stop and request support. Do not delete journals or force unload.
Keep the recovered system inhibited pending the administrator's next managed
restoration/selection procedure. Recovery success does not mean the web
interface must have restarted or that you should enable transmission.

Routine selection and switching belong in [WsprryPi's route controls](routes.md).
Lower-level deployment plans, signing and package operations are described in
the repository's engineering procedures for administrators maintaining those
specific profiles.
