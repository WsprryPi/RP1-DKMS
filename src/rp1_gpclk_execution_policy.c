// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include <linux/errno.h>
#ifndef RP1_GPCLK_HOST_TEST
#include <linux/math64.h>
#endif

#include "rp1_gpclk/execution_policy.h"

int rp1_gpclk_execution_tones_valid(const struct rp1_gpclk_tone *tones,
				    __u32 tone_count, __u32 drive_ma)
{
	__u64 integer;
	__u32 index;

	if (!tones || !tone_count || tone_count > RP1_GPCLK_MAX_TONES ||
	    drive_ma != RP1_GPCLK_DRIVE_MA_2)
		return -EINVAL;
	integer = tones[0].lower_divider_q16 >>
		RP1_GPCLK_DIVIDER_FRACTIONAL_BITS;
	if (!integer || integer > RP1_GPCLK_DIVIDER_INTEGER_MAX)
		return -ERANGE;
	for (index = 0; index < tone_count; index++) {
		if (tones[index].lower_divider_q16 > RP1_GPCLK_DIVIDER_Q16_MAX ||
		    tones[index].upper_divider_q16 > RP1_GPCLK_DIVIDER_Q16_MAX ||
		    tones[index].upper_divider_q16 !=
			    tones[index].lower_divider_q16 + 1 ||
		    (tones[index].lower_divider_q16 >>
			    RP1_GPCLK_DIVIDER_FRACTIONAL_BITS) != integer ||
		    (tones[index].upper_divider_q16 >>
			    RP1_GPCLK_DIVIDER_FRACTIONAL_BITS) != integer)
			return -ERANGE;
	}
	return 0;
}

int rp1_gpclk_execution_event_writes(__u64 duration_ns, size_t *writes)
{
	__u64 value;

	if (!writes || !duration_ns)
		return -EINVAL;
#ifdef RP1_GPCLK_HOST_TEST
	value = (__u64)(((__uint128_t)duration_ns *
		RP1_GPCLK_TICK_SOURCE_HZ) /
		((__u64)RP1_GPCLK_TICK_DIVIDER * 1000000000ULL));
#else
	value = mul_u64_u64_div_u64(duration_ns, RP1_GPCLK_TICK_SOURCE_HZ,
		(__u64)RP1_GPCLK_TICK_DIVIDER * 1000000000ULL);
#endif
	if (!value || value > (size_t)-1)
		return -ERANGE;
	*writes = value;
	return 0;
}

int rp1_gpclk_execution_chunk_writes(__u64 duration_ns, __u64 *remainder,
				     size_t *writes)
{
	const __u64 denominator =
		(__u64)RP1_GPCLK_TICK_DIVIDER * 1000000000ULL;
	__u64 numerator;
	__u64 value;

	if (!duration_ns || duration_ns > RP1_GPCLK_DMA_CHUNK_DURATION_NS ||
	    !remainder || !writes || *remainder >= denominator)
		return -EINVAL;
	numerator = duration_ns * RP1_GPCLK_TICK_SOURCE_HZ + *remainder;
	value = numerator / denominator;
	*remainder = numerator % denominator;
	if (!value || value > (size_t)-1)
		return -ERANGE;
	*writes = value;
	return 0;
}

int rp1_gpclk_chunk_cursor_init(struct rp1_gpclk_chunk_cursor *cursor,
				__u64 duration_ns)
{
	if (!cursor || duration_ns < RP1_GPCLK_EVENT_DURATION_NS_MIN ||
	    duration_ns > RP1_GPCLK_EVENT_DURATION_NS_MAX)
		return -EINVAL;
	cursor->remaining_ns = duration_ns;
	cursor->timing_remainder = 0;
	cursor->cancelled = 0;
	return 0;
}

int rp1_gpclk_chunk_cursor_next(struct rp1_gpclk_chunk_cursor *cursor,
				__u64 *duration_ns, size_t *writes)
{
	__u64 duration;
	int ret;

	if (!cursor || !duration_ns || !writes)
		return -EINVAL;
	if (cursor->cancelled)
		return -ECANCELED;
	if (!cursor->remaining_ns)
		return 0;
	duration = cursor->remaining_ns > RP1_GPCLK_DMA_CHUNK_DURATION_NS ?
		RP1_GPCLK_DMA_CHUNK_DURATION_NS : cursor->remaining_ns;
	if (cursor->remaining_ns > RP1_GPCLK_DMA_CHUNK_DURATION_NS &&
	    cursor->remaining_ns - duration < RP1_GPCLK_EVENT_DURATION_NS_MIN)
		duration = cursor->remaining_ns - RP1_GPCLK_EVENT_DURATION_NS_MIN;
	ret = rp1_gpclk_execution_chunk_writes(duration,
		&cursor->timing_remainder, writes);
	if (ret)
		return ret;
	cursor->remaining_ns -= duration;
	*duration_ns = duration;
	return 1;
}

void rp1_gpclk_chunk_cursor_cancel(struct rp1_gpclk_chunk_cursor *cursor)
{
	if (cursor)
		cursor->cancelled = 1;
}

int rp1_gpclk_execution_fill_words(const struct rp1_gpclk_tone *tone,
				   __u32 *words, size_t count)
{
	__u64 accumulator = 0;

	return rp1_gpclk_execution_fill_words_stateful(tone, words, count,
		&accumulator);
}

int rp1_gpclk_execution_fill_words_stateful(
	const struct rp1_gpclk_tone *tone, __u32 *words, size_t count,
	__u64 *accumulator)
{
	__u64 period;
	size_t index;

	if (!tone || !words || !count || !accumulator)
		return -EINVAL;
	period = (__u64)tone->lower_count + tone->upper_count;
	if (!period || *accumulator >= period)
		return -EINVAL;
	for (index = 0; index < count; index++) {
		*accumulator += tone->lower_count;
		if (*accumulator >= period) {
			words[index] = (__u32)(tone->lower_divider_q16 & 0xffffULL)
				       << 16;
			*accumulator -= period;
		} else {
			words[index] = (__u32)(tone->upper_divider_q16 & 0xffffULL)
				       << 16;
		}
	}
	return 0;
}
