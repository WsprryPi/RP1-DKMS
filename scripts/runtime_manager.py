#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit runtime profile on the existing privileged route-manager socket."""
import json
import re
import sys
import runtime_controller_admin as admin

CONTRACT = 'rp1-gpclk-route-manager-runtime'
MAX_INPUT = 16384


def parse(value):
    # Profile discovery is the only unversioned request accepted by this
    # runtime-only endpoint.
    if value == {'operation': 'query'}:
        return {'schemaVersion': 3, 'operation': 'query'}
    if not isinstance(value, dict) or type(value.get('schemaVersion')) is not int:
        raise ValueError('request object/version required')
    operation = value.get('operation')
    fields = {'schemaVersion', 'operation'}
    if value['schemaVersion'] != 3 or operation not in ('query', 'preflight', 'switch', 'remove', 'recover'):
        raise ValueError('runtime profile requires schemaVersion=3 and an explicit runtime operation')
    if operation in ('preflight', 'switch', 'remove'):
        fields.add('route')
        if value.get('route') not in ('gpio4', 'gpio20'):
            raise ValueError('unsupported route')
    if operation in ('switch', 'remove', 'recover'):
        fields |= {'execute', 'requestId', 'actor'}
        if value.get('execute') is not True:
            raise ValueError('explicit execution required')
        for name, pattern in (('requestId', r'[A-Za-z0-9][A-Za-z0-9._-]{7,63}'),
                              ('actor', r'[A-Za-z0-9][A-Za-z0-9._:@/-]{1,127}')):
            if not isinstance(value.get(name), str) or not re.fullmatch(pattern, value[name]):
                raise ValueError('invalid '+name)
    if operation == 'switch':
        fields.add('preflightToken')
        if not isinstance(value.get('preflightToken'), str) or not re.fullmatch('[0-9a-f]{64}', value['preflightToken']):
            raise ValueError('preflight token required')
    if set(value) != fields:
        raise ValueError('unexpected request fields')
    return value


def token(system, state, route):
    return admin.digest(json.dumps({'boot': system.boot, 'binding': system.binding_hash,
        'controller': state, 'route': route}, sort_keys=True, separators=(',', ':')).encode())


def response(system, operation, state, status='ok', error=None):
    import runtime_application as app
    result = {'schemaVersion': 3, 'contract': CONTRACT, 'operation': operation, 'status': status,
              'state': {'profile': 'runtime', 'controller': state, 'bootId': system.boot,
                        'activeRoute': {1:'gpio4', 2:'gpio20'}.get(state['route']),
                        'configuredRoute': None, 'qualification': False,
                        'outputEnabled': False, 'applicationInhibited': system.inhibited(),
                        'pendingTransaction': system.read_journal(),
                        'application': app.load(system),
                        'bindingSha256': system.binding_hash, 'applicationRestoration': True}}
    if error is not None:
        result['error'] = {'code': 'runtime-fail-closed', 'message': str(error),
                           'kernelError': state['error'], 'overlayId': state['id']}
    return result


def _dispatch(value, factory=admin.Linux, expected_recovery=None):
    if isinstance(value, dict) and value.get('operation') in ('idle','reconcile-output','resume'):
        import runtime_output
        request = runtime_output.parse(value)
        with factory() as system:
            if request['operation'] in ('reconcile-output', 'resume'):
                import runtime_application as app
                pending = app.load(system)
                if pending and pending['phase'] not in app.TERMINAL:
                    raise ValueError('application restoration is still pending')
            state = system.call()
            output = runtime_output.dispatch(system, request, state)
            result = response(system, request['operation'], state)
            result['state']['outputLifecycle'] = output
            return result
    request = parse(value)
    operation = request['operation']
    with factory() as system:
        state = system.call()
        admin.validate_observation(state)
        if (expected_recovery is not None and operation == 'recover' and
                response(system, 'query', state)['state'] != expected_recovery):
            raise ValueError('stale provider recovery state; no mutation performed')
        if operation == 'query':
            return response(system, operation, state)
        if operation == 'preflight':
            if state['flags'] & admin.FAULT:
                raise ValueError('controller fault requires recovery, not a successor')
            previous = system.read_journal()
            if previous is not None and not isinstance(previous, dict):
                raise ValueError('invalid transaction journal')
            if previous and (previous.get('boot') != system.boot or previous.get('binding') != system.binding_hash or previous.get('session') != state['session']):
                raise ValueError('journal identity mismatch')
            if previous is None and (state['id'] or state['flags']):
                raise ValueError('unowned controller state')
            if previous is None:
                import runtime_activation as activation
                activated = system.read_record('activation.json')
                activation.validate_journal(activated)
                if (activated['phase'] != 'complete-neutral' or
                        activated['plan']['bootId'] != system.boot or
                        activated['plan']['bindingSha256'] != system.binding_hash or
                        activated['controller'] != state):
                    raise ValueError('neutral activation identity mismatch')
            if previous and previous.get('phase') not in ('complete-inhibited', 'recovered-inhibited'):
                raise ValueError('pending transaction requires recovery')
            if previous and previous.get('phase') == 'recovered-inhibited':
                import runtime_application as app
                prior_application = app.load(system)
                if prior_application and prior_application['phase'] in app.REMOVAL_TERMINAL:
                    app.verify_removal_terminal(system, prior_application)
            result = response(system, operation, state)
            result['state']['preflightToken'] = token(system, state, request['route'])
            return result
        fingerprint = admin.digest(json.dumps(request, sort_keys=True).encode())
        previous = system.read_manager_record()
        if previous is not None and not isinstance(previous, dict):
            raise ValueError('invalid request journal')
        if previous and previous.get('requestId') == request['requestId']:
            if previous.get('fingerprint') != fingerprint:
                raise ValueError('request ID conflict')
            if previous.get('complete') and previous.get('controller') == state and previous.get('boot') == system.boot and previous.get('binding') == system.binding_hash and system.inhibited():
                return previous['response']
            raise ValueError('request is pending or stale; inspect and explicitly recover')
        if operation == 'switch' and token(system, state, request['route']) != request['preflightToken']:
            raise ValueError('stale preflight; no mutation performed')
        record = {'requestId': request['requestId'], 'actor': request['actor'],
                  'fingerprint': fingerprint, 'complete': False, 'controller': state,
                  'boot': system.boot, 'binding': system.binding_hash}
        system.write_manager_record(record)
        try:
            state = admin.execute(system, route={'gpio4':1,'gpio20':2}.get(request.get('route')),
                                  recover=operation == 'recover')
            result = response(system, operation, state,
                              'recovered-inhibited' if operation == 'recover'
                              else 'complete-inhibited')
        except (OSError, ValueError) as error:
            # Do not retry effects. A busy/unknown status is itself a blocker.
            state = system.call()
            result = response(system, operation, state, 'error', error)
        record.update(complete=True, controller=state, response=result)
        system.write_manager_record(record)
        return result


