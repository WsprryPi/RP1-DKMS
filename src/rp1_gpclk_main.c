// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/atomic.h>
#include <linux/fs.h>
#include <linux/limits.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/stringify.h>
#include <linux/utsname.h>

#include "rp1_gpclk/bootstrap_policy.h"
#include "rp1_gpclk/compatibility.h"
#include "rp1_gpclk/device.h"
#include "rp1_gpclk/execution.h"
#include "rp1_gpclk/kernel_api.h"
#include "rp1_gpclk/lifetime.h"
#include "rp1_gpclk/target_fault.h"
#include "rp1_gpclk/uapi_dispatch.h"
#include "rp1_gpclk/version.h"

#ifdef RP1_RUNTIME_CONTROLLER
#include "../controller/consumer.h"
static bool route_cleanup_failed;
#endif

static bool output_inhibit;
module_param(output_inhibit, bool, 0444);
MODULE_PARM_DESC(output_inhibit,
	"Disable output for clock-disabled development and lifecycle testing");

bool rp1_gpclk_output_inhibited(void)
{
	return output_inhibit;
}

bool rp1_gpclk_operationally_ready(const struct rp1_gpclk_device *device)
{
	return device && device->operational_ready && !output_inhibit;
}

static bool rp1_gpclk_release_identity_allowed(
	const struct rp1_gpclk_device *device)
{
	return device &&
		rp1_gpclk_compatibility_allowed(device->route,
			utsname()->machine,
			RP1_GPCLK_MODULE_VERSION,
			device->clock && device->dma_chan &&
			device->pinctrl &&
			device->tick_dma0 && device->dma_tick0 &&
			device->rate_exclusive);
}

static atomic64_t rp1_gpclk_next_owner = ATOMIC64_INIT(0);
static atomic_t rp1_gpclk_endpoint_owner = ATOMIC_INIT(0);

static int rp1_gpclk_endpoint_claim(struct rp1_gpclk_device *device)
{
	if (atomic_cmpxchg(&rp1_gpclk_endpoint_owner, 0, 1) != 0)
		return -EBUSY;
	device->endpoint_claimed = true;
	return 0;
}

static void rp1_gpclk_endpoint_release(struct rp1_gpclk_device *device)
{
	if (!device->endpoint_claimed)
		return;
	device->endpoint_claimed = false;
	atomic_set_release(&rp1_gpclk_endpoint_owner, 0);
}

static int rp1_gpclk_allocate_owner(u64 *owner)
{
	s64 owner_sequence;

	for (;;) {
		owner_sequence = atomic64_read(&rp1_gpclk_next_owner);
		if (owner_sequence == S64_MAX)
			return -EOVERFLOW;
		if (atomic64_cmpxchg(&rp1_gpclk_next_owner, owner_sequence,
				     owner_sequence + 1) == owner_sequence) {
			*owner = (u64)(owner_sequence + 1);
			return 0;
		}
	}
}

static int rp1_gpclk_open(struct inode *inode, struct file *file)
{
	struct miscdevice *miscdev = file->private_data;
	struct rp1_gpclk_device *device =
		container_of(miscdev, struct rp1_gpclk_device, miscdev);
	struct rp1_gpclk_file *context;
	int ret;

	if (!rp1_gpclk_lifetime_get_live(device))
		return -ENODEV;
	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		rp1_gpclk_lifetime_put(device);
		return -ENOMEM;
	}
	context->device = device;
	ret = rp1_gpclk_allocate_owner(&context->owner);
	if (ret) {
		kfree(context);
		rp1_gpclk_lifetime_put(device);
		return ret;
	}
	file->private_data = context;
	return nonseekable_open(inode, file);
}

static int rp1_gpclk_release(struct inode *inode, struct file *file)
{
	struct rp1_gpclk_file *context = file->private_data;

	mutex_lock(&context->device->lock);
	if (rp1_gpclk_core_owner_close(&context->device->core,
					context->owner) == RP1_GPCLK_CORE_OK)
		rp1_gpclk_execution_request_stop(context->device,
			RP1_GPCLK_REASON_OWNER_CLOSED);
	mutex_unlock(&context->device->lock);
	rp1_gpclk_lifetime_put(context->device);
	kfree(context);
	return 0;
}

