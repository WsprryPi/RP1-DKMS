// SPDX-License-Identifier: GPL-2.0-only OR MIT
#include "rp1_gpclk/core.h"

#define RP1_GPCLK_CORE_U64_MAX (~(__u64)0)

static int rp1_gpclk_fault(struct rp1_gpclk_core *core, __u32 point)
{
#ifdef RP1_GPCLK_HOST_TEST
    if (core->fault_point == point) {
        core->fault_seen++;
        if (core->fault_seen == core->fault_occurrence)
            return 1;
    }
#else
    (void)core;
    (void)point;
#endif
    return 0;
}

static int rp1_gpclk_header_valid(const struct rp1_gpclk_uapi_header *header,
                                  __u16 size)
{
    return header && header->size == size &&
           header->reserved == 0 && header->flags == 0;
}

static int rp1_gpclk_route_valid(__u32 route)
{
    return route == RP1_GPCLK_ROUTE_GPIO4 ||
           route == RP1_GPCLK_ROUTE_GPIO20;
}

static int rp1_gpclk_drive_valid(__u32 drive_ma)
{
    return drive_ma == RP1_GPCLK_DRIVE_MA_2 ||
           drive_ma == RP1_GPCLK_DRIVE_MA_4 ||
           drive_ma == RP1_GPCLK_DRIVE_MA_8 ||
           drive_ma == RP1_GPCLK_DRIVE_MA_12;
}

static int rp1_gpclk_reserved_zero(const __u64 *reserved, __u32 count)
{
    __u32 index;

    for (index = 0; index < count; index++) {
        if (reserved[index] != 0)
            return 0;
    }
    return 1;
}

static int rp1_gpclk_tones_valid(const struct rp1_gpclk_tone *tones,
                                 __u32 count, __u32 expected_period)
{
    __u32 index;

    if (!tones || count == 0 || count > RP1_GPCLK_MAX_TONES)
        return 0;
    for (index = 0; index < count; index++) {
        __u64 sum;

        if (tones[index].lower_divider_q16 == RP1_GPCLK_CORE_U64_MAX ||
            tones[index].upper_divider_q16 !=
                tones[index].lower_divider_q16 + 1 ||
            tones[index].lower_count == 0 || tones[index].upper_count == 0 ||
            tones[index].lower_count > RP1_GPCLK_DITHER_PERIOD_MAX ||
            tones[index].upper_count > RP1_GPCLK_DITHER_PERIOD_MAX ||
            tones[index].lower_count >
                RP1_GPCLK_DITHER_PERIOD_MAX - tones[index].upper_count)
            return 0;
        sum = tones[index].lower_count + tones[index].upper_count;
        if (sum > RP1_GPCLK_DITHER_PERIOD_MAX ||
            (expected_period != 0 && sum != expected_period))
            return 0;
    }
    return 1;
}

static int rp1_gpclk_owner_matches(const struct rp1_gpclk_core *core,
                                   __u64 owner_id, __u64 lease_id)
{
    return owner_id != 0 && owner_id == core->value.owner_id &&
           lease_id != 0 && lease_id == core->value.lease_id;
}

static int rp1_gpclk_generation_matches(const struct rp1_gpclk_core *core,
                                        __u64 owner_id, __u64 lease_id,
                                        __u64 generation)
{
    return rp1_gpclk_owner_matches(core, owner_id, lease_id) &&
           generation != 0 && generation == core->value.generation;
}

static int rp1_gpclk_terminal(__u32 state)
{
    return state == RP1_GPCLK_STATE_COMPLETE ||
           state == RP1_GPCLK_STATE_FAILED || state == RP1_GPCLK_STATE_DEAD;
}

static int rp1_gpclk_reason_valid(__u32 reason)
{
    return reason >= RP1_GPCLK_REASON_DEADLINE_MISSED &&
           reason <= RP1_GPCLK_REASON_INTERNAL_ERROR;
}

static int rp1_gpclk_publish_terminal(struct rp1_gpclk_core *core,
                                      __u32 state, __u32 reason)
{
    if (rp1_gpclk_terminal(core->value.state))
        return RP1_GPCLK_CORE_STATE;
    if (!rp1_gpclk_terminal(state) || reason == RP1_GPCLK_REASON_NONE)
        return RP1_GPCLK_CORE_INVALID;
    if (core->value.generation != 0)
        core->value.terminal_attempts++;
    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_TERMINAL_PRECOMMIT)) {
        state = RP1_GPCLK_STATE_FAILED;
        reason = RP1_GPCLK_REASON_INTERNAL_ERROR;
    }
    core->value.state = state;
    core->value.terminal_reason = reason;
    core->value.drain_units = 0;
    core->pending_reason = RP1_GPCLK_REASON_NONE;
    if (core->value.generation != 0)
        core->value.terminal_publications++;
    return RP1_GPCLK_CORE_OK;
}

