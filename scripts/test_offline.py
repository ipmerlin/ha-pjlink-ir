"""Run offline tests using either supported schema library."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / ".test-deps").exists():
    sys.path.insert(0, str(ROOT / ".test-deps"))
if "--voluptuous" in sys.argv:
    sys.modules["probatio"] = None
sys.path.insert(0, str(ROOT / "tests"))
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
