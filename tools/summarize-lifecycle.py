#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Print only bounded lifecycle outcome fields, never collect filesystem payloads."""
import json
from pathlib import Path
import sys
from lifecycle_results import decode, read_regular, require, SCENARIOS
from lifecycle_coverage import catalog


def summary(value):
    require(value.get('status') in ('PASS', 'FAIL'), 'invalid aggregate status')
    rows = value.get('scenarios')
    require(isinstance(rows, list) and 0 < len(rows) <= len(SCENARIOS), 'invalid scenario summary')
    names = []
    for row in rows:
        require(row.get('scenario') in SCENARIOS and type(row.get('accepted')) is bool,
                'invalid scenario outcome')
        names.append(row['scenario'])
        if row['accepted']:
            require(type(row.get('exitStatus')) is int and row['exitStatus'] == 0
                    and row.get('cleanup', {}).get('status') == 'absent', 'accepted summary has unresolved work')
    require(len(names) == len(set(names)), 'duplicate scenario summary')
    require(type(value.get('completeMatrix')) is bool, 'missing coverage classification')
    if value['status'] == 'PASS':
        require(all(row['accepted'] for row in rows), 'PASS summary contains rejected work')
    if value['completeMatrix']:
        ids = value.get('coveredCaseIds')
        require(set(names) == set(SCENARIOS) and isinstance(ids, list)
                and len(ids) == len(set(ids)) and set(ids) == set(catalog()), 'incomplete full-matrix summary')
    return rows


def main():
    value = decode(read_regular(Path(sys.argv[1]), 1024*1024))
    for row in summary(value):
        print(json.dumps({key: row.get(key) for key in ('scenario', 'accepted', 'exitStatus')}))
    print('Lifecycle aggregate: '+value['status']+(' (complete matrix)' if value['completeMatrix'] else ' (selected subset)'))
    if value['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
