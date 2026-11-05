// SPDX-License-Identifier: MIT
#include <type_traits>
#include "linux/rp1_gpclk.h"
#include "linux/rp1_route_admin.h"

// Both independently versioned interfaces must remain usable by C++ consumers.
static_assert(std::is_standard_layout_v<rp1_gpclk_submit_events>);
static_assert(std::is_standard_layout_v<rp1_route_admin>);
static_assert(sizeof(rp1_gpclk_submit_events) == 112);
static_assert(sizeof(rp1_route_admin) == 64);
static_assert(_IOC_SIZE(RP1_GPCLK_IOC_GET_SNAPSHOT) == sizeof(rp1_gpclk_snapshot));
static_assert(_IOC_SIZE(RP1_ROUTE_ADMIN) == sizeof(rp1_route_admin));
static_assert(RP1_GPCLK_IOC_QUERY != RP1_ROUTE_ADMIN);

int main() { return 0; }
