#!/bin/sh
# SPDX-License-Identifier: MIT
# Adapted from WsprryPi-Docs; copyright 2024 Lee Bussy.
set -eu

doc_source=$(CDPATH= cd -- "$(dirname -- "$0")/../../docs" && pwd)
output=${BUILDDIR:-${TMPDIR:-/tmp}/rp1-gpclk-dkms-docs}
python_bin=${DOCS_PYTHON:-python3}

"$python_bin" -m sphinx -M html "$doc_source" "$output" "$@"