def dispatch(value, factory=admin.Linux, mutation_lock=None, expected_recovery=None):
    import runtime_application as app
    # Only admission waits; no module/overlay effect is retried. Startup queries
    # must not latch a failure merely because a short readiness poll holds flock.
    operation = value.get('operation') if isinstance(value, dict) else None
    if factory is admin.Linux:
        factory = lambda: admin.Linux(wait_for_lock=True,
            allow_activation_query=operation == 'query')
    if operation == 'application-ready':
        if (set(value) != {'schemaVersion', 'operation', 'route', 'token', 'pid', 'transmit'} or
                type(value['schemaVersion']) is not int or value['schemaVersion'] != 3 or
                value['route'] not in ('gpio4', 'gpio20') or
                not isinstance(value['token'], str) or len(value['token']) != 36 or
                type(value['pid']) is not int or value['pid'] <= 0 or value['transmit'] is not False):
            raise ValueError('invalid application acknowledgement')
        with factory() as system:
            state = system.call()
            app.acknowledge(system, value, state)
            return response(system, operation, state)
    if operation not in ('switch', 'remove', 'recover', 'restore'):
        return _dispatch(value, factory)
    if operation == 'restore':
        if value != {'schemaVersion':3, 'operation':'restore', 'execute':True}:
            raise ValueError('restore requires explicit execution')
    else:
        parse(value)
    with (mutation_lock or app.mutation_lock)():
        with factory() as system:
            record = app.load(system)
            if operation in ('switch', 'remove'):
                if record and record.get('requestId') == value['requestId']:
                    if record.get('fingerprint') != admin.digest(json.dumps(value, sort_keys=True).encode()) or record['route'] != value['route'] or record['boot'] != system.boot or record['binding'] != system.binding_hash:
                        raise ValueError('request ID conflict')
                    if operation == 'remove' and record['phase'] in app.REMOVAL_TERMINAL:
                        app.verify_removal_terminal(system, record)
                        result = response(system, operation, system.call(), record['phase'])
                        result['state']['application'] = record
                        return result
                    if operation == 'switch':
                        if record.get('controller') and record['controller'] != system.call():
                            raise ValueError('request ID conflict')
                        result = response(system, operation, system.call(),
                            record['phase'] if record['phase'] in app.TERMINAL else 'error')
                        result['state']['application'] = record
                        return result
                if operation == 'switch' and token(system, system.call(), value['route']) != value['preflightToken']:
                    raise ValueError('stale preflight; no mutation performed')
                state = system.call()
                active = {1:'gpio4', 2:'gpio20'}.get(state['route'])
                if operation == 'remove' and active is None:
                    if (not record or record['route'] != value['route'] or
                            record['boot'] != system.boot or
                            record['binding'] != system.binding_hash or
                            record['phase'] not in ('captured', 'route-recovered', 'neutral-start-intent',
                                'neutral-restoration-failed', *app.REMOVAL_TERMINAL)):
                        raise ValueError('neutral route lacks matching removal restoration evidence')
                    if record['phase'] == 'captured' and record.get('operation') != 'remove':
                        raise ValueError('neutral route lacks bound removal intent')
                    if record['phase'] in app.REMOVAL_TERMINAL:
                        app.verify_removal_terminal(system, record)
                        result = response(system, operation, state, record['phase'])
                        result['state']['application'] = record
                        return result
                    if record['phase'] == 'route-recovered' and record.get('operation') != 'remove':
                        record = app.capture(system, value)
                else:
                    if operation == 'remove' and active != value['route']:
                        raise ValueError('requested removal route is stale')
                    resumable_removal = (operation == 'remove' and record and
                        record.get('operation') == 'remove' and
                        record['phase'] == 'captured' and
                        record['route'] == value['route'] and
                        record['boot'] == system.boot and
                        record['binding'] == system.binding_hash)
                    if not resumable_removal:
                        record = app.capture(system, value)
            elif operation == 'restore':
                if not record:
                    raise ValueError('no application transaction to restore')
                if record['boot'] != system.boot or record['binding'] != system.binding_hash:
                    raise ValueError('prior boot/deployment requires recover and a new route switch; no automatic restart')
                journal = system.read_journal()
                state = system.call()
                if (not journal or journal.get('phase') != 'complete-inhibited' or
                        journal.get('observation') != state or
                        state['route'] != {'gpio4':1, 'gpio20':2}[record['route']]):
                    raise ValueError('route transaction is unresolved; use recover, then switch, not restore')
                if record['phase'] in app.TERMINAL:
                    if record['controller'] != system.call():
                        raise ValueError('completed restoration route no longer matches')
                    result = response(system, operation, system.call(), record['phase'])
                    result['state']['application'] = record
                    return result
        if operation in ('remove', 'recover'):
            if operation == 'remove' and record['phase'] == 'neutral-start-intent':
                # The inhibitor may already have been removed and the service
                # started. Resume its bound restoration without replaying recovery.
                try:
                    record = app.finish_removal(factory, record)
                    with factory() as system:
                        return response(system, operation, system.call(), record['phase'])
                except (OSError, ValueError) as error:
                    with factory() as system:
                        app.failed_removal(system, record, error)
                        return response(system, operation, system.call(), 'error', error)
            with factory() as system:
                state = system.call()
                capture_only = (record and record['phase'] == 'captured' and
                                system.read_journal() is None and
                                not any(state[k] for k in ('generation', 'id', 'route', 'error', 'flags')))
                if capture_only:
                    system.inhibit()
                    result = response(system, operation, state, 'recovered-inhibited')
            if not capture_only and (operation == 'recover' or state['route'] or
                    (operation == 'remove' and record['phase'] == 'captured')):
                recovery = (dict(value, operation='recover')
                            if operation == 'remove' else value)
                if operation == 'remove':
                    recovery.pop('route', None)
                result = _dispatch(recovery, factory, expected_recovery=expected_recovery)
            elif not capture_only:
                with factory() as system:
                    state = system.call()
                    journal = system.read_journal()
                    if (not journal or journal.get('phase') != 'recovered-inhibited' or
                            journal.get('observation') != state or not system.inhibited()):
                        raise ValueError('neutral route is not in an exact recovered-inhibited state')
                    result = response(system, operation, state, 'recovered-inhibited')
            if record and result['status'] != 'error':
                with factory() as system:
                    app.remove_idle(record)
                    app.save(system, record, 'route-recovered')
                    result['state']['application'] = record
            if operation == 'remove' and result['status'] != 'error':
                try:
                    record = app.finish_removal(factory, record)
                    with factory() as system:
                        result = response(system, operation, system.call(), record['phase'])
                except (OSError, ValueError) as error:
                    with factory() as system:
                        app.failed_removal(system, record, error)
                        result = response(system, operation, system.call(), 'error', error)
                        result['error']['code'] = 'neutral-application-restoration-failed'
                result['state']['application'] = record
            return result
        if operation == 'switch':
            result = _dispatch(value, factory)
            if result['status'] == 'error':
                with factory() as system:
                    record['routeError'] = result['error']
                    record['error'] = result['error']['message']
                    app.save(system, record, 'route-failed')
                    result['state']['application'] = record
                return result
        try:
            with factory() as system:
                state = system.call()
                if operation == 'restore':
                    # Recovery of application completion never repeats overlay effects.
                    system.inhibit()
                app.prepare(system, record, state)
            record = app.finish(factory, record)
            with factory() as system:
                result = response(system, operation, system.call(), record['phase'])
        except (OSError, ValueError) as error:
            with factory() as system:
                app.failed(system, record, error)
                result = response(system, operation, system.call(), 'error', error)
                result['error']['code'] = 'application-restoration-failed'
        result['state']['application'] = record
        return result


def main():
    operation = None
    try:
        if len(sys.argv) != 1:
            raise ValueError('JSON on stdin only')
        data = sys.stdin.buffer.read(MAX_INPUT+1)
        if len(data) > MAX_INPUT:
            raise ValueError('request too large')
        value = admin.strict_json(data)
        operation = value.get('operation') if isinstance(value, dict) else None
        result = dispatch(value)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        result = {'schemaVersion':3, 'contract':CONTRACT, 'operation':operation,
                  'status':'error', 'error':{'code':'fail-closed', 'message':str(error)}}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] != 'error' else 2


if __name__ == '__main__':
    raise SystemExit(main())
