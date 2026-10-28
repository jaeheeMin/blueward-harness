"""서브에이전트를 부르는 `Agent` 도구 호출에 위임 규칙(`rules/delegation.md`)을 건다(#400).

규칙은 두 가지다.

1. 호출 때 `model` 을 넘기지 않는다. 넘긴 값이 정의 파일(`agents/*.md`)의 model 보다
   우선하므로(공식 문서의 우선순위), 정의 파일이 정한 `sonnet` 고정이 깨진다.
2. `general-purpose`·`claude` 같은 기본 에이전트나 `subagent_type` 없는 호출을 쓰지 않는다.
   정의 파일이 모델과 도구를 고정하는 `harness:researcher`·`implementer`·`reviewer` 를 쓴다.

**거절 목록 방식.** 허용 목록(harness 에이전트만 통과)이 아니라 위 기본 에이전트만 거절한다.
다른 플러그인의 에이전트와 내장 전문 에이전트(`fork`, `web-fetch`, `claude-code-guide`,
`Explore`, `Plan`, `statusline-setup` 등)를 막지 않기 위해서다. 대가로, 새 기본형 에이전트
이름이 생기면 이 목록(`CATCH_ALL_TYPES`)에 넣기 전까지는 통과한다.

**적용 범위.** 메인 세션과 서브에이전트 안에서 부르는 `Agent` 호출 모두에 같은 규칙을 건다.

**검사 불능.** 입력을 읽지 못하거나 `tool_input` 이 객체가 아니면 통과시키지 않고
거절한다(CLAUDE.md 원칙 7). stdlib 만 쓴다 — 훅은 `uv run --no-project` 로 실행된다.
"""
from __future__ import annotations

import json
import sys

# 정의 파일이 없는 기본형 에이전트. 소문자로 비교한다.
CATCH_ALL_TYPES = frozenset({"general-purpose", "claude"})

NEXT_USE_DEFINED = (
    "다음: 조사는 `harness:researcher`, 구현은 `harness:implementer`, 검토는 "
    "`harness:reviewer` 를 `subagent_type` 으로 골라 `model` 없이 다시 부르십시오(rules/delegation.md)."
)
NEXT_RETRY = (
    "다음: 같은 호출을 한 번 더 시도하십시오. 계속되면 위 내용을 붙여 "
    "jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오(🚨 직접 해 주세요)."
)


def deny(reason: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def _force_utf8_io() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = None
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    if not isinstance(tool_input, dict):
        deny(
            "harness 훅이 Agent 호출의 입력을 해석하지 못해 위임 규칙을 확인할 수 없었습니다"
            "(검사 불능).\n확인되지 않는 상태로 통과시키지 않습니다.\n\n" + NEXT_RETRY
        )

    model = tool_input.get("model")
    if model is not None and model != "":
        deny(
            f"Agent 호출에 model({model!r})을 넘겼습니다. 서브에이전트 모델은 정의 파일이 "
            "정합니다. 호출 때 넘긴 model 이 정의 파일의 `sonnet` 고정보다 우선하기 때문입니다"
            "(rules/delegation.md).\n\n다음: model 을 빼고 다시 부르십시오."
        )

    subagent_type = tool_input.get("subagent_type")
    if not isinstance(subagent_type, str) or not subagent_type.strip():
        deny(
            "Agent 호출에 subagent_type 이 없습니다. 정의 없는 기본 에이전트로 떨어지면 "
            "모델·도구 고정이 걸리지 않습니다(rules/delegation.md).\n\n" + NEXT_USE_DEFINED
        )
    if subagent_type.strip().lower() in CATCH_ALL_TYPES:
        deny(
            f"Agent 호출이 기본 에이전트({subagent_type.strip()})를 씁니다. 이 에이전트는 "
            "모델·도구 고정이 걸리지 않습니다(rules/delegation.md).\n\n" + NEXT_USE_DEFINED
        )

    sys.exit(0)


def main() -> None:
    """무엇이 터지든 막는 쪽으로 떨어지게 한다(`mcp_source_guard.py::main` 과 같다)."""
    _force_utf8_io()
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 - 의도적으로 전부 잡아 fail-closed 로 만든다
        deny(
            "harness 훅에서 예상치 못한 오류가 나 Agent 호출을 확인할 수 없었습니다.\n"
            f"사유: {type(exc).__name__}: {exc}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n" + NEXT_RETRY
        )


if __name__ == "__main__":
    main()
