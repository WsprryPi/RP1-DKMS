// SPDX-License-Identifier: MIT
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "rp1_gpclk/execution_machine.h"

enum operation {
	OP_SET_RATE,
	OP_PREPARE,
	OP_ACTIVE,
	OP_READBACK,
	OP_STOP_TICK,
	OP_TERMINATE,
	OP_DISABLE,
	OP_UNPREPARE,
	OP_SAFE,
	OP_RESTORE_PARENT,
	OP_RESTORE,
	OP_COUNT,
};

struct fake {
	int fail;
	int calls[OP_COUNT];
	int order[32];
	int order_count;
};

static int invoke(void *argument, int operation)
{
	struct fake *fake = argument;

	fake->calls[operation]++;
	fake->order[fake->order_count++] = operation;
	return fake->fail == operation ? -EIO : 0;
}

#define CALLBACK(name, operation) \
	static int name(void *argument) { return invoke(argument, operation); }
CALLBACK(set_rate, OP_SET_RATE)
CALLBACK(prepare, OP_PREPARE)
CALLBACK(active, OP_ACTIVE)
CALLBACK(readback, OP_READBACK)
CALLBACK(stop_tick, OP_STOP_TICK)
CALLBACK(terminate, OP_TERMINATE)
CALLBACK(disable, OP_DISABLE)
CALLBACK(unprepare, OP_UNPREPARE)
CALLBACK(safe, OP_SAFE)
CALLBACK(restore_parent, OP_RESTORE_PARENT)
CALLBACK(restore, OP_RESTORE)

static const struct rp1_gpclk_execution_ops ops = {
	.set_rate = set_rate,
	.prepare = prepare,
	.select_active = active,
	.readback = readback,
	.stop_tick = stop_tick,
	.terminate_dma = terminate,
	.disable_clock = disable,
	.unprepare_clock = unprepare,
	.select_safe = safe,
	.restore_parent = restore_parent,
	.restore_rate = restore,
};

static int expect(int condition, const char *message)
{
	if (!condition) {
		fprintf(stderr, "execution machine: FAIL: %s\n", message);
		return 1;
	}
	return 0;
}

int main(void)
{
	static const int cleanup[] = { OP_STOP_TICK, OP_TERMINATE, OP_DISABLE,
		OP_UNPREPARE, OP_SAFE, OP_RESTORE_PARENT, OP_RESTORE };
	struct fake fake;
	int failures = 0;
	int index;
	int result;

	memset(&fake, 0, sizeof(fake));
	fake.fail = -1;
	result = rp1_gpclk_execution_machine_start(&ops, &fake);
	failures += expect(result == 0 && fake.order_count == 2,
		"successful start keeps active pin selection separate");
	result = rp1_gpclk_execution_machine_activate(&ops, &fake);
	failures += expect(result == 0 && fake.order[2] == OP_ACTIVE,
		"activation is explicit after DMA preparation");

	for (index = OP_SET_RATE; index <= OP_PREPARE; index++) {
		int cleanup_index;

		memset(&fake, 0, sizeof(fake));
		fake.fail = index;
		result = rp1_gpclk_execution_machine_start(&ops, &fake);
		failures += expect(result == -EIO,
			"start preserves the initiating failure");
		for (cleanup_index = 0; cleanup_index < 7; cleanup_index++)
			failures += expect(fake.calls[cleanup[cleanup_index]] == 1,
				"every start failure runs the complete idempotent cleanup");
	}
	memset(&fake, 0, sizeof(fake));
	fake.fail = OP_ACTIVE;
	failures += expect(rp1_gpclk_execution_machine_activate(&ops, &fake) == -EIO,
		"activation failure is returned to the production caller");

	for (index = OP_READBACK; index < OP_COUNT; index++) {
		memset(&fake, 0, sizeof(fake));
		fake.fail = index;
		result = rp1_gpclk_execution_machine_finish(&ops, &fake, true);
		failures += expect(result == -EIO,
			"cleanup preserves its first failure");
		failures += expect(fake.order_count == 8,
			"cleanup attempts every operation after a failure");
		failures += expect(fake.order[0] == OP_READBACK &&
			fake.order[7] == OP_RESTORE,
			"cleanup ordering is readback through restoration");
	}

	memset(&fake, 0, sizeof(fake));
	fake.fail = OP_READBACK;
	result = rp1_gpclk_execution_machine_finish(&ops, &fake, false);
	failures += expect(result == 0 && fake.calls[OP_READBACK] == 0,
		"readback is skipped when no divider was written");

	if (failures)
		return 1;
	puts("execution machine: PASS");
	return 0;
}
