"""GitHub Actions 재사용 워크플로(`ledger-complete.yml`)가 부르는 얇은 진입점.

로직은 전부 `checker.ledger_complete` 에 있다. `ssot_approval.py` 와 같은 자리·같은 모양이다.
"""
from __future__ import annotations

from checker.ledger_complete import main

if __name__ == "__main__":
    raise SystemExit(main())
