<!-- SPDX-License-Identifier: MIT -->

# RP1-GPCLK-DKMS repository and work-harness cleanup

Copyright (c) 2026 Lee Bussy. Adapted from WsprryPico's repository and
work-harness cleanup guidance, distributed under the [MIT License](../../LICENSES/MIT.txt).

Reusable execution prompt for a request such as **“clean up RP1-GPCLK-DKMS”**,
**“clean up this repository”**, or **“clean up the project and its harnesses”**
when RP1-GPCLK-DKMS is the identified project. Read this entire prompt before
execution. Saving, linking or reviewing this prompt does not execute cleanup.
An explicit inventory-only request stops after the inventory.

## Objective and documentation standard

Cleanup retires obsolete project material and maintains clear documentation of
the current product while preserving useful source, tests, tools, settings and
recovery resources.

Maintain a concise description of the current product and a usable development
environment. Delete obsolete development material from the repository and its
project-specific Mac and Raspberry Pi work harnesses.

- Use direct, impersonal, present-tense prose for current behavior, interfaces,
  configuration, constraints, supported workflows and operating procedures.
- Remove first-person narration, vague promises, aspirational feature lists,
  development diaries, abandoned approaches, intermediate failures, completed
  handoffs, phase-by-phase storytelling and retrospective explanations whose
  only purpose is to describe how development reached the current state.
- Keep explanations of current design choices when they help maintainers use
  or change the implementation correctly. State the reason and current
  consequence without recreating the investigation.
- Clean development phase and step references through the same inventory,
  rewrite, reference-repair and validation process as other development
  narratives. This includes headings, prose, status labels, navigation and
  cross-references in ordinary documentation such as `README.md` and
  `SECURITY.md`. Preserve phase/step organization only in explicitly retained,
  currently used planning documents such as `ROADMAP.md` or an equivalent
  active plan; identify these
  exceptions in the inventory. Preserve current behavior, constraints and
  qualification limits in current-state wording. Actual operating instructions
  and technical uses of phase or step are not development chronology.
- Put selected future work only in a maintained backlog document or a real issue.
  [ROADMAP.md](../../ROADMAP.md) is the current work entry point; verify its
  successor if the repository has reorganized. This does not authorize a commit.
  Preserve selected requirements, priority and acceptance criteria. Do not invent issues,
  features, deadlines or commitments during cleanup, or publish issues without
  authorization. Remove unselected speculation. If selection is unclear,
  retain the affected text for a specific decision and continue elsewhere.
- Describe current limitations directly. Remove stale “next,” “pending,”
  “eventually,” “will support” and “under construction” statements. A real
  unsupported capability remains documented as unsupported; its removal from
  a development narrative does not make it implemented or qualified.
- Delete obsolete material directly. Do not create an archive, attic, dated
  historical tree, backup bundle or permanent cleanup report to hold it.
  Normal Git history supplies tracked-file history.

### Operator-facing prose and engineering content

Treat the README and other non-engineering material as explanations for an
operator. Lead with what the current product does, how it is used and any
limitation that changes an operating decision. Use familiar language and
present capabilities, not a report of development or acceptance activity.

The required level of product description is illustrated by:

> RP1-GPCLK-DKMS provides a Linux kernel module for bounded control of the
> Raspberry Pi RP1 GPCLK0 peripheral. DKMS builds it for the installed stock
> Raspberry Pi kernel; route selection and output require separate administration.

Verify current support before using any example as product copy. Preserve
necessary operating instructions and meaningful limitations in plain language;
removing a development narrative must not imply unqualified hardware, bands
or configurations are supported.

An operator should not need to interpret a paragraph about UAPI conformance,
host tests, DMA internals, experimental clock comparisons, kernel build matrices,
receiver hosts, GPSDO comparisons, benchmark victories or the sequence of
validation campaigns to discover those basic capabilities. This applies even
when every technical statement is accurate and there are no phase
numbers. Removing labels or shortening the same status report is insufficient;
rewrite its message for the reader.