static int rp1_gpclk_cleanup_and_publish(struct rp1_gpclk_core *core,
                                         __u32 state, __u32 reason)
{
    int owner_closed = core->owner_closing;
    int result;

    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_CLEANUP)) {
        core->value.cleanup_fault = 1;
        state = RP1_GPCLK_STATE_FAILED;
        reason = RP1_GPCLK_REASON_CLEANUP_FAILED;
    }
    if (core->value.plan_loaded) {
        core->value.plan_loaded = 0;
        core->value.plan_releases++;
    }
    result = rp1_gpclk_publish_terminal(core, state, reason);
    if (result == RP1_GPCLK_CORE_OK && owner_closed) {
        core->value.owner_id = 0;
        core->value.lease_id = 0;
        core->owner_closing = 0;
    }
    return result;
}

void rp1_gpclk_core_init(struct rp1_gpclk_core *core)
{
    struct rp1_gpclk_core empty = { 0 };

    *core = empty;
    core->value.state = RP1_GPCLK_STATE_IDLE;
    core->value.next_lease_id = 1;
}

int rp1_gpclk_core_acquire(struct rp1_gpclk_core *core, __u64 owner_id,
                          __u32 route, __u64 required_capabilities,
                          __u64 *lease_id)
{
    __u64 allocated;

    if (!core || !lease_id || owner_id == 0 || !rp1_gpclk_route_valid(route) ||
        (required_capabilities & ~RP1_GPCLK_CORE_SUPPORTED_CAPABILITIES) != 0)
        return RP1_GPCLK_CORE_INVALID;
    if (core->value.cleanup_fault)
        return RP1_GPCLK_CORE_LATCHED;
    if (core->value.owner_id != 0 || core->value.state == RP1_GPCLK_STATE_DEAD)
        return RP1_GPCLK_CORE_BUSY;
    allocated = core->value.next_lease_id;
    if (allocated == 0 || allocated == RP1_GPCLK_CORE_U64_MAX)
        return RP1_GPCLK_CORE_INVALID;
    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_ACQUIRE_PRECOMMIT))
        return RP1_GPCLK_CORE_FAULT;
    core->value.owner_id = owner_id;
    core->value.lease_id = allocated;
    core->value.next_lease_id = allocated + 1;
    core->value.next_generation = 1;
    core->value.generation = 0;
    core->value.route = route;
    core->value.state = RP1_GPCLK_STATE_IDLE;
    core->value.terminal_reason = RP1_GPCLK_REASON_NONE;
    core->value.total_units = 0;
    core->value.completed_units = 0;
    core->value.drain_units = 0;
    core->value.terminal_publications = 0;
    core->value.terminal_attempts = 0;
    core->value.plan_loaded = 0;
    core->value.plan_releases = 0;
    *lease_id = allocated;
    return RP1_GPCLK_CORE_OK;
}

static int rp1_gpclk_submit_begin(struct rp1_gpclk_core *core, __u64 owner_id,
                                  __u64 lease_id, __u64 requested_generation,
                                  __u32 units, __u64 *generation)
{
    __u64 allocated;

    if (!rp1_gpclk_owner_matches(core, owner_id, lease_id))
        return RP1_GPCLK_CORE_STALE;
    if (core->value.state != RP1_GPCLK_STATE_IDLE &&
        !rp1_gpclk_terminal(core->value.state))
        return RP1_GPCLK_CORE_BUSY;
    if (core->value.cleanup_fault || core->value.state == RP1_GPCLK_STATE_DEAD)
        return RP1_GPCLK_CORE_LATCHED;
    allocated = core->value.next_generation;
    if (allocated == 0 || allocated == RP1_GPCLK_CORE_U64_MAX)
        return RP1_GPCLK_CORE_INVALID;
    if (requested_generation != 0 && requested_generation != allocated)
        return RP1_GPCLK_CORE_STALE;
    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_SUBMIT_COPY) ||
        rp1_gpclk_fault(core, RP1_GPCLK_FAULT_SUBMIT_PRECOMMIT))
        return RP1_GPCLK_CORE_FAULT;
    core->value.generation = allocated;
    core->value.next_generation = allocated + 1;
    core->value.state = RP1_GPCLK_STATE_RUNNING;
    core->value.terminal_reason = RP1_GPCLK_REASON_NONE;
    core->value.total_units = units;
    core->value.completed_units = 0;
    core->value.drain_units = 0;
    core->value.terminal_publications = 0;
    core->value.terminal_attempts = 0;
    core->pending_reason = RP1_GPCLK_REASON_NONE;
    core->owner_closing = 0;
    *generation = allocated;
    return RP1_GPCLK_CORE_OK;
}

