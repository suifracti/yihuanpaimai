"""Run selected unittest modules using repository paths and isolated runtime data."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='+', help='Module or dotted unittest names')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / part) for part in ('app', 'core', 'tests')] + [str(root)]
    with tempfile.TemporaryDirectory(prefix='nte-tests-') as temporary:
        os.environ['YIHUAN_DATA_ROOT'] = str(Path(temporary) / 'data')
        os.environ['YIHUAN_UPPER_TAIL_CAPTURE_DIR'] = str(Path(temporary) / 'captures')
        os.environ['NTE_LOG_FILE'] = str(Path(temporary) / 'runtime.log')
        started = time.monotonic()
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.names)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({'names': args.names, 'tests': result.testsRun,
                'failures': [(t.id(), message) for t, message in result.failures],
                'errors': [(t.id(), message) for t, message in result.errors],
                'skipped': [(t.id(), reason) for t, reason in result.skipped],
                'seconds': time.monotonic() - started}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