Extract technical information still needed by maintainers into the appropriate
existing engineering contracts, implementation/build references or support
records. Keep it concise and current, with applicability and provenance where
needed. Do not mechanically relocate the whole paragraph, create another
history document or retain obsolete evidence merely to avoid deleting it.
Engineering material serves maintainers; it is not the operator manual.

Do not replace the paragraph with an engineering-documentation link or tell an
operator to consult development records to understand the product. The current
operator handbook lives in `docs/` and is published on Read the Docs; technical
contracts and maintainer procedures live in `engineering/`. Preserve useful
links to real operator procedures. Do not add an unavailable site link,
placeholder, "coming soon" statement or promise of later documentation.
The operator-facing description must stand on its own. Keep necessary maintainer
references in maintainer entry points. Cleanup does not execute separately
selected documentation projects or move application policy out of WsprryPi.

This standard applies throughout non-engineering text, including feature and
status paragraphs, headings, captions, navigation and security explanations.
Judge each passage by the operator action or decision it helps, not by whether
it contains a particular development keyword.

## Authority and scope

An explicit cleanup invocation authorizes inventory, documentation maintenance
and deletion of inspected, confidently classified obsolete RP1-GPCLK-DKMS artifacts
within the scope below. Produce and present the inventory before the first
cleanup mutation, then proceed through clear items without routine per-file
approval. An uncertain item stays on hold while independent work continues.

1. The identified RP1-GPCLK-DKMS checkout, including tracked, untracked and ignored
   files. The usual local checkout is `/Users/lbussy/GitHub/RP1-GPCLK-DKMS`; discover
   its actual root, branch, revision, worktree and working state at execution.
2. Local project-owned build trees, source snapshots, temporary directories,
   module/package copies, captures, logs, browser test profiles, staging areas and
   disposable test environments outside the checkout.
3. Equivalent RP1-GPCLK-DKMS work areas on Raspberry Pi harness hosts identified
   from current configuration, scripts, documentation and task context.
   Inventory hosts only where a concrete RP1-GPCLK-DKMS connection exists;
   do not import WsprryPico's host or path hints.
4. Clearly attributable RP1-GPCLK-DKMS run outputs inside a shared harness. This
   scope covers disposable project data; maintained sibling-repository source,
   shared tools and another project's data remain outside it.

Preserve existing user edits, unique source, Git metadata, branches, tags,
releases, installed applications and current operational state. Do not
initialize Git, reset, stash, stage, commit, push, publish, rewrite history,
prune worktrees or remove checkouts merely to make the working tree clean.
Separate staging/commit/push requests govern those actions. Do not run blanket
`git clean`, whole-home cleanup, system package/cache removal or recursive
wildcard deletion.

Keep module behavior, UAPIs, overlays, compatibility policy, RF settings and
device state unchanged. Cleanup alone does not authorize installing, loading,
binding, unbinding, unloading or replacing a module; applying or removing an
overlay; DKMS installation/removal; mutating sudo commands; changes to boot,
signing, udev, systemd or kernel configuration; GPIO, GPCLK, target DMA,
transmission, SDR or RF activity; rebooting or shutting down a Pi; flashing;
changing network profiles; stopping active work; or restarting services.
Even output-inhibited target administration requires explicit authorization
for the exact operation under [AGENTS.md](../../AGENTS.md). Respect any
separately authorized hardware task and its current setup limits, but do not
manufacture a hardware test to validate deletion of old evidence. Do not delete
installed module/package trees, active runtime journals or administrative state
as disposable harness output.

The maintained WsprryPico, WSPR-Transmitter, WsprryPi, WsprryPi-Docs,
WsprryPi-Qualification-Harness and GPSDO repositories are independent. Do not
edit their maintained files under this prompt. Keep application mode and
product policy outside this module. A disposable paired-source test snapshot
can be removed only after its role, lack of unique work and source availability
are verified; a name containing `pi` or `pico` establishes none of these facts.

## Stage 1: Read-only discovery and inventory

Complete this stage before deleting, renaming, rewriting or generating cleanup
replacements. A temporary inventory outside maintained source is permitted.
Do not install tools, download SDKs, start a build or alter a host to inventory it.

