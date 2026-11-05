/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_COMPATIBILITY_H
#define RP1_GPCLK_COMPATIBILITY_H

#include <linux/types.h>

#define RP1_GPCLK_COMPATIBILITY_ARCH "aarch64"
#define RP1_GPCLK_COMPATIBILITY_VERSION "0.0.1"
#define RP1_GPCLK_GPIO4_COMPATIBILITY_ID \
	"v0.0.1-rp1-gpio4"
#define RP1_GPCLK_GPIO20_COMPATIBILITY_ID \
	"v0.0.1-rp1-gpio20"

bool rp1_gpclk_compatibility_allowed(__u32 route,
				     const char *architecture,
				     const char *module_version,
				     bool resources_validated);

const char *rp1_gpclk_compatibility_id(__u32 route);

#endif /* RP1_GPCLK_COMPATIBILITY_H */