int rp1_gpclk_core_submit_events(
    struct rp1_gpclk_core *core, __u64 owner_id,
    struct rp1_gpclk_submit_events *request,
    const struct rp1_gpclk_tone *tones,
    const struct rp1_gpclk_event *events)
{
    __u32 index;
    __u64 total = 0;
    int result;

    if (!core || !request || !events ||
        !rp1_gpclk_header_valid(&request->header, sizeof(*request)) ||
        request->reserved0 != 0 || request->reserved1 != 0 ||
        request->reserved2 != 0 ||
        !rp1_gpclk_reserved_zero(request->reserved, 4) ||
        request->generation != 0 ||
        request->fractional_bits != RP1_GPCLK_FRACTIONAL_BITS ||
        request->tick_divider != RP1_GPCLK_TICK_DIVIDER ||
        request->event_count == 0 ||
        request->event_count > RP1_GPCLK_MAX_EVENTS ||
        !rp1_gpclk_drive_valid(request->drive_ma) ||
        !rp1_gpclk_tones_valid(tones, request->tone_count, 0))
        return RP1_GPCLK_CORE_INVALID;
    for (index = 0; index < request->event_count; index++) {
        if (events[index].duration_ns < RP1_GPCLK_EVENT_DURATION_NS_MIN ||
            events[index].duration_ns > RP1_GPCLK_EVENT_DURATION_NS_MAX ||
            events[index].reserved0 != 0 ||
            (events[index].flags & ~RP1_GPCLK_EVENT_F_OUTPUT_ENABLED) != 0 ||
            ((events[index].flags & RP1_GPCLK_EVENT_F_OUTPUT_ENABLED) != 0 &&
             events[index].tone_index >= request->tone_count) ||
            ((events[index].flags & RP1_GPCLK_EVENT_F_OUTPUT_ENABLED) == 0 &&
             events[index].tone_index != 0) ||
            total > RP1_GPCLK_REQUEST_DURATION_NS_MAX -
                        events[index].duration_ns)
            return RP1_GPCLK_CORE_INVALID;
        total += events[index].duration_ns;
    }
    if (total != request->total_duration_ns ||
        total > RP1_GPCLK_REQUEST_DURATION_NS_MAX)
        return RP1_GPCLK_CORE_INVALID;
    result = rp1_gpclk_submit_begin(core, owner_id, request->lease_id,
                                    request->generation, request->event_count,
                                    &request->generation);
    if (result != RP1_GPCLK_CORE_OK)
        return result;
    core->plan_tone_count = request->tone_count;
    core->plan_event_count = request->event_count;
    for (index = 0; index < request->tone_count; index++)
        core->plan_tones[index] = tones[index];
    for (index = 0; index < request->event_count; index++)
        core->plan_events[index] = events[index];
    core->value.plan_loaded = 1;
    return RP1_GPCLK_CORE_OK;
}

int rp1_gpclk_core_progress(struct rp1_gpclk_core *core, __u64 owner_id,
                           __u64 lease_id, __u64 generation)
{
    if (!core || !rp1_gpclk_generation_matches(core, owner_id, lease_id,
                                                generation))
        return RP1_GPCLK_CORE_STALE;
    if (rp1_gpclk_terminal(core->value.state))
        return RP1_GPCLK_CORE_STATE;
    if (core->value.state != RP1_GPCLK_STATE_RUNNING &&
        core->value.state != RP1_GPCLK_STATE_DRAINING)
        return RP1_GPCLK_CORE_STATE;
    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_PROGRESS_PRECOMMIT))
        return rp1_gpclk_cleanup_and_publish(
            core, RP1_GPCLK_STATE_FAILED, RP1_GPCLK_REASON_INTERNAL_ERROR);
    if (core->value.completed_units >= core->value.total_units)
        return RP1_GPCLK_CORE_STATE;
    core->value.completed_units++;
    if (core->value.state == RP1_GPCLK_STATE_DRAINING) {
        if (core->value.drain_units == 0)
            return RP1_GPCLK_CORE_STATE;
        core->value.drain_units--;
        return rp1_gpclk_cleanup_and_publish(
            core, RP1_GPCLK_STATE_COMPLETE, core->pending_reason);
    }
    if (core->value.completed_units == core->value.total_units)
        return rp1_gpclk_cleanup_and_publish(
            core, RP1_GPCLK_STATE_COMPLETE, RP1_GPCLK_REASON_COMPLETE);
    return RP1_GPCLK_CORE_OK;
}

