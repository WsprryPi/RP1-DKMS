/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_LIFETIME_H
#define RP1_GPCLK_LIFETIME_H

struct rp1_gpclk_device;

int rp1_gpclk_lifetime_init(struct rp1_gpclk_device *device);
bool rp1_gpclk_lifetime_get_live(struct rp1_gpclk_device *device);
void rp1_gpclk_lifetime_mark_dead(struct rp1_gpclk_device *device);
void rp1_gpclk_lifetime_put(struct rp1_gpclk_device *device);

#endif /* RP1_GPCLK_LIFETIME_H */
