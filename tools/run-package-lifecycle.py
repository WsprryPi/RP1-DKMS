#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Opt-in real dpkg/DKMS tests in disposable, restricted Linux containers."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    import os
    os.execv(sys.executable, [sys.executable, '-I', __file__, *sys.argv[1:]])
import argparse
import json
from pathlib import Path
import subprocess
import uuid
import time
if __name__ == '__main__':
    import tempfile
    _cache = tempfile.TemporaryDirectory(prefix='rp1-lifecycle-import-', dir='/tmp')
    sys.pycache_prefix = _cache.name
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_process import (cleanup_owned, run_owned, cancellation_signals,
                               RUN_LABEL, SCENARIO_LABEL)
from lifecycle_results import (SCENARIOS, accept, context, input_identity,
                               selection, source_identity)
from lifecycle_coverage import attribute, catalog

ROOT = Path(__file__).resolve().parents[1]


def main():
    with cancellation_signals() as cancellation:
        execute(cancellation)


def execute(cancellation):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--predecessor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario', choices=(*SCENARIOS, 'all'), default='all')
    args = parser.parse_args()
    for path in (args.candidate, args.predecessor):
        if not path.is_absolute() or path != path.resolve() or not path.is_dir():
            parser.error('absolute nonsymlink input directories required')
    output = args.output
    if (not output.is_absolute() or output != output.resolve() or output.exists() or
            not output.parent.is_dir() or output.is_relative_to(ROOT)):
        parser.error('new absolute output outside source required')
    checkout = subprocess.run(['git', '-C', str(output.parent), 'rev-parse', '--show-toplevel'],
                              capture_output=True, timeout=30, env={'PATH': '/usr/bin:/bin',
                              'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'})
    if checkout.returncode == 0:
        parser.error('lifecycle output must be outside every Git checkout')
    image = subprocess.check_output(['docker', 'image', 'inspect', args.image], text=True, timeout=30)
    identity = json.loads(image)[0]
    requested = selection(SCENARIOS if args.scenario == 'all' else (args.scenario,))
    inputs = input_identity(args.candidate, args.predecessor, identity['Id'], source_identity(ROOT))
    run_id = uuid.uuid4().hex
    output.mkdir(mode=0o700)
    (output/'image.json').write_text(image)
    results = []
    deadline = time.monotonic()+3600
    for scenario in requested:
        expected = context(run_id, scenario, inputs)
        destination = output/scenario
        destination.mkdir()
        # Linux bind mounts retain the runner's uid. Container root deliberately
        # lacks DAC_OVERRIDE, so share only this directory below the private
        # host-owned result root. Do not broaden container capabilities.
        destination.chmod(0o777)
        command = ['docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
                   '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'SETUID',
                   '--cap-add', 'SETGID', '--security-opt', 'no-new-privileges',
                   '--pids-limit', '256', '--cpus', '4', '--memory', '2g',
                   '--cidfile', str(output/(scenario+'.cid')),
                   '--label', RUN_LABEL+'='+run_id,
                   '--label', SCENARIO_LABEL+'='+scenario,
                   '-e', 'RP1_LIFECYCLE_CONTEXT='+json.dumps(expected),
                   '-v', str(ROOT)+':/source:ro',
                   '-v', str(args.candidate)+':/candidate:ro',
                   '-v', str(args.predecessor)+':/predecessor:ro',
                   '-v', str(destination)+':/results', identity['Id'],
                   'python3', '/source/tests/package_lifecycle_linux.py', scenario]
        result, primary, cancelled = None, None, False
        log = output/(scenario+'.log')
        try:
            with log.open('x') as stream:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('overall lifecycle deadline exhausted')
                result = run_owned(command, stdout=stream, timeout=min(900, remaining))
        except (Exception, KeyboardInterrupt) as failure:
            primary = str(failure) or type(failure).__name__
            cancelled = isinstance(failure, KeyboardInterrupt)
        finally:
            cancellation.deferred = True
            try:
                cleanup = cleanup_owned(output/(scenario+'.cid'), run_id, scenario, identity['Id'])
            finally:
                cancellation.deferred = False
        cancelled = cancelled or cancellation.requested
        if cancelled:
            primary = primary or 'cancelled during cleanup'
        error, obligations = primary, []
        exit_status = result.returncode if result is not None else None
        try:
            obligations = attribute(accept(destination/'result.json', expected, exit_status))
        except (ValueError, OSError, KeyError, TypeError) as failure:
            error = error or str(failure)
        results.append({'scenario': scenario, 'exitStatus': exit_status,
                        'accepted': error is None and cleanup['status'] == 'absent',
                        'error': error, 'cleanup': cleanup, 'obligations': obligations})
        print(json.dumps(results[-1]), flush=True)
        if not results[-1]['accepted']:
            with log.open('rb') as stream:
                stream.seek(max(0, stream.seek(0, 2)-8192))
                print(stream.read(8192).decode(errors='replace'), flush=True)
        if cancelled:
            break
    passed = len(results) == len(requested) and all(r['accepted'] for r in results)
    covered = {item['caseId'] for row in results if row['accepted'] for item in row['obligations']}
    complete = covered == set(catalog())
    if args.scenario == 'all':
        passed = passed and complete
    if passed:
        passed = input_identity(args.candidate, args.predecessor, identity['Id'],
                                source_identity(ROOT)) == inputs
    (output/'result.json').write_text(json.dumps({'status': 'PASS' if passed else 'FAIL',
        'runId': run_id, 'identity': inputs, 'imageId': identity['Id'],
        'completeMatrix': complete, 'coveredCaseIds': sorted(covered, key=int),
        'scenarios': results, 'targetQualification': False,
        'wsprrypiAcceptance': False, 'rfQualification': False}, indent=2)+'\n')
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
