"""ADT MCP 호출 결과를 읽어 ABAP 오브젝트의 활성화 상태를 기록한다(#190).

`setObjectSource`·`createObject` 로 쓴 오브젝트는 `written`, `activateObjects`·
`activateByName` 의 응답(`ActivationResult` JSON)으로 `active`/`failed`/`unknown` 이 되고,
`inactiveObjects` 응답으로 Eclipse 등 다른 도구에서 활성화한 것도 `active` 로 맞춘다.
`deleteObject` 는 기록에서 지운다. 기록을 읽어 막는 쪽은 `activation_gate.py` 다.
서버 이름은 도구 이름(`mcp__<서버>__<도구>`)에서 얻는다.

PostToolUse 는 이미 끝난 호출을 막을 수 없다. 대신 기록하지 못하면 조용히 지나가지
않는다 — `<git-dir>/harness-adt-activation.error` 표식을 남기고(관문이 이 표식이 있으면
검사 불능으로 막는다) stderr 경고와 함께 exit 2 로 끝낸다(PostToolUse 의 exit 2 는 stderr 를
Claude 에게 보여 준다). 읽기-수정-쓰기는 잠금으로 감싸 동시에 도는 훅이 서로의 기록을
덮어쓰지 않게 하고, 기록 파일은 임시 파일에 쓴 뒤 바꿔치기해 깨뜨리지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adt_activation as aa  # noqa: E402
import adt_tiers  # noqa: E402


def _force_utf8_io() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _fail(cwd, tool: str, reason: str) -> None:
    """표식을 남기고 경고와 함께 exit 2 로 끝낸다."""
    marker = None
    try:
        marker = aa.mark_error(cwd, tool, reason) if cwd else None
    except Exception:  # noqa: BLE001 - 표식도 못 남기는 경우는 아래 경고로만 알린다
        marker = None
    where = f"표식 파일: {marker}" if marker else "표식 파일도 남기지 못했다"
    print(
        "harness: ABAP 오브젝트의 활성화 기록을 남기지 못했다(PostToolUse 훅은 이미 끝난 호출을 막을 수 없다). "
        f"도구: {tool}. 사유: {reason}. {where}\n"
        "이 표식이 있는 동안 푸시와 src/ 쓰기는 검사 불능으로 막힌다.\n"
        "다음: inactiveObjects 로 서버의 비활성 오브젝트를 확인해 남은 것이 없음을 본 뒤, 사람이 표식 파일을 "
        "지우십시오. 계속되면 위 사유를 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오(사람이 할 일).",
        file=sys.stderr,
    )
    sys.exit(2)


def _run(ctx: dict) -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    ctx["cwd"] = payload.get("cwd") or "."
    ctx["tool"] = payload.get("tool_name") or "?"
    split = adt_tiers.split_mcp_tool_name(payload.get("tool_name") or "")
    if split is None:
        return
    server, tool = split
    path = aa.record_path(ctx["cwd"])
    if path is None:
        return  # git 저장소가 아니면 기록할 곳이 없다

    session_id = payload.get("session_id") or ""
    data = aa.update(path, lambda d: aa.apply_event(
        d, server, tool, payload.get("tool_input") or {}, payload.get("tool_response"), session_id))

    pend = aa.pending_entries(data)
    if pend:
        context = (
            "활성화가 확인되지 않은 ABAP 오브젝트가 남아 있다. 이대로는 푸시와 src/ 쓰기가 막힌다.\n"
            + aa.describe(pend) + "\n" + aa.NEXT_FIX
        )
        json.dump(
            {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}},
            sys.stdout, ensure_ascii=False,
        )
        sys.stdout.write("\n")


def main() -> None:
    _force_utf8_io()
    ctx: dict = {}
    try:
        _run(ctx)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 표식을 남기고 exit 2 로 알린다
        _fail(ctx.get("cwd"), ctx.get("tool", "?"), f"{type(exc).__name__}: {exc}")
    sys.exit(0)


if __name__ == "__main__":
    main()
