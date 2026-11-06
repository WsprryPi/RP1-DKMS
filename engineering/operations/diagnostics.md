<!-- SPDX-License-Identifier: MIT -->

# Read-only diagnostics

For current scoped qualification status use WsprryPi's maintained helper and
its locally installed evidence bundle, or the standalone
[report interpreter](qualification-metadata.md#diagnostics) with explicit inputs.
Structural compatibility, operational readiness, output inhibition, and scoped
qualification are independent observations. An aggregate compatibility summary
does not establish safe output state or qualify the current software. The local
evidence interpreter verifies exact source/build attribution without granting
execution authority.

The collector is `scripts/rp1-gpclk-diagnostics.py` in a reviewed source checkout;
the Debian package does not install a `rp1-gpclk-diagnostics` command. Run it on
the authorized system being observed, from that checkout:

```sh
python3 scripts/rp1-gpclk-diagnostics.py
```

Optionally pass `--release-directory RELEASE` to inventory a separately verified
release directory. This collector reports hashes and parses selected metadata;
it does not perform the independent release validator's complete source,
checksum, archive or publication verification. The tool
does not install, load, bind, apply an overlay, enroll, change GPIO, repair, or
remove anything.

For an exact-source installation, pass
`--development-manifest DEVELOPMENT_MANIFEST.json` instead. Diagnostics checks
the manifest's schema/classification/module markers and reports it as
`Experimental` and not release-qualified. It does not fully validate the
manifest schema, installed-artifact inventory or loaded source identity. A
release directory and development manifest are mutually
exclusive.

Endpoint discovery checks `/dev/rp1-gpclk`, the only canonical transmission
endpoint. No alternate endpoint spelling is supported. A missing endpoint is
reported as unavailable; diagnostics do not create a platform device or
attempt binding.

Diagnostics performs the canonical `QUERY` request and records the complete
advertised capability mask, module/build/compatibility identities, and
generic event limits and DMA chunk bounds. There is no legacy query fallback or version negotiation.

Diagnostics also performs one read-only `GET_SNAPSHOT` request on a separately
opened descriptor and closes that
descriptor in all outcomes. The request never acquires an execution owner or
lease and never exposes a lease token. It reports the route and compatibility
identity, owner/lease presence, operation and drain state, retained terminal
reason and generation, valid elapsed/remaining time, cleanup fault,
output-inhibition and operational-readiness observations, and tri-state
GPIO/clock/DMA quiescence.
`unknown` is preserved as unknown; it is never converted into a safe result.
The descriptor open itself is passive but still counts as endpoint access and
therefore requires separate target authorization before running diagnostics on
a target.

Active route discovery walks the live device tree for the exact
`rp1-gpclk-dkms-gpio4` and `rp1-gpclk-dkms-gpio20` endpoint names. It reports
zero, exactly one, or ambiguous active topology and separately checks whether
the sole endpoint name, endpoint route property, and module-reported route
agree. It records the size and SHA-256 of that node's compatible, register,
clock, DMA, and pinctrl properties without interpreting phandles through a
fixed path. These observations do not substitute for WsprryPi's requested and
persisted route or for the route manager's configured and reconciled state.

The diagnostic summary distinguishes healthy `Qualified`, healthy `Experimental`,
build-compatible but live-disabled, unavailable, rejected, and indeterminate
because required inspection lacked privileges. Run as an administrator only
when support needs fields reported as permission-denied; elevated inspection
still performs no repair.

Those categories are aggregate compatibility labels, not an output measurement
or independent qualification decision. In particular, an accepted development
manifest can produce an Experimental summary without proving route/boot
ownership. Use the runtime facade and its exact binding for managed readiness,
the local evidence interpreter for scoped evidence, and raw passive snapshots for
current lifecycle observations. The runtime inventory collector is a different
tool and never opens either RP1 endpoint.

The report limits commands to five seconds, each command stream to 8192 bytes,
ordinary files to 4096 bytes, build/kernel logs to 16384 bytes, eight build
logs, and 128 journal-recorded residue paths. Kernel messages are current-boot
entries matching only this module. It excludes private keys, passphrases,
tokens, unrelated logs, and unrestricted system data.

An incomplete transaction or cleanup fault is a stop condition, not a repair
request. Preserve the report and request a separately authorized recovery
operation. A clean report does not prove absence of competing or direct-MMIO
software and is not hardware, timing, cleanup, coexistence, transmission, or
RF qualification.
