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

#define PARENT_HZ 200000000.0L
#define PERIOD 66792U
#define CANCELLATION_LATENCY_ALLOWANCE_NS 500000000ULL

enum cancellation_position {
	CANCEL_NONE,
	CANCEL_START,
	CANCEL_MIDDLE,
	CANCEL_BOUNDARY,
};

static void header(struct rp1_gpclk_uapi_header *value, size_t size)
{
	value->size = (uint16_t)size;
}

static void tone(struct rp1_gpclk_tone *out, long double frequency)
{
	long double ideal = PARENT_HZ * 65536.0L / frequency;
	uint64_t lower = (uint64_t)floorl(ideal);
	long double lower_frequency = PARENT_HZ * 65536.0L / (long double)lower;
	long double upper_frequency = PARENT_HZ * 65536.0L / (long double)(lower + 1);
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

static int read_state(int fd, uint64_t lease, uint64_t generation,
		      struct rp1_gpclk_state_request *state)
{
	memset(state, 0, sizeof(*state));
	header(&state->header, sizeof(*state));
	state->lease_id = lease;
	state->generation = generation;
	return ioctl(fd, RP1_GPCLK_IOC_GET_STATE, state);
}

static int read_snapshot(int fd, struct rp1_gpclk_snapshot *snapshot)
{
	memset(snapshot, 0, sizeof(*snapshot));
	header(&snapshot->header, sizeof(*snapshot));
	return ioctl(fd, RP1_GPCLK_IOC_GET_SNAPSHOT, snapshot);
}

static int wait_for_stable_snapshot(int fd, uint64_t generation,
				    uint32_t terminal_reason,
				    uint32_t drain_state,
				    uint32_t owner_present,
				    struct rp1_gpclk_snapshot *snapshot)
{
	const uint64_t deadline = monotonic_ns() + 5000000000ULL;
	struct timespec delay = { .tv_nsec = 1000000L };

	for (;;) {
		if (read_snapshot(fd, snapshot)) {
			perror("GET_SNAPSHOT");
			return -1;
		}
		if (snapshot->generation == generation &&
		    snapshot->operation_state == RP1_GPCLK_STATE_COMPLETE &&
		    snapshot->terminal_reason == terminal_reason &&
		    snapshot->drain_state == drain_state &&
		    snapshot->cleanup_fault == RP1_GPCLK_OBSERVATION_FALSE &&
		    snapshot->owner_present == owner_present &&
		    snapshot->lease_present == owner_present &&
		    snapshot->gpio_safe == RP1_GPCLK_OBSERVATION_TRUE &&
		    snapshot->clock_quiescent == RP1_GPCLK_OBSERVATION_TRUE &&
		    snapshot->dma_quiescent == RP1_GPCLK_OBSERVATION_TRUE &&
		    snapshot->stable == RP1_GPCLK_OBSERVATION_TRUE)
			return 0;
		if (snapshot->operation_state == RP1_GPCLK_STATE_FAILED ||
		    monotonic_ns() >= deadline) {
			fprintf(stderr,
				"stable terminal snapshot was not observed\n");
			return -1;
		}
		while (nanosleep(&delay, &delay) && errno == EINTR)
			;
		delay.tv_nsec = 1000000L;
	}
}

static int wait_until_elapsed(int fd, uint64_t lease, uint64_t generation,
			      uint64_t target_ns)
{
	const uint64_t deadline = monotonic_ns() + 5000000000ULL;
	struct timespec delay = { .tv_nsec = 1000000L };

	for (;;) {
		struct rp1_gpclk_state_request state;

		if (read_state(fd, lease, generation, &state)) {
			perror("STATE before cancellation");
			return -1;
		}
		if (state.elapsed_ns >= target_ns)
			return 0;
		if (state.state == RP1_GPCLK_STATE_COMPLETE ||
		    state.state == RP1_GPCLK_STATE_FAILED ||
		    monotonic_ns() >= deadline) {
			fprintf(stderr, "cancellation position was not reached\n");
			return -1;
		}
		while (nanosleep(&delay, &delay) && errno == EINTR)
			;
		delay.tv_nsec = 1000000L;
	}
}

int main(int argc, char **argv)
{
	struct rp1_gpclk_query query = { 0 };
	struct rp1_gpclk_acquire acquire = { 0 };
	struct rp1_gpclk_submit_events submit = { 0 };
	struct rp1_gpclk_tone event_tone = { 0 };
	struct rp1_gpclk_event event = { 0 };
	struct rp1_gpclk_state_request state = { 0 };
	struct rp1_gpclk_snapshot snapshot = { 0 };
	struct rp1_gpclk_release release = { 0 };
	struct stat endpoint = { 0 };
	const char *route_environment = getenv("RP1_GPCLK_TEST_ROUTE");
	const char *compatibility_id;
	uint32_t expected_route = RP1_GPCLK_ROUTE_GPIO20;
	enum cancellation_position cancellation = CANCEL_NONE;
	const char *position = "none";
	uint64_t stop_requested_ns = 0;
	uint64_t cancellation_latency_ns = 0;
	int fd;

	if (route_environment && !strcmp(route_environment, "4"))
		expected_route = RP1_GPCLK_ROUTE_GPIO4;
	else if (route_environment && strcmp(route_environment, "20")) {
		fprintf(stderr, "RP1_GPCLK_TEST_ROUTE must be 4 or 20\n");
		return 2;
	}
	compatibility_id = expected_route == RP1_GPCLK_ROUTE_GPIO4 ?
			"v0.99.0-rp1-gpio4" :
			"v0.99.0-rp1-gpio20";
	if (argc != 2) {
		fprintf(stderr, "usage: %s finite|cancel-start|cancel-middle|cancel-boundary\n",
			argv[0]);
		return 2;
	}
	if (!strcmp(argv[1], "cancel-start")) {
		cancellation = CANCEL_START;
		position = "start";
	} else if (!strcmp(argv[1], "cancel-middle")) {
		cancellation = CANCEL_MIDDLE;
		position = "middle";
	} else if (!strcmp(argv[1], "cancel-boundary")) {
		cancellation = CANCEL_BOUNDARY;
		position = "boundary";
	} else if (strcmp(argv[1], "finite")) {
		fprintf(stderr, "usage: %s finite|cancel-start|cancel-middle|cancel-boundary\n",
			argv[0]);
		return 2;
	}
	fd = open("/dev/rp1-gpclk", O_RDONLY | O_CLOEXEC);
	if (fd < 0) { perror("open"); return 1; }
	if (fstat(fd, &endpoint)) { perror("fstat"); return 1; }
	if (!S_ISCHR(endpoint.st_mode) || endpoint.st_uid != 0 ||
	    (endpoint.st_mode & 0777) != 0600) {
		fprintf(stderr, "endpoint is not a root-owned mode-0600 character device\n");
		return 1;
	}
	header(&query.header, sizeof(query));
	if (ioctl(fd, RP1_GPCLK_IOC_QUERY, &query)) { perror("QUERY"); return 1; }
	if (query.route != expected_route || strcmp(query.build_id, "0.99.0") ||
	    strcmp(query.compatibility_id, compatibility_id) ||
	    (query.capabilities & (RP1_GPCLK_CAP_SUBMIT_EVENTS |
	     RP1_GPCLK_CAP_BOUNDED_DMA_CHUNKS)) !=
	    (RP1_GPCLK_CAP_SUBMIT_EVENTS | RP1_GPCLK_CAP_BOUNDED_DMA_CHUNKS))
		return 1;
	header(&acquire.header, sizeof(acquire));
	acquire.expected_route = expected_route;
	acquire.required_capabilities = RP1_GPCLK_CAP_SUBMIT_EVENTS |
		RP1_GPCLK_CAP_BOUNDED_DMA_CHUNKS;
	if (ioctl(fd, RP1_GPCLK_IOC_ACQUIRE, &acquire)) { perror("ACQUIRE"); return 1; }
	header(&submit.header, sizeof(submit));
	submit.lease_id = acquire.lease_id;
	tone(&event_tone, 10140200.0L);
	event.duration_ns = cancellation == CANCEL_NONE ?
		1000000000ULL : RP1_GPCLK_EVENT_DURATION_NS_MAX;
	event.flags = RP1_GPCLK_EVENT_F_OUTPUT_ENABLED;
	submit.tones_ptr = (uintptr_t)&event_tone;
	submit.events_ptr = (uintptr_t)&event;
	submit.fractional_bits = RP1_GPCLK_FRACTIONAL_BITS;
	submit.tick_divider = RP1_GPCLK_TICK_DIVIDER;
	submit.tone_count = 1;
	submit.event_count = 1;
	submit.drive_ma = RP1_GPCLK_DRIVE_MA_2;
	submit.total_duration_ns = event.duration_ns;
	if (ioctl(fd, RP1_GPCLK_IOC_SUBMIT_EVENTS, &submit)) { perror("SUBMIT_EVENTS"); return 1; }
	if (cancellation != CANCEL_NONE) {
		struct rp1_gpclk_stop stop = { 0 };
		uint64_t target_ns = 0;

		if (cancellation == CANCEL_MIDDLE)
			target_ns = RP1_GPCLK_DMA_CHUNK_DURATION_NS / 2;
		else if (cancellation == CANCEL_BOUNDARY)
			target_ns = RP1_GPCLK_DMA_CHUNK_DURATION_NS;
		if (target_ns && wait_until_elapsed(fd, acquire.lease_id,
				submit.generation, target_ns))
			return 1;
		header(&stop.header, sizeof(stop));
		stop.lease_id = acquire.lease_id;
		stop.generation = submit.generation;
		stop_requested_ns = monotonic_ns();
		if (ioctl(fd, RP1_GPCLK_IOC_STOP, &stop)) { perror("STOP"); return 1; }
	}
	for (;;) {
		struct timespec delay = { .tv_nsec = 10000000L };
		if (read_state(fd, acquire.lease_id, submit.generation, &state)) {
			perror("STATE");
			return 1;
		}
		if (state.state == RP1_GPCLK_STATE_COMPLETE || state.state == RP1_GPCLK_STATE_FAILED)
			break;
		nanosleep(&delay, NULL);
	}
	if (cancellation != CANCEL_NONE) {
		cancellation_latency_ns = monotonic_ns() - stop_requested_ns;
		if (cancellation_latency_ns > RP1_GPCLK_DMA_CHUNK_DURATION_NS +
		    CANCELLATION_LATENCY_ALLOWANCE_NS) {
			fprintf(stderr, "cancellation latency exceeded bound: %llu ns\n",
				(unsigned long long)cancellation_latency_ns);
			return 1;
		}
	}
	printf("tone=%s cancellation_position=%s generation=%llu state=%u reason=%u cleanup=%u elapsed_ns=%llu cancellation_latency_ns=%llu\n",
	       argv[1], position, (unsigned long long)state.generation, state.state,
	       state.terminal_reason, state.cleanup_fault,
	       (unsigned long long)state.elapsed_ns,
	       (unsigned long long)cancellation_latency_ns);
	if (state.state != RP1_GPCLK_STATE_COMPLETE || state.cleanup_fault ||
	    state.terminal_reason != (cancellation != CANCEL_NONE ? RP1_GPCLK_REASON_STOPPED :
		RP1_GPCLK_REASON_COMPLETE))
		return 1;
	if (wait_for_stable_snapshot(fd, submit.generation,
		state.terminal_reason,
		cancellation != CANCEL_NONE ? RP1_GPCLK_DRAIN_COMPLETE :
			RP1_GPCLK_DRAIN_NONE,
		RP1_GPCLK_OBSERVATION_TRUE, &snapshot))
		return 1;
	if (snapshot.output_inhibited != RP1_GPCLK_OBSERVATION_FALSE ||
	    snapshot.operational_ready != RP1_GPCLK_OBSERVATION_TRUE ||
	    (snapshot.capabilities & (RP1_GPCLK_CAP_PASSIVE_SNAPSHOT |
	     RP1_GPCLK_CAP_STABLE_STATE)) !=
	    (RP1_GPCLK_CAP_PASSIVE_SNAPSHOT | RP1_GPCLK_CAP_STABLE_STATE))
		return 1;
	header(&release.header, sizeof(release));
	release.lease_id = acquire.lease_id;
	release.generation = submit.generation;
	if (ioctl(fd, RP1_GPCLK_IOC_RELEASE, &release)) { perror("RELEASE"); return 1; }
	if (wait_for_stable_snapshot(fd, submit.generation,
		state.terminal_reason,
		cancellation != CANCEL_NONE ? RP1_GPCLK_DRAIN_COMPLETE :
			RP1_GPCLK_DRAIN_NONE,
		RP1_GPCLK_OBSERVATION_FALSE, &snapshot))
		return 1;
	printf("endpoint_uid=%lu endpoint_mode=%03o stable=%u gpio_safe=%u clock_quiescent=%u dma_quiescent=%u owner_present=%u lease_present=%u\n",
	       (unsigned long)endpoint.st_uid, endpoint.st_mode & 0777,
	       snapshot.stable, snapshot.gpio_safe, snapshot.clock_quiescent,
	       snapshot.dma_quiescent, snapshot.owner_present,
	       snapshot.lease_present);
	close(fd);
	return 0;
}
