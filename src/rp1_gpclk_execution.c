// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/dmaengine.h>
#include <linux/dma-mapping.h>
#include <linux/err.h>
#include <linux/jiffies.h>
#include <linux/iopoll.h>
#include <linux/kthread.h>
#include <linux/math64.h>
#include <linux/ktime.h>
#include <linux/pinctrl/consumer.h>
#include <linux/sched/task.h>
#include <linux/slab.h>
#include <linux/scatterlist.h>
#include <linux/wait.h>

#include "rp1_gpclk/device.h"
#include "rp1_gpclk/dma_segments.h"
#include "rp1_gpclk/clock_setup.h"
#include "rp1_gpclk/execution.h"
#include "rp1_gpclk/execution_machine.h"
#include "rp1_gpclk/execution_policy.h"
#include "rp1_gpclk/kernel_api.h"
#include "rp1_gpclk/resource_policy.h"
#include "rp1_gpclk/target_fault.h"

#define RP1_GPCLK_TICKS_DMA0_CTRL 0x0
#define RP1_GPCLK_TICKS_DMA0_CYCLES 0x4
#define RP1_GPCLK_DMA_TICK0_EN 0x0
#define RP1_GPCLK_DMA_TICK0_CTRL 0x4
#define RP1_GPCLK_DMA_TICK_REQUEST BIT(0)
#define RP1_GPCLK_DMA_TICK_SINGLE BIT(1)
#define RP1_GPCLK_DMA_TICK_DREQ BIT(12)
#define RP1_GPCLK_DMA_TICK_DWELL (19U << 4)
#define RP1_GPCLK_FIRMWARE_TICK_CTRL 3U
#define RP1_GPCLK_FIRMWARE_TICK_CYCLES 50U
#define RP1_GPCLK_COMPLETION_SLACK_MS 1000U
#define RP1_GPCLK_QUIESCE_TIMEOUT_MS 3000U

struct rp1_gpclk_execution_plan {
	__u32 drive_ma;
	__u32 tone_count;
	__u32 event_count;
	struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
	struct rp1_gpclk_event events[RP1_GPCLK_MAX_EVENTS];
};

struct rp1_gpclk_execution_context {
	struct rp1_gpclk_device *device;
	const struct rp1_gpclk_execution_plan *plan;
	__u32 *word;
	dma_addr_t word_dma;
	__u32 expected;
};

static void rp1_gpclk_dma_complete(void *argument)
{
	struct rp1_gpclk_device *device = argument;

	if (rp1_gpclk_target_fault(
		    RP1_GPCLK_TARGET_FAULT_DMA_COMPLETION))
		return;
	if (READ_ONCE(device->dma_generation) ==
	    READ_ONCE(device->execution_generation))
		complete(&device->dma_done);
}

static void rp1_gpclk_tick_stop(struct rp1_gpclk_device *device)
{
	writel(0, device->dma_tick0 + RP1_GPCLK_DMA_TICK0_EN);
	writel(0, device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CTRL);
}

static void rp1_gpclk_tick_start(struct rp1_gpclk_device *device)
{
	writel(RP1_GPCLK_TICK_DIVIDER,
	       device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CYCLES);
	/* dma_finish can occur at an intermediate linked-list block. Keep
	 * requests enabled until the complete DMA descriptor drains; clearing
	 * them on the first block strands the next block waiting for DREQ.
	 */
	writel(RP1_GPCLK_DMA_TICK_DWELL,
	       device->dma_tick0 + RP1_GPCLK_DMA_TICK0_CTRL);
	dma_async_issue_pending(device->dma_chan);
	writel(RP1_GPCLK_DMA_TICK_REQUEST | RP1_GPCLK_DMA_TICK_SINGLE,
	       device->dma_tick0 + RP1_GPCLK_DMA_TICK0_EN);
	writel(1, device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CTRL);
}

static unsigned long rp1_gpclk_timeout_jiffies(__u64 duration_ns)
{
	__u64 milliseconds = div_u64(duration_ns + NSEC_PER_MSEC - 1,
				      NSEC_PER_MSEC);

	if (milliseconds > UINT_MAX - RP1_GPCLK_COMPLETION_SLACK_MS)
		milliseconds = UINT_MAX - RP1_GPCLK_COMPLETION_SLACK_MS;
	return msecs_to_jiffies((unsigned int)milliseconds +
				RP1_GPCLK_COMPLETION_SLACK_MS);
}

static int rp1_gpclk_configure_dma(struct rp1_gpclk_device *device,
				   dma_addr_t buffer_dma, size_t bytes,
				   enum dma_transfer_direction direction)
{
	struct dma_async_tx_descriptor *descriptor;
	struct dma_slave_config config = { };
	struct sg_table table;
	struct scatterlist *entry;
	size_t remaining = bytes, offset = 0;
	unsigned int count, i;
	dma_cookie_t cookie;
	int ret;

