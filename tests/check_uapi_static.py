#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import sys as _identity_sys
from pathlib import Path as _IdentityPath
_identity_sys.path.insert(0, str(_IdentityPath(__file__).resolve().parents[1]/'scripts'))
from version_identity import VERSION, DEBIAN, COMPATIBILITY, expand
from pathlib import Path
R=Path(__file__).resolve().parents[1]
u=(R/'include/uapi/linux/rp1_gpclk.h').read_text()
d=(R/'src/rp1_gpclk_uapi_dispatch.c').read_text()
e=(R/'src/rp1_gpclk_execution.c').read_text()
c=(R/'src/rp1_gpclk_core.c').read_text()
device=(R/'include/rp1_gpclk/device.h').read_text()
target_client=(R/'tests/development_tone_client.c').read_text()
contract=(R/'engineering/contracts/uapi.md').read_text()
source_development=(R/'engineering/operations/source-development.md').read_text()
assert 'authorization_digest' not in u and 'authorization_flags' not in u
assert 'RP1_GPCLK_CAP_OPERATION_LIVE_GATE' not in u
assert 'RP1_GPCLK_CAP_OUTPUT_INHIBIT' in u
assert '--live-output' not in source_development
assert source_development.count('--output-inhibit 1') >= 4
for legacy_document in ('uapi-v1.md','uapi-v2.md','uapi-v3-passive-snapshot.md',
                        'uapi-v4-operation-live.md'):
    assert not (R/'engineering/contracts'/legacy_document).exists()
for legacy_token in ('RP1_GPCLK_UAPI_ABI_V','RP1_GPCLK_IOC_QUERY_V2',
                     'RP1_GPCLK_IOC_ACQUIRE_V4','RP1_GPCLK_IOC_RELEASE_V2',
                     'RP1_GPCLK_IOC_GET_SNAPSHOT_V3','struct rp1_gpclk_query_v'):
    assert legacy_token not in u
assert 'has no legacy layouts, negotiation, or fallback behavior' in contract
for token in ('RP1_GPCLK_IOC_QUERY','RP1_GPCLK_IOC_SUBMIT_EVENTS',
              'RP1_GPCLK_IOC_RELEASE','RP1_GPCLK_CAP_BOUNDED_DMA_CHUNKS'):
    assert token in u
assert d.count('request.capabilities = RP1_GPCLK_CAPABILITIES') == 2
assert 'complete_all(&device->dma_done);' not in e
assert "expected != 0 && !ret &&" in e
for reason in ('RP1_GPCLK_REASON_CLOCK_FAILED',
               'RP1_GPCLK_REASON_PINCTRL_FAILED',
               'RP1_GPCLK_REASON_DMA_FAILED',
               'RP1_GPCLK_REASON_READBACK_FAILED'):
    assert reason in e
assert 'readback_ret = rp1_gpclk_machine_readback(&context);' in e
readback_start = e.index('static int rp1_gpclk_readback')
readback = e[readback_start:
             e.index('static int rp1_gpclk_machine_readback', readback_start)]
assert readback.index('rp1_gpclk_configure_dma') < \
       readback.index('mutex_lock(&device->execution_commit_lock)') < \
       readback.index('if (atomic_read(&device->stop_requested))') < \
       readback.index('rp1_gpclk_tick_start(device)') < \
       readback.index('rp1_gpclk_wait_dma')
