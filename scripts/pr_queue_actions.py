"""GitHub Actions 워크플로의 pr-queue 단계(`pr-checks.yml` 등, 이 저장소는 `pr-queue-self.yml`)가 부르는 얇은 진입점.

로직은 전부 `checker.pr_queue_actions` 에 있다. `scripts/risk_gate.py` 와 같은 자리·같은 방식이다.
"""
from __future__ import annotations

from checker.pr_queue_actions import main

if __name__ == "__main__":
    raise SystemExit(main())
