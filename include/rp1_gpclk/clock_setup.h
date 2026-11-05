/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_CLOCK_SETUP_H
#define RP1_GPCLK_CLOCK_SETUP_H

#include <linux/types.h>

struct rp1_gpclk_clock_setup_ops {
	int (*set_rate)(void *context, __u64 rate);
	__u64 (*parent_rate)(void *context);
	__u64 (*output_rate)(void *context);
	int (*select_parent)(void *context);
	bool (*parent_matches)(void *context);
};

int rp1_gpclk_clock_setup(const struct rp1_gpclk_clock_setup_ops *ops,
	void *context, __u64 divider_q16, __u64 required_parent_rate);

int rp1_gpclk_clock_restore(const struct rp1_gpclk_clock_setup_ops *ops,
	void *context, __u64 rate, __u64 parent_rate);

#endif
