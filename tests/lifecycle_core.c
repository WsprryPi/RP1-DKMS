// SPDX-License-Identifier: MIT
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rp1_gpclk/core.h"

#define OWNER_A 0x41ULL
#define OWNER_B 0x42ULL

static unsigned int tests_run;

#define CHECK(expression)                                                     \
    do {                                                                      \
        if (!(expression)) {                                                  \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, \
                    #expression);                                             \
            exit(1);                                                          \
        }                                                                     \
    } while (0)

#define RUN(test)                                                             \
    do {                                                                      \
        test();                                                               \
        tests_run++;                                                          \
    } while (0)

static void fill_tones(struct rp1_gpclk_tone *tones, __u32 count,
                       __u32 period)
{
    __u32 index;

    for (index = 0; index < count; index++) {
        tones[index].lower_divider_q16 = 1000 + index * 2;
        tones[index].upper_divider_q16 = tones[index].lower_divider_q16 + 1;
        tones[index].lower_count = 1;
        tones[index].upper_count = period - 1;
    }
}

static void setup_events(struct rp1_gpclk_submit_events *request,
                         struct rp1_gpclk_tone *tones,
                         struct rp1_gpclk_event *events, __u32 count)
{
    __u32 index;

    memset(request, 0, sizeof(*request));
    memset(tones, 0, sizeof(*tones) * RP1_GPCLK_MAX_TONES);
    memset(events, 0, sizeof(*events) * count);
    request->header.size = sizeof(*request);
    request->fractional_bits = RP1_GPCLK_FRACTIONAL_BITS;
    request->tick_divider = RP1_GPCLK_TICK_DIVIDER;
    request->tone_count = 1;
    request->event_count = count;
    request->drive_ma = RP1_GPCLK_DRIVE_MA_2;
    request->total_duration_ns = (__u64)count * RP1_GPCLK_EVENT_DURATION_NS_MIN;
    fill_tones(tones, 1, 2);
    for (index = 0; index < count; index++) {
        events[index].duration_ns = RP1_GPCLK_EVENT_DURATION_NS_MIN;
        events[index].flags = RP1_GPCLK_EVENT_F_OUTPUT_ENABLED;
    }
}

static __u64 acquire(struct rp1_gpclk_core *core, __u64 owner)
{
    __u64 lease = 0;

    CHECK(rp1_gpclk_core_acquire(core, owner, RP1_GPCLK_ROUTE_GPIO4, 0,
                                 &lease) == RP1_GPCLK_CORE_OK);
    CHECK(lease != 0);
    return lease;
}

static __u64 submit_events(struct rp1_gpclk_core *core, __u64 owner,
                           __u64 lease, __u32 count)
{
    struct rp1_gpclk_submit_events request;
    struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
    struct rp1_gpclk_event events[4];

    CHECK(count <= 4);
    setup_events(&request, tones, events, count);
    request.lease_id = lease;
    CHECK(rp1_gpclk_core_submit_events(core, owner, &request, tones, events) ==
          RP1_GPCLK_CORE_OK);
    CHECK(request.generation != 0);
    CHECK(core->value.plan_loaded == 1);
    return request.generation;
}

static void test_initial_and_acquire(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    struct rp1_gpclk_core_snapshot snapshot;
    __u64 lease;

    rp1_gpclk_core_init(&core);
    CHECK(core.value.state == RP1_GPCLK_STATE_IDLE);
    CHECK(core.value.owner_id == 0);
    CHECK(rp1_gpclk_core_get_public_state(&core, &snapshot) ==
          RP1_GPCLK_CORE_OK);
    CHECK(snapshot.owner_id == 0 && snapshot.lease_id == 0);
    CHECK(snapshot.generation == 0);
    before = core;
    CHECK(rp1_gpclk_core_acquire(&core, 0, RP1_GPCLK_ROUTE_GPIO4, 0, &lease) ==
          RP1_GPCLK_CORE_INVALID);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    lease = acquire(&core, OWNER_A);
    before = core;
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_B, RP1_GPCLK_ROUTE_GPIO20, 0,
                                 &lease) == RP1_GPCLK_CORE_BUSY);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
}