### Repository and dependency discovery

- Read applicable [AGENTS.md](../../AGENTS.md), [README.md](../../README.md),
  the [module contract](../contracts/rp1-gpclk-dkms-module-contract.md),
  [CONTRIBUTING.md](../../CONTRIBUTING.md), [Testing](../testing.md),
  the [current roadmap](../../ROADMAP.md), `.gitignore`, `Makefile`, `Kbuild`,
  DKMS and Debian inputs, dependency pins and relevant release metadata.
  Read the affected UAPI, runtime, lifecycle and release contracts as needed.
  Inspect the actual implementation where documentation disagrees. Historical
  result files do not override current code or selected requirements.
- Record branch, revision, upstream relationship and worktree identity with
  read-only Git commands. Inspect staged and unstaged diffs and list untracked
  and ignored artifacts. Capture the pre-existing dirty-path set. Do not fetch,
  pull or synchronize as an incidental cleanup step.
- Use `rg --files`, `rg` and bounded directory listings first. Include hidden
  generated files through an explicit ignored/untracked inventory; ordinary
  `rg --files` omits them. Exclude Git internals from content searches.
- Trace candidate references through Markdown links and anchors, JSON/YAML
  manifests, Kbuild/DKMS/Makefile inputs, scripts, tests, packaging, site inputs,
  diagrams/images and symlinks. Identify both the files a candidate uses and
  the files that use it. Classify dependency groups before removing members.
- Distinguish executable regression tests and necessary fixtures from tests
  that only assert the presence or historical wording of completed records.
  Inspect their assertions and build registration; a phase number alone is
  not a deletion reason.
- Classify documentation by audience and inspect mixed sections separately.
  Identify the operator capability or decision each retained passage explains.
  Record where useful technical content will be consolidated in engineering
  material before removing its operator-facing development narrative.

### Local and Raspberry Pi harness discovery

- Discover locations from scripts, launchers, build metadata, current records,
  configured host aliases and bounded parent-directory listings. Search only
  attributable locations; do not crawl all home directories or every SSH host.
- Resolve physical paths and mounts before acting. A local path may be an
  SSHFS view of remote storage, a symlink, a shared SDK or cloud-synchronized
  storage. Record one physical target once, including aliases. Do not follow
  symlinks into new deletion scope or assume `Documents` is local-only.
- On a named Raspberry Pi, use the configured SSH alias and normal host-key
  verification. Verify hostname, user, physical path and repository identity
  before classifying files. Do not replace aliases with guessed addresses,
  override host-key identity or disable host-key checking. Use bounded SSH
  connection/command timeouts. Report unreachable hosts and continue locally.
- Inspect active build, capture, browser and test processes and their working
  directories/output files without opening devices. Where needed, inspect
  relevant service/session status read-only. A file's age, a stale PID file or
  an apparently idle terminal alone does not prove it is unused. Do not stop
  processes, terminate sessions or change permissions to force cleanup.
- Inventory project-owned build outputs, KO/O/DTBO/DEB files, source
  snapshots, copied dependency trees, test scripts, receiver captures, packet
  captures, audio/IQ files, reports, logs, screenshots, browser profiles,
  backup images, tarballs and task staging directories. Include attributable
  `/tmp` and `/var/tmp` areas as well as project and home work directories.
- Identify active kernel header trees, toolchains, capture/decoder utilities,
  Python/Node environments and shared caches before classifying duplicates. Trace their
  callers and regeneration requirements. Retain functioning dependencies;
  remove stale task-only copies only when no retained workflow uses them.
- Inventory sensitive artifacts by path, role and protection requirements.
  Do not print passwords, private keys, tokens, certificates' private key
  material or configuration contents into the inventory. Protect live
  settings, trust stores, device identities, provisioning data and calibration.
- Identify any unfinished restoration, unresolved active investigation or
  current rollback need before deleting its sole backup or input. Keep that
  specific artifact on hold with a concrete reason. Historical instructions
  to retain every intermediate failure do not by themselves require permanent
  retention during this explicitly requested cleanup.

