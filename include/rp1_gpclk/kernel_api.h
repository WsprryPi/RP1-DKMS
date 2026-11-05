/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_KERNEL_API_H
#define RP1_GPCLK_KERNEL_API_H

#include <linux/platform_device.h>

struct rp1_gpclk_device;

int rp1_gpclk_dt_validate(struct rp1_gpclk_device *device);
int rp1_gpclk_clock_acquire(struct rp1_gpclk_device *device);
int rp1_gpclk_dma_acquire(struct rp1_gpclk_device *device);
int rp1_gpclk_pinctrl_acquire(struct rp1_gpclk_device *device);
int rp1_gpclk_tick_resources_acquire(struct platform_device *pdev,
				     struct rp1_gpclk_device *device);
bool rp1_gpclk_output_inhibited(void);
bool rp1_gpclk_operationally_ready(const struct rp1_gpclk_device *device);
void rp1_gpclk_quiesce(struct rp1_gpclk_device *device);
void rp1_gpclk_resources_release(struct rp1_gpclk_device *device);

#endif /* RP1_GPCLK_KERNEL_API_H */
