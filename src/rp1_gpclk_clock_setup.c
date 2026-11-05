// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/errno.h>
#ifndef RP1_GPCLK_HOST_TEST
#include <linux/math64.h>
#endif
#include "rp1_gpclk/clock_setup.h"

static __u64 divide(__u64 numerator, __u64 denominator)
{
#ifdef RP1_GPCLK_HOST_TEST
	return numerator / denominator;
#else
	return div64_u64(numerator, denominator);
#endif
}

/* The provider reports whole Hz, rounded down. Both bounds must imply the
 * same integer divider; an ambiguous boundary is not sufficient evidence.
 */
static bool integer_matches(__u64 parent, __u64 rate, __u64 integer)
{
	__u64 minimum, maximum;

	if (!parent || parent > 0xffffffffULL || !rate || rate >= 0xffffffffULL)
		return false;
	minimum = divide(parent << 16, rate + 1) + 1;
	maximum = divide(parent << 16, rate);
	return minimum <= maximum && (minimum >> 16) == integer &&
		(maximum >> 16) == integer;
}

int rp1_gpclk_clock_setup(const struct rp1_gpclk_clock_setup_ops *ops,
	void *context, __u64 divider_q16, __u64 required_parent_rate)
{
	__u64 integer = divider_q16 >> 16;
	unsigned int attempt;
	unsigned int bias = 0;
	int ret;

	if (!ops || !context || !ops->set_rate || !ops->parent_rate ||
	    !ops->output_rate || !ops->select_parent || !ops->parent_matches ||
	    !integer || divider_q16 > 0xffffffffULL ||
	    !required_parent_rate || required_parent_rate > 0xffffffffULL)
		return -EINVAL;

	/* A rate request may select another parent. Seed the required divider
	 * using the observed parent, while the output pin is still inactive.
	 * Once its integer portion is proven, select the contracted parent LAST.
	 * Fractional DMA subsequently supplies the operation's exact sequence.
	 * Never search indefinitely or accept a different integer/source.
	 */
	for (attempt = 0; attempt < 4; attempt++) {
		__u64 parent = ops->parent_rate(context);
		__u64 rate;

		if (!parent || parent > 0xffffffffULL)
			return -ERANGE;
		rate = divide((parent << 16) + divider_q16 / 2,
			      divider_q16);
		if (rate <= bias || rate > 0xffffffffULL)
			return -ERANGE;
		rate -= bias;
		ret = ops->set_rate(context, rate);
		if (ret)
			return ret;
		if (!integer_matches(ops->parent_rate(context),
				     ops->output_rate(context), integer)) {
			/* Shift the next seed by one requested Hz. Do not reset this
			 * on reparenting: nearest-rate selection can otherwise cycle
			 * forever between two parents (for example at 3570100 Hz).
			 */
			bias++;
			continue;
		}
		ret = ops->select_parent(context);
		if (ret)
			return ret;
		if (!ops->parent_matches(context) ||
		    ops->parent_rate(context) != required_parent_rate ||
		    !integer_matches(required_parent_rate,
				     ops->output_rate(context), integer))
			return -EIO;
		return 0;
	}
	return -ERANGE;
}

/* Rate selection may reparent here too. Always select the saved parent last,
 * and accept restoration only when both parent and output rate match.
 */
int rp1_gpclk_clock_restore(const struct rp1_gpclk_clock_setup_ops *ops,
	void *context, __u64 rate, __u64 parent_rate)
{
	__u64 seed = rate;
	unsigned int attempt;
	int ret;

	if (!ops || !context || !ops->set_rate || !ops->parent_rate ||
	    !ops->output_rate || !ops->select_parent || !ops->parent_matches ||
	    !rate || rate > 0xffffffffULL || !parent_rate ||
	    parent_rate > 0xffffffffULL)
		return -EINVAL;
	for (attempt = 0; attempt < 4; attempt++) {
		__u64 observed;

		ret = ops->set_rate(context, seed);
		if (ret)
			return ret;
		observed = ops->parent_rate(context);
		ret = ops->select_parent(context);
		if (ret)
			return ret;
		if (!ops->parent_matches(context) ||
		    ops->parent_rate(context) != parent_rate)
			return -EIO;
		if (ops->output_rate(context) == rate)
			return 0;
		if (!observed || observed > 0xffffffffULL)
			return -ERANGE;
		seed = divide(rate * observed + parent_rate / 2, parent_rate);
		if (!seed || seed > 0xffffffffULL)
			return -ERANGE;
	}
	return -ERANGE;
}
