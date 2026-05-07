#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "fetch_eastmoney_stock_data.py"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--symbol",
            "sh600111",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
