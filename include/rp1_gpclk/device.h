/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_DEVICE_H
#define RP1_GPCLK_DEVICE_H

#include <linux/clk.h>
#include <linux/completion.h>
#include <linux/dmaengine.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/mutex.h>
#include <linux/pinctrl/consumer.h>
#include <linux/types.h>

#include "rp1_gpclk/core.h"

struct rp1_gpclk_device {
	struct device *dev;
	struct kref refcount;
	struct mutex lock;
	/* Serializes cancellation with the last check before a DMA chunk is
	 * activated. This cannot be lock because UAPI cancellation holds lock. */
	struct mutex execution_commit_lock;
	bool dead;
	bool misc_registered;
	bool endpoint_claimed;
	bool rate_exclusive;
	void __iomem *tick_dma0;
	void __iomem *dma_tick0;
	struct miscdevice miscdev;
	struct clk *clock;
	struct clk *parent_clock;
	struct clk *initial_parent;
	struct dma_chan *dma_chan;
	struct pinctrl *pinctrl;
	struct pinctrl_state *pins_default;
	struct pinctrl_state *pins_active;
	struct pinctrl_state *pins_safe;
	phys_addr_t divider_phys;
	dma_addr_t divider_dma;
	resource_size_t tick_dma0_phys;
	resource_size_t dma_tick0_phys;
	resource_size_t rp1_phys_start;
	resource_size_t rp1_phys_end;
	struct task_struct *worker;
	void *execution_plan;
	struct completion dma_done;
	struct completion execution_done;
	atomic_t stop_requested;
	__u32 stop_reason;
	__u32 execution_failure_reason;
	__u64 execution_owner;
	__u64 execution_lease;
	__u64 execution_generation;
	dma_cookie_t dma_cookie;
	__u64 dma_generation;
	__u64 execution_started_ns;
	__u64 execution_total_ns;
	bool dma_submitted;
	bool clock_prepared;
	bool clock_enabled;
	bool parent_selected;
	bool pins_active_selected;
	bool operational_ready;
	bool tick_state_captured;
	unsigned long initial_rate;
	int clock_cleanup_error;
	__u32 initial_tick_dma0_ctrl;
	__u32 initial_tick_dma0_cycles;
	__u32 initial_dma_tick0_en;
	__u32 initial_dma_tick0_ctrl;
	__u32 readback_expected;
	__u32 readback_observed;
	__u64 execution_finished_ns;
	__u32 route;
	struct rp1_gpclk_core core;
};

struct rp1_gpclk_file {
	struct rp1_gpclk_device *device;
	__u64 owner;
};

#endif /* RP1_GPCLK_DEVICE_H */
