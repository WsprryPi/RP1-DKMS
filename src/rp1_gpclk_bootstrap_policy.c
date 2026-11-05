// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include "rp1_gpclk/bootstrap_policy.h"

enum rp1_gpclk_bootstrap_action rp1_gpclk_bootstrap_decide(
	unsigned int matching_nodes, bool selected_available,
	bool platform_device_present, bool bound_to_driver)
{
	if (!matching_nodes)
		return RP1_GPCLK_BOOTSTRAP_REJECT_NO_NODE;
	if (matching_nodes != 1U)
		return RP1_GPCLK_BOOTSTRAP_REJECT_AMBIGUOUS;
	if (!selected_available)
		return RP1_GPCLK_BOOTSTRAP_REJECT_DISABLED;
	if (!platform_device_present)
		return RP1_GPCLK_BOOTSTRAP_CREATE;
	if (!bound_to_driver)
		return RP1_GPCLK_BOOTSTRAP_REJECT_UNBOUND;
	return RP1_GPCLK_BOOTSTRAP_USE_EXISTING;
}
