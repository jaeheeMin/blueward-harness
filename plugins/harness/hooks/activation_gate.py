"""활성화되지 않은 ABAP 오브젝트가 있으면 막는 관문(#190).

사용: `activation_gate.py check <cwd>`

- 종료코드 0: 통과(기록이 없거나 모두 active).
- 종료코드 1: 막음. stdout 에 오브젝트 목록과 `다음:` 안내. 기록을 읽지 못한 검사 불능도
  통과가 아니라 1 이다(CLAUDE.md 원칙 7).

`pre-bash-git-guard.sh`(푸시), `pre_write_guard.py`(`src/` 쓰기), `/harness:deliver`
스킬이 부른다. 기록은 `mcp_activation_tracker.py` 가 남긴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adt_activation as aa  # noqa: E402


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    if len(argv) != 3 or argv[1] != "check":
        print("사용법: activation_gate.py check <cwd>", file=sys.stderr)
        return 2
    ok, message = aa.gate(argv[2])
    if ok:
        return 0
    print(message)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