static long rp1_gpclk_ioctl(struct file *file, unsigned int command,
			    unsigned long argument)
{
	return rp1_gpclk_uapi_dispatch(file, command, argument);
}

static const struct file_operations rp1_gpclk_fops = {
	.owner = THIS_MODULE,
	.open = rp1_gpclk_open,
	.release = rp1_gpclk_release,
	.unlocked_ioctl = rp1_gpclk_ioctl,
};

static int rp1_gpclk_probe(struct platform_device *pdev)
{
	struct rp1_gpclk_device *device;
	int ret;

	device = kzalloc(sizeof(*device), GFP_KERNEL);
	if (!device)
		return -ENOMEM;
	device->dev = &pdev->dev;
	ret = rp1_gpclk_lifetime_init(device);
	if (ret)
		goto free_device;
	rp1_gpclk_core_init(&device->core);
	ret = rp1_gpclk_execution_init(device);
	if (ret)
		goto put_device;
	ret = rp1_gpclk_dt_validate(device);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "device-tree identity validation failed\n");
		goto put_device;
	}
	ret = rp1_gpclk_endpoint_claim(device);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "endpoint resource ownership conflict\n");
		goto put_device;
	}
	ret = rp1_gpclk_clock_acquire(device);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "clock resource acquisition failed\n");
		goto release_resources;
	}
	ret = rp1_gpclk_pinctrl_acquire(device);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "pinctrl resource acquisition failed\n");
		goto release_resources;
	}
	ret = rp1_gpclk_tick_resources_acquire(pdev, device);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "DMA-tick resource acquisition failed\n");
		goto release_resources;
	}
	ret = rp1_gpclk_dma_acquire(device);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "DMA resource acquisition failed\n");
		goto release_resources;
	}
	device->operational_ready = rp1_gpclk_release_identity_allowed(device);
	if (!device->operational_ready) {
		ret = -EOPNOTSUPP;
		dev_err_probe(&pdev->dev, ret,
			      "RP1 route resources are not operationally supported\n");
		goto release_resources;
	}

	device->miscdev.minor = MISC_DYNAMIC_MINOR;
	device->miscdev.name = "rp1-gpclk";
	device->miscdev.fops = &rp1_gpclk_fops;
	device->miscdev.parent = &pdev->dev;
	device->miscdev.mode = 0600;
	ret = misc_register(&device->miscdev);
	if (ret) {
		dev_err_probe(&pdev->dev, ret,
			      "misc-device registration failed\n");
		goto release_resources;
	}
	device->misc_registered = true;
	platform_set_drvdata(pdev, device);
	dev_info(&pdev->dev, "probe complete; /dev/rp1-gpclk registered\n");
	return 0;

release_resources:
	rp1_gpclk_resources_release(device);
	rp1_gpclk_endpoint_release(device);
put_device:
	rp1_gpclk_lifetime_mark_dead(device);
	rp1_gpclk_lifetime_put(device);
	return ret;
free_device:
	kfree(device);
	return ret;
}

static void rp1_gpclk_remove(struct platform_device *pdev)
{
	struct rp1_gpclk_device *device = platform_get_drvdata(pdev);

	if (!device)
		return;
	if (device->misc_registered) {
		misc_deregister(&device->miscdev);
		device->misc_registered = false;
	}
	rp1_gpclk_lifetime_mark_dead(device);
	mutex_lock(&device->lock);
	rp1_gpclk_core_mark_dead(&device->core,
				 RP1_GPCLK_REASON_PROVIDER_REMOVED);
	mutex_unlock(&device->lock);
	rp1_gpclk_execution_quiesce(device,
				    RP1_GPCLK_REASON_PROVIDER_REMOVED);
	rp1_gpclk_quiesce(device);
#ifdef RP1_RUNTIME_CONTROLLER
	if (device->core.value.cleanup_fault || device->clock_cleanup_error ||
	    device->dma_submitted || device->clock_enabled ||
	    device->clock_prepared || device->parent_selected ||
	    device->tick_state_captured || device->pins_active_selected ||
	    READ_ONCE(device->worker))
		route_cleanup_failed = true;
#endif
	rp1_gpclk_resources_release(device);
	rp1_gpclk_endpoint_release(device);
	platform_set_drvdata(pdev, NULL);
	rp1_gpclk_lifetime_put(device);
}

