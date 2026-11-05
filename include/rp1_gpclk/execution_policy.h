/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_EXECUTION_POLICY_H
#define RP1_GPCLK_EXECUTION_POLICY_H

#include <linux/types.h>
#include <linux/stddef.h>

#include <uapi/linux/rp1_gpclk.h>

#define RP1_GPCLK_TICK_SOURCE_HZ 50000000ULL
#define RP1_GPCLK_DIVIDER_INTEGER_BITS 16U
#define RP1_GPCLK_DIVIDER_FRACTIONAL_BITS 16U
#define RP1_GPCLK_DIVIDER_INTEGER_MAX 65535ULL
#define RP1_GPCLK_DIVIDER_Q16_MAX 0xffffffffULL

struct rp1_gpclk_chunk_cursor {
	__u64 remaining_ns;
	__u64 timing_remainder;
	__u32 cancelled;
};

int rp1_gpclk_execution_tones_valid(const struct rp1_gpclk_tone *tones,
				    __u32 tone_count, __u32 drive_ma);
int rp1_gpclk_execution_event_writes(__u64 duration_ns, size_t *writes);
int rp1_gpclk_execution_chunk_writes(__u64 duration_ns, __u64 *remainder,
				     size_t *writes);
int rp1_gpclk_chunk_cursor_init(struct rp1_gpclk_chunk_cursor *cursor,
				__u64 duration_ns);
int rp1_gpclk_chunk_cursor_next(struct rp1_gpclk_chunk_cursor *cursor,
				__u64 *duration_ns, size_t *writes);
void rp1_gpclk_chunk_cursor_cancel(struct rp1_gpclk_chunk_cursor *cursor);
int rp1_gpclk_execution_fill_words(const struct rp1_gpclk_tone *tone,
				   __u32 *words, size_t count);
int rp1_gpclk_execution_fill_words_stateful(
	const struct rp1_gpclk_tone *tone, __u32 *words, size_t count,
	__u64 *accumulator);

#endif /* RP1_GPCLK_EXECUTION_POLICY_H */
