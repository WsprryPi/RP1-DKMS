// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/errno.h>

#include "rp1_gpclk/execution_machine.h"

static void rp1_gpclk_first_error(int *first, int result)
{
	if (!*first && result)
		*first = result;
}

int rp1_gpclk_execution_machine_finish(
	const struct rp1_gpclk_execution_ops *ops, void *context,
	bool require_readback)
{
	int first = 0;

	if (!ops || !context)
		return -EINVAL;
	if (require_readback)
		rp1_gpclk_first_error(&first, ops->readback(context));
	rp1_gpclk_first_error(&first, ops->stop_tick(context));
	rp1_gpclk_first_error(&first, ops->terminate_dma(context));
	rp1_gpclk_first_error(&first, ops->disable_clock(context));
	rp1_gpclk_first_error(&first, ops->unprepare_clock(context));
	rp1_gpclk_first_error(&first, ops->select_safe(context));
	rp1_gpclk_first_error(&first, ops->restore_parent(context));
	rp1_gpclk_first_error(&first, ops->restore_rate(context));
	return first;
}

int rp1_gpclk_execution_machine_start(
	const struct rp1_gpclk_execution_ops *ops, void *context)
{
	int result;

	if (!ops || !context)
		return -EINVAL;
	result = ops->set_rate(context);
	if (result)
		goto unwind;
	result = ops->prepare(context);
	if (!result)
		return 0;
unwind:
	rp1_gpclk_execution_machine_finish(ops, context, false);
	return result;
}

int rp1_gpclk_execution_machine_activate(
	const struct rp1_gpclk_execution_ops *ops, void *context)
{
	if (!ops || !context)
		return -EINVAL;
	return ops->select_active(context);
}
