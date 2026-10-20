"""세션 시작 때 뒤에서 만든 "내 PR 상태" 표를 첫 프롬프트에 끼운다(#389).

`session-start-sync.sh` 가 엔진(`checker.pr_queue`)을 뒤에서 돌려 `.git/harness-pr-table.<session_id>` 에
쓴다. 첫 줄은 `rc=<종료코드>`, 나머지는 엔진 stdout 이다. 다 쓴 뒤에 `.tmp` 이름을 최종 이름으로
바꾸므로 `.tmp` 만 있으면 아직 진행 중이라 아무것도 내지 않고 다음 프롬프트에 다시 본다.

- 최종 파일이 있으면 한 번 내고 지운다. 같은 세션 ID 의 파일만 읽는다.
- rc=0 이고 본문이 비면 내 PR 이 없는 것이라 조용히 지운다. rc=2 는 엔진이 낸 "확인 불능" 문장을 그대로
  쓰고, 그 밖(124 시간 초과 포함)은 "확인 불능" 으로 낸다. "문제없음" 으로 뭉개지 않는다(원칙 7).
- 출력은 `update_notice.py` 처럼 `additionalContext` 다. 이 이벤트의 출력은 사용자 화면이 아니라 Claude
  컨텍스트로 가므로 Claude 에게 "첫 줄에 그대로 보여 줘라" 고 시킨다. 이 훅은 파일만 읽어 빠르므로
  `async` 를 쓰지 않는다 — async 훅의 출력은 다음 턴에야 컨텍스트에 들어간다.
- 안내일 뿐이다. 무엇이 실패하든 출력 없이 exit 0 으로 끝내 프롬프트를 막지 않는다.

stdlib 만 쓴다 — 훅은 프로젝트 의존성 없이 `uv run --no-project` 로 돈다.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

FILE_PREFIX = "harness-pr-table."
FOOTER = "자세한 상태와 다음 할 일은 /harness:prs 로 봅니다."
RETRY = "다음: /harness:prs 로 다시 확인하십시오."


def safe_session_id(value: object) -> str:
    """session-start-sync.sh 가 파일 이름에 쓰는 규칙(영문·숫자·_·- 만)과 같다."""
    return re.sub(r"[^A-Za-z0-9_-]", "", value) if isinstance(value, str) else ""


def git_dir(cwd: str) -> Path | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", stdin=subprocess.DEVNULL, timeout=3,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    out = done.stdout.strip()
    return Path(out) if done.returncode == 0 and out else None


def parse(text: str) -> tuple[int | None, str]:
    """(종료코드, 본문). 첫 줄이 `rc=<정수>` 가 아니면 종료코드는 None."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    head, _, body = text.partition("\n")
    match = re.fullmatch(r"rc=(\d+)", head.strip())
    return (int(match.group(1)) if match else None), body.strip()


def message(rc: int | None, body: str) -> str | None:
    """사용자에게 보일 문장. 말할 것이 없으면 None."""
    first = body.splitlines()[0] if body else ""
    if rc == 0:
        return f"{body}\n{FOOTER}" if body else None
    if rc == 2 and first:
        return f"{first} {RETRY}"
    why = first or (f"종료코드 {rc}" if rc is not None else "결과 파일을 읽지 못함")
    return f"PR 상태 확인 불능({why}) - /harness:prs 로 다시 확인하십시오."


def run(payload: dict, emit: Callable[[str], None] | None = None) -> str | None:
    """출력할 JSON 문자열, 말할 것이 없으면 None.

    `emit` 이 있으면 파일을 지우기 전에 출력을 먼저 내보낸다(내기 전에 지우고 출력이 실패하면 표가 사라진다).
    """
    sid = safe_session_id(payload.get("session_id"))
    cwd = payload.get("cwd")
    if not sid or not isinstance(cwd, str) or not cwd:
        return None
    gdir = git_dir(cwd)
    if gdir is None:
        return None
    final = gdir / f"{FILE_PREFIX}{sid}"
    if not final.is_file():  # 없거나 `.tmp` 만 있다(아직 진행 중)
        return None
    try:
        text = message(*parse(final.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        # 읽지 못한 것을 "내 PR 없음" 으로 뭉개지 않는다.
        text = "PR 상태 확인 불능(결과 파일을 읽지 못함) - /harness:prs 로 다시 확인하십시오."
    out = None
    if text is not None:
        context = (
            "[harness 내 PR 상태] 세션 시작 때 뒤에서 확인한 결과다. 이번 답변의 첫머리에 아래 내용을 "
            "고치지 말고 그대로 사용자에게 보여 줘라. 이 안내는 한 번만 나온다.\n" + text
        )
        out = json.dumps(
            {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}},
            ensure_ascii=False,
        )
        if emit is not None:
            emit(out)
    try:
        final.unlink()  # 한 번만 낸다
    except OSError:
        pass  # 못 지우면 다음 프롬프트에 한 번 더 나올 수 있다. 표를 잃는 것보다 낫다.
    return out


def main() -> int:
    try:
        for stream in (sys.stdin, sys.stdout):
            stream.reconfigure(encoding="utf-8")
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        def emit(text: str) -> None:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()

        run(payload, emit)
    except Exception:  # noqa: BLE001 - 안내일 뿐이라 어떤 실패도 프롬프트를 막지 않는다
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
