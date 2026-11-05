// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/slab.h>

#include "rp1_gpclk/device.h"
#include "rp1_gpclk/lifetime.h"

static void rp1_gpclk_lifetime_destroy(struct kref *refcount)
{
	struct rp1_gpclk_device *device =
		container_of(refcount, struct rp1_gpclk_device, refcount);

	mutex_destroy(&device->lock);
	kfree(device);
}

int rp1_gpclk_lifetime_init(struct rp1_gpclk_device *device)
{
	if (!device)
		return -EINVAL;
	kref_init(&device->refcount);
	mutex_init(&device->lock);
	device->dead = false;
	return 0;
}

bool rp1_gpclk_lifetime_get_live(struct rp1_gpclk_device *device)
{
	bool live;

	mutex_lock(&device->lock);
	live = !device->dead;
	if (live)
		kref_get(&device->refcount);
	mutex_unlock(&device->lock);
	return live;
}

void rp1_gpclk_lifetime_mark_dead(struct rp1_gpclk_device *device)
{
	mutex_lock(&device->lock);
	device->dead = true;
	mutex_unlock(&device->lock);
}

void rp1_gpclk_lifetime_put(struct rp1_gpclk_device *device)
{
	kref_put(&device->refcount, rp1_gpclk_lifetime_destroy);
}
