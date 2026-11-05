/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_BOOTSTRAP_POLICY_H
#define RP1_GPCLK_BOOTSTRAP_POLICY_H

#ifdef RP1_GPCLK_HOST_TEST
#include <stdbool.h>
#else
#include <linux/types.h>
#endif

enum rp1_gpclk_bootstrap_action {
	RP1_GPCLK_BOOTSTRAP_REJECT_NO_NODE = -1,
	RP1_GPCLK_BOOTSTRAP_REJECT_AMBIGUOUS = -2,
	RP1_GPCLK_BOOTSTRAP_REJECT_DISABLED = -3,
	RP1_GPCLK_BOOTSTRAP_REJECT_UNBOUND = -4,
	RP1_GPCLK_BOOTSTRAP_CREATE = 1,
	RP1_GPCLK_BOOTSTRAP_USE_EXISTING = 2,
};

enum rp1_gpclk_bootstrap_action rp1_gpclk_bootstrap_decide(
	unsigned int matching_nodes, bool selected_available,
	bool platform_device_present, bool bound_to_driver);

#endif
