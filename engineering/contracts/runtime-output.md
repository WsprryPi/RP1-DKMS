<!-- SPDX-License-Identifier: MIT -->

# Runtime route reconciliation for application output

The runtime manager completes application restoration as specified in
[Runtime application restoration](runtime-application-restoration.md). A
successful route switch restores a previously running application in idle mode;
`restore --execute` retries application completion after a successful route
transaction.

The controller continues to own its overlay and exclude removal while the
consumer is attached. Production loads the consumer with its default
`output_inhibit=0`. This makes the root-owned mode-`0600` consumer endpoint the
execution authority; it does not start output. Clock-disabled development and
lifecycle workflows instead load with `output_inhibit=1`.

In neutral administration only the controller is loaded. There is no overlay,
consumer endpoint, owner, lease, clock, GPIO, or DMA execution state.
`neutral_ready` means administration is available for a later explicit route
plan, not that a consumer or transmission is qualified.

The runtime manager supports `idle` and `reconcile-output` for an explicit
`gpio4` or `gpio20` route. Both are observational and return
`productionAuthority=root-owned-endpoint`. They require the current
boot/session/binding, a completed route journal agreeing with controller
readback, and a passive consumer snapshot reporting the selected route,
`outputInhibited=false`, `operationalReady=true`, no owner or lease, no cleanup
fault, and stable GPIO/clock/DMA quiescence. The response always includes the
strict boolean `executionAuthorized`, derived from the same coherent snapshot:
matching present owner and lease observations report `true`, while matching
absent observations report `false` only for verified idle or terminal lifecycle
state. Missing, unknown, malformed, contradictory, stale, or identity-mismatched
evidence fails closed. An active authorization is reported with `ready=false`;
it is not mistaken for idle readiness.
The result is evidence that a root client may proceed to ordinary UAPI
acquisition; reconciliation is not a transmission or RF qualification.

A matching WsprryPi integration uses `idle` during startup without clearing its
application inhibit. Its adapter translates product modes, schedules, and
operator decisions into generic finite events after reconciliation, then relies
on the canonical lease, cancellation, cleanup, and terminal-state contract. The
kernel does not receive an authorization digest or product-mode identifier.

The companion is compatible only when its copied UAPI header digest exactly
matches `uapi-identity.json`. It must use `SUBMIT_EVENTS` for WSPR, keyed modes,
and finite carriers; require `outputInhibited=false` and
`operationalReady=true` before acquisition; and surface the provider's terminal
reason without replacing it with a generic failure. An application feature that
has no operator-supplied end time, such as a continuous carrier, still chooses
an explicit finite request duration. If it uses successor requests, the
application checks its stop condition before each successor and never treats one
completed request as permission to start another.

`resume gpio4|gpio20 --execute` verifies the idle route and releases owned
application inhibition without starting the service or submitting output. It is
not the application-restoration handshake. Normal switching performs that
handshake; use `restore --execute` if completion fails. Open consumer files
block unload, removal errors remain visible, and no prior transmission resumes
automatically.

## Coherent update procedure

Use the [runtime deployment workflow](../operations/runtime-manager-workflow.md)
with one complete binding and matching WsprryPi companion. Keep the module,
manager, UAPI, overlays, and application identities coherent. Failed deployment
uses the existing deployment recovery path; failed route effects retain their
ID and error for explicit recovery. Compilation or idle reconciliation is not
output evidence.

After a clean reboot, use the public facade's digest-bound
`activation-plan`/`activation-ensure` workflow. Exact terminal prior-boot evidence
and inactive current-boot state permit a new neutral controller session;
WsprryPi separately restores only its explicitly persisted route in idle mode.
Do not manually load the controller or run route recovery as ordinary reboot
reconciliation. Incomplete, faulted or foreign state needs its owning recovery
operation or investigation. Explicit route recovery remains distinct: it ends
neutral with application inhibition retained. See the
[reboot and deployment workflow](../operations/runtime-manager-workflow.md).
