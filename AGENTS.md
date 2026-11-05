<!-- SPDX-License-Identifier: MIT -->

# RP1-GPCLK-DKMS repository instructions

These instructions apply to the entire project unless a more specific nested
`AGENTS.md` overrides them.

## Scope and authority

- Inspect the current files and applicable contracts before acting. Once Git is
  initialized, also inspect the branch, working tree, remotes, and relevant
  history before making changes.
- Preserve all existing work. Do not discard, reset, clean, stash, overwrite,
  stage, commit, amend, rebase, push, publish, or create a pull request unless
  explicitly authorized.
- Keep work within the requested phase. Do not silently advance from offline
  design or compilation into installation, binding, GPIO, transmission, or RF
  activity.
- Distinguish implemented behavior, planned behavior, non-goals, unresolved
  decisions, and validation still required.
- Prefer the smallest maintainable change that satisfies the current contract.

## Repository and work-harness cleanup

- Cleanup retires obsolete project material and maintains clear documentation
  of the current product while preserving useful source, tests, tools, settings
  and recovery resources.
- For an explicit request to clean up RP1-GPCLK-DKMS or this project/repository,
  follow [the reusable cleanup prompt](engineering/development/repository-cleanup-prompt.md).
- Inventory deletion, rewrite, retention and hold decisions before cleanup
  changes. Cover project artifacts in the checkout, local work areas and
  identified Raspberry Pi harnesses; preserve user work and shared tools.
- Documentation describes the current product in direct, impersonal language.
  Selected future work belongs in the maintained roadmap or an issue.
  Remove obsolete evidence and development narratives without creating an archive.
- Operator-facing prose, especially README.md, explains current capabilities
  and use in plain language. Replace engineering status and validation narratives
  with capability descriptions; retain needed technical detail in engineering
  documentation. Do not substitute engineering links for operator explanations,
  add documentation placeholders or promise future documentation.
- Delete completed, superseded and abandoned execution prompts and temporary
  handoffs after consolidating any needed technical content. Repair their
  references; do not archive them or retain them solely because a completed
  checklist item links to them. Keep only handoffs needed for selected unfinished
  work and genuinely reusable instructions.
- Apply the same inventory, rewrite, reference-repair and validation process to
  development phase and step references, including those in README.md and
  SECURITY.md. Preserve phase/step organization only in explicitly retained,
  currently used planning documents such as ROADMAP.md or an equivalent active
  plan. Preserve actual operating instructions and technical uses of phase or step.
- Preserve useful source, behavioral tests and fixtures, tools, live settings,
  shared dependencies, recovery resources and consumed compatibility, release,
  runtime and integrity metadata. Keep the licensing and hardware boundaries below.
- Reading or maintaining the prompt alone does not invoke cleanup.

## Authoritative contracts and project boundary

- Read `engineering/contracts/rp1-gpclk-dkms-module-contract.md` before architecture,
  implementation, packaging, compatibility, installation, or target work.
- This repository owns the RP1 kernel module, canonical UAPI, device-tree
  overlays, DKMS packaging, compatibility metadata, module lifecycle tooling,
  and module-specific tests and releases.
- `WsprryPi/WSPR-Transmitter` owns its userspace adapter and translation into
  the UAPI. `WsprryPi/WsprryPi` owns application policy, configuration,
  scheduling, installer orchestration, operator workflow, and product
  qualification.
- Do not vendor WsprryPi application source here. Do not copy this complete
  module source tree into WsprryPi.
- Coordinate repositories only through tagged artifacts, the canonical UAPI,
  compatibility manifests, and explicit cross-repository validation.

## Licensing

- Follow `LICENSE.md` and preserve SPDX identifiers in every source file.
- Original kernel-module source should use:
  `GPL-2.0-only OR MIT`.
- The loadable module must use `MODULE_LICENSE("Dual MIT/GPL")` unless a later
  reviewed licensing decision changes the source license consistently.
- Original project tooling, tests, and documentation should use MIT where they
  are independent of GPL-only kernel material.
- Canonical userspace-visible UAPI headers should use:
  `(GPL-2.0-only WITH Linux-syscall-note) OR MIT`.
- Imported or adapted material retains its license and provenance. Review
  compatibility before copying code; do not remove upstream notices.
- Do not claim that an SPDX tag or `MODULE_LICENSE()` resolves whether adapted
  code is derivative. Escalate uncertain provenance or licensing questions.

## Kernel and hardware safety

Unless the user explicitly authorizes the exact operation, do not:

