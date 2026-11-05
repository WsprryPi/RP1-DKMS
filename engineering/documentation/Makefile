# SPDX-License-Identifier: MIT
# Adapted from WsprryPi-Docs; copyright 2024 Lee Bussy.

SPHINXBUILD ?= python3 -m sphinx
SPHINXOPTS ?=
SOURCEDIR = ../../docs
BUILDDIR ?= $(if $(TMPDIR),$(TMPDIR),/tmp)/rp1-gpclk-dkms-docs

.PHONY: help Makefile

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
