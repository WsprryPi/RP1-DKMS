/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_GPCLK_CORE_H
#define RP1_GPCLK_CORE_H

#include <linux/types.h>

#include <uapi/linux/rp1_gpclk.h>

#define RP1_GPCLK_CORE_SUPPORTED_CAPABILITIES \
    (RP1_GPCLK_CAP_SUBMIT_EVENTS | \
     RP1_GPCLK_CAP_STOP_DRAIN | RP1_GPCLK_CAP_STABLE_STATE | \
     RP1_GPCLK_CAP_ROUTE_IDENTITY | RP1_GPCLK_CAP_COMPAT_IDENTITY | \
     RP1_GPCLK_CAP_CLEANUP_FAULT_LATCH | RP1_GPCLK_CAP_OUTPUT_INHIBIT | \
     RP1_GPCLK_CAP_PASSIVE_SNAPSHOT | RP1_GPCLK_CAP_BOUNDED_DMA_CHUNKS)

enum rp1_gpclk_core_result {
    RP1_GPCLK_CORE_OK = 0,
    RP1_GPCLK_CORE_INVALID = -1,
    RP1_GPCLK_CORE_BUSY = -2,
    RP1_GPCLK_CORE_STALE = -3,
    RP1_GPCLK_CORE_STATE = -4,
    RP1_GPCLK_CORE_FAULT = -5,
    RP1_GPCLK_CORE_LATCHED = -6,
};

enum rp1_gpclk_core_fault_point {
    RP1_GPCLK_FAULT_NONE = 0,
    RP1_GPCLK_FAULT_ACQUIRE_PRECOMMIT,
    RP1_GPCLK_FAULT_SUBMIT_COPY,
    RP1_GPCLK_FAULT_SUBMIT_PRECOMMIT,
    RP1_GPCLK_FAULT_PROGRESS_PRECOMMIT,
    RP1_GPCLK_FAULT_STOP_PRECOMMIT,
    RP1_GPCLK_FAULT_TERMINAL_PRECOMMIT,
    RP1_GPCLK_FAULT_CLEANUP,
    RP1_GPCLK_FAULT_RELEASE_PRECOMMIT,
    RP1_GPCLK_FAULT_POINT_COUNT,
};

struct rp1_gpclk_core_snapshot {
    __u64 owner_id;
    __u64 lease_id;
    __u64 generation;
    __u64 next_lease_id;
    __u64 next_generation;
    __u32 route;
    __u32 state;
    __u32 terminal_reason;
    __u32 total_units;
    __u32 completed_units;
    __u32 drain_units;
    __u32 cleanup_fault;
    __u32 terminal_publications;
    __u32 terminal_attempts;
    __u32 plan_loaded;
    __u32 plan_releases;
};

struct rp1_gpclk_core {
    struct rp1_gpclk_core_snapshot value;
    __u32 pending_reason;
    __u32 owner_closing;
    __u32 plan_tone_count;
    __u32 plan_event_count;
    struct rp1_gpclk_tone plan_tones[RP1_GPCLK_MAX_TONES];
    struct rp1_gpclk_event plan_events[RP1_GPCLK_MAX_EVENTS];
#ifdef RP1_GPCLK_HOST_TEST
    __u32 fault_point;
    __u32 fault_occurrence;
    __u32 fault_seen;
#endif
};

void rp1_gpclk_core_init(struct rp1_gpclk_core *core);
int rp1_gpclk_core_acquire(struct rp1_gpclk_core *core, __u64 owner_id,
                          __u32 route, __u64 required_capabilities,
                          __u64 *lease_id);
int rp1_gpclk_core_submit_events(
    struct rp1_gpclk_core *core, __u64 owner_id,
    struct rp1_gpclk_submit_events *request,
    const struct rp1_gpclk_tone *tones,
    const struct rp1_gpclk_event *events);
int rp1_gpclk_core_progress(struct rp1_gpclk_core *core, __u64 owner_id,
                           __u64 lease_id, __u64 generation);
int rp1_gpclk_core_stop(struct rp1_gpclk_core *core, __u64 owner_id,
                       __u64 lease_id, __u64 generation);
int rp1_gpclk_core_fail(struct rp1_gpclk_core *core, __u64 owner_id,
                       __u64 lease_id, __u64 generation, __u32 reason);
int rp1_gpclk_core_cleanup_failed(struct rp1_gpclk_core *core,
				  __u64 owner_id, __u64 lease_id,
				  __u64 generation);
int rp1_gpclk_core_release(struct rp1_gpclk_core *core, __u64 owner_id,
                          __u64 lease_id);
int rp1_gpclk_core_owner_close(struct rp1_gpclk_core *core, __u64 owner_id);
int rp1_gpclk_core_mark_dead(struct rp1_gpclk_core *core, __u32 reason);
int rp1_gpclk_core_get_state(const struct rp1_gpclk_core *core,
                            __u64 owner_id, __u64 lease_id, __u64 generation,
                            struct rp1_gpclk_core_snapshot *snapshot);
int rp1_gpclk_core_get_public_state(const struct rp1_gpclk_core *core,
                                    struct rp1_gpclk_core_snapshot *snapshot);

#ifdef RP1_GPCLK_HOST_TEST
void rp1_gpclk_core_inject_fault(struct rp1_gpclk_core *core,
                                 enum rp1_gpclk_core_fault_point point,
                                 __u32 occurrence);
int rp1_gpclk_core_test_publish_terminal(struct rp1_gpclk_core *core,
                                         __u32 state, __u32 reason);
#endif

#endif /* RP1_GPCLK_CORE_H */
