# SPDX-License-Identifier: MIT
"""Ownership of disposable lifecycle processes and labeled containers."""
from contextlib import contextmanager
import os
import re
import signal
import subprocess
import time
from types import SimpleNamespace
from lifecycle_results import decode, read_regular, require

RUN_LABEL = 'org.wsprrypi.lifecycle.run'
SCENARIO_LABEL = 'org.wsprrypi.lifecycle.scenario'
# Failure guards for control commands/reaping, never readiness delays.
CONTROL_GUARD = 30
REAP_GUARD = 10


@contextmanager
def cancellation_signals():
    state = SimpleNamespace(requested=False, deferred=False)
    def cancel(signum, frame):
        state.requested = True
        if not state.deferred:
            raise KeyboardInterrupt('cancelled by signal '+str(signum))
    previous = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield state
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def group_exists(group):
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False


def reap(process):
    """Retain a dedicated process group until observed absent or report failure."""
    if group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=REAP_GUARD)
    deadline = time.monotonic() + REAP_GUARD
    while group_exists(process.pid):
        # Container PID 1 can inherit grandchildren. Reap only this owned group.
        try:
            while os.waitpid(-process.pid, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('owned process group cleanup unresolved')
        time.sleep(0.02)


@contextmanager
def owned_process(argv, stdout, env=None):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout,
                               stderr=subprocess.STDOUT, start_new_session=True, env=env)
    primary = None
    try:
        yield process
    except BaseException as error:
        primary = error
        raise
    finally:
        pending = []
        previous = {s: signal.signal(s, lambda signum, frame: pending.append((signum, frame)))
                    for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            reap(process)
        except Exception as error:
            if primary is None:
                raise
            raise RuntimeError(str(primary) + '; secondary process cleanup: ' + str(error)) from primary
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        if pending and primary is None:
            signum, frame = pending[0]
            handler = previous[signum]
            if callable(handler):
                handler(signum, frame)
            else:
                raise KeyboardInterrupt('cancelled during process cleanup')


def run_owned(argv, stdout, timeout, env=None, output_limit=64*1024*1024):
    deadline = time.monotonic()+timeout
    with owned_process(argv, stdout, env) as process:
        while True:
            require(os.fstat(stdout.fileno()).st_size <= output_limit,
                    'owned command output exceeded byte budget')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                code = process.wait(timeout=min(remaining, 0.1))
                require(os.fstat(stdout.fileno()).st_size <= output_limit,
                        'owned command output exceeded byte budget')
                return subprocess.CompletedProcess(argv, code)
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(argv, timeout)


def docker(argv):
    result = subprocess.run(['docker', *argv], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=CONTROL_GUARD)
    require(result.returncode == 0, 'Docker control failed: ' + result.stderr[-2048:])
    return result.stdout


def cleanup_owned(cidfile, run_id, scenario, image_id):
    """An engine-confirmed empty labeled set also handles normal --rm races."""
    diagnostics = []
    try:
        filters = ['--filter', 'label='+RUN_LABEL+'='+run_id,
                   '--filter', 'label='+SCENARIO_LABEL+'='+scenario]
        def listing():
            ids = docker(['ps', '-aq', '--no-trunc', *filters]).splitlines()
            require(len(ids) == len(set(ids)) and all(re.fullmatch('[0-9a-f]{64}', x) for x in ids),
                    'invalid container inventory')
            return ids
        recorded = None
        if cidfile.exists() or cidfile.is_symlink():
            recorded = read_regular(cidfile, 128).decode().strip()
            require(re.fullmatch('[0-9a-f]{64}', recorded), 'invalid owned cidfile')
        ids = listing()
        require(recorded is None or not ids or ids == [recorded], 'container identity differs from launch')
        require(len(ids) <= 1, 'ambiguous owned container inventory')
        for cid in ids:
            value = decode(docker(['inspect', '--type', 'container', cid]))
            require(isinstance(value, list) and len(value) == 1, 'container inspection shape')
            value = value[0]
            labels = value.get('Config', {}).get('Labels', {})
            require(value.get('Id') == cid and value.get('Image') == image_id
                    and labels.get(RUN_LABEL) == run_id
                    and labels.get(SCENARIO_LABEL) == scenario, 'container ownership differs')
            try:
                docker(['rm', '-f', cid])
            except ValueError as error:
                # Auto-removal can race rm; only a fresh successful query proves absence.
                diagnostics.append(str(error))
        require(not listing(), 'owned container remains after cleanup')
        return {'status': 'absent', 'diagnostics': diagnostics}
    except Exception as error:
        return {'status': 'unresolved', 'error': str(error), 'diagnostics': diagnostics}
