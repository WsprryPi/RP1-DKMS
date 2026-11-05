/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef RP1_ROUTE_CONSUMER_H
#define RP1_ROUTE_CONSUMER_H
int rp1_route_consumer_attach(void);
void rp1_route_consumer_detach(bool cleanup_failed);
#endif
