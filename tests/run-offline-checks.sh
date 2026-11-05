#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
# Assertions and hardware-blocking stubs must not leave core files in the tree.
# Linux and macOS sh support this limit; POSIX specifies only ulimit -f.
# shellcheck disable=SC3045
ulimit -c 0


unset CDPATH
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/rp1-gpclk-offline.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

python3 "$repo_dir/tests/offline_checks.py"


if command -v shellcheck >/dev/null 2>&1; then
    shellcheck "$repo_dir/tests/run-offline-checks.sh" \
        "$repo_dir/scripts/rp1-gpclk-lifecycle.sh" \
        "$repo_dir/debian/rp1-gpclk-dkms.preinst" \
        "$repo_dir/debian/rp1-gpclk-dkms.postinst" \
        "$repo_dir/debian/rp1-gpclk-dkms.prerm"
    echo "shellcheck: PASS"
else
    if [ "${CI:-}" = true ]; then echo "shellcheck: required in CI" >&2; exit 1; fi
    echo "shellcheck: SKIP (not installed)"
fi

if [ "$(uname -s)" = Linux ]; then
    for client in development_tone_client.c development_fault_client.c; do
        ${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
            -DRP1_GPCLK_TEST_CLIENT_SOURCE=\"$client\" \
            -I"$repo_dir/include" -I"$repo_dir/include/uapi" \
            "$repo_dir/tests/development_client_tones.c" -lm \
            -o "$tmp_dir/client_tones"
        "$tmp_dir/client_tones"
    done
    ${CXX:-c++} -std=c++20 -Wall -Wextra -Werror -pedantic -pthread \
        -I"$repo_dir/tests/fixtures/sweep" \
        -I"$repo_dir/include" -I"$repo_dir/include/uapi" \
        "$repo_dir/tests/development_sweep_plan.cpp" -o "$tmp_dir/sweep_plan"
    python3 "$repo_dir/tests/check_development_sweep.py" "$tmp_dir/sweep_plan"
else
    echo "client tone planning: SKIP (requires Linux userspace headers)"
fi

${CC:-cc} -std=c11 -Wall -Wextra -Werror \
    -I"$repo_dir/tests/fixtures/linux" \
    -I"$repo_dir/include/uapi" "$repo_dir/tests/uapi_contract.c" \
    -o "$tmp_dir/uapi_contract"

${CXX:-c++} -std=c++17 -Wall -Wextra -Werror \
    -I"$repo_dir/tests/fixtures/linux" -I"$repo_dir/include/uapi" \
    "$repo_dir/tests/uapi_cpp.cpp" -o "$tmp_dir/uapi_cpp"
"$tmp_dir/uapi_cpp"
echo "C++ consumer/admin UAPI compile: PASS"
"$tmp_dir/uapi_contract"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -DRP1_GPCLK_HOST_TEST \
    -I"$repo_dir/tests/fixtures/linux" \
    -I"$repo_dir/include" -I"$repo_dir/include/uapi" \
    "$repo_dir/src/rp1_gpclk_core.c" "$repo_dir/tests/lifecycle_core.c" \
    -o "$tmp_dir/lifecycle_core"
"$tmp_dir/lifecycle_core"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -I"$repo_dir/tests/fixtures/linux" \
    -I"$repo_dir/include" -I"$repo_dir/include/uapi" \
    "$repo_dir/src/rp1_gpclk_resource_policy.c" "$repo_dir/tests/resource_policy.c" \
    -o "$tmp_dir/resource_policy"
"$tmp_dir/resource_policy"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -I"$repo_dir/tests/fixtures/linux" -I"$repo_dir/include" \
    "$repo_dir/src/rp1_gpclk_compatibility.c" \
    "$repo_dir/tests/compatibility_identity.c" \
    -o "$tmp_dir/compatibility_identity"
"$tmp_dir/compatibility_identity"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -DRP1_GPCLK_HOST_TEST \
    -I"$repo_dir/tests/fixtures/linux" \
    -I"$repo_dir/include" -I"$repo_dir/include/uapi" \
    "$repo_dir/src/rp1_gpclk_execution_policy.c" "$repo_dir/tests/execution_policy.c" \
    -o "$tmp_dir/execution_policy"
"$tmp_dir/execution_policy"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -DRP1_GPCLK_HOST_TEST \
    -I"$repo_dir/tests/fixtures/linux" -I"$repo_dir/include" \
    "$repo_dir/src/rp1_gpclk_clock_setup.c" "$repo_dir/tests/clock_setup.c" \
    -o "$tmp_dir/clock_setup"
"$tmp_dir/clock_setup"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -I"$repo_dir/tests/fixtures/linux" -I"$repo_dir/include" \
    "$repo_dir/src/rp1_gpclk_execution_machine.c" "$repo_dir/tests/execution_machine.c" \
    -o "$tmp_dir/execution_machine"
"$tmp_dir/execution_machine"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -DRP1_GPCLK_HOST_TEST \
    -I"$repo_dir/include" \
    "$repo_dir/src/rp1_gpclk_bootstrap_policy.c" \
    "$repo_dir/tests/bootstrap_policy.c" \
    -o "$tmp_dir/bootstrap_policy"
"$tmp_dir/bootstrap_policy"

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic \
    -I"$repo_dir/include" "$repo_dir/tests/dma_segments.c" -o "$tmp_dir/dma_segments"
"$tmp_dir/dma_segments"
echo "DMA segment alignment and byte conservation: PASS"

git -C "$repo_dir" diff --check
echo "whitespace: PASS"
