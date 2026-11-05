#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate executable dispatch, classifications, and nonempty-suite guards."""
from pathlib import Path
import ast
import io
import shlex
import unittest
from offline_checks import CHECKS
from nonempty_unittest import NonemptyRunner

ROOT = Path(__file__).resolve().parents[1]
PARAMETERIZED = {'check_built_module.py', 'check_development_sweep.py'}
TARGET_C = {'development_fault_client.c', 'development_tone_client.c'}
TARGET_CPP = {'development_frequency_sweep.cpp'}


def validate(checks=CHECKS, shell=None):
    tests = ROOT/'tests'
    assert checks and len(checks) == len(set(checks)), 'empty or duplicate dispatch'
    assert set(checks) | PARAMETERIZED == {p.name for p in tests.glob('check_*.py')}, 'dispatch differs from inventory'
    assert not set(checks) & PARAMETERIZED, 'parameterized utility dispatched without context'
    if shell is None:
        shell = (tests/'run-offline-checks.sh').read_text()
    lines = [shlex.split(line, comments=True) for line in shell.replace('\\\n', ' ').splitlines()]
    assert ['python3', '$repo_dir/tests/offline_checks.py'] in lines, 'registry is not executed'
    compile_commands = [line for line in lines if line and line[0] in ('${CC:-cc}', '${CXX:-c++}')]
    sources = {Path(token).name for line in compile_commands for token in line if token.startswith('$repo_dir/tests/') and token.endswith(('.c', '.cpp'))}
    host = {p.name for p in tests.glob('*.c')} - TARGET_C
    host |= {p.name for p in tests.glob('*.cpp')} - TARGET_CPP
    assert sources == host, 'compiled source contexts differ'
    assert ['for', 'client', 'in', 'development_tone_client.c', 'development_fault_client.c;', 'do'] in lines, 'both real planners required'
    assert any('-DRP1_GPCLK_TEST_CLIENT_SOURCE="$client"' in line for line in compile_commands), 'planner substitution missing'
    outputs = {line[line.index('-o')+1] for line in compile_commands}
    executed = {line[0] for line in lines if len(line) == 1}
    assert outputs <= executed | {'$tmp_dir/sweep_plan'}, 'compiled program not executed'
    assert ['python3', '$repo_dir/tests/check_development_sweep.py', '$tmp_dir/sweep_plan'] in lines, 'sweep validation missing'
    for path in tests.glob('check_*.py'):
        text = path.read_text()
        if any(isinstance(node, ast.ClassDef) and any(isinstance(base, ast.Attribute) and base.attr == 'TestCase' for base in node.bases) for node in ast.walk(ast.parse(text))):
            assert '__import__("nonempty_unittest").main()' in text, 'missing nonempty suite guard: '+path.name
    assert 'tests/nonempty_unittest.py' in (ROOT/'Makefile').read_text()
    assert 'tests/nonempty_unittest.py' in (ROOT/'.github/workflows/documentation.yml').read_text()


def adversaries():
    shell = (ROOT/'tests/run-offline-checks.sh').read_text()
    for checks, source in (((), shell), (CHECKS[1:], shell),
            (CHECKS, shell.replace('python3 "$repo_dir/tests/offline_checks.py"', '# python3 "$repo_dir/tests/offline_checks.py"')),
            (CHECKS, shell.replace('development_fault_client.c;', ';')),
            (CHECKS, shell.replace('\n"$tmp_dir/lifecycle_core"\n', '\n# "$tmp_dir/lifecycle_core"\n'))):
        try:
            validate(checks, source)
        except AssertionError:
            pass
        else:
            raise AssertionError('deliberately missing dispatch was accepted')
    class Undispatched(unittest.TestSuite):
        def countTestCases(self): return 1
        def run(self, result, debug=False): return result
    for suite in (unittest.TestSuite(), Undispatched()):
        try:
            NonemptyRunner(stream=io.StringIO()).run(suite)
        except RuntimeError:
            pass
        else:
            raise AssertionError('empty execution accepted')


if __name__ == '__main__':
    validate()
    adversaries()
    print(f'test inventory: PASS ({len(CHECKS)} isolated checks; C/C++ and planner dispatch validated)')
