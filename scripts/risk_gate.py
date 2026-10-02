"""GitHub Actions 재사용 워크플로(`risk-gate.yml`)가 부르는 얇은 진입점.

판정 로직은 전부 `checker.risk_gate` 에 있다(훅이 `uvx` 로 같은 코드를 부르기 위해서).
`scripts/ssot_approval.py` 와 같은 자리·같은 방식이다.
"""
from __future__ import annotations

from checker.risk_gate import main

if __name__ == "__main__":
    raise SystemExit(main())
