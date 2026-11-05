<!-- SPDX-License-Identifier: MIT -->

# Read provider status

Use WsprryPi's route controls for everyday status. Detailed facts are available
through the [installed command-line tools](command-line.md) or a support
bundle. The detailed RP1 fact panel may be hidden in the normal Setup view.

## Route-control messages

Start with the message beside **Transmit Pin** or in the route-status dialog.

| Message | What it means and what to do |
| --- | --- |
| **Route Unsaved** | The dropdown is a draft. Confirm **Switch route** or **Remove route** to apply it, or select the active GPIO again to discard it. |
| **Route plan ready** | Preflight passed; the route has not changed. Review the confirmation before proceeding. |
| **Route switch queued**, **Removing route**, **Restoring application** or **Reconnecting** | Completion is still pending. Keep transmission off and let status checks continue. |
| **Automatic checks paused** | The browser has no confirmed terminal result. Choose **Retry status**, or use the read-only client query if WsprryPi is unavailable. Do not repeat the route action. |
| **Route selected** | The requested GPIO is selected and application restoration completed. A previously running application is online and idle. This does not authorize transmission. |
| **Route removed** | Neutral state is confirmed and a previously running application is back online and idle. No output GPIO is selected. |
| **Route removed; service stopped** | The route is neutral; the application was already stopped or administrator-masked and stays that way. |
| **Application restoration failed** | Route selection completed but application restoration did not. Review the error, then use the [restoration procedure](maintenance.md#when-service-restoration-fails). |
| **Route removed; service unavailable** | Normal removal reached neutral, but application restoration failed. Correct its reported cause, then retry removal for the original GPIO. |
| **Route not switched** | Preflight refused the change before it began. Read the reason; do not assume a route was applied. |
| **Recovery required**, **Mismatch** or **Unavailable** | Preserve the complete message and [investigate](troubleshooting.md). These are not instructions to force-load a module or delete a record. |

**Active** in detailed facts names the provider's reported GPIO. The managed
runtime's successful operator message is **Route selected**. An older
boot-configured profile can use different messages, including **Reboot required**;
identify that installation before following a runtime switching procedure.

## Route facts

| Fact | Meaning |
| --- | --- |
| Requested | The route in the current draft or transaction request |
| Persisted | The RP1 route saved in WsprryPi configuration |
| Configured | The route reported by managed administration |
| Active | The route reported by the loaded provider |
| Eligible | Current application checks admit the requested operation |

WsprryPi blocks transmission when required route facts disagree or readiness
cannot be proved. A retained GPIO setting for another backend is not RP1 route
consent. `eligible=false` in an observational response does not by itself mean
a band is unavailable; no specific application plan may have been evaluated.

## Runtime provider results

`runtime_provider.py inspect` uses the following result and process exit codes.
Nonzero codes can describe an expected incomplete installation, not just a
failed command. Inspect an idle system for an idle-readiness decision; a busy
operation can make that decision fail even while it is legitimately running.

| Result | Exit | What to do |
| --- | ---: | --- |
| `neutral_ready` | 0 | Administration is ready with no consumer route. Select a route when needed. |
| `exact_ready` | 0 | The exact owned runtime has one aligned route and verified idle state. Use WsprryPi for operation checks. |
| `absent` | 10 | No runtime installation is present. Use the WsprryPi installer if RP1 is intended. |
| `deployment_required` | 11 | Filesystem deployment is incomplete. Review the installer result. |
| `recovery_required` | 12 | A transaction or restoration record needs its owning recovery operation. Preserve records. |
| `conflict` | 13 | Identity, ownership or state is unsafe, mixed or contradictory. Stop and investigate. |
| `activation_required` | 14 | Files are deployed but managed neutral activation remains. Use the owning installer/startup workflow. |

These describe an idle readiness inspection. A running operation may have an
owner and open endpoint; collect status in context and do not attempt recovery
merely because an idle-readiness check cannot admit active state.

For example, this **illustrative excerpt** describes a healthy neutral
installation, not a failed transmitter:

```json
{
  "result": "neutral_ready",
  "administrationEligible": true,
  "routeSelected": false,
  "executionReady": false
}
```

The full response includes more fields. Read `result`, `conflicts` and
`remediation` together with the last transaction and service status. The
provider's `eligible` and `executionReady` fields describe runtime readiness;
they do not evaluate an application's particular band/mode plan or prove RF
output. A retained journal can describe a completed transaction; its presence
alone does not mean recovery is required.

## Compatibility, qualification and output

**Structural compatibility** describes the provider's recognized resources.
`Compatible-unqualified` does not erase separately established application
qualification. `Experimental` identifies development scope; it is not a
release or RF approval. `Unavailable`, `Rejected` or an unknown state requires
the accompanying reason before further operation.

**Qualification evidence** describes a particular software, route and test
scope. Development compatibility defaults to `Unavailable` without invented
qualified entries. WsprryPi's independently bound evidence does not qualify new
source. Evidence ships
with the application and needs no separate download or cache refresh. Missing
or corrupt installed evidence is an installation-integrity problem and must
not be converted into an invented application band restriction.

If the route is selected but WsprryPi still refuses an operation, keep the
refusal message. Check the application band/mode guidance and any required
bounded-operation confirmation. Do not switch routes or change the module's
inhibition setting simply to clear an eligibility message.

**Operational readiness** describes current resources, ownership, cleanup and
inhibition. The production module's `output_inhibit=0` means submissions can
be considered through the root-only endpoint; it does not mean that output is
currently active. `output_inhibit=1` is an immutable load-time development gate
that rejects submission. Do not change it as a troubleshooting shortcut.

Passive observations can be **true**, **false** or **unknown**. Unknown is never
converted into safe. Lease or owner presence, a cleanup fault or a pending
transaction must be resolved through its owning workflow.
