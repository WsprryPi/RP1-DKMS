/* SPDX-License-Identifier: (GPL-2.0-only WITH Linux-syscall-note) OR MIT */
#ifndef RP1_ROUTE_ADMIN_H
#define RP1_ROUTE_ADMIN_H
#include <linux/types.h>
#include <linux/ioctl.h>
#define RP1_ROUTE_STATUS 0U
#define RP1_ROUTE_APPLY 1U
#define RP1_ROUTE_REMOVE 2U
#define RP1_ROUTE_FAULT 1U
#define RP1_ROUTE_CONSUMER 2U
#define RP1_ROUTE_PINNED 4U
/* Reserved fields are zero on input and output; output fields are zero on input. */
/* STATUS also requires zero session/generation. */
struct rp1_route_admin {
	__u32 reserved0;
	__u32 operation;
	__u32 route;
	__u32 reserved;
	__u64 session;
	__u64 generation;
	__s32 overlay_id;
	__s32 last_error;
	__u32 active_route;
	__u32 flags;
	__u64 reserved2[2];
};
#define RP1_ROUTE_ADMIN _IOWR(0xb8, 0x01, struct rp1_route_admin)
#endif