	config.direction = direction;
	if (direction == DMA_MEM_TO_DEV) {
		config.dst_addr = device->divider_dma;
		config.dst_addr_width = DMA_SLAVE_BUSWIDTH_4_BYTES;
		config.dst_maxburst = 1;
	} else {
		config.src_addr = device->divider_dma;
		config.src_addr_width = DMA_SLAVE_BUSWIDTH_4_BYTES;
		config.src_maxburst = 1;
	}
	ret = dmaengine_slave_config(device->dma_chan, &config);
	if (ret)
		return ret;
	if (direction == DMA_MEM_TO_DEV &&
	    rp1_gpclk_target_fault(RP1_GPCLK_TARGET_FAULT_DMA_PREPARE))
		return -EIO;
	reinit_completion(&device->dma_done);
	if (!bytes || bytes % sizeof(__u32))
		return -EINVAL;
	count = DIV_ROUND_UP(bytes, RP1_GPCLK_DMA_SEGMENT_BYTES);
	ret = sg_alloc_table(&table, count, GFP_KERNEL);
	if (ret)
		return ret;
	for_each_sg(table.sgl, entry, count, i) {
		unsigned int length = rp1_gpclk_dma_segment_bytes(remaining);

		/* dma_alloc_coherent already supplied DMA addresses; do not map
		 * them again or translate them through CPU physical addresses.
		 */
		sg_dma_address(entry) = buffer_dma + offset;
		sg_dma_len(entry) = length;
		offset += length;
		remaining -= length;
	}
	descriptor = dmaengine_prep_slave_sg(device->dma_chan, table.sgl,
		count, direction, DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
	sg_free_table(&table);
	if (!descriptor)
		return -EIO;
	descriptor->callback = rp1_gpclk_dma_complete;
	descriptor->callback_param = device;
	cookie = dmaengine_submit(descriptor);
	ret = dma_submit_error(cookie);
	if (ret)
		return ret;
	device->dma_cookie = cookie;
	WRITE_ONCE(device->dma_generation, device->execution_generation);
	device->dma_submitted = true;
	if (direction == DMA_MEM_TO_DEV &&
	    rp1_gpclk_target_fault(RP1_GPCLK_TARGET_FAULT_DMA_SUBMIT))
		return -EIO;
	return 0;
}

static int rp1_gpclk_wait_dma(struct rp1_gpclk_device *device,
			      __u64 duration_ns)
{
	unsigned long completed;

	completed = wait_for_completion_timeout(&device->dma_done,
		rp1_gpclk_timeout_jiffies(duration_ns));
	if (!completed) {
		struct dma_tx_state state = { };
		enum dma_status status = dmaengine_tx_status(device->dma_chan,
			device->dma_cookie, &state);

		dev_err(device->dev,
			"DMA deadline: duration_ns=%llu status=%u residue=%u stop=%d\n",
			duration_ns, status, state.residue,
			atomic_read(&device->stop_requested));
		/* A requested cancellation does not turn a failed drain into
		 * successful cancellation. Keep pacing available during teardown.
		 */
		dmaengine_terminate_sync(device->dma_chan);
		device->dma_submitted = false;
		rp1_gpclk_tick_stop(device);
		return -ETIMEDOUT;
	}
	if (atomic_read(&device->stop_requested)) {
		dmaengine_terminate_sync(device->dma_chan);
		device->dma_submitted = false;
		rp1_gpclk_tick_stop(device);
		return -ECANCELED;
	}
	rp1_gpclk_tick_stop(device);
	/* RP1 DMA must reach a terminated channel state before direction change. */
	dmaengine_terminate_sync(device->dma_chan);
	device->dma_submitted = false;
	return 0;
}

static int rp1_gpclk_setup_rate(void *argument, __u64 rate)
{
	struct rp1_gpclk_device *device = argument;
	int ret;

	if (rate > ULONG_MAX)
		return -ERANGE;
	/* Fractional DMA bypasses the CCF rate cache. A same-rate request could
	 * otherwise be a no-op and leave the last transmitted divider behind.
	 * Output is inactive for every caller of this helper.
	 */
	if (clk_get_rate(device->clock) == rate) {
		ret = clk_set_rate(device->clock, rate > 1 ? rate / 2 : 2);
		if (ret)
			return ret;
		if (clk_get_rate(device->clock) == rate)
			return -EIO;
	}
	return clk_set_rate(device->clock, (unsigned long)rate);
}

static __u64 rp1_gpclk_setup_parent_rate(void *argument)
{
	struct rp1_gpclk_device *device = argument;
	struct clk *parent = clk_get_parent(device->clock);

	return parent ? clk_get_rate(parent) : 0;
}

static __u64 rp1_gpclk_setup_output_rate(void *argument)
{
	struct rp1_gpclk_device *device = argument;

	return clk_get_rate(device->clock);
}

static int rp1_gpclk_setup_select_parent(void *argument)
{
	struct rp1_gpclk_device *device = argument;

	return clk_set_parent(device->clock, device->parent_clock);
}

static bool rp1_gpclk_setup_parent_matches(void *argument)
{
	struct rp1_gpclk_device *device = argument;

	return clk_is_match(clk_get_parent(device->clock), device->parent_clock);
}

static const struct rp1_gpclk_clock_setup_ops rp1_gpclk_setup_ops = {
	.set_rate = rp1_gpclk_setup_rate,
	.parent_rate = rp1_gpclk_setup_parent_rate,
	.output_rate = rp1_gpclk_setup_output_rate,
	.select_parent = rp1_gpclk_setup_select_parent,
	.parent_matches = rp1_gpclk_setup_parent_matches,
};

static int rp1_gpclk_machine_set_rate(void *argument)
{
	struct rp1_gpclk_execution_context *context = argument;
	struct rp1_gpclk_device *device = context->device;
	const struct rp1_gpclk_execution_plan *plan = context->plan;
	unsigned long parent_rate;
	int ret;

	ret = rp1_gpclk_execution_tones_valid(plan->tones, plan->tone_count,
					      plan->drive_ma);
	if (ret)
		return ret;
	device->initial_tick_dma0_ctrl =
		readl(device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CTRL);
	device->initial_tick_dma0_cycles =
		readl(device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CYCLES);
	device->initial_dma_tick0_en =
		readl(device->dma_tick0 + RP1_GPCLK_DMA_TICK0_EN);
	device->initial_dma_tick0_ctrl =
		readl(device->dma_tick0 + RP1_GPCLK_DMA_TICK0_CTRL) &
		~RP1_GPCLK_DMA_TICK_DREQ;
	if (device->initial_dma_tick0_en || device->initial_dma_tick0_ctrl ||
	    (device->initial_tick_dma0_ctrl &&
	     (device->initial_tick_dma0_ctrl != RP1_GPCLK_FIRMWARE_TICK_CTRL ||
	      device->initial_tick_dma0_cycles !=
		RP1_GPCLK_FIRMWARE_TICK_CYCLES))) {
		dev_err(device->dev,
			"phase4d startup conflict: tick=%08x/%08x/%08x/%08x\n",
			device->initial_tick_dma0_ctrl,
			device->initial_tick_dma0_cycles,
			device->initial_dma_tick0_en,
			device->initial_dma_tick0_ctrl);
		device->execution_failure_reason =
			RP1_GPCLK_REASON_STARTUP_CONFLICT;
		return -EBUSY;
	}
	if (__clk_is_enabled(device->clock)) {
		dev_err(device->dev,
			"phase4d startup conflict: common clock reports hardware enabled\n");
		return -EBUSY;
	}
	device->tick_state_captured = true;
	device->initial_rate = clk_get_rate(device->clock);
	device->initial_parent = clk_get_parent(device->clock);
	if (!device->initial_parent || !device->initial_rate)
		return -ENODEV;
	/* Even a failed parent request may have partially changed the provider. */
	device->parent_selected = true;
	ret = clk_set_parent(device->clock, device->parent_clock);
	if (ret)
		return ret;
	if (!clk_is_match(clk_get_parent(device->clock), device->parent_clock)) {
		dev_err(device->dev,
			"phase4d selected parent readback mismatch\n");
		return -EIO;
	}
	parent_rate = clk_get_rate(device->parent_clock);
	if (parent_rate != RP1_GPCLK_PARENT_RATE_HZ) {
		dev_err(device->dev,
			"phase4d selected parent rate mismatch: %lu\n", parent_rate);
		return -ERANGE;
	}
	ret = rp1_gpclk_clock_setup(&rp1_gpclk_setup_ops, device,
		plan->tones[0].lower_divider_q16, parent_rate);
	if (!ret && rp1_gpclk_target_fault(
			    RP1_GPCLK_TARGET_FAULT_CLOCK_SETUP))
		ret = -EIO;
	if (ret)
		dev_err(device->dev,
			"phase4d parent/integer-divider setup failed: %d\n", ret);
	return ret;
}

static int rp1_gpclk_machine_prepare(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;
	int ret;

	if (rp1_gpclk_target_fault(RP1_GPCLK_TARGET_FAULT_PREPARE))
		return -EIO;
	ret = clk_prepare(device->clock);

	if (ret)
		return ret;
	device->clock_prepared = true;
	if (!rp1_gpclk_setup_parent_matches(device) ||
	    rp1_gpclk_setup_parent_rate(device) != RP1_GPCLK_PARENT_RATE_HZ)
		return -EIO;
	return 0;
}

static int rp1_gpclk_machine_select_active(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;
	int ret;

	if (rp1_gpclk_target_fault(RP1_GPCLK_TARGET_FAULT_PIN_ACTIVE))
		return -EIO;
	ret = pinctrl_select_state(device->pinctrl, device->pins_active);

	if (ret)
		return ret;
	device->pins_active_selected = true;
	return 0;
}

static int rp1_gpclk_machine_readback(void *argument);

static int rp1_gpclk_machine_stop_tick(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;

	if (device->tick_state_captured)
		rp1_gpclk_tick_stop(device);
	if (rp1_gpclk_target_fault(
		    RP1_GPCLK_TARGET_FAULT_CLEANUP_STOP_TICK))
		return -EIO;
	return 0;
}

static int rp1_gpclk_machine_terminate_dma(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;

	if (device->dma_submitted) {
		dmaengine_terminate_sync(device->dma_chan);
		device->dma_submitted = false;
	}
	if (device->tick_state_captured) {
		__u32 observed;
		int ret;

		writel(device->initial_tick_dma0_cycles,
		       device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CYCLES);
		writel(device->initial_dma_tick0_ctrl,
		       device->dma_tick0 + RP1_GPCLK_DMA_TICK0_CTRL);
		writel(device->initial_dma_tick0_en,
		       device->dma_tick0 + RP1_GPCLK_DMA_TICK0_EN);
		writel(device->initial_tick_dma0_ctrl,
		       device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CTRL);
		ret = readl_poll_timeout(
			device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CTRL, observed,
			observed == device->initial_tick_dma0_ctrl, 1, 1000);
		ret = ret ?: readl_poll_timeout(
			device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CYCLES, observed,
			observed == device->initial_tick_dma0_cycles, 1, 1000);
		ret = ret ?: readl_poll_timeout(
			device->dma_tick0 + RP1_GPCLK_DMA_TICK0_EN, observed,
			observed == device->initial_dma_tick0_en, 1, 1000);
		ret = ret ?: readl_poll_timeout(
			device->dma_tick0 + RP1_GPCLK_DMA_TICK0_CTRL, observed,
			(observed & ~RP1_GPCLK_DMA_TICK_DREQ) ==
			device->initial_dma_tick0_ctrl, 1, 1000);
		if (ret) {
			dev_err(device->dev,
				"phase4d cleanup: tick register restoration verification failed\n");
			return ret;
		}
		device->tick_state_captured = false;
	}
	if (rp1_gpclk_target_fault(
		    RP1_GPCLK_TARGET_FAULT_CLEANUP_TERMINATE_DMA))
		return -EIO;
	return 0;
}

static int rp1_gpclk_machine_disable(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;

	if (device->clock_enabled) {
		clk_disable(device->clock);
		device->clock_enabled = false;
	}
	if (rp1_gpclk_target_fault(RP1_GPCLK_TARGET_FAULT_CLEANUP_DISABLE))
		return -EIO;
	return 0;
}

static int rp1_gpclk_machine_unprepare(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;

	if (device->clock_prepared) {
		clk_unprepare(device->clock);
		device->clock_prepared = false;
	}
	if (rp1_gpclk_target_fault(
		    RP1_GPCLK_TARGET_FAULT_CLEANUP_UNPREPARE))
		return -EIO;
	return 0;
}

static int rp1_gpclk_machine_select_safe(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;
	int ret = 0;

	if (device->pins_active_selected)
		ret = pinctrl_select_state(device->pinctrl, device->pins_safe);
	if (ret)
		dev_err(device->dev, "phase4d cleanup: safe pinctrl failed: %d\n",
			ret);
	else
		device->pins_active_selected = false;
	if (!ret && rp1_gpclk_target_fault(
			    RP1_GPCLK_TARGET_FAULT_CLEANUP_PIN_SAFE))
		ret = -EIO;
	return ret;
}

static int rp1_gpclk_restore_select_parent(void *argument)
{
	struct rp1_gpclk_device *device = argument;

	return clk_set_parent(device->clock, device->initial_parent);
}

static bool rp1_gpclk_restore_parent_matches(void *argument)
{
	struct rp1_gpclk_device *device = argument;

	return clk_is_match(clk_get_parent(device->clock), device->initial_parent);
}

static int rp1_gpclk_machine_restore_rate(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;
	unsigned long initial_rate = device->initial_rate;
	const struct rp1_gpclk_clock_setup_ops ops = {
		.set_rate = rp1_gpclk_setup_rate,
		.parent_rate = rp1_gpclk_setup_parent_rate,
		.output_rate = rp1_gpclk_setup_output_rate,
		.select_parent = rp1_gpclk_restore_select_parent,
		.parent_matches = rp1_gpclk_restore_parent_matches,
	};
	int ret = 0;

	if (device->parent_selected && device->initial_parent && initial_rate) {
		ret = rp1_gpclk_clock_restore(&ops, device, initial_rate,
			clk_get_rate(device->initial_parent));

		if (ret)
			dev_err(device->dev,
				"phase4d cleanup: clock rate restore to %lu failed: %d current=%lu\n",
				initial_rate, ret, clk_get_rate(device->clock));
	}
	device->initial_rate = 0;
	device->initial_parent = NULL;
	device->parent_selected = false;
	if (ret && !device->clock_cleanup_error)
		device->clock_cleanup_error = ret;
	if (!ret && rp1_gpclk_target_fault(
			    RP1_GPCLK_TARGET_FAULT_CLEANUP_RESTORE_RATE))
		ret = -EIO;
	return ret ?: device->clock_cleanup_error;
}

static int rp1_gpclk_machine_restore_parent(void *argument)
{
	struct rp1_gpclk_device *device =
		((struct rp1_gpclk_execution_context *)argument)->device;
	struct clk *initial_parent = device->initial_parent;
	int ret = 0;

	if (device->parent_selected && initial_parent) {
		ret = clk_set_parent(device->clock, initial_parent);
		if (!ret && !clk_is_match(clk_get_parent(device->clock),
					      initial_parent))
			ret = -EIO;
		if (ret)
			dev_err(device->dev,
				"phase4d cleanup: clock parent restore failed: %d\n",
				ret);
	}
	if (ret && !device->clock_cleanup_error)
		device->clock_cleanup_error = ret;
	if (!ret && rp1_gpclk_target_fault(
			    RP1_GPCLK_TARGET_FAULT_CLEANUP_RESTORE_PARENT))
		ret = -EIO;
	return ret ?: device->clock_cleanup_error;
}

static const struct rp1_gpclk_execution_ops rp1_gpclk_machine_ops = {
	.set_rate = rp1_gpclk_machine_set_rate,
	.prepare = rp1_gpclk_machine_prepare,
	.select_active = rp1_gpclk_machine_select_active,
	.readback = rp1_gpclk_machine_readback,
	.stop_tick = rp1_gpclk_machine_stop_tick,
	.terminate_dma = rp1_gpclk_machine_terminate_dma,
	.disable_clock = rp1_gpclk_machine_disable,
	.unprepare_clock = rp1_gpclk_machine_unprepare,
	.select_safe = rp1_gpclk_machine_select_safe,
	.restore_parent = rp1_gpclk_machine_restore_parent,
	.restore_rate = rp1_gpclk_machine_restore_rate,
};

static int rp1_gpclk_set_enabled(struct rp1_gpclk_device *device, bool enabled)
{
	int ret;

	if (enabled == device->clock_enabled)
		return 0;
	if (enabled) {
		if (rp1_gpclk_target_fault(
			    RP1_GPCLK_TARGET_FAULT_CLOCK_ENABLE))
			return -EIO;
		ret = clk_enable(device->clock);
		if (ret)
			return ret;
		device->clock_enabled = true;
	} else {
		clk_disable(device->clock);
		device->clock_enabled = false;
	}
	return 0;
}

static int rp1_gpclk_readback(struct rp1_gpclk_device *device,
			      __u32 *word, dma_addr_t word_dma,
			      __u32 expected)
{
	int ret;

	if (rp1_gpclk_target_fault(RP1_GPCLK_TARGET_FAULT_READBACK))
		return -EIO;
	*word = 0;
	device->readback_expected = expected;
	ret = rp1_gpclk_configure_dma(device, word_dma, sizeof(*word),
				      DMA_DEV_TO_MEM);
	if (ret)
		return ret;
	mutex_lock(&device->execution_commit_lock);
	if (atomic_read(&device->stop_requested)) {
		mutex_unlock(&device->execution_commit_lock);
		dmaengine_terminate_sync(device->dma_chan);
		device->dma_submitted = false;
		return -ECANCELED;
	}
	rp1_gpclk_tick_start(device);
	mutex_unlock(&device->execution_commit_lock);
	ret = rp1_gpclk_wait_dma(device, NSEC_PER_MSEC);
	if (ret) {
		device->readback_observed = *word;
		return ret;
	}
	device->readback_observed = *word;
	return *word == expected ? 0 : -EIO;
}

static int rp1_gpclk_machine_readback(void *argument)
{
	struct rp1_gpclk_execution_context *context = argument;

	return rp1_gpclk_readback(context->device, context->word,
		context->word_dma, context->expected);
}

static int rp1_gpclk_sleep_or_stop(struct rp1_gpclk_device *device,
				   __u64 duration_ns)
{
	ktime_t interval = ns_to_ktime(duration_ns);

	set_current_state(TASK_INTERRUPTIBLE);
	if (!atomic_read(&device->stop_requested))
		schedule_hrtimeout(&interval, HRTIMER_MODE_REL);
	__set_current_state(TASK_RUNNING);
	return atomic_read(&device->stop_requested) ? -ECANCELED : 0;
}

static int rp1_gpclk_run_descriptor(struct rp1_gpclk_device *device,
				    struct rp1_gpclk_execution_context *context,
				    const struct rp1_gpclk_tone *tone,
				    __u32 *words, dma_addr_t words_dma,
				    size_t writes, __u64 duration_ns,
				    __u64 *accumulator, __u32 *expected)
{
	int ret;

	ret = rp1_gpclk_execution_fill_words_stateful(tone, words, writes,
		accumulator);
	if (ret) {
		device->execution_failure_reason =
			RP1_GPCLK_REASON_INVALID_REQUEST;
		return ret;
	}
	*expected = words[writes - 1];
	device->execution_failure_reason = RP1_GPCLK_REASON_DMA_FAILED;
	ret = rp1_gpclk_configure_dma(device, words_dma,
				      writes * sizeof(*words), DMA_MEM_TO_DEV);
	if (ret)
		return ret;
	mutex_lock(&device->execution_commit_lock);
	if (atomic_read(&device->stop_requested)) {
		mutex_unlock(&device->execution_commit_lock);
		dmaengine_terminate_sync(device->dma_chan);
		device->dma_submitted = false;
		return -ECANCELED;
	}
	if (!device->pins_active_selected) {
		device->execution_failure_reason = RP1_GPCLK_REASON_PINCTRL_FAILED;
		ret = rp1_gpclk_execution_machine_activate(
			&rp1_gpclk_machine_ops, context);
		if (ret) {
			mutex_unlock(&device->execution_commit_lock);
			dmaengine_terminate_sync(device->dma_chan);
			device->dma_submitted = false;
			return ret;
		}
	}
	device->execution_failure_reason = RP1_GPCLK_REASON_CLOCK_FAILED;
	ret = rp1_gpclk_set_enabled(device, true);
	if (ret) {
		mutex_unlock(&device->execution_commit_lock);
		dmaengine_terminate_sync(device->dma_chan);
		device->dma_submitted = false;
		return ret;
	}
	device->execution_failure_reason = RP1_GPCLK_REASON_DMA_FAILED;
	rp1_gpclk_tick_start(device);
	mutex_unlock(&device->execution_commit_lock);
	return rp1_gpclk_wait_dma(device, duration_ns);
}

static void rp1_gpclk_publish_failure(struct rp1_gpclk_device *device,
				      int error, bool cleanup_failed)
{
	__u32 reason = device->execution_failure_reason;

	if (error == -ETIMEDOUT)
		reason = RP1_GPCLK_REASON_DEADLINE_MISSED;
	if (reason < RP1_GPCLK_REASON_DEADLINE_MISSED ||
	    reason > RP1_GPCLK_REASON_INTERNAL_ERROR)
		reason = RP1_GPCLK_REASON_INTERNAL_ERROR;
	mutex_lock(&device->lock);
	if (cleanup_failed)
		rp1_gpclk_core_cleanup_failed(&device->core,
			device->execution_owner, device->execution_lease,
			device->execution_generation);
	else
		rp1_gpclk_core_fail(&device->core, device->execution_owner,
			device->execution_lease, device->execution_generation, reason);
	mutex_unlock(&device->lock);
}

static void rp1_gpclk_wake_worker_locked(struct rp1_gpclk_device *device)
{
	struct task_struct *worker = device->worker;

	if (worker)
		wake_up_process(worker);
}

static struct task_struct *
rp1_gpclk_get_worker(struct rp1_gpclk_device *device)
{
	struct task_struct *worker;

	mutex_lock(&device->execution_commit_lock);
	worker = device->worker;
	if (worker)
		get_task_struct(worker);
	mutex_unlock(&device->execution_commit_lock);
	return worker;
}

static void rp1_gpclk_retire_worker(struct rp1_gpclk_device *device)
{
	/* Match submission's device -> execution_commit lock order. Publishing
	 * completion while both shared pointers are retired prevents a successor
	 * from reinitializing the completion before this generation is finished.
	 */
	mutex_lock(&device->lock);
	mutex_lock(&device->execution_commit_lock);
	device->execution_plan = NULL;
	WRITE_ONCE(device->worker, NULL);
	complete_all(&device->execution_done);
	mutex_unlock(&device->execution_commit_lock);
	mutex_unlock(&device->lock);
}

static int rp1_gpclk_execution_thread(void *argument)
{
	struct rp1_gpclk_device *device = argument;
	struct rp1_gpclk_execution_plan *plan = device->execution_plan;
	struct device *dma_device = device->dma_chan->device->dev;
	dma_addr_t words_dma;
	__u32 *words;
	__u32 expected = 0;
	__u64 tone_accumulators[RP1_GPCLK_MAX_TONES] = { 0 };
	__u64 timing_remainder = 0;
	__u64 maximum_remainder =
		(__u64)RP1_GPCLK_TICK_DIVIDER * 1000000000ULL - 1;
	size_t maximum;
	__u32 index;
	int cleanup_ret;
	int readback_ret = 0;
	int ret = 0;
	struct rp1_gpclk_execution_context context = {
		.device = device,
		.plan = plan,
	};

	if (atomic_read(&device->stop_requested))
		goto cancelled_before_buffer;
	ret = rp1_gpclk_execution_chunk_writes(
		RP1_GPCLK_DMA_CHUNK_DURATION_NS, &maximum_remainder, &maximum);
	if (ret)
		goto fail_without_buffer;
	if (!maximum || maximum > SIZE_MAX / sizeof(*words)) {
		ret = -EOVERFLOW;
		goto fail_without_buffer;
	}
	words = dma_alloc_coherent(dma_device, maximum * sizeof(*words),
				   &words_dma, GFP_KERNEL);
	if (!words) {
		ret = -ENOMEM;
		goto fail_without_buffer;
	}
	context.word = words;
	context.word_dma = words_dma;
	WRITE_ONCE(device->execution_started_ns, ktime_get_boottime_ns());
	device->execution_failure_reason = RP1_GPCLK_REASON_CLOCK_FAILED;
	ret = rp1_gpclk_execution_machine_start(&rp1_gpclk_machine_ops,
		&context);
	if (ret)
		goto fail;

	for (index = 0; index < plan->event_count; index++) {
		const struct rp1_gpclk_event *event = &plan->events[index];
		bool enabled = event->flags & RP1_GPCLK_EVENT_F_OUTPUT_ENABLED;

		if (atomic_read(&device->stop_requested)) {
			ret = -ECANCELED;
			break;
		}
		if (!enabled) {
			device->execution_failure_reason =
				RP1_GPCLK_REASON_CLOCK_FAILED;
			ret = rp1_gpclk_set_enabled(device, false);
			if (!ret) {
				device->execution_failure_reason =
					RP1_GPCLK_REASON_PINCTRL_FAILED;
				ret = rp1_gpclk_machine_select_safe(&context);
			}
			if (!ret)
				ret = rp1_gpclk_sleep_or_stop(device,
					event->duration_ns);
			expected = 0;
			timing_remainder = 0;
		} else {
			struct rp1_gpclk_chunk_cursor cursor;
			__u64 duration;
			size_t writes;
			int next;

			ret = rp1_gpclk_chunk_cursor_init(&cursor,
				event->duration_ns);
			cursor.timing_remainder = timing_remainder;
			while (!ret) {
				if (atomic_read(&device->stop_requested))
					rp1_gpclk_chunk_cursor_cancel(&cursor);
				next = rp1_gpclk_chunk_cursor_next(&cursor, &duration,
					&writes);
				if (next <= 0) {
					if (next < 0)
						ret = next;
					break;
				}
				ret = rp1_gpclk_run_descriptor(device, &context,
					&plan->tones[event->tone_index], words,
					words_dma, writes, duration,
					&tone_accumulators[event->tone_index],
					&expected);
				if (ret)
					break;
			}
			timing_remainder = cursor.timing_remainder;
		}
		if (ret && ret != -ECANCELED)
			break;
		if (ret == -ECANCELED ||
		    atomic_read(&device->stop_requested)) {
			ret = -ECANCELED;
			break;
		}
		if (index + 1 != plan->event_count) {
			mutex_lock(&device->lock);
			rp1_gpclk_core_progress(&device->core,
				device->execution_owner, device->execution_lease,
				device->execution_generation);
			mutex_unlock(&device->lock);
		}
	}

	context.expected = expected;
	if (expected != 0 && !ret &&
	    !atomic_read(&device->stop_requested)) {
		device->execution_failure_reason = RP1_GPCLK_REASON_READBACK_FAILED;
		readback_ret = rp1_gpclk_machine_readback(&context);
		if (readback_ret == -ECANCELED) {
			ret = -ECANCELED;
			readback_ret = 0;
		}
	}
	cleanup_ret = rp1_gpclk_execution_machine_finish(
		&rp1_gpclk_machine_ops, &context, false);
	WRITE_ONCE(device->execution_finished_ns, ktime_get_boottime_ns());
	if (cleanup_ret) {
		ret = cleanup_ret;
		rp1_gpclk_publish_failure(device, ret, true);
	} else if (ret && ret != -ECANCELED) {
		rp1_gpclk_publish_failure(device, ret, false);
	} else if (readback_ret) {
		device->execution_failure_reason =
			readback_ret == -ETIMEDOUT ?
			RP1_GPCLK_REASON_DEADLINE_MISSED :
			RP1_GPCLK_REASON_READBACK_FAILED;
		rp1_gpclk_publish_failure(device, readback_ret, false);
	} else {
		mutex_lock(&device->lock);
		rp1_gpclk_core_progress(&device->core, device->execution_owner,
			device->execution_lease, device->execution_generation);
		mutex_unlock(&device->lock);
	}
	dev_info(device->dev,
		 "generation=%llu events=%u start_ns=%llu finish_ns=%llu expected_div_frac=0x%08x observed_div_frac=0x%08x tick_initial=%08x/%08x/%08x/%08x tick_final=%08x/%08x/%08x/%08x cleanup=%d result=%d\n",
		 device->execution_generation, plan->event_count,
		 device->execution_started_ns, device->execution_finished_ns,
		 device->readback_expected, device->readback_observed,
		 device->initial_tick_dma0_ctrl, device->initial_tick_dma0_cycles,
		 device->initial_dma_tick0_en, device->initial_dma_tick0_ctrl,
		 readl(device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CTRL),
		 readl(device->tick_dma0 + RP1_GPCLK_TICKS_DMA0_CYCLES),
		 readl(device->dma_tick0 + RP1_GPCLK_DMA_TICK0_EN),
		 readl(device->dma_tick0 + RP1_GPCLK_DMA_TICK0_CTRL),
		 cleanup_ret, ret);
	dma_free_coherent(dma_device, maximum * sizeof(*words), words, words_dma);
	kfree_sensitive(plan);
	rp1_gpclk_retire_worker(device);
	return 0;

fail:
	cleanup_ret = rp1_gpclk_execution_machine_finish(
		&rp1_gpclk_machine_ops, &context, false);
	dma_free_coherent(dma_device, maximum * sizeof(*words), words, words_dma);
	WRITE_ONCE(device->execution_finished_ns, ktime_get_boottime_ns());
	if (cleanup_ret)
		rp1_gpclk_publish_failure(device, cleanup_ret, true);
	else
		rp1_gpclk_publish_failure(device, ret, false);
	goto release_plan;

fail_without_buffer:
	WRITE_ONCE(device->execution_finished_ns, ktime_get_boottime_ns());
	rp1_gpclk_publish_failure(device, ret, false);
release_plan:
	kfree_sensitive(plan);
	rp1_gpclk_retire_worker(device);
	return 0;

cancelled_before_buffer:
	WRITE_ONCE(device->execution_finished_ns, ktime_get_boottime_ns());
	mutex_lock(&device->lock);
	rp1_gpclk_core_progress(&device->core, device->execution_owner,
		device->execution_lease, device->execution_generation);
	mutex_unlock(&device->lock);
	goto release_plan;
}

int rp1_gpclk_execution_init(struct rp1_gpclk_device *device)
{
	if (!device)
		return -EINVAL;
	init_completion(&device->dma_done);
	init_completion(&device->execution_done);
	mutex_init(&device->execution_commit_lock);
	complete_all(&device->execution_done);
	atomic_set(&device->stop_requested, 0);
	return 0;
}

static int rp1_gpclk_start_thread(struct rp1_gpclk_device *device,
				  struct rp1_gpclk_execution_plan *plan,
				  __u64 owner, __u64 lease, __u64 generation)
{
	struct task_struct *worker;
	__u32 index;

	if (READ_ONCE(device->worker))
		return -EBUSY;
	device->execution_owner = owner;
	device->execution_lease = lease;
	device->execution_generation = generation;
	device->execution_started_ns = 0;
	device->execution_finished_ns = 0;
	device->readback_expected = 0;
	device->readback_observed = 0;
	device->tick_state_captured = false;
	device->execution_total_ns = 0;
	for (index = 0; index < plan->event_count; index++)
		device->execution_total_ns += plan->events[index].duration_ns;
	device->stop_reason = RP1_GPCLK_REASON_NONE;
	device->execution_failure_reason = RP1_GPCLK_REASON_NONE;
	atomic_set(&device->stop_requested, 0);
	device->execution_plan = plan;
	reinit_completion(&device->execution_done);
	worker = kthread_create(rp1_gpclk_execution_thread, device,
				"rp1-gpclk/%llu", generation);
	if (IS_ERR(worker)) {
		device->execution_plan = NULL;
		complete_all(&device->execution_done);
		return PTR_ERR(worker);
	}
	mutex_lock(&device->execution_commit_lock);
	WRITE_ONCE(device->worker, worker);
	mutex_unlock(&device->execution_commit_lock);
	return 0;
}

void rp1_gpclk_execution_activate(struct rp1_gpclk_device *device,
				  __u64 generation)
{
	mutex_lock(&device->execution_commit_lock);
	if (generation == device->execution_generation)
		rp1_gpclk_wake_worker_locked(device);
	mutex_unlock(&device->execution_commit_lock);
}

int rp1_gpclk_execution_submit_events(
	struct rp1_gpclk_device *device, __u64 owner,
	struct rp1_gpclk_submit_events *request,
	const struct rp1_gpclk_tone *tones,
	const struct rp1_gpclk_event *events)
{
	struct rp1_gpclk_execution_plan *plan;
	__u32 index;
	int result;

	plan = kzalloc(sizeof(*plan), GFP_KERNEL);
	if (!plan)
		return -ENOMEM;
	if (rp1_gpclk_execution_tones_valid(tones, request->tone_count,
					    request->drive_ma)) {
		kfree(plan);
		return RP1_GPCLK_CORE_INVALID;
	}
	for (index = 0; index < request->event_count; index++) {
		__u64 duration;
		__u64 remainder = 0;
		size_t writes;

		if (!(events[index].flags & RP1_GPCLK_EVENT_F_OUTPUT_ENABLED))
			continue;
		duration = min_t(__u64, events[index].duration_ns,
			RP1_GPCLK_DMA_CHUNK_DURATION_NS);
		if (rp1_gpclk_execution_chunk_writes(duration, &remainder,
						     &writes)) {
			kfree(plan);
			return RP1_GPCLK_CORE_INVALID;
		}
	}
	if (READ_ONCE(device->worker)) {
		kfree(plan);
		return RP1_GPCLK_CORE_BUSY;
	}
	result = rp1_gpclk_core_submit_events(&device->core, owner, request,
					      tones, events);
	if (result != RP1_GPCLK_CORE_OK) {
		kfree(plan);
		return result;
	}
	plan->drive_ma = request->drive_ma;
	plan->tone_count = request->tone_count;
	plan->event_count = request->event_count;
	memcpy(plan->tones, tones, sizeof(*tones) * request->tone_count);
	memcpy(plan->events, events, sizeof(*events) * request->event_count);
	result = rp1_gpclk_start_thread(device, plan, owner, request->lease_id,
					request->generation);
	if (result) {
		rp1_gpclk_core_fail(&device->core, owner, request->lease_id,
			request->generation, RP1_GPCLK_REASON_INTERNAL_ERROR);
		kfree(plan);
	}
	return result;
}

int rp1_gpclk_execution_stop(struct rp1_gpclk_device *device, __u64 owner,
			     __u64 lease, __u64 generation, __u32 reason)
{
	int result;

	result = rp1_gpclk_core_stop(&device->core, owner, lease, generation);
	if (result != RP1_GPCLK_CORE_OK)
		return result;
	mutex_lock(&device->execution_commit_lock);
	device->stop_reason = reason;
	atomic_set(&device->stop_requested, 1);
	rp1_gpclk_wake_worker_locked(device);
	mutex_unlock(&device->execution_commit_lock);
	return RP1_GPCLK_CORE_OK;
}

void rp1_gpclk_execution_quiesce(struct rp1_gpclk_device *device,
				 __u32 reason)
{
	rp1_gpclk_execution_request_stop(device, reason);
	if (!wait_for_completion_timeout(&device->execution_done,
			msecs_to_jiffies(RP1_GPCLK_QUIESCE_TIMEOUT_MS))) {
		struct task_struct *worker;

		rp1_gpclk_tick_stop(device);
		dmaengine_terminate_sync(device->dma_chan);
		if (!wait_for_completion_timeout(&device->execution_done,
				msecs_to_jiffies(RP1_GPCLK_COMPLETION_SLACK_MS))) {
			dev_crit(device->dev,
				 "forced execution teardown after bounded drain failure\n");
			worker = rp1_gpclk_get_worker(device);
			if (worker) {
				kthread_stop(worker);
				put_task_struct(worker);
			}
		}
	}
}

void rp1_gpclk_execution_request_stop(struct rp1_gpclk_device *device,
				      __u32 reason)
{
	mutex_lock(&device->execution_commit_lock);
	device->stop_reason = reason;
	atomic_set(&device->stop_requested, 1);
	rp1_gpclk_wake_worker_locked(device);
	mutex_unlock(&device->execution_commit_lock);
}
