/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_UAPI_DISPATCH_H
#define RP1_GPCLK_UAPI_DISPATCH_H

struct file;

/* Phase 2C endpoint is lifetime-testable but all commands remain unavailable. */
long rp1_gpclk_uapi_dispatch(struct file *file, unsigned int command,
                            unsigned long argument);

#endif /* RP1_GPCLK_UAPI_DISPATCH_H */
