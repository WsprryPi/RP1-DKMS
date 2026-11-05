// SPDX-License-Identifier: MIT
#include <assert.h>
#include <stdio.h>
#include <errno.h>
#include "rp1_gpclk/clock_setup.h"

struct model {
	__u64 parent, divider, desired_parent;
	unsigned int calls;
	int error;
	bool wrong_parent, wrong_integer, oscillate;
	bool reject_parent, bad_readback;
	bool nearest_parent;
};

static int set_rate(void *arg, __u64 rate)
{
	struct model *m = arg;

	m->calls++;
	if (m->error)
		return m->error;
	/* Model provider reparenting, including a 50 MHz state that cleanup may
	 * restore. Output setup must explicitly select the 200 MHz parent. */
	m->parent = rate > 50000000 ||
		(m->oscillate && !(m->calls % 2)) ? 200000000 : 50000000;
	if (m->nearest_parent) {
		const __u64 parents[] = {50000000, 200000000};
		__u64 best_error = ~0ULL, rounded_rate = 0;
		unsigned int i;

		for (i = 0; i < 2; i++) {
			__u64 d = ((parents[i] << 16) + rate / 2) / rate;
			__u64 actual, error;

			if (d < 65536 || d > (65535ULL << 16))
				continue;
			actual = (parents[i] << 16) / d;
			error = actual > rate ? actual - rate : rate - actual;
			if (error < best_error) {
				best_error = error;
				m->parent = parents[i];
				rounded_rate = actual;
			}
		}
		assert(rounded_rate);
		/* The provider applies the rate selected by determine_rate. */
		rate = rounded_rate;
	}
	m->divider = ((m->parent << 16) + rate / 2) / rate;
	if (m->divider < 65536)
		m->divider = 65536;
	if (m->divider > (65535ULL << 16))
		m->divider = 65535ULL << 16;
	return 0;
}

static __u64 parent_rate(void *arg) { return ((struct model *)arg)->parent; }
static __u64 output_rate(void *arg)
{
	struct model *m = arg;
	return m->bad_readback ? 0 : (m->parent << 16) / m->divider;
}
static int select_parent(void *arg)
{
	struct model *m = arg;
	if (m->reject_parent)
		return -EIO;
	if (!m->wrong_parent)
		m->parent = m->desired_parent;
	if (m->wrong_integer)
		m->divider += 65536;
	return 0;
}
static bool matches(void *arg)
{
	struct model *m = arg;
	return m->parent == m->desired_parent;
}
static const struct rp1_gpclk_clock_setup_ops ops = {
	set_rate, parent_rate, output_rate, select_parent, matches
};

int main(void)
{
	const __u64 frequencies[] = {137500, 475700, 1838100, 3570100,
		5288700, 7040100, 10140200, 14097100, 18106100, 21096100,
		24926100, 28126100, 50294500, 70092500, 1000000, 100000000};
	__u64 divider = (200000000ULL << 16) / 475700;
	struct model m;
	unsigned int i;

	for (i = 0; i < sizeof(frequencies) / sizeof(frequencies[0]); i++) {
		__u64 d = (200000000ULL << 16) / frequencies[i];
		m = (struct model){.parent = 200000000, .desired_parent = 200000000};
		assert(!rp1_gpclk_clock_setup(&ops, &m, d, 200000000));
		assert(m.parent == 200000000 && (m.divider >> 16) == (d >> 16));
		assert(m.calls <= 4);
		m = (struct model){.parent = 200000000, .desired_parent = 200000000,
			.nearest_parent = true};
		assert(!rp1_gpclk_clock_setup(&ops, &m, d, 200000000));
		assert(m.parent == 200000000 && (m.divider >> 16) == (d >> 16));
		assert(m.calls <= 4);
	}
	m = (struct model){.parent = 200000000, .desired_parent = 200000000,
		.wrong_parent = true};
	assert(rp1_gpclk_clock_setup(&ops, &m, divider, 200000000) == -EIO);
	m = (struct model){.parent = 200000000, .desired_parent = 200000000,
		.wrong_integer = true};
	assert(rp1_gpclk_clock_setup(&ops, &m, divider, 200000000) == -EIO);
	m = (struct model){.parent = 200000000, .desired_parent = 200000000,
		.oscillate = true};
	assert(rp1_gpclk_clock_setup(&ops, &m, divider, 200000000) == -ERANGE);
	assert(m.calls == 4);
	m = (struct model){.parent = 200000000, .error = -EBUSY};
	assert(rp1_gpclk_clock_setup(&ops, &m, divider, 200000000) == -EBUSY);
	assert(m.calls == 1);
	assert(rp1_gpclk_clock_setup(&ops, &m, 0, 200000000) == -EINVAL);
	assert(rp1_gpclk_clock_setup(NULL, &m, divider, 200000000) == -EINVAL);
	for (i = 0; i < 2; i++) {
		m = (struct model){.parent = 200000000,
			.desired_parent = i ? 200000000 : 50000000};
		assert(!rp1_gpclk_clock_restore(&ops, &m, 1000000, m.desired_parent));
		assert(output_rate(&m) == 1000000 && matches(&m));
	}
	m.wrong_parent = true;
	assert(rp1_gpclk_clock_restore(&ops, &m, 1000000, 200000000) == -EIO);
	m = (struct model){.parent = 200000000, .desired_parent = 200000000,
		.reject_parent = true};
	assert(rp1_gpclk_clock_setup(&ops, &m, divider, 200000000) == -EIO);
	assert(rp1_gpclk_clock_restore(&ops, &m, 1000000, 200000000) == -EIO);
	m = (struct model){.parent = 200000000, .desired_parent = 200000000,
		.bad_readback = true};
	assert(rp1_gpclk_clock_setup(&ops, &m, divider, 200000000) == -ERANGE);
	assert(m.calls == 4);
	m.calls = 0;
	assert(rp1_gpclk_clock_restore(&ops, &m, 1000000, 200000000) == -ERANGE);
	assert(m.calls == 4);
	assert(rp1_gpclk_clock_setup(&ops, &m, 1ULL << 32, 200000000) == -EINVAL);
	assert(rp1_gpclk_clock_restore(&ops, &m, 0, 200000000) == -EINVAL);
	assert(rp1_gpclk_clock_restore(NULL, &m, 1000000, 200000000) == -EINVAL);
	puts("clock parent setup and restoration: PASS");
	return 0;
}
