// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/capability.h>
#include <linux/compat.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/random.h>
#include <linux/uaccess.h>
#include <linux/rp1_route_admin.h>
#include "rp1_gpclk/version.h"
#include "consumer.h"
#include "state.h"
#include "overlays.h"

static DEFINE_MUTEX(route_lock);
static struct rp1_route_state state;
static u64 session;
static u64 generation;
static bool consumer;
static bool consumer_fault;
static bool pinned;

/* No node references survive an overlay call. Refuse existing firmware nodes
 * and canonical pinctrl names: overlay merge must not modify foreign objects.
 * Conflicting privileged OF administration is excluded by the operator contract.
 */
static bool foreign_route_nodes(void)
{
	static const char * const names[] = {
		"rp1-gpclk-gpio4-safe", "rp1-gpclk-gpio4-active",
		"rp1-gpclk-gpio20-safe", "rp1-gpclk-gpio20-active",
		"rp1-gpclk-dkms-gpio4", "rp1-gpclk-dkms-gpio20",
	};
	struct device_node *node;
	unsigned int i;

	node = of_find_compatible_node(NULL, NULL, "wsprrypi,rp1-gpclk-dkms-v1");
	if (node) {
		of_node_put(node);
		return true;
	}
	for (i = 0; i < ARRAY_SIZE(names); i++) {
		node = of_find_node_by_name(NULL, names[i]);
		if (node) {
			of_node_put(node);
			return true;
		}
	}
	return false;
}

static struct device_node *single_available_compatible(const char *compatible)
{
	struct device_node *node = NULL;
	struct device_node *match = NULL;

	while ((node = of_find_compatible_node(node, NULL, compatible))) {
		if (!of_device_is_available(node))
			continue;
		if (match) {
			of_node_put(match);
			of_node_put(node);
			return NULL;
		}
		match = of_node_get(node);
	}
	return match;
}

static bool single_rp1_present(void)
{
	struct device_node *clocks, *gpio, *clocks_parent, *gpio_parent, *dma;
	bool valid = false;

	/* Stock firmware describes the RP1 bus as a simple-bus, not with a
	 * marketing-model or rp1-compatible string. Identify one RP1 topology by
	 * its unique clock and GPIO providers and a sibling DMA provider.
	 */
	clocks = single_available_compatible("raspberrypi,rp1-clocks");
	gpio = single_available_compatible("raspberrypi,rp1-gpio");
	if (!clocks || !gpio)
		goto out;
	clocks_parent = of_get_parent(clocks);
	gpio_parent = of_get_parent(gpio);
	if (!clocks_parent || !gpio_parent || clocks_parent != gpio_parent)
		goto put_parents;
	dma = of_get_compatible_child(clocks_parent, "snps,axi-dma-1.01a");
	valid = dma != NULL;
	of_node_put(dma);
put_parents:
	of_node_put(gpio_parent);
	of_node_put(clocks_parent);
out:
	of_node_put(gpio);
	of_node_put(clocks);
	return valid;
}

int rp1_route_consumer_attach(void)
{
	int ret = 0;

	/* OF notification may trigger probe/module work during an overlay syscall.
	 * Never wait recursively on a controller operation in that path.
	 */
	if (!mutex_trylock(&route_lock))
		return -EBUSY;
	if (consumer || state.fault || state.id <= 0)
		ret = -EPERM;
	else
		consumer = true;
	mutex_unlock(&route_lock);
	return ret;
}
EXPORT_SYMBOL_GPL(rp1_route_consumer_attach);

void rp1_route_consumer_detach(bool cleanup_failed)
{
	mutex_lock(&route_lock);
	consumer = false;
	if (cleanup_failed) {
		consumer_fault = true;
		state.fault = 1;
		state.error = -EIO;
	}
	mutex_unlock(&route_lock);
}
EXPORT_SYMBOL_GPL(rp1_route_consumer_detach);

