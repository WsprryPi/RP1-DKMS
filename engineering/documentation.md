<!-- SPDX-License-Identifier: MIT -->

# Documentation maintenance

`docs/` is the published operator handbook. Keep current capabilities,
prerequisites, procedures, support limits and troubleshooting there. Technical
contracts, build and packaging procedures and developer workflows belong in
`engineering/`. Update repository references and package-source mappings when
moving a technical document; retained files can be current build inputs.

## Scaffold and provenance

The handbook uses the Sphinx/MyST/Read the Docs theme scaffold from
[WsprryPi-Docs](https://github.com/WsprryPi/WsprryPi-Docs). Its navigation groups,
typography, colors, logo, favicon, mobile navigation template and accessibility
script are reused or adapted for the provider handbook. The upstream MIT
notice is preserved in
[the static asset license](../docs/_static/LICENSE-WsprryPi-Docs.txt).
No application source is included. Original independent documentation and
build configuration use MIT; the module and canonical UAPI licensing remain
unchanged.
The adapted scaffold is based on
[revision c0a0ec5](https://github.com/WsprryPi/WsprryPi-Docs/tree/c0a0ec5dd8ea6d7cb49fd7fa3d417ee0640c5672).

## Build configuration

Sphinx uses MyST Markdown, task lists and the shared image-delivery extension.
The extension supplies intrinsic image dimensions, asynchronous decoding and
eager loading for the first local content image. Later local images load lazily.
Explicit author sizing/loading is preserved, and print output retains its
builder's sizing defaults. Its regression fixture exercises clean and incremental
builds, nested sources, external images, explicit sizing and print output.

The direct Sphinx/MyST/theme versions are pinned in `docs/requirements.txt`,
alongside the scaffold's Requests and Pygments minimum versions. The handbook
uses no Python API autodocumentation, code introspection, developer TODOs or
editor language server, so those optional scaffold dependencies are unnecessary.

Version labels identify `main`, `devel` or a local checkout; `latest` displays
as `main`. The release label adds the checked-out Git revision. Hosted builds
use `READTHEDOCS_GIT_COMMIT_HASH` for that revision and
`READTHEDOCS_GIT_IDENTIFIER` for the source branch/tag. Pull request source links
use the exact commit rather than treating the pull request number as a branch.
These identifiers follow the
[Read the Docs environment-variable reference](https://docs.readthedocs.com/platform/stable/reference/environment-variables.html).

## Build locally

Use Python 3.14 and a disposable environment outside the checkout:

```sh
python3.14 -m venv /tmp/rp1-docs-venv
/tmp/rp1-docs-venv/bin/python -m pip install -r docs/requirements.txt
make docs DOCS_PYTHON=/tmp/rp1-docs-venv/bin/python \
  DOCS_BUILDDIR=/tmp/rp1-docs-build
make docs-check DOCS_PYTHON=/tmp/rp1-docs-venv/bin/python \
  DOCS_BUILDDIR=/tmp/rp1-docs-build
```

Open `/tmp/rp1-docs-build/html/index.html` for a preview. Check navigation, local
anchors and the mobile menu. Generated files stay outside the checkout.
`docs-check` runs the documentation regressions, strict HTML, EPUB, LaTeX source,
HTML Help, manual-page and Texinfo builds, and repository link/license/whitespace
checks. The Linux documentation CI job uses the same target and Python version
as Read the Docs. A separate Windows job checks the documentation regressions,
batch entry point and failed-build exit status. The ordinary module offline suite
does not require Sphinx. `sphinx -b linkcheck` can additionally check public
external URLs; network failures require interpretation rather than a blind URL rewrite.

The scaffold's platform entry points are kept with engineering tools:

- [Makefile](documentation/Makefile): `make -C engineering/documentation help`
  lists the Sphinx builders. Set `SPHINXBUILD` to the chosen environment's
  `python -m sphinx` command and `BUILDDIR` to an external output directory.
- [makedocs.sh](documentation/makedocs.sh): builds HTML without changing file
  ownership or deploying to a web server. Set `DOCS_PYTHON` and `BUILDDIR` as
  needed; extra arguments are passed to Sphinx.
- [make.bat](documentation/make.bat): after activating a Python 3.14 environment
  with the documentation dependencies, run
  `engineering\documentation\make.bat html` on Windows. It defaults to
  `%TEMP%\rp1-gpclk-dkms-docs` and preserves the Sphinx exit status.

The Makefile and shell helper default to a `rp1-gpclk-dkms-docs` directory under
`TMPDIR` or `/tmp`. These tools build documentation only. PDF compilation uses
the Read the Docs environment or an explicitly provisioned local TeX toolchain.
HTML Help, manual-page and Texinfo outputs are optional local exports; Read the
Docs publishes HTML, PDF, EPUB and the offline HTML archive.

## External hosting

The root [.readthedocs.yaml](../.readthedocs.yaml) defines the build interface:
`docs/conf.py`, Python 3.14, documentation requirements, and HTML/PDF/EPUB exports.
Warnings fail the Sphinx build. This file does not configure or publish an
external project. The handbook is available from the [local source](../docs/index.md).

External hosting requires a separately authorized project connection, selected
GitHub App access, branch/version configuration, and trigger verification.
Do not repoint another product's project or imply it serves this repository.
Do not store integration tokens or webhook secrets in source. Review exact
commit identities and hosted navigation after any authorized publication.

## Engineering-document validation

Engineering Markdown is maintained in the repository, not in the Sphinx
operator handbook. `make docs-check` includes its relative-link and SPDX checks,
but does not render engineering pages or check their heading fragments and
external URLs. Review those separately, including command syntax against the
actual parser, current paths against package/runtime inventories, and recovery
preconditions against the implementation. A passing handbook build cannot
establish engineering-document completeness.

Keep normative contracts distinct from implementation limitations and proposed
work. Examples must identify privilege, system effects, input identity, expected
result and refusal/recovery behavior; alternative mutation commands must not
look like a batch script. Keep review results in the execution chat and generated
output outside the checkout. Technical-document changes that are staged into
packages also need the ordinary Linux candidate/package checks.
