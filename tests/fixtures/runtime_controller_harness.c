// SPDX-License-Identifier: MIT
#include "main.c"

static void reset(void)
{
 state = (struct rp1_route_state){0};
 consumer = false; consumer_fault = false; pinned = false; generation = 0; session = 1234;
 references = 0; apply_error = 0; apply_id = 9; remove_error = 0; remove_id = 0;
 copyout_error = 0; foreign = false; rp1_present = true; allowed = true; route_lock = 0;
 apply_calls = remove_calls = 0;
}
static struct rp1_route_admin request(unsigned int op, unsigned int route)
{
 struct rp1_route_admin value = { .operation = op, .route = route,
  .session = op ? session : 0, .generation = op ? generation : 0 };
 return value;
}
static long call(struct rp1_route_admin *value)
{
 return route_ioctl(NULL, RP1_ROUTE_ADMIN, (unsigned long)value);
}
int main(void)
{
 struct rp1_route_admin value;
 int errors[] = {-EBUSY, -EINVAL, -EIO, -ENODEV};
 unsigned int i;
 assert(sizeof(value) == 64);
 reset(); assert(route_init() == 0); route_exit();
 reset(); rp1_present = false; assert(route_init() == -EOPNOTSUPP);
 reset(); foreign = true; assert(route_init() == -EOPNOTSUPP);
 reset(); value = request(1, 1); allowed = false; assert(call(&value) == -EPERM);
 allowed = true;
 value = request(0, 0); value.reserved0 = 1; assert(call(&value) == -EINVAL);
 value = request(1, 1);
 value.reserved2[1] = 1; assert(call(&value) == -EINVAL);
 value = request(1, 3); assert(call(&value) == -EINVAL);
 value = request(0, 0); value.session = 1; assert(call(&value) == -EINVAL);
 value = request(1, 1); value.session++; assert(call(&value) == -ESTALE);
 value = request(1, 1); value.generation++; assert(call(&value) == -ESTALE);
 route_lock = 1; value = request(1, 1); assert(call(&value) == -EBUSY);
 assert(rp1_route_consumer_attach() == -EBUSY); route_lock = 0;
 assert(apply_calls == 0);
 for (i = 1; i <= 2; i++) {
  value = request(1, i); assert(call(&value) == 0);
  assert(value.reserved0 == 0 && value.active_route == i &&
         value.overlay_id == 9 && references == 1);
  assert(rp1_route_consumer_attach() == 0);
  value = request(2, 0); assert(call(&value) == -EBUSY && remove_calls == (int)i-1);
  rp1_route_consumer_detach(false);
  value = request(2, 0); assert(call(&value) == 0);
  assert(value.reserved0 == 0 && value.overlay_id == 0 &&
         value.flags == 0 && references == 0);
 }
 for (i = 0; i < sizeof(errors)/sizeof(errors[0]); i++) {
  reset(); apply_error = errors[i]; value = request(1, 1); assert(call(&value) == 0);
  assert(value.last_error == errors[i] && value.overlay_id == 9 && value.flags & RP1_ROUTE_FAULT);
  value = request(1, 2); assert(call(&value) == -EBUSY);
  remove_error = errors[i]; remove_id = 9; value = request(2, 0); assert(call(&value) == 0);
  assert(value.overlay_id == 9 && value.last_error == errors[i] && references == 1);
  remove_error = 0; remove_id = 0; value = request(2, 0); assert(call(&value) == 0);
  assert(value.overlay_id == 0 && value.flags & RP1_ROUTE_FAULT && references == 1);
  value = request(1, 2); assert(call(&value) == -EBUSY);
  reset(); value = request(1, 1); assert(call(&value) == 0);
  remove_error = errors[i]; value = request(2, 0); assert(call(&value) == 0);
  assert(value.overlay_id == 0 && value.last_error == errors[i] && references == 1);
  assert(value.flags & RP1_ROUTE_FAULT);
 }
 reset(); apply_error = -ENOMEM; apply_id = 0; value = request(1, 1); assert(call(&value) == 0);
 assert(state.fault && state.id == 0 && references == 1);
 reset(); value = request(1, 1); copyout_error = 1; assert(call(&value) == -EFAULT);
 copyout_error = 0; value = request(0, 0); assert(call(&value) == 0);
 assert(value.overlay_id == 9 && value.generation == 1 && references == 1);
 reset(); foreign = true; value = request(1, 1); assert(call(&value) == 0);
 assert(value.last_error == -EEXIST && apply_calls == 0);
 reset(); value = request(1, 1); assert(call(&value) == 0);
 assert(rp1_route_consumer_attach() == 0); rp1_route_consumer_detach(true);
 assert(state.fault && state.error == -EIO);
 value = request(2, 0); assert(call(&value) == -EBUSY && remove_calls == 0);
 puts("real controller ioctl/interlock fault-injection: PASS");
 return 0;
}
