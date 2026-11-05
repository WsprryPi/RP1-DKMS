// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <linux/rp1_gpclk.h>

#ifndef EUCLEAN
#define EUCLEAN 117
#endif

#define PARENT_HZ 200000000.0L
#define PERIOD 66792U
#define EVENT_DURATION_NS 100000000ULL

static void header(struct rp1_gpclk_uapi_header *value, size_t size)
{
	value->size = (uint16_t)size;
}

static void tone(struct rp1_gpclk_tone *out, long double frequency)
{
	long double ideal = PARENT_HZ * 65536.0L / frequency;
	uint64_t lower = (uint64_t)floorl(ideal);
	long double lower_frequency = PARENT_HZ * 65536.0L / (long double)lower;
	long double upper_frequency = PARENT_HZ * 65536.0L /
		(long double)(lower + 1);
	long double ratio = (frequency - upper_frequency) /
		(lower_frequency - upper_frequency);

	out->lower_divider_q16 = lower;
	out->upper_divider_q16 = lower + 1;
	out->lower_count = (uint32_t)llroundl(ratio * PERIOD);
	out->upper_count = PERIOD - out->lower_count;
}

static uint64_t monotonic_ns(void)
{
	struct timespec now;

	if (clock_gettime(CLOCK_MONOTONIC, &now)) {
		perror("clock_gettime");
		exit(1);
	}
	return (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
}

static int snapshot(int fd, struct rp1_gpclk_snapshot *value)
{
	memset(value, 0, sizeof(*value));
	header(&value->header, sizeof(*value));
	return ioctl(fd, RP1_GPCLK_IOC_GET_SNAPSHOT, value);
}

static int snapshots_equal(const struct rp1_gpclk_snapshot *first,
			   const struct rp1_gpclk_snapshot *second)
{
	const unsigned char *left = (const unsigned char *)first;
	const unsigned char *right = (const unsigned char *)second;
	size_t index;

	for (index = 0; index < sizeof(*first); index++) {
		if (left[index] == right[index])
			continue;
		fprintf(stderr,
			"retained snapshot changed at byte %zu: 0x%02x -> 0x%02x "
			"(elapsed=%llu -> %llu remaining=%llu -> %llu flags=0x%x -> 0x%x)\n",
			index, left[index], right[index],
			(unsigned long long)first->elapsed_ns,
			(unsigned long long)second->elapsed_ns,
			(unsigned long long)first->remaining_ns,
			(unsigned long long)second->remaining_ns,
			first->snapshot_flags, second->snapshot_flags);
		return 0;
	}
	return 1;
}

static int wait_terminal(int fd, uint64_t lease, uint64_t generation,
			 struct rp1_gpclk_state_request *state)
{
	const uint64_t deadline = monotonic_ns() + 5000000000ULL;
	struct timespec delay = { .tv_nsec = 1000000L };

	for (;;) {
		memset(state, 0, sizeof(*state));
		header(&state->header, sizeof(*state));
		state->lease_id = lease;
		state->generation = generation;
		if (ioctl(fd, RP1_GPCLK_IOC_GET_STATE, state))
			return -1;
		if (state->state == RP1_GPCLK_STATE_COMPLETE ||
		    state->state == RP1_GPCLK_STATE_FAILED)
			return 0;
		if (monotonic_ns() >= deadline)
			return -1;
		while (nanosleep(&delay, &delay) && errno == EINTR)
			;
		delay.tv_nsec = 1000000L;
	}
}

static int wait_snapshot_settled(int fd, uint64_t generation,
				 uint32_t reason, int cleanup_fault,
				 struct rp1_gpclk_snapshot *value)
{
	const uint64_t deadline = monotonic_ns() + 5000000000ULL;
	struct timespec delay = { .tv_nsec = 1000000L };
	uint32_t cleanup = cleanup_fault ? RP1_GPCLK_OBSERVATION_TRUE :
		RP1_GPCLK_OBSERVATION_FALSE;
	uint32_t stable = cleanup_fault ? RP1_GPCLK_OBSERVATION_FALSE :
		RP1_GPCLK_OBSERVATION_TRUE;

	for (;;) {
		if (snapshot(fd, value))
			return -1;
		if (value->generation == generation &&
		    value->operation_state == RP1_GPCLK_STATE_FAILED &&
		    value->terminal_reason == reason &&
		    value->cleanup_fault == cleanup &&
		    value->gpio_safe == RP1_GPCLK_OBSERVATION_TRUE &&
		    value->clock_quiescent == RP1_GPCLK_OBSERVATION_TRUE &&
		    value->dma_quiescent == RP1_GPCLK_OBSERVATION_TRUE &&
		    value->stable == stable)
			return 0;
		if (monotonic_ns() >= deadline)
			return -1;
		while (nanosleep(&delay, &delay) && errno == EINTR)
			;
		delay.tv_nsec = 1000000L;
	}
}

static unsigned long parse_number(const char *value, const char *name)
{
	char *end = NULL;
	unsigned long number;

	errno = 0;
	number = strtoul(value, &end, 10);
	if (errno || !end || *end) {
		fprintf(stderr, "invalid %s\n", name);
		exit(2);
	}
	return number;
}

int main(int argc, char **argv)
{
	struct rp1_gpclk_query query = { 0 };
	struct rp1_gpclk_acquire acquire = { 0 };
	struct rp1_gpclk_tone event_tone = { 0 };
	struct rp1_gpclk_event event = { 0 };
	struct rp1_gpclk_submit_events submit = { 0 };
	struct rp1_gpclk_state_request state = { 0 };
	struct rp1_gpclk_snapshot first = { 0 }, second = { 0 };
	struct rp1_gpclk_release release = { 0 };
	struct stat endpoint = { 0 };
	const char *route_environment = getenv("RP1_GPCLK_TEST_ROUTE");
	uint32_t expected_route = RP1_GPCLK_ROUTE_GPIO20;
	uint32_t expected_reason;
	int expected_cleanup;
	struct timespec retained_delay = { .tv_nsec = 100000000L };
	int fd;

	if (argc != 3) {
		fprintf(stderr, "usage: %s EXPECTED_REASON EXPECTED_CLEANUP_0_OR_1\n",
			argv[0]);
		return 2;
	}
	expected_reason = (uint32_t)parse_number(argv[1], "reason");
	expected_cleanup = (int)parse_number(argv[2], "cleanup");
	if (expected_cleanup != 0 && expected_cleanup != 1)
		return 2;
	if (route_environment && !strcmp(route_environment, "4"))
		expected_route = RP1_GPCLK_ROUTE_GPIO4;
	else if (route_environment && strcmp(route_environment, "20"))
		return 2;

	fd = open("/dev/rp1-gpclk", O_RDWR | O_CLOEXEC);
	if (fd < 0) { perror("open"); return 1; }
	if (fstat(fd, &endpoint) || !S_ISCHR(endpoint.st_mode) ||
	    endpoint.st_uid != 0 || (endpoint.st_mode & 0777) != 0600)
		return 1;
	header(&query.header, sizeof(query));
	if (ioctl(fd, RP1_GPCLK_IOC_QUERY, &query) ||
	    query.route != expected_route ||
	    !(query.capabilities & RP1_GPCLK_CAP_CLEANUP_FAULT_LATCH))
		return 1;
	header(&acquire.header, sizeof(acquire));
	acquire.expected_route = expected_route;
	acquire.required_capabilities = RP1_GPCLK_CAP_CLEANUP_FAULT_LATCH |
		RP1_GPCLK_CAP_PASSIVE_SNAPSHOT;
	if (ioctl(fd, RP1_GPCLK_IOC_ACQUIRE, &acquire))
		return 1;
	tone(&event_tone, 10140200.0L);
	event.duration_ns = EVENT_DURATION_NS;
	event.flags = RP1_GPCLK_EVENT_F_OUTPUT_ENABLED;
	header(&submit.header, sizeof(submit));
	submit.lease_id = acquire.lease_id;
	submit.tones_ptr = (uintptr_t)&event_tone;
	submit.events_ptr = (uintptr_t)&event;
	submit.fractional_bits = RP1_GPCLK_FRACTIONAL_BITS;
	submit.tick_divider = RP1_GPCLK_TICK_DIVIDER;
	submit.tone_count = 1;
	submit.event_count = 1;
	submit.drive_ma = RP1_GPCLK_DRIVE_MA_2;
	submit.total_duration_ns = event.duration_ns;
	if (ioctl(fd, RP1_GPCLK_IOC_SUBMIT_EVENTS, &submit))
		return 1;
	if (wait_terminal(fd, acquire.lease_id, submit.generation, &state) ||
	    state.state != RP1_GPCLK_STATE_FAILED ||
	    state.terminal_reason != expected_reason ||
	    !!state.cleanup_fault != expected_cleanup)
		return 1;
	if (wait_snapshot_settled(fd, submit.generation, expected_reason,
			expected_cleanup, &first))
		return 1;
	while (nanosleep(&retained_delay, &retained_delay) && errno == EINTR)
		;
	if (snapshot(fd, &second) || !snapshots_equal(&first, &second))
		return 1;
	if (first.owner_present != RP1_GPCLK_OBSERVATION_TRUE ||
	    first.lease_present != RP1_GPCLK_OBSERVATION_TRUE)
		return 1;
	header(&release.header, sizeof(release));
	release.lease_id = acquire.lease_id;
	release.generation = submit.generation;
	if (expected_cleanup) {
		errno = 0;
		if (!ioctl(fd, RP1_GPCLK_IOC_RELEASE, &release) ||
		    errno != EUCLEAN)
			return 1;
	} else {
		if (ioctl(fd, RP1_GPCLK_IOC_RELEASE, &release))
			return 1;
		if (snapshot(fd, &second) ||
		    second.owner_present != RP1_GPCLK_OBSERVATION_FALSE ||
		    second.lease_present != RP1_GPCLK_OBSERVATION_FALSE ||
		    second.stable != RP1_GPCLK_OBSERVATION_TRUE)
			return 1;
	}
	printf("reason=%u cleanup_fault=%d terminal_retained=1 gpio_safe=1 clock_quiescent=1 dma_quiescent=1 release=%s\n",
	       expected_reason, expected_cleanup,
	       expected_cleanup ? "latched" : "complete");
	close(fd);
	return 0;
}