static void test_repeated_route_ownership(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    __u64 lease, refused, previous = 0;
    unsigned int iteration;

    rp1_gpclk_core_init(&core);
    for (iteration = 0; iteration < 12; iteration++) {
        __u32 route = iteration % 2 ? RP1_GPCLK_ROUTE_GPIO20 : RP1_GPCLK_ROUTE_GPIO4;
        __u32 other = iteration % 2 ? RP1_GPCLK_ROUTE_GPIO4 : RP1_GPCLK_ROUTE_GPIO20;

        CHECK(rp1_gpclk_core_acquire(&core, OWNER_A, route, 0, &lease) == RP1_GPCLK_CORE_OK);
        CHECK(lease > previous && core.value.route == route);
        previous = lease;
        before = core;
        refused = 0xfeed;
        CHECK(rp1_gpclk_core_acquire(&core, OWNER_B, other, 0, &refused) == RP1_GPCLK_CORE_BUSY);
        CHECK(refused == 0xfeed && memcmp(&before, &core, sizeof(core)) == 0);
        CHECK(rp1_gpclk_core_acquire(&core, OWNER_A, other, 0, &refused) == RP1_GPCLK_CORE_BUSY);
        CHECK(refused == 0xfeed && memcmp(&before, &core, sizeof(core)) == 0);
        CHECK(rp1_gpclk_core_release(&core, OWNER_B, lease) == RP1_GPCLK_CORE_STALE);
        CHECK(memcmp(&before, &core, sizeof(core)) == 0);
        CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) == RP1_GPCLK_CORE_OK);
        CHECK(core.value.owner_id == 0 && core.value.lease_id == 0);
    }
}

static void test_passive_retained_terminal_state(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core_snapshot snapshot;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 1);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
          RP1_GPCLK_CORE_OK);
    CHECK(rp1_gpclk_core_get_public_state(&core, &snapshot) ==
          RP1_GPCLK_CORE_OK);
    CHECK(snapshot.owner_id == 0 && snapshot.lease_id == 0);
    CHECK(snapshot.generation == generation);
    CHECK(snapshot.state == RP1_GPCLK_STATE_COMPLETE);
    CHECK(snapshot.terminal_reason == RP1_GPCLK_REASON_COMPLETE);

    lease = acquire(&core, OWNER_B);
    CHECK(rp1_gpclk_core_get_public_state(&core, &snapshot) ==
          RP1_GPCLK_CORE_OK);
    CHECK(snapshot.owner_id == OWNER_B && snapshot.lease_id == lease);
    CHECK(snapshot.generation == 0);
    CHECK(snapshot.state == RP1_GPCLK_STATE_IDLE);
}

static void test_passive_inspection_does_not_mutate_owner(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    struct rp1_gpclk_core_snapshot snapshot;
    __u64 lease;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    before = core;
    CHECK(rp1_gpclk_core_get_public_state(&core, &snapshot) ==
          RP1_GPCLK_CORE_OK);
    CHECK(snapshot.owner_id == OWNER_A && snapshot.lease_id == lease);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    /* A passive descriptor close has no core call; a second observation is
     * therefore identical and the actual owner remains authoritative. */
    CHECK(rp1_gpclk_core_get_public_state(&core, &snapshot) ==
          RP1_GPCLK_CORE_OK);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
}

static void test_routes_capabilities_and_wrap(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    __u64 lease = 0;

    rp1_gpclk_core_init(&core);
    before = core;
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_A, 3, 0, &lease) ==
          RP1_GPCLK_CORE_INVALID);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_A, RP1_GPCLK_ROUTE_GPIO4,
                                 1ULL << 63, &lease) ==
          RP1_GPCLK_CORE_INVALID);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    core.value.next_lease_id = ~(__u64)0;
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_A, RP1_GPCLK_ROUTE_GPIO20, 0,
                                 &lease) == RP1_GPCLK_CORE_INVALID);
    CHECK(core.value.owner_id == 0);
}

