/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_DMA_SEGMENTS_H
#define RP1_GPCLK_DMA_SEGMENTS_H
/* Keep each mapped SG entry small and word-aligned. Older stock DW-AXI
 * providers repartition a large entry into equal, non-word-aligned lengths.
 * This partitions the same buffer; it adds no samples or software gaps.
 */
#define RP1_GPCLK_DMA_SEGMENT_BYTES 4096U
static inline unsigned int rp1_gpclk_dma_segment_bytes(unsigned long remaining)
{
	return remaining > RP1_GPCLK_DMA_SEGMENT_BYTES ?
		RP1_GPCLK_DMA_SEGMENT_BYTES : (unsigned int)remaining;
}
#endif