Discover local build/staging areas and project-specific Python caches from
current ignore rules, build registration and scripts. Discover remote paths
from attributable current workflows rather than copied campaign records.
Any historical host/path reference is a discovery hint, **never a deletion
allowlist**. Verify existence, ownership, contents, active dependencies and
mixed-project material at execution. Discover newer locations through the
same process.

### Required inventory output

Present a readable summary in the conversation and an exact, expanded action
list before cleanup starts. A large machine-readable list can live in a
private temporary file outside the repository, with its absolute path linked
in the conversation. Do not copy raw evidence into it. For each file or
inspected directory group, record:

| Field | Required information |
| --- | --- |
| Identity | Host, absolute path, resolved physical path and artifact role |
| State | Tracked/untracked/ignored/external; pre-existing edits or unique work |
| Extent | Type, file count and size; distinguish logical size from disk usage |
| Use | Current callers/references, active use and recovery dependency |
| Audience | Operator purpose or engineering use; destination for needed technical content |
| Action | `DELETE`, `REWRITE`, `RETAIN` or `HOLD` |
| Reason | Concrete obsolescence or current purpose; retention/migration prerequisite |
| Validation | Checks needed after this action and expected reference repairs |

Directory groups are acceptable only when their complete contents are
classified and no protected/unknown child is hidden by the grouping. Expand
the exact paths into the action list before mutation. Mixed directories
require separate decisions for their children. Include retention and hold
decisions as well as deletion candidates, host accessibility and total size
per host. If privilege limits prevent inspection, mark the item `HOLD`.

Make the inventory available before execution; it is a reviewable record, not
a mandatory approval gate. Ask only for a decision that is necessary to resolve
a specific ambiguity or an action outside the authorized scope. Continue safe,
independent cleanup while held items remain intact. Refresh the inventory
before acting if files, active jobs, ownership or dependencies change.

## Stage 2: Apply the classified cleanup

### Delete obsolete artifacts

- Delete completed, superseded and abandoned execution prompts and temporary
  handoffs after consolidating any useful current technical information. They
  are disposable execution instructions, not permanent engineering records.
  A link from a completed checklist item, old acceptance record or prompt index
  is a reference to repair, not a reason to retain an obsolete prompt. Remove
  its obsolete link or replace it with an appropriate current technical
  reference; do not create an archive, mirror or another history report.
- Retain handoffs still needed for selected unfinished work, including an
  execution currently in flight, and genuinely reusable instructions such as
  this cleanup guidance and its discovery links. Review their current purpose;
  an old date alone does not establish obsolescence. Retire the task-specific
  cleanup handoff when its execution is finished, repairing the checklist link
  while retaining this reusable guidance.
- Remove intermediate review reports, superseded plans, phase journals, old
  result matrices and raw test evidence whose useful current information has
  been consolidated. Preserve behavioral tests and necessary current fixtures;
  do not preserve obsolete execution prompts just to satisfy record-presence
  tests.
- Remove obsolete capture/analysis results, dated screenshots, stale local
  module/package candidates, duplicate local release copies, old KO/DTBO/DEB
  files, build intermediates, abandoned source snapshots, editor backups,
  temporary scripts and
  project-specific caches after satisfying their inventory prerequisites.
  Remove stale lock/PID files only after verifying that no active owner or
  retained recovery workflow needs them.
- Prefer deletion of regenerable output over keeping a dated binary collection.
  Preserve any currently required deployment/recovery package, module or image
  and the matching checksum, manifest and source identity until it is
  demonstrably replaceable. Published releases, tags and assets stay intact;
  retain the selected lifecycle predecessor and other active regression inputs.
  Neither modification time nor the highest-looking filename proves currency.
- Delete a backup when its restoration duty is finished and no unique settings
  or source depend on it. Retain only backups with an identified present duty.
- A reusable tool hidden in an obsolete run directory may be moved into an
  existing maintained location only when a current workflow actually needs it.
  Preserve licensing and exact provenance, update callers and verify behavior.
  Do not rescue every one-off script into `scripts/`.
