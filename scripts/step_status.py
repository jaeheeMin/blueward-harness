"""GitHub Actions 재사용 워크플로(`pr-checks.yml`)가 부르는 얇은 진입점.

로직은 전부 `checker.step_status` 에 있다. `scripts/risk_gate.py` 와 같은 자리·같은 방식이다.
"""
from __future__ import annotations

from checker.step_status import main

if __name__ == "__main__":
    raise SystemExit(main())
