#!/usr/bin/env python3
"""Zero-dependency test runner, so CI installs nothing.

pytest would be nicer locally; requiring it would make the module heavier than
the thing it builds.
"""
import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))

modules = [importlib.import_module(f.stem)
           for f in sorted(TESTS.glob("test_*.py"))]

fns = [(mod, getattr(mod, n)) for mod in modules for n in dir(mod) if n.startswith("test_")]
failed = 0
for mod, fn in fns:
    try:
        fn()
        print(f"  PASS  {mod.__name__}.{fn.__name__}")
    except Exception:
        failed += 1
        print(f"  FAIL  {mod.__name__}.{fn.__name__}")
        traceback.print_exc()

print(f"\n{len(fns) - failed}/{len(fns)} passed")
sys.exit(1 if failed else 0)