int rp1_gpclk_core_stop(struct rp1_gpclk_core *core, __u64 owner_id,
                       __u64 lease_id, __u64 generation)
{
    if (!core || !rp1_gpclk_generation_matches(core, owner_id, lease_id,
                                                generation))
        return RP1_GPCLK_CORE_STALE;
    if (rp1_gpclk_terminal(core->value.state))
        return core->value.terminal_reason == RP1_GPCLK_REASON_STOPPED ?
                   RP1_GPCLK_CORE_OK : RP1_GPCLK_CORE_STATE;
    if (core->value.state == RP1_GPCLK_STATE_DRAINING)
        return core->pending_reason == RP1_GPCLK_REASON_STOPPED ?
                   RP1_GPCLK_CORE_OK : RP1_GPCLK_CORE_STATE;
    if (core->value.state != RP1_GPCLK_STATE_RUNNING)
        return RP1_GPCLK_CORE_STATE;
    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_STOP_PRECOMMIT))
        return RP1_GPCLK_CORE_FAULT;
    core->value.state = RP1_GPCLK_STATE_DRAINING;
    core->pending_reason = RP1_GPCLK_REASON_STOPPED;
    core->value.drain_units =
        core->value.completed_units < core->value.total_units ? 1 : 0;
    if (core->value.drain_units == 0)
        return rp1_gpclk_cleanup_and_publish(
            core, RP1_GPCLK_STATE_COMPLETE, RP1_GPCLK_REASON_STOPPED);
    return RP1_GPCLK_CORE_OK;
}

int rp1_gpclk_core_fail(struct rp1_gpclk_core *core, __u64 owner_id,
                       __u64 lease_id, __u64 generation, __u32 reason)
{
    if (!core || !rp1_gpclk_generation_matches(core, owner_id, lease_id,
                                                generation))
        return RP1_GPCLK_CORE_STALE;
    if (!rp1_gpclk_reason_valid(reason) ||
        reason == RP1_GPCLK_REASON_CLEANUP_FAILED)
        return RP1_GPCLK_CORE_INVALID;
    if (rp1_gpclk_terminal(core->value.state))
        return RP1_GPCLK_CORE_STATE;
    return rp1_gpclk_cleanup_and_publish(core, RP1_GPCLK_STATE_FAILED, reason);
}

int rp1_gpclk_core_cleanup_failed(struct rp1_gpclk_core *core,
				  __u64 owner_id, __u64 lease_id,
				  __u64 generation)
{
	if (!core || !rp1_gpclk_generation_matches(core, owner_id, lease_id,
						   generation))
		return RP1_GPCLK_CORE_STALE;
	core->value.cleanup_fault = 1;
	if (rp1_gpclk_terminal(core->value.state)) {
		core->value.state = RP1_GPCLK_STATE_FAILED;
		core->value.terminal_reason = RP1_GPCLK_REASON_CLEANUP_FAILED;
		return RP1_GPCLK_CORE_OK;
	}
	if (core->value.plan_loaded) {
		core->value.plan_loaded = 0;
		core->value.plan_releases++;
	}
	return rp1_gpclk_publish_terminal(core, RP1_GPCLK_STATE_FAILED,
					  RP1_GPCLK_REASON_CLEANUP_FAILED);
}

