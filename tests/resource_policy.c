// SPDX-License-Identifier: MIT
#include <stdint.h>
#include <stdio.h>

#include "rp1_gpclk/resource_policy.h"

static int failures;

enum resource_stage { STAGE_DT, STAGE_CLOCK, STAGE_PINCTRL, STAGE_DMA,
	STAGE_MISC, STAGE_COUNT };

struct resource_model {
	unsigned int acquired;
	unsigned int released;
	unsigned int trace[STAGE_COUNT];
	unsigned int trace_count;
	unsigned int references;
	unsigned int dead;
	unsigned int destroyed;
};

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
		failures++; \
	} \
} while (0)

static void model_release(struct resource_model *model)
{
	int stage;

	for (stage = STAGE_COUNT - 1; stage >= 0; stage--) {
		unsigned int bit = 1U << stage;

		if (!(model->acquired & bit) || (model->released & bit))
			continue;
		model->released |= bit;
		model->trace[model->trace_count++] = (unsigned int)stage;
	}
}

static void model_remove(struct resource_model *model)
{
	model->dead = 1;
	model_release(model);
	if (--model->references == 0)
		model->destroyed = 1;
}

int main(void)
{
	__u64 target = 0xfeedU;
	unsigned int fail;

	CHECK(rp1_gpclk_route_pin_validate(RP1_GPCLK_ROUTE_GPIO4, 4) == 0);
	CHECK(rp1_gpclk_route_pin_validate(RP1_GPCLK_ROUTE_GPIO20, 20) == 0);
	CHECK(rp1_gpclk_route_pin_validate(RP1_GPCLK_ROUTE_INVALID, 4) != 0);
	CHECK(rp1_gpclk_route_pin_validate(3, 20) != 0);
	CHECK(rp1_gpclk_route_pin_validate(99, 99) != 0);
	CHECK(rp1_gpclk_route_pin_validate(RP1_GPCLK_ROUTE_GPIO4, 20) != 0);
	CHECK(rp1_gpclk_route_pin_validate(RP1_GPCLK_ROUTE_GPIO20, 4) != 0);
	CHECK(rp1_gpclk_route_endpoint_validate(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_GPIO4_ENDPOINT_NAME) == 0);
	CHECK(rp1_gpclk_route_endpoint_validate(RP1_GPCLK_ROUTE_GPIO20,
		RP1_GPCLK_GPIO20_ENDPOINT_NAME) == 0);
	CHECK(rp1_gpclk_route_endpoint_validate(RP1_GPCLK_ROUTE_GPIO4,
		RP1_GPCLK_GPIO20_ENDPOINT_NAME) != 0);
	CHECK(rp1_gpclk_route_endpoint_validate(RP1_GPCLK_ROUTE_GPIO20,
		RP1_GPCLK_GPIO4_ENDPOINT_NAME) != 0);
	CHECK(rp1_gpclk_route_endpoint_validate(RP1_GPCLK_ROUTE_GPIO4,
		"rp1-gpclk-dkms") != 0);
	CHECK(rp1_gpclk_route_endpoint_validate(RP1_GPCLK_ROUTE_GPIO20,
		NULL) != 0);

	CHECK(rp1_gpclk_derive_target(0x10000000U, 0x100003ffU,
		RP1_GPCLK_DIV_FRAC_OFFSET, RP1_GPCLK_REGISTER_BYTES,
		&target) == 0);
	CHECK(target == 0x1000017cU);
	CHECK(rp1_gpclk_derive_target(0, 0x17fU, 0x17cU, 4, &target) == 0);
	CHECK(rp1_gpclk_derive_target(0, 0x17eU, 0x17cU, 4, &target) != 0);
	CHECK(rp1_gpclk_derive_target(0x1000U, 0x1003U, 4, 4, &target) != 0);
	CHECK(rp1_gpclk_derive_target(UINT64_MAX - 1, UINT64_MAX,
		4, 4, &target) != 0);
	CHECK(rp1_gpclk_derive_target(0, UINT64_MAX, UINT64_MAX - 1,
		4, &target) != 0);
	CHECK(rp1_gpclk_derive_target(4, 3, 0, 4, &target) != 0);
	CHECK(rp1_gpclk_derive_target(0, 3, 0, 0, &target) != 0);
	CHECK(rp1_gpclk_derive_target(0, 3, 0, 4, NULL) != 0);
	CHECK(rp1_gpclk_derive_target(1, 8, 0, 4, &target) != 0);

	for (fail = 0; fail <= STAGE_COUNT; fail++) {
		struct resource_model model = { .references = 1 };
		unsigned int stage;

		for (stage = 0; stage < STAGE_COUNT; stage++) {
			if (stage == fail)
				break;
			model.acquired |= 1U << stage;
		}
		model_release(&model);
		model_release(&model);
		CHECK(model.released == model.acquired);
		CHECK(model.trace_count == stage);
		while (model.trace_count > 1) {
			unsigned int i = --model.trace_count;
			CHECK(model.trace[i - 1] > model.trace[i]);
		}
	}
	{
		struct resource_model model = {
			.acquired = (1U << STAGE_COUNT) - 1,
			.references = 2,
		};

		model_remove(&model);
		CHECK(model.dead && !model.destroyed && model.references == 1);
		CHECK(model.dead); /* An open attempt must reject this state. */
		if (--model.references == 0)
			model.destroyed = 1;
		CHECK(model.destroyed);
	}

	if (failures)
		return 1;
	puts("resource policy: PASS (production route/target derivation; independent unwind/lifetime model)");
	return 0;
}