static void test_validation(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_submit_events events_request;
    struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
    struct rp1_gpclk_event events[2];
    struct rp1_gpclk_core before;
    __u64 lease;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    setup_events(&events_request, tones, events, 2);
    events_request.lease_id = lease;
    events[0].duration_ns = RP1_GPCLK_EVENT_DURATION_NS_MAX;
    events_request.total_duration_ns = RP1_GPCLK_EVENT_DURATION_NS_MAX;
    before = core;
    CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &events_request, tones,
                                       events) == RP1_GPCLK_CORE_INVALID);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    events[0].duration_ns = 1200000000000ULL;
    events[1].duration_ns = RP1_GPCLK_EVENT_DURATION_NS_MIN;
    events_request.total_duration_ns = events[0].duration_ns +
        events[1].duration_ns;
    CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &events_request, tones,
                                       events) == RP1_GPCLK_CORE_OK);
    CHECK(events_request.generation == 1);
}

static void test_validation_matrix(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    struct rp1_gpclk_submit_events request;
    struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
    struct rp1_gpclk_event events[2];
    __u64 lease;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);

#define EXPECT_EVENT_INVALID(change)                                          \
    do {                                                                      \
        setup_events(&request, tones, events, 2);                             \
        request.lease_id = lease;                                             \
        change;                                                               \
        before = core;                                                        \
        CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &request, tones,   \
                                           events) ==                         \
              RP1_GPCLK_CORE_INVALID);                                        \
        CHECK(memcmp(&before, &core, sizeof(core)) == 0);                     \
    } while (0)

    EXPECT_EVENT_INVALID(request.header.size--);
    EXPECT_EVENT_INVALID(request.header.reserved++);
    EXPECT_EVENT_INVALID(request.header.flags = 1);
    EXPECT_EVENT_INVALID(request.reserved0 = 1);
    EXPECT_EVENT_INVALID(request.reserved1 = 1);
    EXPECT_EVENT_INVALID(request.reserved2 = 1);
    EXPECT_EVENT_INVALID(request.reserved[3] = 1);
    EXPECT_EVENT_INVALID(request.generation = 1);
    EXPECT_EVENT_INVALID(request.fractional_bits--);
    EXPECT_EVENT_INVALID(request.tick_divider--);
    EXPECT_EVENT_INVALID(request.event_count = 0);
    EXPECT_EVENT_INVALID(request.tone_count = 0);
    EXPECT_EVENT_INVALID(request.drive_ma = 3);
    EXPECT_EVENT_INVALID(tones[0].upper_divider_q16++);
    EXPECT_EVENT_INVALID(tones[0].lower_count = 0);
    EXPECT_EVENT_INVALID(events[0].flags = 2);
    EXPECT_EVENT_INVALID(events[0].tone_index = 1);
    EXPECT_EVENT_INVALID(events[0].duration_ns = 0);
    EXPECT_EVENT_INVALID(events[0].flags = 0; events[0].tone_index = 1);
    EXPECT_EVENT_INVALID(request.total_duration_ns++);

#undef EXPECT_EVENT_INVALID
}

static void test_stop_and_exactly_one(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core frozen;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 3);
    CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_DRAINING);
    CHECK(core.value.drain_units == 1);
    CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_COMPLETE);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_STOPPED);
    CHECK(core.value.terminal_publications == 1);
    CHECK(core.value.plan_releases == 1);
    frozen = core;
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_STATE);
    CHECK(rp1_gpclk_core_fail(&core, OWNER_A, lease, generation,
                              RP1_GPCLK_REASON_DMA_FAILED) ==
          RP1_GPCLK_CORE_STATE);
    CHECK(memcmp(&frozen, &core, sizeof(core)) == 0);
    CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.terminal_publications == 1);
    CHECK(core.value.plan_releases == 1);
}

static void test_stale_generation(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    __u64 lease;
    __u64 old_generation;
    __u64 new_generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    old_generation = submit_events(&core, OWNER_A, lease, 1);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, old_generation) ==
          RP1_GPCLK_CORE_OK);
    new_generation = submit_events(&core, OWNER_A, lease, 2);
    CHECK(new_generation == old_generation + 1);
    before = core;
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, old_generation) ==
          RP1_GPCLK_CORE_STALE);
    CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease, old_generation) ==
          RP1_GPCLK_CORE_STALE);
    CHECK(rp1_gpclk_core_fail(&core, OWNER_A, lease, old_generation,
                              RP1_GPCLK_REASON_DMA_FAILED) ==
          RP1_GPCLK_CORE_STALE);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_B, lease, new_generation) ==
          RP1_GPCLK_CORE_STALE);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
}

