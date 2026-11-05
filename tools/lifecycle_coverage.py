# SPDX-License-Identifier: MIT
"""Attribute matrix obligations to completed stages and independent state rules."""
import json
from pathlib import Path
from lifecycle_results import require, SCENARIOS

# Multiple obligations may share a transition; this does not count as independent
# fault executions. Every listed stage must occur, with its matrix exit status.
ROWS = '''
1 clean-cycle clean-install
2 clean-cycle repeat-install
3 clean-cycle apt-reinstall
4 clean-cycle repeat-install
5 clean-cycle missing-module-reinstall
6 clean-cycle reinstall-after-removal
7 foreign-state foreign-dkms-0.99.0
8 foreign-state foreign-dkms-9.9.9
9 foreign-state refuse-DEVELOPMENT_MANIFEST
10 foreign-state refuse-rp1-gpclk-dkms-installation
11 foreign-state refuse-foreign
12 foreign-state refuse-runtime-controller
13 foreign-state refuse-drifted-reinstall
14 foreign-state refuse-duplicate-module
15 missing-headers refuse-missing-headers
16 foreign-state refuse-unknown-hook
17 predecessor refuse-direct-upgrade-before-dpkg
18 predecessor successor-clean-install
19 predecessor refuse-direct-downgrade-before-dpkg
20 multi-kernel one-kernel-purge
21 multi-kernel purge
22 compression-signing remove-.ko remove-.ko.xz remove-.ko.zst
23 compression-signing remove-.ko remove-.ko.xz remove-.ko.zst
24 clean-cycle remove purge
25 clean-cycle remove
26 clean-cycle purge
27 multi-kernel install-nonrunning-kernel
28 multi-kernel kernel-readdition
29 multi-kernel new-kernel-autoinstall
30 multi-kernel exact-autoinstall-noop
31 multi-kernel kernel-removal
32 dependency-recovery dependency-configure-refusal
33 dependency-recovery retry-after-dependency-repair
34 fault-preinstall interrupted-preinstall
35 fault-preinstall retry-preinstall
36 fault-unpack interrupted-overlay-unpack
37 fault-unpack retry-exact-unpack-configure
38 fault-configure interrupted-configure
39 fault-configure retry-configure
40 fault-add injected-add
41 fault-add retry-configure
42 fault-gcc injected-gcc
43 fault-gcc retry-configure
44 fault-build injected-build
45 fault-build retry-configure
46 fault-install injected-install
47 fault-install retry-configure
48 fault-depmod injected-depmod
49 fault-depmod retry-configure
50 fault-inventory interrupted-inventory
51 fault-inventory retry-inventory
52 fault-remove injected-remove
53 fault-remove retry-remove
54 fault-purge injected-purge
55 fault-purge retry-remove
56 predecessor failed-rollback
57 predecessor retry-exact-rollback-configure
58 predecessor retry-exact-rollback-configure
59 package-lock refuse-concurrent-same-version
60 missing-payload repair-missing-package_preflight.py repair-missing-dkms.conf
61 foreign-state refuse-foreign-cache-removal refuse-foreign-cache-reinstall
62 fault-signature refuse-native-signing-warning
63 fault-signature retry-after-signing-repair
64 fault-remove-depmod injected-remove-depmod
65 fault-remove-depmod retry-remove
66 predecessor failed-owning-predecessor-removal
67 predecessor successor-clean-install
68 packaged-runtime-baseline preserve-passive-baseline
69 packaged-runtime-baseline refuse-changed-passive-baseline refuse-foreign-passive-baseline
'''
RULES = {row[0]: (row[1], row[2:]) for row in (line.split() for line in ROWS.splitlines() if line)}
MATRIX = Path(__file__).resolve().parents[1]/'release/package-lifecycle-matrix-v1.json'
KERNELS = ('6.18.50+rpt-rpi-2712', '6.18.50+rpt-rpi-v8')


def catalog():
    matrix = json.loads(MATRIX.read_text())
    cases = {case['id']: case for case in matrix['cases']}
    require(len([line for line in ROWS.splitlines() if line]) == len(RULES), 'duplicate coverage rule')
    require(cases and len(cases) == len(matrix['cases']) == len(RULES)
            and set(cases) == set(RULES), 'coverage mapping differs from matrix')
    require(all(scenario in SCENARIOS and stages for scenario, stages in RULES.values()),
            'unsupported coverage context')
    require({owner for owner, stages in RULES.values()} | {'header-profiles', 'unpack-recovery'} == set(SCENARIOS), 'scenario lacks an execution contract')
    return cases


