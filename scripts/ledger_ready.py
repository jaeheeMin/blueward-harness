"""GitHub Actions 의 pr-checks.yml `ledger-ready` 단계가 부르는 얇은 진입점(#479).

판정 로직은 전부 `checker.ledger_stale` 에 있다. `ssot_approval.py` 와 같은 자리·같은 모양이다.
"""
from __future__ import annotations

from checker.ledger_stale import main

if __name__ == "__main__":
    raise SystemExit(main())