- install, load, bind, unbind, unload, or replace a kernel module;
- apply or remove a device-tree overlay;
- run DKMS installation or removal;
- use `sudo` for a mutating action;
- change boot, module-signing, udev, systemd, or kernel configuration;
- change GPIO state, enable GPCLK, submit target DMA, key a transmitter, or
  produce RF output;
- reboot or shut down a Raspberry Pi; or
- run a test whose implementation has not first been inspected for hardware or
  system effects.

Compilation, static analysis, host-side unit tests, and clock-disabled target
tests are separate evidence classes. Target binding and even clock-disabled
administration require explicit authorization. Never infer hardware, timing,
cleanup, coexistence, installation, or RF qualification from a successful
build.

## Architecture and safety invariants

- Target stock Raspberry Pi kernels; do not introduce a maintained custom
  kernel dependency.
- Fail closed for unknown hardware, kernel, device tree, signing policy,
  resource identity, route, capability, or cleanup state.
- Never fall back to `/dev/mem`, raw userspace MMIO, a custom kernel, or another
  physical transmitter backend.
- Treat the stock `clk-rp1` provider as authoritative for normal clock
  operations. Do not claim the DKMS consumer recreates the historical custom
  provider lease.
- Derive and validate resources from device tree and exported kernel APIs. Do
  not make fixed physical addresses or opportunistic internal symbols product
  contracts.
- Keep the UAPI bounded, additive, versioned, route-neutral, and fail-closed.
  Never expose arbitrary physical addresses, DMA channels, register writes, or
  unrestricted programs to userspace.
- Support only explicitly allowlisted routes. GPIO4 and GPIO20 are separate
  administrative routes with independent evidence and qualification.
- Use single-owner state, bounded finite work, generation identifiers, stale
  callback rejection, and explicit terminal reasons.
- Protect open-file, platform-device, DMA callback, unbind, overlay, and module
  lifetimes explicitly. Managed allocation alone is not sufficient.
- Cancellation uses no successor plus bounded drain unless later target
  evidence proves another safe contract.
- Release only resources acquired by this module and never restore another
  consumer's state from a stale snapshot.

## Development and validation

- Follow `.editorconfig`.
- Add deterministic tests with implementation changes. Keep ordinary tests
  offline, unprivileged, network-free, hardware-free, and safe to repeat.
- Build against explicitly identified representative kernel headers. Record
  the kernel, configuration, compiler, architecture, module version, UAPI
  version, and result.
- Treat a DKMS or header build as build compatibility only; it cannot promote a
  combination beyond `Compatible-unqualified`.
- Inspect test commands before running them. Report skipped checks and
  environment limitations honestly.
- Run whitespace checks and applicable documentation/link validation before
  handoff.
- At each phase exit, perform a separate adversarial assessment against the
  contract. Reinject every failed assertion and repeat affected work.

## Documentation and release discipline

- Keep durable architecture and lifecycle decisions in `engineering/`.
  Reserve `docs/` for the published operator handbook.
- Update the module contract when ownership, UAPI, compatibility, licensing,
  route, lifecycle, or distribution policy changes.
- Keep warnings precise: operator responsibility does not create technical
  isolation, and a clean run does not prove the absence of interference.
- Releases must be tagged, checksummed, reproducible from source, and accompanied
  by compatibility and provenance metadata. WsprryPi must never consume the
  moving default branch.
- A module release must precede a dependent WsprryPi release. Keep module and
  application commits, reviews, releases, and qualification claims separate.

## Completion reports

Lead with the outcome and include:

- files and behavior changed;
- checks run and exact results;
- hardware, system, GPIO, transmission, and RF work performed or explicitly
  not performed;
- licensing and documentation impact;
- unresolved validation and the next gated step; and
- Git state and whether anything was staged, committed, pushed, or published.

## Current-state documentation

Describe current capabilities, interfaces, prerequisites, limitations and operating
procedures. Keep durable technical contracts and necessary source provenance.
Do not add phase histories, completed handoff prompts, task completion reports,
recorded test output or qualification campaigns to the repository. Report task
results and validation in the execution chat. Do not create replacement archives.

Keep maintained tests and compact deterministic fixtures. Build, package, runtime,
update and integrity metadata must remain when consumed by current workflows.
Generated run artifacts belong outside the checkout; test output is temporary.
A passing test supports only the behavior it exercises and grants no target or
RF authorization. Keep WsprryPi mode and product policy outside this module.

## Release configuration

Use ordinary editable GitHub releases. Do not enable or require release
immutability, tag or asset locks, mandatory attestations, or equivalent permanent
publication restrictions. Checksums and exact source attribution remain required.
The first stable release requires an explicit user readiness decision.
