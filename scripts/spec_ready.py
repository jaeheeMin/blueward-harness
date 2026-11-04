"""GitHub Actions 의 pr-checks.yml `spec-ready` 단계가 부르는 얇은 진입점(#668).

판정 로직은 전부 `checker.spec_ready` 에 있다. `ledger_ready.py` 와 같은 자리·같은 모양이다.
"""
from __future__ import annotations

from checker.spec_ready import main

if __name__ == "__main__":
    raise SystemExit(main())