assert 'rp1_gpclk_execution_machine_finish(\n\t\t&rp1_gpclk_machine_ops, &context, false)' in e
assert "completion_done(&context->device->execution_done)" in d
assert 'if (atomic_read(&device->stop_requested)) {' in e
assert 'dmaengine_terminate_sync(device->dma_chan);' in e
wait = e[e.index('static int rp1_gpclk_wait_dma'):e.index('static int rp1_gpclk_setup_rate')]
assert wait.index('if (!completed)') < wait.index('if (atomic_read(&device->stop_requested))')
assert 'return -ETIMEDOUT;' in wait
tick = e[e.index('static void rp1_gpclk_tick_start'):e.index('static unsigned long rp1_gpclk_timeout_jiffies')]
assert 'writel(RP1_GPCLK_DMA_TICK_DWELL,' in tick
assert 'FINISH_CLEAR' not in tick
assert '#define RP1_GPCLK_DMA_TICK_DREQ BIT(12)' in e
assert e.count('~RP1_GPCLK_DMA_TICK_DREQ') == 2
setup = e[e.index('static int rp1_gpclk_machine_set_rate'):e.index('static int rp1_gpclk_machine_prepare')]
assert setup.index('device->tick_state_captured = true') > setup.index('if (__clk_is_enabled')
stop_tick = e[e.index('static int rp1_gpclk_machine_stop_tick'):e.index('static int rp1_gpclk_machine_terminate_dma')]
assert 'if (device->tick_state_captured)' in stop_tick
cancel = e[e.index("if (atomic_read(&device->stop_requested)) {"):]
cancel = cancel[:cancel.index("return -ECANCELED;")]
assert cancel.index("dmaengine_terminate_sync") < cancel.index("rp1_gpclk_tick_stop")
stop_source = e[e.index("int rp1_gpclk_execution_stop"):]
assert "complete_all(&device->dma_done)" not in stop_source
finish=e.index('cleanup_ret = rp1_gpclk_execution_machine_finish')
assert finish < e.index('rp1_gpclk_core_progress', finish)
finished = 'WRITE_ONCE(device->execution_finished_ns, ktime_get_boottime_ns());'
assert e.count(finished) == 4
normal_terminal = e[finish:e.index('dev_info(device->dev,', finish)]
assert normal_terminal.index(finished) < normal_terminal.index('if (cleanup_ret)')
fail_terminal = e[e.index('\nfail:\n'):e.index('\nfail_without_buffer:\n')]
assert fail_terminal.index(finished) < fail_terminal.index('rp1_gpclk_publish_failure')
no_buffer_terminal = e[e.index('\nfail_without_buffer:\n'):
                       e.index('\nrelease_plan:\n')]
assert no_buffer_terminal.index(finished) < \
       no_buffer_terminal.index('rp1_gpclk_publish_failure')
cancelled_terminal = e[e.index('\ncancelled_before_buffer:\n'):
                       e.index('\nint rp1_gpclk_execution_init')]
assert cancelled_terminal.index(finished) < \
       cancelled_terminal.index('rp1_gpclk_core_progress')
assert 'events[index].duration_ns < RP1_GPCLK_EVENT_DURATION_NS_MIN' in c
assert 'events[index].duration_ns > RP1_GPCLK_EVENT_DURATION_NS_MAX' in c
for product_token in ('WSPR', 'QRSS', 'FSKCW', 'DFCW', 'rp1_gpclk_mode',
                      'SUBMIT_TONE'):
    assert product_token not in u
assert ('#define RP1_GPCLK_MODULE_VERSION "' + VERSION + '"') in (R/'include/rp1_gpclk/version.h').read_text()
assert '#define RP1_GPCLK_DMA_CHUNK_DURATION_NS 1000000000ULL' in u
assert '#define RP1_GPCLK_REQUEST_DURATION_NS_MAX 9223372036854775807ULL' in u
assert 'dma_alloc_coherent(dma_device, maximum * sizeof(*words)' in e
assert 'rp1_gpclk_chunk_cursor_next' in e
chunk_loop = e[e.index('while (!ret) {'):e.index('if (ret && ret != -ECANCELED)')]
assert chunk_loop.index('atomic_read(&device->stop_requested)') < \
       chunk_loop.index('rp1_gpclk_chunk_cursor_next')
assert chunk_loop.index('rp1_gpclk_chunk_cursor_next') < \
       chunk_loop.index('rp1_gpclk_run_descriptor')
assert 'struct mutex execution_commit_lock;' in device
assert 'mutex_init(&device->execution_commit_lock);' in e
descriptor = e[e.index('static int rp1_gpclk_run_descriptor'):
               e.index('static void rp1_gpclk_publish_failure')]