- Remove obsolete record-presence tests and their registration only where the
  behavior they check is exclusively the retired history. Preserve behavioral
  coverage, conformance vectors, meaningful failure cases and current fixtures.
  Reduce bulky evidence-based fixtures to minimal deterministic equivalents
  only when equivalence can be checked. Do not weaken checks to hide regressions.

Use exact inspected paths and explicit argument boundaries. Recheck physical
target, host, ownership, content changes and active use immediately before
external/untracked/ignored deletion. Reject roots, home directories, repository
roots, mount roots and unresolved links as recursive deletion targets. Do not
delete an entire directory containing retained, dirty or unknown children.
Do not make another backup of material classified for deletion.

### Rewrite retained documentation

- Rewrite README and other operator-facing passages around current capabilities
  and actual use. Apply the operator standard above to the meaning and structure
  of the prose, including technically accurate status/validation catalogues.
  Consolidate needed implementation and measurement detail in engineering
  material; keep ordinary product descriptions readable without those records.
  Add no documentation placeholder, engineering-guide substitute or future
  documentation promise.
- Consolidate current behavior into appropriate maintained guides and
  contracts. Remove duplicate status paragraphs and completed milestone lists
  from `README.md`, module contracts and maintainer guides.
- Remove development phase/step framing outside the explicitly retained active
  planning documents. Review phase/step-named files and link targets with their
  dependencies before any rename or deletion; retaining a necessary contract
  or technical detail does not require retaining its development narrative.
- Replace historical acceptance stories with concise current support limits
  where those limits remain useful. Retain exact source, module, UAPI, kernel,
  board, firmware, route, clock and setup applicability when a retained
  physical or RF claim requires it. Preserve externally established RF
  applicability without importing WsprryPi mode or product policy. Test-evidence
  deletion must not broaden claims or erase known exclusions.
- Raw evidence is not automatically permanent merely because it once supported
  a result. Preserve the necessary current disposition and applicability; if
  the remaining material cannot substantiate a claim, narrow or remove that
  claim instead of presenting it as verified. Do not rerun RF tests to replace
  deleted historical evidence as part of cleanup.
- Keep enduring protocol/storage/security/ownership constraints, useful design
  rationale, current build instructions, dependency pins, API schemas,
  conformance vectors, package/version metadata, compatibility and qualification
  metadata, runtime/update/integrity manifests and necessary migration/rollback
  procedures. A version number or hash alone does not make a file obsolete.
  Machine-consumed identity, ownership, recovery and release data are current
  workflow inputs, not disposable evidence merely because they contain results.
- Preserve the per-file licensing matrix in [LICENSE.md](../../LICENSE.md):
  MIT for independent tools, tests and documentation; `GPL-2.0-only OR MIT`
  for original kernel-facing and device-tree source; and
  `(GPL-2.0-only WITH Linux-syscall-note) OR MIT` for canonical UAPI headers.
  Retain `MODULE_LICENSE("Dual MIT/GPL")`, third-party notices, attribution and
  required source provenance. Retain useful diagrams, instructional screenshots
  and sanitized examples; delete orphaned evidence-only assets after checking
  their callers.
- Reconcile references in prose, code, schemas, manifests, tests, build inputs
  and documentation navigation. Repair relative links and anchors. Remove
  stale references rather than adding “see Git history” placeholders everywhere.
- Keep the backlog's selected work intact. Consolidate duplicate proposals
  without changing their selection or priority. Do not turn cleanup into
  implementation of deferred features or a general architecture rewrite.
- Tighten ignore rules only for genuinely generated/private artifacts, keeping
  maintained examples visible. Ignoring a file does not delete it or remove a
  tracked copy; verify each separately.

Respect pre-existing edits. An overlapping required repair must preserve the
user's content; hold it if that cannot be established. Check the working state
again during long runs to avoid overwriting concurrent work.

## Stage 3: Validate and finish