static void test_release_and_owner_close(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core before;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 2);
    before = core;
    CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
          RP1_GPCLK_CORE_BUSY);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
    CHECK(rp1_gpclk_core_owner_close(&core, OWNER_A) == RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_DRAINING);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_OWNER_CLOSED);
    CHECK(core.value.terminal_publications == 1);
    CHECK(core.value.owner_id == 0);
    CHECK(core.value.lease_id == 0);
    CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
          RP1_GPCLK_CORE_STALE);
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_B, RP1_GPCLK_ROUTE_GPIO20, 0,
                                 &lease) == RP1_GPCLK_CORE_OK);
}

static void test_cleanup_latch(void)
{
    struct rp1_gpclk_core core;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 1);
    rp1_gpclk_core_inject_fault(&core, RP1_GPCLK_FAULT_CLEANUP, 1);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_FAILED);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_CLEANUP_FAILED);
    CHECK(core.value.cleanup_fault == 1);
    CHECK(core.value.terminal_publications == 1);
    CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
          RP1_GPCLK_CORE_LATCHED);
}

static void test_runtime_cleanup_failure_latch(void)
{
    struct rp1_gpclk_core core;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 2);
    CHECK(rp1_gpclk_core_cleanup_failed(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_FAILED);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_CLEANUP_FAILED);
    CHECK(core.value.cleanup_fault == 1);
    CHECK(core.value.plan_loaded == 0);
    CHECK(core.value.plan_releases == 1);
    CHECK(core.value.terminal_publications == 1);
    CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
          RP1_GPCLK_CORE_LATCHED);
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_B, RP1_GPCLK_ROUTE_GPIO4, 0,
                                 &lease) == RP1_GPCLK_CORE_LATCHED);
}

static void test_owner_close_during_stop_drain(void)
{
    struct rp1_gpclk_core core;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 3);
    CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(rp1_gpclk_core_owner_close(&core, OWNER_A) == RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_DRAINING);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_COMPLETE);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_OWNER_CLOSED);
    CHECK(core.value.terminal_publications == 1);
    CHECK(core.value.owner_id == 0);
    CHECK(core.value.lease_id == 0);
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_B, RP1_GPCLK_ROUTE_GPIO4, 0,
                                 &lease) == RP1_GPCLK_CORE_OK);
}

