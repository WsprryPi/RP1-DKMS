/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_RESOURCE_POLICY_H
#define RP1_GPCLK_RESOURCE_POLICY_H

#include <linux/types.h>

#include <linux/rp1_gpclk.h>

#define RP1_GPCLK_PROVIDER_COMPATIBLE "raspberrypi,rp1-clocks"
#define RP1_GPCLK_CLOCK_ID 33U
#define RP1_GPCLK_PARENT_PROVIDER_COMPATIBLE "raspberrypi,rp1-clocks"
#define RP1_GPCLK_PARENT_CLOCK_ID 3U
#define RP1_GPCLK_PARENT_RATE_HZ 200000000U
#define RP1_GPCLK_DMA_PROVIDER_COMPATIBLE "snps,axi-dma-1.01a"
#define RP1_GPCLK_DMA_REQUEST 0x30U
#define RP1_GPCLK_DIV_FRAC_OFFSET 0x17cU
#define RP1_GPCLK_REGISTER_BYTES 4U
#define RP1_GPCLK_TICK_DMA0_OFFSET 0x174024U
#define RP1_GPCLK_DMA_TICK0_OFFSET 0x158000U
#define RP1_GPCLK_TICK_RESOURCE_BYTES 8U
#define RP1_GPCLK_GPIO4_ENDPOINT_NAME "rp1-gpclk-dkms-gpio4"
#define RP1_GPCLK_GPIO20_ENDPOINT_NAME "rp1-gpclk-dkms-gpio20"

int rp1_gpclk_derive_target(__u64 resource_start, __u64 resource_end,
			    __u64 offset, __u64 bytes, __u64 *target);
int rp1_gpclk_route_pin_validate(__u32 route, __u32 pin);
int rp1_gpclk_route_endpoint_validate(__u32 route, const char *name);

#endif /* RP1_GPCLK_RESOURCE_POLICY_H */