assert descriptor.index('mutex_lock(&device->execution_commit_lock)') < \
       descriptor.index('if (atomic_read(&device->stop_requested))')
assert descriptor.index('rp1_gpclk_tick_start(device)') < \
       descriptor.rindex('mutex_unlock(&device->execution_commit_lock)')
stop = e[e.index('int rp1_gpclk_execution_stop'):
         e.index('void rp1_gpclk_execution_quiesce')]
assert stop.index('mutex_lock(&device->execution_commit_lock)') < \
       stop.index('atomic_set(&device->stop_requested, 1)') < \
       stop.index('mutex_unlock(&device->execution_commit_lock)')
quiesce_stop = e[e.index('void rp1_gpclk_execution_request_stop'):]
assert quiesce_stop.index('mutex_lock(&device->execution_commit_lock)') < \
       quiesce_stop.index('atomic_set(&device->stop_requested, 1)') < \
       quiesce_stop.index('mutex_unlock(&device->execution_commit_lock)')
assert ('if (READ_ONCE(device->worker))\n'
        '\t\twake_up_process(device->worker);') not in e
wake = e[e.index('static void rp1_gpclk_wake_worker_locked'):
         e.index('static int rp1_gpclk_execution_thread')]
assert wake.count('wake_up_process(worker);') == 1
assert wake.index('worker = device->worker;') < wake.index('wake_up_process(worker);')
assert wake.index('worker = device->worker;') < wake.index('get_task_struct(worker);')
activate = e[e.index('void rp1_gpclk_execution_activate'):
             e.index('int rp1_gpclk_execution_submit_events')]
assert activate.index('mutex_lock(&device->execution_commit_lock)') < \
       activate.index('generation == device->execution_generation') < \
       activate.index('rp1_gpclk_wake_worker_locked(device)') < \
       activate.index('mutex_unlock(&device->execution_commit_lock)')
assert 'rp1_gpclk_execution_activate(context->device,\n\t\t\trequest.generation);' in d
retire = wake[wake.index('static void rp1_gpclk_retire_worker'):]
assert retire.index('mutex_lock(&device->lock)') < \
       retire.index('mutex_lock(&device->execution_commit_lock)') < \
       retire.index('device->execution_plan = NULL') < \
       retire.index('WRITE_ONCE(device->worker, NULL)') < \
       retire.index('complete_all(&device->execution_done)')
assert e.count('rp1_gpclk_retire_worker(device);') == 2
quiesce = e[e.index('void rp1_gpclk_execution_quiesce'):
            e.index('void rp1_gpclk_execution_request_stop')]
assert quiesce.index('worker = rp1_gpclk_get_worker(device);') < \
       quiesce.index('kthread_stop(worker);') < \
       quiesce.index('put_task_struct(worker);')
release_dispatch = d[d.index('static long rp1_gpclk_release_lease'):
                     d.index('long rp1_gpclk_uapi_dispatch')]
assert 'request.generation == 0 &&' in release_dispatch
assert 'context->device->core.value.generation == 0' in release_dispatch
assert release_dispatch.index('rp1_gpclk_core_release') < \
       release_dispatch.index('rp1_gpclk_execution_stop')
for mode in ('cancel-start', 'cancel-middle', 'cancel-boundary'):
    assert mode in target_client
assert 'RP1_GPCLK_EVENT_DURATION_NS_MAX' in target_client
assert 'CANCELLATION_LATENCY_ALLOWANCE_NS 500000000ULL' in target_client
assert 'cancellation_latency_ns > RP1_GPCLK_DMA_CHUNK_DURATION_NS +' in target_client
assert 'fstat(fd, &endpoint)' in target_client
assert '(endpoint.st_mode & 0777) != 0600' in target_client
assert target_client.count('wait_for_stable_snapshot(') == 3
for observation in ('snapshot->gpio_safe', 'snapshot->clock_quiescent',
                    'snapshot->dma_quiescent', 'snapshot->stable',
                    'snapshot->owner_present', 'snapshot->lease_present',
                    'snapshot->drain_state'):
    assert observation in target_client
print('canonical UAPI static safety contract: PASS')
