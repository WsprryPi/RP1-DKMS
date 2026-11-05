// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/string.h>

#include "rp1_gpclk/resource_policy.h"

int rp1_gpclk_route_endpoint_validate(__u32 route, const char *name)
{
	if (!name)
		return -1;
	if (route == RP1_GPCLK_ROUTE_GPIO4 &&
	    !strcmp(name, RP1_GPCLK_GPIO4_ENDPOINT_NAME))
		return 0;
	if (route == RP1_GPCLK_ROUTE_GPIO20 &&
	    !strcmp(name, RP1_GPCLK_GPIO20_ENDPOINT_NAME))
		return 0;
	return -1;
}

int rp1_gpclk_route_pin_validate(__u32 route, __u32 pin)
{
	if (route == RP1_GPCLK_ROUTE_GPIO4 && pin == 4)
		return 0;
	if (route == RP1_GPCLK_ROUTE_GPIO20 && pin == 20)
		return 0;
	return -1;
}

int rp1_gpclk_derive_target(__u64 resource_start, __u64 resource_end,
			    __u64 offset, __u64 bytes, __u64 *target)
{
	__u64 address;
	__u64 last;

	if (!target || resource_end < resource_start || !bytes ||
	    resource_start > ~(__u64)0 - offset)
		return -1;
	address = resource_start + offset;
	if (address > ~(__u64)0 - (bytes - 1))
		return -1;
	last = address + bytes - 1;
	if (address < resource_start || last > resource_end ||
	    address % bytes)
		return -1;
	*target = address;
	return 0;
}
