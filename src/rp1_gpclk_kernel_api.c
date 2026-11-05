// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/clk.h>
#include <linux/dmaengine.h>
#include <linux/err.h>
#include <linux/of_address.h>
#include <linux/of_clk.h>
#include <linux/overflow.h>
#include <linux/platform_device.h>
#include <linux/pinctrl/consumer.h>

#include "rp1_gpclk/device.h"
#include "rp1_gpclk/kernel_api.h"
#include "rp1_gpclk/resource_policy.h"

int rp1_gpclk_dt_validate(struct rp1_gpclk_device *device)
{
	struct of_phandle_args clock_spec;
	struct of_phandle_args parent_spec;
	struct of_phandle_args dma_spec;
	struct resource resource;
	struct resource rp1_resource;
	__u64 divider_phys;
	__u32 pin;
	__u32 route;
	int ret;

	if (!device || !device->dev || !device->dev->of_node)
		return -ENODEV;
	if (of_property_count_strings(device->dev->of_node, "clock-names") != 2 ||
	    of_count_phandle_with_args(device->dev->of_node, "clocks",
				       "#clock-cells") != 2)
		return -EINVAL;
	if (of_property_match_string(device->dev->of_node, "clock-names",
				     "gpclk") != 0 ||
	    of_property_match_string(device->dev->of_node, "clock-names",
				     "parent") != 1)
		return -EINVAL;
	ret = of_property_read_u32(device->dev->of_node, "wsprrypi,route",
				   &route);
	if (ret || (route != RP1_GPCLK_ROUTE_GPIO4 &&
		    route != RP1_GPCLK_ROUTE_GPIO20))
		return -EINVAL;
	if (rp1_gpclk_route_endpoint_validate(route,
					     device->dev->of_node->name))
		return -EINVAL;
	ret = of_property_read_u32(device->dev->of_node, "wsprrypi,pin", &pin);
	if (ret || rp1_gpclk_route_pin_validate(route, pin))
		return -EINVAL;
	device->route = route;
	ret = of_parse_phandle_with_args(device->dev->of_node, "clocks",
					 "#clock-cells", 0, &clock_spec);
	if (ret)
		return ret;
	if (!of_device_is_compatible(clock_spec.np,
				     RP1_GPCLK_PROVIDER_COMPATIBLE) ||
	    clock_spec.args_count != 1 ||
	    clock_spec.args[0] != RP1_GPCLK_CLOCK_ID) {
		ret = -EINVAL;
		goto put_clock_node;
	}
	ret = of_parse_phandle_with_args(device->dev->of_node, "clocks",
					 "#clock-cells", 1, &parent_spec);
	if (ret)
		goto put_clock_node;
	if (!of_device_is_compatible(parent_spec.np,
				     RP1_GPCLK_PARENT_PROVIDER_COMPATIBLE) ||
	    parent_spec.np != clock_spec.np || parent_spec.args_count != 1 ||
	    parent_spec.args[0] != RP1_GPCLK_PARENT_CLOCK_ID) {
		ret = -EINVAL;
		goto put_parent_node;
	}
	ret = of_parse_phandle_with_args(device->dev->of_node, "dmas",
					 "#dma-cells", 0, &dma_spec);
	if (ret)
		goto put_parent_node;
	if (!of_device_is_compatible(dma_spec.np,
				     RP1_GPCLK_DMA_PROVIDER_COMPATIBLE) ||
	    dma_spec.args_count != 1 ||
	    dma_spec.args[0] != RP1_GPCLK_DMA_REQUEST ||
	    dma_spec.np->parent != clock_spec.np->parent ||
	    device->dev->of_node->parent != clock_spec.np->parent) {
		ret = -EINVAL;
		goto put_dma_node;
	}
	ret = of_address_to_resource(clock_spec.np, 0, &resource);
	if (ret)
		goto put_dma_node;
	if (resource_type(&resource) != IORESOURCE_MEM) {
		ret = -EINVAL;
		goto put_dma_node;
	}
	ret = of_range_to_resource(clock_spec.np->parent, 0, &rp1_resource);
	if (ret || resource_type(&rp1_resource) != IORESOURCE_MEM ||
	    resource.start < rp1_resource.start ||
	    resource.end > rp1_resource.end) {
		ret = ret ?: -EINVAL;
		goto put_dma_node;
	}
	device->rp1_phys_start = rp1_resource.start;
	device->rp1_phys_end = rp1_resource.end;
	if (rp1_gpclk_derive_target(resource.start, resource.end,
				    RP1_GPCLK_DIV_FRAC_OFFSET,
				    RP1_GPCLK_REGISTER_BYTES, &divider_phys)) {
		device->divider_phys = 0;
		ret = -ERANGE;
	} else {
		device->divider_phys = (phys_addr_t)divider_phys;
	}
put_dma_node:
	of_node_put(dma_spec.np);
put_parent_node:
	of_node_put(parent_spec.np);
put_clock_node:
	of_node_put(clock_spec.np);
	return ret;
}

int rp1_gpclk_clock_acquire(struct rp1_gpclk_device *device)
{
	int ret;

	device->clock = clk_get(device->dev, "gpclk");
	if (IS_ERR(device->clock)) {
		ret = PTR_ERR(device->clock);
		device->clock = NULL;
		return ret;
	}
	ret = clk_rate_exclusive_get(device->clock);
	if (ret)
		goto put_clock;
	device->rate_exclusive = true;
	device->parent_clock = clk_get(device->dev, "parent");
	if (IS_ERR(device->parent_clock)) {
		ret = PTR_ERR(device->parent_clock);
		device->parent_clock = NULL;
		goto put_exclusive;
	}
	return 0;
put_exclusive:
	clk_rate_exclusive_put(device->clock);
	device->rate_exclusive = false;
put_clock:
	clk_put(device->clock);
	device->clock = NULL;
	return ret;
}

