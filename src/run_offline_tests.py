"""Run unit/regression tests with bytecode and scratch output isolated."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import tempfile
import unittest


def main():
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='geosot_offline_tests_') as scratch:
        old = tempfile.tempdir
        tempfile.tempdir = scratch
        try:
            suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        finally:
            tempfile.tempdir = old


if __name__ == '__main__':
    raise SystemExit(main())