def state_is(name, before, after):
    modules, dkms = after.get('modules'), after.get('dkms')
    require(isinstance(modules, list) and isinstance(dkms, str), 'incomplete state observation')
    status = after.get('packageManager')
    if name in ('refused', 'refused-downgrade', 'refused-concurrent'):
        keys = ('modules', 'dkms', 'sourceTrees', 'bootSha256', 'endpointsAbsent', 'modulesUnloaded')
        return all(key in before and before[key] == after.get(key) for key in keys)
    if name == 'absent':
        return not modules and not dkms and after.get('sourceTrees') == []
    if name == 'preinstall-refused':
        return not modules and not dkms and after.get('sourceTrees') == []
    if name in ('installed', 'one-kernel', 'legacy'):
        count = 4 if name == 'installed' else 2
        version = '0.9.0' if name == 'legacy' else '0.99.0'
        return (status == 'ii  '+version+'-1' and len(modules) == count
                and all(m.get('version') == version for m in modules)
                and dkms.count(': installed') == count//(1 if name == 'legacy' else 2))
    expected = {
        'dependency-unconfigured': ('iU  0.99.0-1', 0),
        'unpack-aborted': ('in', 0),
        'partial': ('iF  0.99.0-1', 0),
        'failed-add': ('iF  0.99.0-1', 0),
        'failed-build': ('iF  0.99.0-1', 0),
        'failed-install': ('iF  0.99.0-1', 0),
        'failed-index': ('iF  0.99.0-1', 4),
        'failed-inventory': ('iF  0.99.0-1', 4),
        'failed-remove': ('ri  0.99.0-1', 4),
        'failed-purge': ('pi  0.99.0-1', 4),
        'failed-remove-index': ('ri  0.99.0-1', 0),
        'legacy-partial': ('iF  0.9.0-1', 0),
        'legacy-remove-failed': ('pi  0.9.0-1', 2),
    }
    require(name in expected, 'unsupported matrix state oracle: '+name)
    return (status, len(modules)) == expected[name]




def starting_context(case_id, step):
    number = int(case_id)
    groups = {
        0: (1, 6, 7, 8, 9, 10, 11, 12, 15, 16, 18, 27, 32, 33, 34, 35, 36,
            37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 50, 56, 57, 58, 62, 26, 65, 67),
        2: (17, 20, 28, 29, 66),
        3: (5,),
        4: (2, 3, 4, 13, 19, 21, 22, 23, 25, 30, 31, 49, 51, 52, 53,
            54, 55, 60, 61, 63, 64, 68, 69),
        5: (14,),
    }
    if number == 24:
        return len(step['before']['modules']) == (4 if step['stage'] == 'remove' else 0)
    if number == 59:
        return step['before'] == step['after'] and 'lock' in step['diagnosticTail']
    expected = [count for count, members in groups.items() if number in members]
    require(len(expected) == 1, 'missing starting context rule')
    before = step['before']
    if len(before.get('modules', [])) != expected[0]:
        return False
    if number in (22, 23):
        suffix = step['stage'].removeprefix('remove-')
        return all(m.get('path', '').endswith(suffix) and m.get('signer') for m in before['modules'])
    return True

def command_is(case_id, step):
    number = int(case_id)
    if number in (17, 19):
        prefix = ['python3', '/source/scripts/package_preflight.py', 'unpack'] if number == 17 else ['sh', '/tmp/old-control/preinst', 'upgrade', '0.99.0-1']
    elif number in (68, 69):
        prefix = ['in-process', 'runtime_deployment.Files.prune_removed_directories']
    elif number == 3:
        prefix = ['apt-get', '-o', 'Acquire::Retries=0', '--reinstall']
    elif number in (28, 29, 30, 31):
        prefix = ['dkms', 'remove' if number == 31 else 'autoinstall']
    elif number == 61:
        prefix = ['dpkg', '--remove' if 'removal' in step['stage'] else '-i']
    elif number == 24:
        prefix = ['dpkg', '--remove' if step['stage'] == 'remove' else '--purge']
    elif number in (20, 21, 22, 23, 26, 54, 55, 66):
        prefix = ['dpkg', '--purge']
    elif number in (25, 52, 53, 64, 65):
        prefix = ['dpkg', '--remove']
    elif number in (33, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 57, 58, 63):
        prefix = ['dpkg', '--configure']
    else:
        prefix = ['dpkg', '-i']
    return step['command'][:len(prefix)] == prefix

def attribute(value):
    cases = catalog()
    scenario, steps = value['scenario'], value['steps']
    attributed = []
    for case_id, (owner, stages) in RULES.items():
        if owner != scenario:
            continue
        case = cases[case_id]
        indices = []
        for stage in stages:
            matched = [(i, step) for i, step in enumerate(steps) if step['stage'] == stage]
            count = 2 if case_id == '61' else 1
            require(len(matched) == count, 'missing/duplicate obligation stage: '+case_id+' '+stage)
            for index, step in matched:
                require(starting_context(case_id, step), 'obligation starting context differs: '+case_id)
                require(command_is(case_id, step), 'obligation command differs: '+case_id)
                require(step['exitStatus'] == case['exitStatus'], 'obligation exit differs: '+case_id)
                require(state_is(case['expectedState'], step['before'], step['after']),
                        'obligation state differs: '+case_id+' '+stage)
                indices.append(index)
        attributed.append({'caseId': case_id, 'stepIndices': indices,
                           'evidenceClass': case['evidenceClass'], 'expectedState': case['expectedState']})
    if scenario == 'header-profiles':
        for kernel in KERNELS:
            for profile in (0, 1):
                stages = ['build-'+kernel+'-'+str(profile)]
                stages += ['validate-'+kernel+'-'+module+'-'+str(profile) for module in
                           (('rp1_gpclk_dkms', 'rp1_route_controller') if profile else ('rp1_gpclk_dkms',))]
                require(all(sum(step['stage'] == stage and step['exitStatus'] == 0 for step in steps) == 1
                            for stage in stages), 'header/profile execution missing')
    if scenario == 'unpack-recovery':
        require([step['stage'] for step in steps] == ['interrupted-before-configure', 'recover-configure', 'purge'], 'unpack recovery stages differ')
    final = {'clean-cycle': 'final-purge', 'foreign-state': 'purge-restored-fixture',
             'packaged-runtime-baseline': 'purge-after-runtime-retirement',
             'predecessor': 'final-predecessor-cleanup', 'compression-signing': 'remove-.ko.zst'}
    if scenario != 'header-profiles':
        require(steps[-1]['stage'] == final.get(scenario, 'purge') and steps[-1]['exitStatus'] == 0
                and state_is('absent', steps[-1]['before'], steps[-1]['after']), 'final cleanup stage missing')
    return attributed