static void test_owner_close_authority(void)
{
    const __u32 routes[] = { RP1_GPCLK_ROUTE_GPIO4, RP1_GPCLK_ROUTE_GPIO20 };
    const __u32 faults[] = { RP1_GPCLK_FAULT_NONE, RP1_GPCLK_FAULT_CLEANUP,
                             RP1_GPCLK_FAULT_TERMINAL_PRECOMMIT };
    unsigned int route_index;
    unsigned int fault_index;
    unsigned int stop_first;

    for (route_index = 0; route_index < 2; route_index++) {
        for (fault_index = 0; fault_index < 3; fault_index++) {
            for (stop_first = 0; stop_first < 2; stop_first++) {
                struct rp1_gpclk_core core;
                struct rp1_gpclk_core before;
                struct rp1_gpclk_core_snapshot snapshot;
                __u64 lease;
                __u64 next_lease;
                __u64 generation;
                __u32 reason = RP1_GPCLK_REASON_OWNER_CLOSED;

                rp1_gpclk_core_init(&core);
                CHECK(rp1_gpclk_core_acquire(&core, OWNER_A,
                          routes[route_index], 0, &lease) == RP1_GPCLK_CORE_OK);
                generation = submit_events(&core, OWNER_A, lease, 3);
                if (stop_first)
                    CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease,
                              generation) == RP1_GPCLK_CORE_OK);
                CHECK(rp1_gpclk_core_owner_close(&core, OWNER_A) ==
                      RP1_GPCLK_CORE_OK);
                CHECK(core.value.state == RP1_GPCLK_STATE_DRAINING);
                CHECK(core.value.owner_id == OWNER_A);
                CHECK(core.value.lease_id == lease);
                CHECK(core.value.terminal_publications == 0);
                if (faults[fault_index] != RP1_GPCLK_FAULT_NONE)
                    rp1_gpclk_core_inject_fault(&core, faults[fault_index], 1);
                CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease,
                          generation) == RP1_GPCLK_CORE_OK);
                if (faults[fault_index] == RP1_GPCLK_FAULT_CLEANUP)
                    reason = RP1_GPCLK_REASON_CLEANUP_FAILED;
                else if (faults[fault_index] == RP1_GPCLK_FAULT_TERMINAL_PRECOMMIT)
                    reason = RP1_GPCLK_REASON_INTERNAL_ERROR;
                CHECK(core.value.state == (fault_index == 0 ?
                      RP1_GPCLK_STATE_COMPLETE : RP1_GPCLK_STATE_FAILED));
                CHECK(core.value.terminal_reason == reason);
                CHECK(core.value.cleanup_fault == (faults[fault_index] ==
                      RP1_GPCLK_FAULT_CLEANUP));
                CHECK(core.value.generation == generation);
                CHECK(core.value.completed_units == 1);
                CHECK(core.value.drain_units == 0);
                CHECK(core.value.plan_loaded == 0);
                CHECK(core.value.plan_releases == 1);
                CHECK(core.value.terminal_publications == 1);
                CHECK(core.owner_closing == 0);
                CHECK(rp1_gpclk_core_get_public_state(&core, &snapshot) ==
                      RP1_GPCLK_CORE_OK);
                CHECK(snapshot.owner_id == 0 && snapshot.lease_id == 0);
                CHECK(snapshot.generation == generation);
                CHECK(snapshot.terminal_reason == reason);
                before = core;
                CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease,
                          generation) == RP1_GPCLK_CORE_STALE);
                CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease,
                          generation) == RP1_GPCLK_CORE_STALE);
                CHECK(rp1_gpclk_core_owner_close(&core, OWNER_A) ==
                      RP1_GPCLK_CORE_STALE);
                CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
                      RP1_GPCLK_CORE_STALE);
                CHECK(memcmp(&before, &core, sizeof(core)) == 0);
                CHECK(rp1_gpclk_core_acquire(&core, OWNER_B,
                          routes[route_index], 0, &next_lease) ==
                      (faults[fault_index] == RP1_GPCLK_FAULT_CLEANUP ?
                       RP1_GPCLK_CORE_LATCHED : RP1_GPCLK_CORE_OK));
                if (faults[fault_index] == RP1_GPCLK_FAULT_CLEANUP)
                    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
                else
                    CHECK(next_lease != 0 && next_lease != lease);
            }
        }
    }
}

static void test_generation_wrap(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_submit_events request;
    struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
    struct rp1_gpclk_event event;
    struct rp1_gpclk_core before;
    __u64 lease;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    core.value.next_generation = ~(__u64)0;
    setup_events(&request, tones, &event, 1);
    request.lease_id = lease;
    before = core;
    CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &request, tones,
                                       &event) == RP1_GPCLK_CORE_INVALID);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);
}

static void test_limit_boundaries(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_submit_events request;
    struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
    struct rp1_gpclk_event events[RP1_GPCLK_MAX_EVENTS];
    struct rp1_gpclk_core before;
    __u64 lease;
    __u64 generation;
    __u32 index;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    setup_events(&request, tones, events, RP1_GPCLK_MAX_EVENTS);
    request.lease_id = lease;
    CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &request, tones,
                                       events) == RP1_GPCLK_CORE_OK);
    generation = request.generation;
    for (index = 0; index < RP1_GPCLK_MAX_EVENTS; index++)
        CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease, generation) ==
              RP1_GPCLK_CORE_OK);
    CHECK(core.value.completed_units == RP1_GPCLK_MAX_EVENTS);
    CHECK(core.value.terminal_publications == 1);
    CHECK(core.value.plan_releases == 1);

    setup_events(&request, tones, events, 1);
    request.lease_id = lease;
    request.event_count = RP1_GPCLK_MAX_EVENTS + 1;
    before = core;
    CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &request, tones,
                                       events) == RP1_GPCLK_CORE_INVALID);
    CHECK(memcmp(&before, &core, sizeof(core)) == 0);

    setup_events(&request, tones, events, 1);
    request.lease_id = lease;
    events[0].duration_ns = RP1_GPCLK_EVENT_DURATION_NS_MAX;
    request.total_duration_ns = RP1_GPCLK_EVENT_DURATION_NS_MAX;
    CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &request, tones,
                                       events) == RP1_GPCLK_CORE_OK);
    CHECK(rp1_gpclk_core_progress(&core, OWNER_A, lease,
                                  request.generation) == RP1_GPCLK_CORE_OK);

}

