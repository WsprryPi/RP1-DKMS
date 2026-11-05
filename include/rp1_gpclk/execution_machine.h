/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_EXECUTION_MACHINE_H
#define RP1_GPCLK_EXECUTION_MACHINE_H

#include <linux/types.h>

struct rp1_gpclk_execution_ops {
	int (*set_rate)(void *context);
	int (*prepare)(void *context);
	int (*select_active)(void *context);
	int (*readback)(void *context);
	int (*stop_tick)(void *context);
	int (*terminate_dma)(void *context);
	int (*disable_clock)(void *context);
	int (*unprepare_clock)(void *context);
	int (*select_safe)(void *context);
	int (*restore_parent)(void *context);
	int (*restore_rate)(void *context);
};

int rp1_gpclk_execution_machine_start(
	const struct rp1_gpclk_execution_ops *ops, void *context);
int rp1_gpclk_execution_machine_activate(
	const struct rp1_gpclk_execution_ops *ops, void *context);
int rp1_gpclk_execution_machine_finish(
	const struct rp1_gpclk_execution_ops *ops, void *context,
	bool require_readback);

#endif /* RP1_GPCLK_EXECUTION_MACHINE_H */
