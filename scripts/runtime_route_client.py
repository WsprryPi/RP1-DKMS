#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Operator client for the existing route-manager socket; never uses sudo."""
import json
import socket
import sys
import uuid
import time
import runtime_controller_admin as admin

SOCKET = '/run/rp1-gpclk-dkms/route-manager.sock'
CONTRACT = 'rp1-gpclk-route-manager-runtime'


def exchange(request):
    deadline = time.monotonic()+30
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        def budget():
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('route-manager transaction timeout; state requires observation')
            stream.settimeout(remaining)
        budget()
        stream.connect(SOCKET)
        budget()
        stream.sendall(json.dumps(request).encode()+b'\n')
        stream.shutdown(socket.SHUT_WR)
        chunks = bytearray()
        while True:
            budget()
            data = stream.recv(min(4096, 1048577-len(chunks)))
            if not data: break
            chunks.extend(data)
            if len(chunks) > 1048576: raise ValueError('response too large')
    result = admin.strict_json(chunks)
    if not isinstance(result, dict):
        raise ValueError('runtime response object required')
    if result.get('schemaVersion') != 3 or result.get('contract') != CONTRACT:
        raise ValueError('runtime profile is not deployed')
    return result


def main():
    args = sys.argv[1:]
    if args not in (['query'], ['restore', '--execute'], ['recover', '--execute'],
                    ['remove','gpio4','--execute'], ['remove','gpio20','--execute'], ['preflight','gpio4'], ['preflight','gpio20'],
                    ['switch','gpio4','--execute'], ['switch','gpio20','--execute'],
                    ['idle','gpio4'], ['idle','gpio20'],
                    ['reconcile-output','gpio4'], ['reconcile-output','gpio20'],
                    ['resume','gpio4','--execute'], ['resume','gpio20','--execute']):
        raise SystemExit('usage: runtime_route_client.py query | restore --execute | preflight gpio4|gpio20 | switch gpio4|gpio20 --execute | remove gpio4|gpio20 --execute | recover --execute | idle gpio4|gpio20 | reconcile-output gpio4|gpio20 | resume gpio4|gpio20 --execute')
    operation = args[0]
    request = {'schemaVersion':3, 'operation':operation}
    if operation in ('switch','remove','preflight','idle','reconcile-output','resume'): request['route'] = args[1]
    if operation == 'switch':
        checked = exchange({'schemaVersion':3,'operation':'preflight','route':args[1]})
        if checked['status'] != 'ok': print(json.dumps(checked)); return 2
        request['preflightToken'] = checked['state']['preflightToken']
    if operation in ('resume', 'restore'): request['execute'] = True
    if operation in ('switch','remove','recover'):
        request.update(execute=True, requestId=str(uuid.uuid4()), actor='runtime-route-client')
    result = exchange(request)
    print(json.dumps(result, indent=2))
    return 2 if result['status'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
