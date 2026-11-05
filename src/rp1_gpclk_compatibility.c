// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/string.h>

#include "rp1_gpclk/compatibility.h"
#include "rp1_gpclk/core.h"

bool rp1_gpclk_compatibility_allowed(__u32 route,
				     const char *architecture,
				     const char *module_version,
				     bool resources_validated)
{
	if (!architecture || !module_version || !resources_validated)
		return false;
	if (strcmp(architecture, RP1_GPCLK_COMPATIBILITY_ARCH) ||
	    strcmp(module_version, RP1_GPCLK_COMPATIBILITY_VERSION))
		return false;

	/*
	 * Eligibility follows the resources validated from device tree and exported
	 * kernel APIs. It intentionally does not identify a Raspberry Pi product
	 * model or turn a kernel release string into an authorization policy.
	 * GPIO4 and GPIO20 remain independent administrative routes.
	 */
	switch (route) {
	case RP1_GPCLK_ROUTE_GPIO4:
	case RP1_GPCLK_ROUTE_GPIO20:
		return true;
	default:
		return false;
	}
}

const char *rp1_gpclk_compatibility_id(__u32 route)
{
	switch (route) {
	case RP1_GPCLK_ROUTE_GPIO4:
		return RP1_GPCLK_GPIO4_COMPATIBILITY_ID;
	case RP1_GPCLK_ROUTE_GPIO20:
		return RP1_GPCLK_GPIO20_COMPATIBILITY_ID;
	default:
		return "v0.99.0-invalid-route";
	}
}
