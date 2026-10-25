"""작업 트리의 JSON 파일이 HEAD 판과 값이 같은지(키 순서·공백만 다른지) 판정한다.

`claude plugin install` 이 `.claude/settings.json` 의 키 순서만 바꿔 저장해도 Stop 훅과
세션 시작 훅이 "커밋되지 않은 변경" 으로 세지 않게 하려는 것이다(#448). 두 훅이 같은 판정을
쓰도록 한 곳에 둔다. 파일은 고치지 않는다.

사용법: python json_same_as_head.py <저장소 기준 경로>
종료 코드: 0 = 값이 같다(변경으로 세지 않는다), 1 = 다르거나 판정할 수 없다(보통 변경으로 센다).
HEAD 에 없는 새 파일, 파싱 실패, git 실패는 모두 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _git(*args: str) -> bytes | None:
    try:
        done = subprocess.run(["git", *args], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def same_as_head(rel_path: str) -> bool:
    top = _git("rev-parse", "--show-toplevel")
    if top is None:
        return False
    root = Path(top.decode("utf-8", "replace").strip())
    head = _git("show", f"HEAD:{rel_path}")
    if head is None:
        return False
    try:
        now = (root / rel_path).read_bytes()
        return json.loads(head.decode("utf-8-sig")) == json.loads(now.decode("utf-8-sig"))
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    sys.exit(0 if len(sys.argv) == 2 and same_as_head(sys.argv[1]) else 1)
