# SPDX-License-Identifier: MIT
"""Unittest entry points that reject missing discovery or zero execution."""
import sys
import unittest


class NonemptyRunner(unittest.TextTestRunner):
    def run(self, test):
        if test.countTestCases() == 0:
            raise RuntimeError('empty unittest suite')
        result = super().run(test)
        if result.testsRun == 0:
            raise RuntimeError('unittest suite executed zero cases')
        return result


def main():
    unittest.main(testRunner=NonemptyRunner)


def documentation():
    from pathlib import Path
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root), pattern='test_documentation*.py')
    def cases(node):
        for child in node:
            if isinstance(child, unittest.TestSuite):
                yield from cases(child)
            else:
                yield child
    owners = {case.id().split('.')[0] for case in cases(suite)}
    expected = {p.stem for p in root.glob('test_documentation*.py')}
    if not expected or owners != expected:
        raise RuntimeError('documentation discovery owners differ')
    raise SystemExit(0 if NonemptyRunner().run(suite).wasSuccessful() else 1)


if __name__ == '__main__':
    documentation()