static long route_ioctl(struct file *file, unsigned int command, unsigned long arg)
{
	struct rp1_route_admin request, result = { 0 };
	void __user *address = (void __user *)arg;
	int ret = 0, id;
	unsigned int route;

	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	if (command != RP1_ROUTE_ADMIN)
		return -ENOTTY;
	if (copy_from_user(&request, address, sizeof(request)))
		return -EFAULT;
	if (request.reserved0 || request.reserved ||
	    request.overlay_id || request.last_error || request.active_route ||
	    request.flags || request.reserved2[0] || request.reserved2[1] ||
	    request.operation > RP1_ROUTE_REMOVE ||
	    (request.operation == RP1_ROUTE_APPLY ?
	     (request.route != 1 && request.route != 2) : request.route != 0))
		return -EINVAL;
	if (request.operation == RP1_ROUTE_STATUS &&
	    (request.session || request.generation))
		return -EINVAL;
	if (!mutex_trylock(&route_lock))
		return -EBUSY;
	if (request.operation != RP1_ROUTE_STATUS) {
		if (request.session != session || request.generation != generation) {
			ret = -ESTALE;
			goto out;
		}
		if (consumer || consumer_fault || generation == U64_MAX ||
		    (request.operation == RP1_ROUTE_APPLY && (state.id || state.fault)) ||
		    (request.operation == RP1_ROUTE_REMOVE && state.id <= 0)) {
			ret = -EBUSY;
			goto out;
		}
		if (!pinned) {
			/* fops.owner holds the module live; retain it after this fd closes. */
			__module_get(THIS_MODULE);
			pinned = true;
		}
		generation++;
		if (request.operation == RP1_ROUTE_APPLY) {
			route = request.route;
			id = 0;
			if (foreign_route_nodes())
				ret = -EEXIST;
			else if (route == 1)
				ret = of_overlay_fdt_apply(gpio4_dtbo, sizeof(gpio4_dtbo), &id, NULL);
			else
				ret = of_overlay_fdt_apply(gpio20_dtbo, sizeof(gpio20_dtbo), &id, NULL);
			if (!ret && id <= 0)
				ret = -EIO;
		} else {
			route = state.route;
			id = state.id;
			ret = of_overlay_remove(&id);
			if (!ret && (id || foreign_route_nodes()))
				ret = -EIO;
		}
		rp1_route_result(&state, route, id, ret);
		if (!state.id && !state.fault) {
			pinned = false;
			module_put(THIS_MODULE);
		}
		/* Actual effect errno is preserved in readback even if copy_to_user
		 * fails or the caller dies. ioctl success means response delivery only.
		 */
		ret = 0;
	}
	result.session = session;
	result.generation = generation;
	result.overlay_id = state.id;
	result.last_error = state.error;
	result.active_route = state.route;
	result.flags = (state.fault ? RP1_ROUTE_FAULT : 0) |
		(consumer ? RP1_ROUTE_CONSUMER : 0) | (pinned ? RP1_ROUTE_PINNED : 0);
	if (copy_to_user(address, &result, sizeof(result)))
		ret = -EFAULT;
out:
	mutex_unlock(&route_lock);
	return ret;
}

static const struct file_operations route_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = route_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = compat_ptr_ioctl,
#endif
};
static struct miscdevice route_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "rp1-route-admin",
	.fops = &route_fops,
	.mode = 0600,
};
static int __init route_init(void)
{
	if (!IS_ENABLED(CONFIG_OF_OVERLAY) ||
	    !single_rp1_present() || foreign_route_nodes())
		return -EOPNOTSUPP;
	do {
		session = get_random_u64();
	} while (!session);
	return misc_register(&route_device);
}
static void __exit route_exit(void)
{
	/* Ownership/fault pins and the consumer dependency prevent ordinary exit.
	 * Never discard an overlay handle in a void module-exit callback.
	 */
	misc_deregister(&route_device);
}
module_init(route_init);
module_exit(route_exit);
MODULE_LICENSE("Dual MIT/GPL");
MODULE_DESCRIPTION("Experimental clock-disabled RP1 route administrator");
MODULE_VERSION(RP1_GPCLK_MODULE_VERSION);
