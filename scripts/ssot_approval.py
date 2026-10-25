"""GitHub Actions 워크플로의 ssot-approval 단계(`pr-checks.yml`·`pr-review.yml`·`main-checks.yml`)가 부르는 얇은 진입점.

판정 로직은 전부 `checker.ssot_approval` 에 있다. 그 모듈이 `checker` 패키지
안에 사는 이유(훅이 `uvx` 로 같은 코드를 부르기 위해서)는 그 파일의 docstring을
읽는다. 이 파일은 `check_changed.py` 와 같은 자리(`scripts/`)에서, Actions
쪽 호출 방식(`uv run --project .harness-engine python
.harness-engine/scripts/ssot_approval.py ...`)을 `check_changed.py` 와
맞추기 위한 겉포장일 뿐이다.
"""
from __future__ import annotations

from checker.ssot_approval import main

if __name__ == "__main__":
    raise SystemExit(main())
