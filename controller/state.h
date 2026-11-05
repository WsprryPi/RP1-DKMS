/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_ROUTE_STATE_H
#define RP1_ROUTE_STATE_H
/* Caller serializes all state and preserves kernel ownership even on error. */
struct rp1_route_state {
	int id;
	int error;
	unsigned int route;
	unsigned int fault;
};
static inline void rp1_route_result(struct rp1_route_state *state,
				   unsigned int route, int id, int error)
{
	state->id = id;
	state->error = error;
	state->route = id > 0 ? route : 0;
	/* A cleared ID plus an error is NOT successful cleanup. Never auto-clear. */
	if (error || id < 0)
		state->fault = 1;
}
#endif
