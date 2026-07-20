#!/usr/bin/env python3
"""Zero-dependency test runner, so CI installs nothing.

pytest would be nicer locally; requiring it would make the module heavier than
the thing it builds.
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_pipeline as T  # noqa: E402

fns = [getattr(T, n) for n in dir(T) if n.startswith("test_")]
failed = 0
for fn in fns:
    try:
        fn()
        print(f"  PASS  {fn.__name__}")
    except Exception:
        failed += 1
        print(f"  FAIL  {fn.__name__}")
        traceback.print_exc()

print(f"\n{len(fns) - failed}/{len(fns)} passed")
sys.exit(1 if failed else 0)
