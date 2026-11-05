// SPDX-License-Identifier: MIT
#include <assert.h>
#include <stdbool.h>

#include "rp1_gpclk/bootstrap_policy.h"

int main(void)
{
	assert(rp1_gpclk_bootstrap_decide(0, false, false, false) ==
	       RP1_GPCLK_BOOTSTRAP_REJECT_NO_NODE);
	assert(rp1_gpclk_bootstrap_decide(2, true, false, false) ==
	       RP1_GPCLK_BOOTSTRAP_REJECT_AMBIGUOUS);
	assert(rp1_gpclk_bootstrap_decide(1, false, false, false) ==
	       RP1_GPCLK_BOOTSTRAP_REJECT_DISABLED);
	assert(rp1_gpclk_bootstrap_decide(1, true, false, false) ==
	       RP1_GPCLK_BOOTSTRAP_CREATE);
	assert(rp1_gpclk_bootstrap_decide(1, true, true, false) ==
	       RP1_GPCLK_BOOTSTRAP_REJECT_UNBOUND);
	assert(rp1_gpclk_bootstrap_decide(1, true, true, true) ==
	       RP1_GPCLK_BOOTSTRAP_USE_EXISTING);
	return 0;
}
