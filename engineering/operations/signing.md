<!-- SPDX-License-Identifier: MIT -->

# Module signing and key enrollment

Signing is provenance and possible kernel-load evidence. It is not hardware
compatibility, root-endpoint authority, cleanup, timing, or RF evidence. Never
disable signature enforcement or select another physical backend after failure.

## Choose and protect the local identity

This release contains no shared private signing key and never generates one as
an install side effect. The root administrator selects an existing local module-
signing identity or uses the installed distribution/DKMS procedure to generate
one. Keep it outside source, release, evidence, and package-owned directories.
A filesystem private key must be a nonsymlink root-owned `0600` regular file;
the public certificate must be a nonsymlink root-owned regular file no broader
than `0644`. Record the certificate SHA-256 fingerprint, subject, validity, and
code-signing extended-key-usage result when the kernel requires that EKU. Never
record private bytes, a passphrase, PIN, or token secret.

Configure DKMS's native module signing with exact administrator-selected
`mok_signing_key`, `mok_certificate`, and target-kernel `sign_file` paths in the
site's DKMS framework configuration. Supported DKMS releases sign every build,
including autoinstall builds after kernel updates. Verify the installed DKMS
version and configuration first. If a configured file is absent, stop: DKMS may
generate replacement material, which is a different, unenrolled identity.

## Enroll and verify trust

First determine the actual kernel policy. Keep these cases distinct:

- no enforcement: an exact-kernel unsigned module may pass signing policy, but
  remains non-live until every independent compatibility gate passes;
- locally signed modules accepted, or enforcement active with a previously
  enrolled local key: require a valid signature from the exact trusted
  certificate fingerprint;
- key/certificate missing, expired, replaced, revoked, or untrusted; signature
  corrupt; or signed module built for the wrong kernel: the module is
  unavailable.

Enrollment imports only the intended public certificate using the distribution's
documented MOK or firmware workflow. Password entry, firmware confirmation,
reboot, and post-reboot trust verification are separate administrator actions;
the package never performs them automatically.

After every build and after installation, verify the exact module file's
SHA-256, release version, target-kernel vermagic, signer, signature key ID,
signature and hash algorithms, certificate fingerprint, certificate validity,
and kernel trust result. A nonempty `modinfo signer` value alone is insufficient.
Manual target-kernel `scripts/sign-file` is an explicit recovery operation only;
repeat the complete verification afterward.

## Rotate and remove safely

Rotate with overlap: select and validate the successor; enroll and verify its
public certificate; configure DKMS to use it; rebuild, sign, and verify modules
for every retained kernel; audit dependencies on the prior identity; then retire
the old identity only when unused. An interruption leaves operational readiness
disabled.

Uninstall removes package-owned policy and records only. It intentionally
retains administrator-owned private keys, certificates, MOK/firmware trust
entries, hardware tokens, and DKMS-global configuration, and reports that
retention. Removing trust is a separate administrator action after auditing all
local modules. A key used to sign another local module must not be deleted.
A key shared with another module is therefore intentionally retained.

## Candidate package guard

The current package reads static DKMS framework configuration before native DKMS
effects. It refuses automatic module loading, post-transaction hooks, dynamic
configuration and module-specific overrides. For installed signing-capable effective DKMS configurations
(`include/config/auto.conf`, with `.config` fallback) it requires an existing secure filesystem key and public
certificate before DKMS can generate a replacement. PKCS#11/dynamic signing
setups require a separately reviewed guard extension; they are not silently
interpreted. Native libkmod compression support is also a prerequisite; for example a
`-ZLIB` build cannot validate gzip modules. Unsupported formats are refused
before package effects. Required installed signatures are verified against the exact selected public
certificate, including its validity period. A native DKMS warning after sign-file
failure cannot silently accept an unsigned result. Cryptographic verification
does not establish running-kernel trust, code-signing EKU policy or load eligibility.
No source or Debian candidate contains a compiled or signed module.
See [package prerequisites](debian-packaging.md) and
[candidate provenance](release-candidate.md).

## Offline policy evaluation

`scripts/signing_policy.py` evaluates an explicitly supplied observation record;
it does not discover kernel enforcement, enroll a certificate or cryptographically
verify a module itself. Its exact input fields are defined by `evaluate()` and
the maintained [policy metadata](../../release/signing-policy-v1.json).

```sh
python3 scripts/signing_policy.py /absolute/reviewed-signing-snapshot.json
```

A valid input can exit successfully while returning `signaturePolicyAccepted:
false` and state `Unavailable`. Inspect those fields and the reason; process
success is not signing acceptance. Even an accepted policy returns
`operationalReady: false`, because resource, route, ownership and cleanup checks
are independent. Keep the actual trust/enforcement observations with the
administrator's separately authorized verification, not inferred from a signer
string or this evaluator's JSON.