int rp1_gpclk_dma_acquire(struct rp1_gpclk_device *device)
{
	int ret;

	device->dma_chan = dma_request_chan(device->dev, "tx");
	if (IS_ERR(device->dma_chan)) {
		ret = PTR_ERR(device->dma_chan);
		device->dma_chan = NULL;
		return ret;
	}
	if (!device->dma_chan->device || !device->dma_chan->device->dev) {
		dma_release_channel(device->dma_chan);
		device->dma_chan = NULL;
		return -ENODEV;
	}
	/* DW AXI DMA translates this CPU-physical peripheral address itself. */
	device->divider_dma = (dma_addr_t)device->divider_phys;
	if ((phys_addr_t)device->divider_dma != device->divider_phys) {
		device->divider_dma = 0;
		dma_release_channel(device->dma_chan);
		device->dma_chan = NULL;
		return -ERANGE;
	}
	return 0;
}

int rp1_gpclk_pinctrl_acquire(struct rp1_gpclk_device *device)
{
	device->pinctrl = pinctrl_get(device->dev);
	if (IS_ERR(device->pinctrl))
		return PTR_ERR(device->pinctrl);
	device->pins_default = pinctrl_lookup_state(device->pinctrl, "default");
	if (IS_ERR(device->pins_default))
		return PTR_ERR(device->pins_default);
	device->pins_active = pinctrl_lookup_state(device->pinctrl, "active");
	if (IS_ERR(device->pins_active))
		return PTR_ERR(device->pins_active);
	device->pins_safe = pinctrl_lookup_state(device->pinctrl, "safe");
	if (IS_ERR(device->pins_safe))
		return PTR_ERR(device->pins_safe);
	return 0;
}

int rp1_gpclk_tick_resources_acquire(struct platform_device *pdev,
				     struct rp1_gpclk_device *device)
{
	struct resource *cycles;
	struct resource *tick;
	resource_size_t expected_cycles;
	resource_size_t expected_tick;

	cycles = platform_get_resource_byname(pdev, IORESOURCE_MEM,
					       "tick-dma0");
	tick = platform_get_resource_byname(pdev, IORESOURCE_MEM, "dma-tick0");
	if (!cycles || !tick ||
	    resource_size(cycles) != RP1_GPCLK_TICK_RESOURCE_BYTES ||
	    resource_size(tick) != RP1_GPCLK_TICK_RESOURCE_BYTES ||
	    resource_overlaps(cycles, tick) ||
	    check_add_overflow(device->rp1_phys_start,
			       (resource_size_t)RP1_GPCLK_TICK_DMA0_OFFSET,
			       &expected_cycles) ||
	    check_add_overflow(device->rp1_phys_start,
			       (resource_size_t)RP1_GPCLK_DMA_TICK0_OFFSET,
			       &expected_tick))
		return -EINVAL;
	if (cycles->start != expected_cycles || tick->start != expected_tick ||
	    cycles->end > device->rp1_phys_end ||
	    tick->end > device->rp1_phys_end)
		return -EINVAL;
	device->tick_dma0 = devm_ioremap_resource(&pdev->dev, cycles);
	if (IS_ERR(device->tick_dma0)) {
		int ret = PTR_ERR(device->tick_dma0);

		device->tick_dma0 = NULL;
		return ret;
	}
	device->dma_tick0 = devm_ioremap_resource(&pdev->dev, tick);
	if (IS_ERR(device->dma_tick0)) {
		int ret = PTR_ERR(device->dma_tick0);

		device->dma_tick0 = NULL;
		return ret;
	}
	device->tick_dma0_phys = cycles->start;
	device->dma_tick0_phys = tick->start;
	return 0;
}

void rp1_gpclk_quiesce(struct rp1_gpclk_device *device)
{
	/* Phase 2C cannot create a descriptor, callback, clock, or pin transition. */
}

void rp1_gpclk_resources_release(struct rp1_gpclk_device *device)
{
	if (device->dma_chan) {
		dma_release_channel(device->dma_chan);
		device->dma_chan = NULL;
	}
	device->divider_dma = 0;
	if (device->pinctrl && !IS_ERR(device->pinctrl)) {
		pinctrl_put(device->pinctrl);
		device->pinctrl = NULL;
		device->pins_default = NULL;
		device->pins_active = NULL;
		device->pins_safe = NULL;
	}
	if (device->parent_clock) {
		clk_put(device->parent_clock);
		device->parent_clock = NULL;
	}
	if (device->rate_exclusive) {
		clk_rate_exclusive_put(device->clock);
		device->rate_exclusive = false;
	}
	if (device->clock) {
		clk_put(device->clock);
		device->clock = NULL;
	}
	device->divider_phys = 0;
	device->rp1_phys_start = 0;
	device->rp1_phys_end = 0;
	device->tick_dma0 = NULL;
	device->dma_tick0 = NULL;
	device->tick_dma0_phys = 0;
	device->dma_tick0_phys = 0;
	device->route = RP1_GPCLK_ROUTE_INVALID;
}
