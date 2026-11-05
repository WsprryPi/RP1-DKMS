<!-- SPDX-License-Identifier: MIT -->

# Application route manager contract

This document describes the **packaged boot/reboot profile**, including its
passive source-development binding. The
[runtime profile](https://github.com/WsprryPi/RP1-DKMS/blob/main/engineering/operations/runtime-manager-workflow.md) uses the same socket
with a different contract and schema. Query the profile before constructing any
effect request; do not send these reboot operations to a runtime deployment.
Package installation alone neither activates this executor's socket nor deploys
the runtime profile.

`/usr/sbin/rp1-gpclk-route-manager` is the application-facing executor. It accepts one JSON object on standard input, no command-line arguments, and writes one JSON object to standard output. Both directions use `schema/rp1-gpclk-route-manager.schema.json`; the contract identifier is `rp1-gpclk-route-manager`.

The package installs that schema at
`/usr/share/rp1-gpclk-dkms/0.0.1/rp1-gpclk-route-manager.schema.json`.
This document is also installed independently at
`/usr/share/doc/rp1-gpclk-dkms/route-manager.md`; its web reference above points
to the maintained engineering guide, not a file included beside it.

Requests contain one operation. `query` has no other fields. `preflight` requires `route` (`gpio4` or `gpio20`). `apply-and-reboot` requires `route`, `execute: true`, an 8--64-character `requestId`, and an attributable `actor`. `rollback` and `reconcile` require the same mutation fields except `route`. Unknown or operation-inappropriate fields fail closed.

Responses contain `contract`, `operation`, `status`, and either `state` or `error`. State keeps `configuredRoute` (the package-owned boot block) separate from `activeRoute` (the enabled post-boot device-tree endpoint). A configured route never establishes an active or operationally ready endpoint. Consumers require successful post-boot reconciliation and their own exact-build compatibility decision.

`query` is passive. `preflight` is read-only and needs no physical-topology confirmation. It validates exact `0.0.1` package, module, UAPI and both overlay identities, route ownership syntax, journals, endpoint ownership and closure, and a readable immutable `output_inhibit` state. It observes and reports each fixed service state but deliberately accepts an active `wsprrypi.service`, allowing the running UI to present the result before confirmation. Application execution, scheduling, drain, and commitment idleness remain WsprryPi policy. Preflight does not open the endpoint, stop a service, or operate GPIO.

Mutations require UID 0 and `execute: true`. They accept no paths, overlays, commands, sudo arguments, or shell fragments. Before any boot write, the executor records the observed fixed service states in its root-only attributable journal, owns a bounded stop of only `wsprrypi.service` and `soapyremote-server.service`, and verifies both are inactive or failed. A partial quiescence or later pre-reboot failure restores every service that was active and retains explicit recovery state. Only after verified quiescence may it atomically replace and read back the boot configuration and invoke `/usr/bin/systemctl reboot`. Rollback uses the same ownership protocol and restores only exact journaled bytes. Reconciliation is an attributable root mutation and completes only after the boot ID changes and configured and active routes agree.

The package ships disabled-by-default `rp1-gpclk-route-manager.socket` and `rp1-gpclk-route-manager@.service` units. The Unix socket is mode 0660, owned by root and group `rp1-gpclk-route`. An explicitly enrolled WsprryPi service account can send the same closed JSON request over that fixed socket. Systemd runs the executor as root in a separate service cgroup, so stopping WsprryPi cannot terminate the transaction. Enrollment and enabling the socket are explicit WsprryPi/operator policy; neither occurs silently. This is the supported interactive mutation transport and requires no sudo command, wrapper, arguments, or shell.

Package installation installs the executor, schema, document, disabled units, restricted group, and empty state parent but creates no route block or journal, starts no socket, selects no route, loads no module, and performs no reboot or output activity. WsprryPi retains application policy, scheduling, operator confirmation, topology ownership, enrollment, and qualification. The route manager does not expose event submission or carrier execution.

An explicit source-development binding may replace only the service
`ExecStart` through a recorded `/etc/systemd/system` drop-in. It binds the
clean userspace source commit and executable hash separately from the enrolled
module source commit and development-manifest hash. In this mode the executor
accepts `query` only and uses the authenticated `Experimental` module/UAPI/route
binding instead of the unrelated installed-package version gate. All malformed,
pending, ambiguous, or mismatched route state still fails closed. Packaged
preflight, reconciliation, and mutation identity rules are unchanged.

Source-development boot ownership is current only through an explicit
current-boot adoption record. The root-owned record
binds one boot ID and configuration digest to exact configured and active route,
userspace commit and executable, module source manifest, kernel, UAPI, and
compatibility identity. It is not inferred from completed journals. Missing,
stale, altered, pending, or disagreeing state fails closed. Adoption changes no
boot file, overlay, endpoint, module, output gate, GPIO, clock, or DMA state and
does not authorize execution.