static const struct of_device_id rp1_gpclk_of_match[] = {
	{ .compatible = "wsprrypi,rp1-gpclk-dkms-v1" },
	{ }
};
#ifndef RP1_RUNTIME_CONTROLLER
/* Runtime administration explicitly loads the checked consumer after APPLY.
 * Do not race that step with OF-modalias autoload on the new endpoint.
 */
MODULE_DEVICE_TABLE(of, rp1_gpclk_of_match);
#endif

static DEFINE_MUTEX(rp1_gpclk_bootstrap_lock);
static struct platform_device *rp1_gpclk_created_pdev;
static struct device_node *rp1_gpclk_creating_node;
static bool rp1_gpclk_creation_removed;

static int rp1_gpclk_platform_bus_event(struct notifier_block *notifier,
					unsigned long event, void *data)
{
	struct device *dev = data;

	(void)notifier;
	if (event != BUS_NOTIFY_DEL_DEVICE)
		return NOTIFY_DONE;

	mutex_lock(&rp1_gpclk_bootstrap_lock);
	if (rp1_gpclk_created_pdev &&
	    &rp1_gpclk_created_pdev->dev == dev)
		rp1_gpclk_created_pdev = NULL;
	if (rp1_gpclk_creating_node &&
	    dev->of_node == rp1_gpclk_creating_node)
		rp1_gpclk_creation_removed = true;
	mutex_unlock(&rp1_gpclk_bootstrap_lock);
	return NOTIFY_OK;
}

static struct notifier_block rp1_gpclk_platform_bus_notifier = {
	.notifier_call = rp1_gpclk_platform_bus_event,
};

static struct platform_driver rp1_gpclk_driver = {
	.probe = rp1_gpclk_probe,
	.remove = rp1_gpclk_remove,
	.driver = {
		.name = "rp1-gpclk-dkms",
		.of_match_table = rp1_gpclk_of_match,
	},
};

static void rp1_gpclk_find_endpoint(struct device_node **selected,
				   unsigned int *matching_nodes)
{
	struct device_node *node;

	*selected = NULL;
	*matching_nodes = 0;
	for_each_matching_node(node, rp1_gpclk_of_match) {
		(*matching_nodes)++;
		if (*matching_nodes == 1U)
			*selected = of_node_get(node);
	}
}

static int rp1_gpclk_validate_endpoint_topology(void)
{
	struct device_node *node;
	unsigned int matching_nodes;
	int ret;

	rp1_gpclk_find_endpoint(&node, &matching_nodes);
	if (matching_nodes != 1U) {
		pr_err("rp1-gpclk-dkms: pre-registration topology rejected %u matching nodes\n",
		       matching_nodes);
		return matching_nodes ? -EEXIST : -ENODEV;
	}
	ret = of_device_is_available(node) ? 0 : -ENODEV;
	of_node_put(node);
	return ret;
}

static bool rp1_gpclk_bound_to_this_driver(struct platform_device *pdev)
{
	bool bound;

	device_lock(&pdev->dev);
	bound = pdev->dev.driver == &rp1_gpclk_driver.driver;
	device_unlock(&pdev->dev);
	return bound;
}

