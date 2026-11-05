/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_EXECUTION_H
#define RP1_GPCLK_EXECUTION_H

#include <linux/types.h>

struct rp1_gpclk_device;

int rp1_gpclk_execution_init(struct rp1_gpclk_device *device);
int rp1_gpclk_execution_submit_events(
	struct rp1_gpclk_device *device, __u64 owner,
	struct rp1_gpclk_submit_events *request,
	const struct rp1_gpclk_tone *tones,
	const struct rp1_gpclk_event *events);
void rp1_gpclk_execution_activate(struct rp1_gpclk_device *device,
				  __u64 generation);
int rp1_gpclk_execution_stop(struct rp1_gpclk_device *device, __u64 owner,
			     __u64 lease, __u64 generation, __u32 reason);
void rp1_gpclk_execution_request_stop(struct rp1_gpclk_device *device,
				      __u32 reason);
void rp1_gpclk_execution_quiesce(struct rp1_gpclk_device *device,
				 __u32 reason);

#endif /* RP1_GPCLK_EXECUTION_H */
