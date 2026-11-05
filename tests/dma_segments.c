// SPDX-License-Identifier: MIT
#include <assert.h>
#include <stddef.h>
#include "rp1_gpclk/dma_segments.h"
int main(void)
{
	unsigned long lengths[] = {4, 4092, 4096, 4100, 3913892, 15655568};
	unsigned int i;
	for (i = 0; i < sizeof(lengths)/sizeof(lengths[0]); i++) {
		unsigned long left = lengths[i], total = 0;
		while (left) {
			unsigned int size = rp1_gpclk_dma_segment_bytes(left);
			assert(size && size <= 4096 && size % 4 == 0);
			assert(size <= left);
			total += size;
			left -= size;
		}
		assert(total == lengths[i]);
	}
	return 0;
}