static bool rp1_gpclk_detach_created_device(struct platform_device *pdev)
{
	bool owned;

	mutex_lock(&rp1_gpclk_bootstrap_lock);
	owned = rp1_gpclk_created_pdev == pdev;
	if (owned)
		rp1_gpclk_created_pdev = NULL;
	mutex_unlock(&rp1_gpclk_bootstrap_lock);
	return owned;
}

static void
rp1_gpclk_unregister_created_device(struct platform_device *pdev)
{
	struct device_node *node = of_node_get(pdev->dev.of_node);

	platform_device_unregister(pdev);
	if (node) {
		of_node_clear_flag(node, OF_POPULATED);
		of_node_put(node);
	}
}

static struct platform_device *
rp1_gpclk_find_instantiated_ancestor(struct device_node *node)
{
	struct platform_device *pdev;
	struct device_node *ancestor;
	struct device_node *parent;

	ancestor = of_get_parent(node);
	while (ancestor) {
		pdev = of_find_device_by_node(ancestor);
		if (pdev) {
			of_node_put(ancestor);
			return pdev;
		}
		parent = of_get_parent(ancestor);
		of_node_put(ancestor);
		ancestor = parent;
	}
	return NULL;
}

static int rp1_gpclk_bootstrap_endpoint(void)
{
	struct platform_device *existing;
	struct platform_device *parent;
	struct platform_device *created;
	struct device_node *node;
	enum rp1_gpclk_bootstrap_action action;
	unsigned int matching_nodes;
	bool removed_during_creation;
	bool bound;
	int ret;

	rp1_gpclk_find_endpoint(&node, &matching_nodes);
	if (!node) {
		action = rp1_gpclk_bootstrap_decide(matching_nodes, false,
						     false, false);
		ret = action == RP1_GPCLK_BOOTSTRAP_REJECT_AMBIGUOUS ?
			-EEXIST : -ENODEV;
		pr_err("rp1-gpclk-dkms: endpoint discovery rejected %u matching nodes\n",
		       matching_nodes);
		return ret;
	}

	existing = of_find_device_by_node(node);
	action = rp1_gpclk_bootstrap_decide(
		matching_nodes, of_device_is_available(node), existing != NULL,
		existing && rp1_gpclk_bound_to_this_driver(existing));

	if (action == RP1_GPCLK_BOOTSTRAP_USE_EXISTING) {
		dev_info(&existing->dev,
			 "using kernel-created RP1 GPCLK platform device\n");
		platform_device_put(existing);
		of_node_put(node);
		return 0;
	}
	if (existing) {
		dev_err(&existing->dev,
			"RP1 GPCLK endpoint exists but is not bound to this driver\n");
		platform_device_put(existing);
	}
	if (action != RP1_GPCLK_BOOTSTRAP_CREATE) {
		ret = action == RP1_GPCLK_BOOTSTRAP_REJECT_AMBIGUOUS ?
			-EEXIST : action == RP1_GPCLK_BOOTSTRAP_REJECT_UNBOUND ?
			-EBUSY : -ENODEV;
		pr_err("rp1-gpclk-dkms: endpoint bootstrap rejected action %d\n",
		       action);
		of_node_put(node);
		return ret;
	}

	parent = rp1_gpclk_find_instantiated_ancestor(node);
	if (!parent) {
		pr_err("rp1-gpclk-dkms: instantiated platform ancestor is absent\n");
		of_node_put(node);
		return -ENODEV;
	}
	mutex_lock(&rp1_gpclk_bootstrap_lock);
	rp1_gpclk_creating_node = node;
	rp1_gpclk_creation_removed = false;
	mutex_unlock(&rp1_gpclk_bootstrap_lock);
	created = of_platform_device_create(node, NULL, &parent->dev);
	platform_device_put(parent);
	mutex_lock(&rp1_gpclk_bootstrap_lock);
	removed_during_creation = rp1_gpclk_creation_removed;
	rp1_gpclk_creating_node = NULL;
	if (created && !removed_during_creation) {
		get_device(&created->dev);
		rp1_gpclk_created_pdev = created;
	}
	mutex_unlock(&rp1_gpclk_bootstrap_lock);
	of_node_put(node);
	if (!created) {
		pr_err("rp1-gpclk-dkms: failed to create endpoint platform device\n");
		return -ENODEV;
	}
	if (removed_during_creation) {
		pr_err("rp1-gpclk-dkms: endpoint was removed during creation\n");
		return -ENODEV;
	}
	bound = rp1_gpclk_bound_to_this_driver(created);
	if (!bound) {
		dev_err(&created->dev,
			"created endpoint did not bind synchronously\n");
		if (rp1_gpclk_detach_created_device(created))
			rp1_gpclk_unregister_created_device(created);
		put_device(&created->dev);
		return -ENODEV;
	}

	mutex_lock(&rp1_gpclk_bootstrap_lock);
	bound = rp1_gpclk_created_pdev == created;
	mutex_unlock(&rp1_gpclk_bootstrap_lock);
	if (!bound) {
		put_device(&created->dev);
		pr_err("rp1-gpclk-dkms: endpoint was removed before bootstrap completed\n");
		return -ENODEV;
	}
	dev_info(&created->dev,
		 "created and bound boot-time RP1 GPCLK platform device\n");
	put_device(&created->dev);
	return 0;
}