int rp1_gpclk_core_release(struct rp1_gpclk_core *core, __u64 owner_id,
                          __u64 lease_id)
{
    if (!core || !rp1_gpclk_owner_matches(core, owner_id, lease_id))
        return RP1_GPCLK_CORE_STALE;
    if (core->value.cleanup_fault)
        return RP1_GPCLK_CORE_LATCHED;
    if (core->value.state == RP1_GPCLK_STATE_RUNNING ||
        core->value.state == RP1_GPCLK_STATE_DRAINING)
        return RP1_GPCLK_CORE_BUSY;
    if (rp1_gpclk_fault(core, RP1_GPCLK_FAULT_RELEASE_PRECOMMIT))
        return RP1_GPCLK_CORE_FAULT;
    if (core->value.state == RP1_GPCLK_STATE_DEAD) {
        core->value.owner_id = 0;
        core->value.lease_id = 0;
        core->value.route = RP1_GPCLK_ROUTE_INVALID;
        core->owner_closing = 0;
        return RP1_GPCLK_CORE_OK;
    }
    core->value.owner_id = 0;
    core->value.lease_id = 0;
    /* Retain the completed generation and terminal outcome for passive
     * inspection.  The next acquire resets them before accepting work. */
    core->value.route = RP1_GPCLK_ROUTE_INVALID;
    if (core->value.generation == 0) {
        core->value.state = RP1_GPCLK_STATE_IDLE;
        core->value.terminal_reason = RP1_GPCLK_REASON_NONE;
        core->value.total_units = 0;
        core->value.completed_units = 0;
    }
    core->value.drain_units = 0;
    core->value.terminal_publications = 0;
    core->value.terminal_attempts = 0;
    core->value.plan_loaded = 0;
    core->value.plan_releases = 0;
    core->pending_reason = RP1_GPCLK_REASON_NONE;
    core->owner_closing = 0;
    return RP1_GPCLK_CORE_OK;
}

int rp1_gpclk_core_owner_close(struct rp1_gpclk_core *core, __u64 owner_id)
{
    if (!core || owner_id == 0 || owner_id != core->value.owner_id)
        return RP1_GPCLK_CORE_STALE;
    if (core->value.state == RP1_GPCLK_STATE_RUNNING) {
        core->owner_closing = 1;
        core->value.state = RP1_GPCLK_STATE_DRAINING;
        core->pending_reason = RP1_GPCLK_REASON_OWNER_CLOSED;
        core->value.drain_units =
            core->value.completed_units < core->value.total_units ? 1 : 0;
        if (core->value.drain_units != 0)
            return RP1_GPCLK_CORE_OK;
        return rp1_gpclk_cleanup_and_publish(
            core, RP1_GPCLK_STATE_COMPLETE, RP1_GPCLK_REASON_OWNER_CLOSED);
    }
    if (core->value.state == RP1_GPCLK_STATE_DRAINING) {
        core->owner_closing = 1;
        core->pending_reason = RP1_GPCLK_REASON_OWNER_CLOSED;
        return RP1_GPCLK_CORE_OK;
    }
    return rp1_gpclk_core_release(core, owner_id, core->value.lease_id);
}

int rp1_gpclk_core_mark_dead(struct rp1_gpclk_core *core, __u32 reason)
{
    if (!core || reason != RP1_GPCLK_REASON_PROVIDER_REMOVED)
        return RP1_GPCLK_CORE_INVALID;
    if (rp1_gpclk_terminal(core->value.state))
        return RP1_GPCLK_CORE_STATE;
    return rp1_gpclk_cleanup_and_publish(core, RP1_GPCLK_STATE_DEAD, reason);
}

int rp1_gpclk_core_get_state(const struct rp1_gpclk_core *core,
                            __u64 owner_id, __u64 lease_id, __u64 generation,
                            struct rp1_gpclk_core_snapshot *snapshot)
{
    if (!core || !snapshot ||
        !rp1_gpclk_generation_matches(core, owner_id, lease_id, generation))
        return RP1_GPCLK_CORE_STALE;
    *snapshot = core->value;
    return RP1_GPCLK_CORE_OK;
}

int rp1_gpclk_core_get_public_state(const struct rp1_gpclk_core *core,
                                    struct rp1_gpclk_core_snapshot *snapshot)
{
    if (!core || !snapshot)
        return RP1_GPCLK_CORE_INVALID;
    *snapshot = core->value;
    return RP1_GPCLK_CORE_OK;
}

#ifdef RP1_GPCLK_HOST_TEST
void rp1_gpclk_core_inject_fault(struct rp1_gpclk_core *core,
                                 enum rp1_gpclk_core_fault_point point,
                                 __u32 occurrence)
{
    core->fault_point = point;
    core->fault_occurrence = occurrence;
    core->fault_seen = 0;
}

int rp1_gpclk_core_test_publish_terminal(struct rp1_gpclk_core *core,
                                         __u32 state, __u32 reason)
{
    return rp1_gpclk_publish_terminal(core, state, reason);
}
#endif