Derive commands from the current development guide and actual build/test
registration. Use installed tools and existing dependencies. Select checks
according to affected behavior; documentation-only changes need link,
reference and formatting validation, not hardware acceptance.

1. Audit every removed/renamed path against all retained tracked and relevant
   untracked material, including JSON/YAML data and build/test inputs. Check
   local Markdown file/directory links and anchors, generated-site inputs,
   removed assets and script entry points. Do not equate `git diff --check`
   with link or untracked-file validation.
2. Review the final diff and newly created files for current-state prose,
   normative meaning, preservation of selected backlog work and user edits.
   Check development phase/step references throughout retained documentation,
   including `README.md` and `SECURITY.md`, against the explicit active-plan
   exceptions; preserve actual procedures and technical terminology.
   Read operator-facing passages as an operator: can the reader identify the
   product's capabilities and relevant operating limits without interpreting
   engineering milestones or following a chain of validation records? Confirm
   needed technical content has an engineering home, obsolete narrative is
   removed, and no documentation substitute, stub or promise was introduced.
   Run `git diff --check`; inspect untracked text separately. Confirm no
   credentials, local toolchain paths or generated modules/packages were added
   to source.
3. Run affected deterministic tests after inspecting their implementation and
   current registration. [Testing](../testing.md) documents `make check` and
   `make package-check`; choose narrower checks where appropriate. For
   documentation-only changes, run `python3 tests/check_doc_links.py`,
   `python3 tests/check_spdx.py` and `git diff --check`, and check changed
   anchors separately. Do not delete unrelated outputs by rebuilding over them.
4. Validate source/build-input or harness-tool changes on the supported host.
   Do not retry a known-broken local macOS C++ toolchain unless toolchain repair
   or a local build is explicitly requested. Use an identified supported Linux
   environment where needed. Module compilation uses explicitly identified
   representative kernel headers, for example
   `make KERNEL_BUILD=/path/to/kernel/build`; record kernel, configuration,
   compiler, architecture, module version, UAPI version/digest and result.
   Do not install headers, download dependencies or change a host incidentally.
   On a Pi, cap parallelism to available resources, normally leaving one core
   free. A module/header build is build compatibility only, at most
   `Compatible-unqualified`; it establishes no target, lifecycle, timing,
   coexistence, GPIO, transmission or RF qualification. Compilation does not
   authorize target binding or clock-disabled administration.
5. Check retained harness commands and environment entry points without opening
   devices or starting campaigns. Never assume a script's default is harmless;
   inspect it before even using `--help` or importing it. Use offline fixtures
   or safe checks appropriate to the changed tool.
6. Fix actionable findings and rerun affected checks. Do not add tests that
   merely assert deletion or restate documentation. A dedicated review pass
   must challenge mistaken deletion, dangling dependencies, lost coverage,
   broadened qualification claims, unreadable operator prose, retained
   development narratives, documentation placeholders/promises, scope drift
   and concealed user changes.
7. Recheck each reachable host: exact deletion targets are absent, retained
   files and tools exist, and active services/configuration/workloads were
   preserved. Remove disposable outputs created by validation after collecting
   results, while retaining the usable baseline build/dependency environment.
   Report logical bytes deleted separately from measured free-space change;
   shared blocks, open files and snapshots can make these differ.
8. Verify the prompt remains reachable from [AGENTS.md](../../AGENTS.md) and
   [CONTRIBUTING.md](../../CONTRIBUTING.md). Keep the memory breadcrumb's
   canonical path valid if this prompt moves; memory edits require an explicit
   user request.

Finish with a concise factual report containing the documentation changes,
deleted categories/counts/size by host, retained exceptions, affected check
results, inaccessible locations or held items and their concrete reasons, and
the actual branch/dirty/staged/commit/push state. Link the exact action
inventory while the user needs it; treat it as temporary execution output,
with no promised indefinite availability or permanent repo report. Remove
task-only scratch files when their purpose is finished.

Do not claim complete harness cleanup for an unreachable host or an uninspected
area. Report completed scope and remaining exceptions explicitly. Do not fill
the closeout with a development chronology, generic promises or speculative
next steps.
