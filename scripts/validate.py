"""Run meaningful data regressions, compile checks and local-reference validation."""
import argparse
import importlib
import re
import tempfile
import unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--temp-root", required=True, help="Writable test scratch directory")
    args = parser.parse_args()
    scratch = Path(args.temp_root).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(scratch)
    root = Path(__file__).resolve().parents[1]
    for path in (root / "scripts").rglob("*.py"):
        compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
    for path in root.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8-sig")):
            if not target.startswith(("http:", "https:", "#")) and not (path.parent / target.split("#")[0]).exists():
                raise ValueError(f"Broken reference in {path.name}: {target}")
    suite = unittest.TestSuite()
    for module in ['self_test']+sorted(path.stem for path in (root/'scripts').glob('test_*.py')):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(module)))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
