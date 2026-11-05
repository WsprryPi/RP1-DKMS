// SPDX-License-Identifier: MIT
#include <stdio.h>
#include <string.h>

#include "rp1_gpclk/compatibility.h"
#include "rp1_gpclk/core.h"

#define CHECK(value) do { if (!(value)) return __LINE__; } while (0)

int main(void)
{
	const char *version = RP1_GPCLK_COMPATIBILITY_VERSION;
	CHECK(rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_COMPATIBILITY_ARCH, version, true));
	CHECK(rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO20,
		RP1_GPCLK_COMPATIBILITY_ARCH, version, true));
	CHECK(!strcmp(rp1_gpclk_compatibility_id(RP1_GPCLK_ROUTE_GPIO4),
		RP1_GPCLK_GPIO4_COMPATIBILITY_ID));
	CHECK(!strcmp(rp1_gpclk_compatibility_id(RP1_GPCLK_ROUTE_GPIO20),
		RP1_GPCLK_GPIO20_COMPATIBILITY_ID));
	CHECK(strcmp(rp1_gpclk_compatibility_id(RP1_GPCLK_ROUTE_GPIO4),
		rp1_gpclk_compatibility_id(RP1_GPCLK_ROUTE_GPIO20)));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_COMPATIBILITY_ARCH, "1.1.1", true));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_COMPATIBILITY_ARCH, version, false));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		"armv7l", version, true));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		NULL, version, true));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_COMPATIBILITY_ARCH, NULL, true));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_COMPATIBILITY_ARCH, version, false));
	CHECK(!rp1_gpclk_compatibility_allowed(RP1_GPCLK_ROUTE_INVALID,
		RP1_GPCLK_COMPATIBILITY_ARCH, version, true));
	puts("compatibility identity: PASS (structural GPIO4/GPIO20 identities)");
	return 0;
}
