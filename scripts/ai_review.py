"""재사용 워크플로 `ai-review.yml` 의 리뷰 단계가 부르는 얇은 진입점.

리뷰 로직은 전부 `checker.ai_review` 에 있다(워크플로와 로컬 시험이 같은 코드를 쓰려고).
`scripts/risk_gate.py` 와 같은 자리·같은 방식이다.
"""
from __future__ import annotations

from checker.ai_review import main

if __name__ == "__main__":
    raise SystemExit(main())