static void test_terminal_precedence_and_dead(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core frozen;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 2);
    CHECK(rp1_gpclk_core_fail(&core, OWNER_A, lease, generation,
                              RP1_GPCLK_REASON_DMA_FAILED) ==
          RP1_GPCLK_CORE_OK);
    frozen = core;
    CHECK(rp1_gpclk_core_mark_dead(&core,
                                   RP1_GPCLK_REASON_PROVIDER_REMOVED) ==
          RP1_GPCLK_CORE_STATE);
    CHECK(memcmp(&frozen, &core, sizeof(core)) == 0);
    CHECK(core.value.terminal_publications == 1);

    rp1_gpclk_core_init(&core);
    CHECK(rp1_gpclk_core_mark_dead(&core,
                                   RP1_GPCLK_REASON_PROVIDER_REMOVED) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.state == RP1_GPCLK_STATE_DEAD);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_PROVIDER_REMOVED);
    CHECK(core.value.terminal_publications == 0);
}

static void test_dead_release_does_not_resurrect(void)
{
    struct rp1_gpclk_core core;
    __u64 lease;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    CHECK(rp1_gpclk_core_mark_dead(&core,
                                   RP1_GPCLK_REASON_PROVIDER_REMOVED) ==
          RP1_GPCLK_CORE_OK);
    CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.owner_id == 0);
    CHECK(core.value.state == RP1_GPCLK_STATE_DEAD);
    CHECK(core.value.terminal_reason == RP1_GPCLK_REASON_PROVIDER_REMOVED);
    CHECK(rp1_gpclk_core_acquire(&core, OWNER_B, RP1_GPCLK_ROUTE_GPIO4, 0,
                                 &lease) == RP1_GPCLK_CORE_BUSY);
}

static void test_failure_reason_matrix(void)
{
    __u32 reason;

    for (reason = RP1_GPCLK_REASON_DEADLINE_MISSED;
         reason <= RP1_GPCLK_REASON_INTERNAL_ERROR; reason++) {
        struct rp1_gpclk_core core;
        __u64 lease;
        __u64 generation;

        if (reason == RP1_GPCLK_REASON_CLEANUP_FAILED)
            continue;
        rp1_gpclk_core_init(&core);
        lease = acquire(&core, OWNER_A);
        generation = submit_events(&core, OWNER_A, lease, 1);
        CHECK(rp1_gpclk_core_fail(&core, OWNER_A, lease, generation, reason) ==
              RP1_GPCLK_CORE_OK);
        CHECK(core.value.state == RP1_GPCLK_STATE_FAILED);
        CHECK(core.value.terminal_reason == reason);
        CHECK(core.value.terminal_publications == 1);
    }
}

static void test_central_terminal_guard(void)
{
    struct rp1_gpclk_core core;
    struct rp1_gpclk_core frozen;
    __u64 lease;
    __u64 generation;

    rp1_gpclk_core_init(&core);
    lease = acquire(&core, OWNER_A);
    generation = submit_events(&core, OWNER_A, lease, 2);
    CHECK(generation != 0);
    CHECK(rp1_gpclk_core_test_publish_terminal(
              &core, RP1_GPCLK_STATE_COMPLETE, RP1_GPCLK_REASON_COMPLETE) ==
          RP1_GPCLK_CORE_OK);
    CHECK(core.value.terminal_publications == 1);
    frozen = core;
    CHECK(rp1_gpclk_core_test_publish_terminal(
              &core, RP1_GPCLK_STATE_FAILED, RP1_GPCLK_REASON_DMA_FAILED) ==
          RP1_GPCLK_CORE_STATE);
    CHECK(memcmp(&frozen, &core, sizeof(core)) == 0);
}