static int __init rp1_gpclk_init(void)
{
	int ret;

#ifdef RP1_GPCLK_TARGET_FAULT_STAGE
	pr_warn("rp1-gpclk-dkms: TEST-ONLY fault artifact stage=%u\n",
		RP1_GPCLK_TARGET_FAULT_STAGE);
#endif
#ifdef RP1_RUNTIME_CONTROLLER
	ret = rp1_route_consumer_attach();
	if (ret)
		return ret;
#endif
	ret = rp1_gpclk_validate_endpoint_topology();
	if (ret)
		goto detach_controller;
	ret = bus_register_notifier(&platform_bus_type,
				    &rp1_gpclk_platform_bus_notifier);
	if (ret)
		goto detach_controller;
	ret = platform_driver_register(&rp1_gpclk_driver);
	if (ret)
		goto unregister_notifier;
	ret = rp1_gpclk_bootstrap_endpoint();
	if (ret)
		goto unregister_driver;
	return 0;

unregister_driver:
	platform_driver_unregister(&rp1_gpclk_driver);
unregister_notifier:
	bus_unregister_notifier(&platform_bus_type,
				&rp1_gpclk_platform_bus_notifier);
detach_controller:
#ifdef RP1_RUNTIME_CONTROLLER
	rp1_route_consumer_detach(true);
#endif
	return ret;
}

static void __exit rp1_gpclk_exit(void)
{
	struct platform_device *created;

	mutex_lock(&rp1_gpclk_bootstrap_lock);
	created = rp1_gpclk_created_pdev;
	if (created)
		rp1_gpclk_created_pdev = NULL;
	mutex_unlock(&rp1_gpclk_bootstrap_lock);
	if (created)
		rp1_gpclk_unregister_created_device(created);
	platform_driver_unregister(&rp1_gpclk_driver);
	bus_unregister_notifier(&platform_bus_type,
				&rp1_gpclk_platform_bus_notifier);
#ifdef RP1_RUNTIME_CONTROLLER
	rp1_route_consumer_detach(route_cleanup_failed);
#endif
}

module_init(rp1_gpclk_init);
module_exit(rp1_gpclk_exit);

MODULE_AUTHOR("Lee Bussy");
MODULE_DESCRIPTION("Experimental RP1 GPCLK controlled-output provider");
MODULE_LICENSE("Dual MIT/GPL");
MODULE_VERSION(RP1_GPCLK_MODULE_VERSION);
#ifdef RP1_GPCLK_TARGET_FAULT_STAGE
MODULE_INFO(rp1_target_fault_stage,
	    __stringify(RP1_GPCLK_TARGET_FAULT_STAGE));
#endif
#ifdef RP1_RUNTIME_CONTROLLER
MODULE_INFO(rp1_runtime_controller, "1");
#endif
