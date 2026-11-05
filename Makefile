# SPDX-License-Identifier: MIT

.PHONY: all modules check development-check development-frequency-sweep-client package-check clean docs docs-check

DOCS_PYTHON ?= python3
DOCS_BUILDDIR ?= $(if $(TMPDIR),$(TMPDIR),/tmp)/rp1-gpclk-dkms-docs

all: modules

modules:
	@test -n "$(KERNEL_BUILD)" || { echo "KERNEL_BUILD=/path/to/kernel/build is required"; exit 2; }
	$(if $(filter 1,$(RP1_RUNTIME_CONTROLLER)),python3 scripts/build_runtime_controller.py,@true)
	$(MAKE) -C $(KERNEL_BUILD) M=$(CURDIR) modules

check:
	./tests/run-offline-checks.sh

development-check:
	python3 tests/check_development_workflow.py

development-frequency-sweep-client:
	mkdir -p build
	$(CXX) -std=c++20 -O2 -Wall -Wextra -Werror -pthread -Iinclude -Iinclude/uapi \
		tests/development_frequency_sweep.cpp -lSoapySDR \
		-o build/development-frequency-sweep

package-check:
	python3 tests/check_debian_packaging.py
	python3 tests/check_package_lifecycle.py

docs:
	$(MAKE) -C engineering/documentation html SPHINXBUILD="$(DOCS_PYTHON) -m sphinx" BUILDDIR="$(DOCS_BUILDDIR)"

docs-check:
	$(DOCS_PYTHON) tests/nonempty_unittest.py
	$(MAKE) -C engineering/documentation html epub latex htmlhelp man texinfo SPHINXBUILD="$(DOCS_PYTHON) -m sphinx" BUILDDIR="$(DOCS_BUILDDIR)" SPHINXOPTS="-n -W --keep-going"
	$(DOCS_PYTHON) tests/check_doc_links.py
	$(DOCS_PYTHON) tests/check_spdx.py
	git diff --check

clean:
	@test -n "$(KERNEL_BUILD)" || { echo "KERNEL_BUILD=/path/to/kernel/build is required"; exit 2; }
	$(MAKE) -C $(KERNEL_BUILD) M=$(CURDIR) clean
