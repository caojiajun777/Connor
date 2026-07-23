"""Smoke the dry end-to-end daily pipeline test (collect → write → publish).

Usage:
  python scripts/smoke_daily_pipeline.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/daily/test_pipeline_e2e.py",
        "-q",
        "--tb=short",
    ]
    print("Running:", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=str(ROOT))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
