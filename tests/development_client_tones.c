// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>

/* No endpoint access is possible, even if the unused client entry is called. */
static int forbidden_open(const char *path, int flags, ...)
{
    (void)path;
    (void)flags;
    fputs("offline tone test attempted to open an endpoint\n", stderr);
    abort();
}

static int forbidden_ioctl(int fd, unsigned long request, ...)
{
    (void)fd;
    (void)request;
    fputs("offline tone test attempted an ioctl\n", stderr);
    abort();
}

/* Compile each real client, but invoke only its pure divider planner. */
#define open forbidden_open
#define ioctl forbidden_ioctl
#define main unused_target_client_main
#include RP1_GPCLK_TEST_CLIENT_SOURCE
#undef main
#undef ioctl
#undef open

#include "rp1_gpclk/resource_policy.h"

int main(void)
{
    const long double frequency = 10140200.0L;
    const long double scaled_parent = 200000000.0L * 65536.0L;
    struct rp1_gpclk_tone planned = { 0 };
    long double lower_frequency, upper_frequency, achieved_frequency;

    assert(PARENT_HZ == RP1_GPCLK_PARENT_RATE_HZ);
    tone(&planned, frequency);

    /* Independent exact-rational fixture for the clients' fixed test tone. */
    assert(planned.lower_divider_q16 == 1292597U);
    assert(planned.upper_divider_q16 == 1292598U);
    assert(planned.lower_count == 14752U);
    assert(planned.upper_count == 52040U);
    assert(planned.lower_count + planned.upper_count == PERIOD);
    assert(PERIOD <= RP1_GPCLK_DITHER_PERIOD_MAX);
    assert(planned.lower_divider_q16 >= 65536U);
    assert(planned.upper_divider_q16 <= UINT32_MAX);
    assert((planned.lower_divider_q16 >> 16) ==
           (planned.upper_divider_q16 >> 16));

    lower_frequency = scaled_parent / planned.lower_divider_q16;
    upper_frequency = scaled_parent / planned.upper_divider_q16;
    assert(upper_frequency <= frequency && frequency <= lower_frequency);
    achieved_frequency =
        (lower_frequency * planned.lower_count +
         upper_frequency * planned.upper_count) / PERIOD;
    assert(fabsl(achieved_frequency - frequency) < 0.0001L);

    printf("%s: 200 MHz fixed-tone divider planning: PASS\n",
           RP1_GPCLK_TEST_CLIENT_SOURCE);
    return 0;
}