static void test_fault_points(void)
{
    enum rp1_gpclk_core_fault_point point;

    for (point = RP1_GPCLK_FAULT_ACQUIRE_PRECOMMIT;
         point < RP1_GPCLK_FAULT_POINT_COUNT; point++) {
        struct rp1_gpclk_core core;
        struct rp1_gpclk_core before;
        __u64 lease = 0;
        __u64 generation;
        int result;

        rp1_gpclk_core_init(&core);
        if (point == RP1_GPCLK_FAULT_ACQUIRE_PRECOMMIT) {
            before = core;
            rp1_gpclk_core_inject_fault(&core, point, 1);
            CHECK(rp1_gpclk_core_acquire(&core, OWNER_A,
                                         RP1_GPCLK_ROUTE_GPIO4, 0, &lease) ==
                  RP1_GPCLK_CORE_FAULT);
            CHECK(core.value.owner_id == before.value.owner_id);
            CHECK(core.value.next_lease_id == before.value.next_lease_id);
            continue;
        }
        lease = acquire(&core, OWNER_A);
        if (point == RP1_GPCLK_FAULT_SUBMIT_COPY ||
            point == RP1_GPCLK_FAULT_SUBMIT_PRECOMMIT) {
            struct rp1_gpclk_submit_events request;
            struct rp1_gpclk_tone tones[RP1_GPCLK_MAX_TONES];
            struct rp1_gpclk_event event;

            setup_events(&request, tones, &event, 1);
            request.lease_id = lease;
            before = core;
            rp1_gpclk_core_inject_fault(&core, point, 1);
            CHECK(rp1_gpclk_core_submit_events(&core, OWNER_A, &request,
                                               tones, &event) ==
                  RP1_GPCLK_CORE_FAULT);
            CHECK(core.value.generation == before.value.generation);
            CHECK(core.value.next_generation == before.value.next_generation);
            continue;
        }
        generation = submit_events(&core, OWNER_A, lease, 2);
        rp1_gpclk_core_inject_fault(&core, point, 1);
        if (point == RP1_GPCLK_FAULT_PROGRESS_PRECOMMIT ||
            point == RP1_GPCLK_FAULT_TERMINAL_PRECOMMIT ||
            point == RP1_GPCLK_FAULT_CLEANUP) {
            if (point != RP1_GPCLK_FAULT_PROGRESS_PRECOMMIT)
                core.value.completed_units = core.value.total_units - 1;
            result = rp1_gpclk_core_progress(&core, OWNER_A, lease, generation);
            CHECK(result == RP1_GPCLK_CORE_OK);
            CHECK(core.value.terminal_publications == 1);
            CHECK(core.value.state == RP1_GPCLK_STATE_FAILED);
            continue;
        }
        if (point == RP1_GPCLK_FAULT_STOP_PRECOMMIT) {
            before = core;
            CHECK(rp1_gpclk_core_stop(&core, OWNER_A, lease, generation) ==
                  RP1_GPCLK_CORE_FAULT);
            CHECK(core.value.state == before.value.state);
            continue;
        }
        CHECK(rp1_gpclk_core_fail(&core, OWNER_A, lease, generation,
                                  RP1_GPCLK_REASON_INTERNAL_ERROR) ==
              RP1_GPCLK_CORE_OK);
        before = core;
        CHECK(rp1_gpclk_core_release(&core, OWNER_A, lease) ==
              RP1_GPCLK_CORE_FAULT);
        CHECK(core.value.owner_id == before.value.owner_id);
    }
}

int main(void)
{
    RUN(test_initial_and_acquire);
    RUN(test_repeated_route_ownership);
    RUN(test_passive_retained_terminal_state);
    RUN(test_passive_inspection_does_not_mutate_owner);
    RUN(test_routes_capabilities_and_wrap);
    RUN(test_validation);
    RUN(test_validation_matrix);
    RUN(test_stop_and_exactly_one);
    RUN(test_stale_generation);
    RUN(test_release_and_owner_close);
    RUN(test_cleanup_latch);
    RUN(test_runtime_cleanup_failure_latch);
    RUN(test_owner_close_during_stop_drain);
    RUN(test_owner_close_authority);
    RUN(test_generation_wrap);
    RUN(test_limit_boundaries);
    RUN(test_terminal_precedence_and_dead);
    RUN(test_dead_release_does_not_resurrect);
    RUN(test_failure_reason_matrix);
    RUN(test_central_terminal_guard);
    RUN(test_fault_points);
    printf("lifecycle core: PASS (%u groups)\n", tests_run);
    return 0;
}
