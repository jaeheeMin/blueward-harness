"""다음 갈래로 넘어갈 때의 자동 인계: 인계 결과에서 새 세션용 프롬프트를 뽑고 새 세션의 첫 메시지를 만든다(web-console.md §7c)."""
from __future__ import annotations

import re

HANDOFF_SKILL = "handoff"
# 여는 울타리(백틱 3개 이상) 다음 줄부터, 같은 길이의 닫는 울타리 앞까지
FENCE = re.compile(r"^(?P<fence>`{3,})[^\n`]*\n(?P<body>.*?)\n?(?P=fence)[ \t]*$", re.DOTALL | re.MULTILINE)
CHECK_INTRO = ("새 세션 시작 점검: /harness:sync 로 최신을 받고, 플러그인 판(/harness:version)을 확인해 낡았으면 알려 줘"
               "(갱신은 사용자 버튼으로 한다). 그다음 인계 내용을 이어서: ")


def last_code_block(text: str) -> str:
    """결과 글의 마지막 코드 블록 내용(새 세션용 프롬프트). 없거나 비었으면 빈 문자열."""
    found = [m["body"].strip() for m in FENCE.finditer(text or "")]
    return next((b for b in reversed(found) if b), "")


def new_session_message(prompt: str, flow: dict, plugin_name: str, devs: list[str] | None = None) -> str:
    """새 세션의 첫 메시지: 시작 점검 + 인계 프롬프트 + 그 갈래 첫 단계 지시. devs 가 있으면 이번에 맡는 개발 건 번호를 덧붙인다."""
    text = CHECK_INTRO + prompt.strip()
    if devs:
        text += "\n\n이번에 맡는 개발 건: " + ", ".join(devs)
    step = flow["steps"][0]
    if step["kind"] == "skill":
        text += f"\n\n이 갈래({flow.get('name', flow['id'])})의 첫 단계는 /{plugin_name}:{step['skill']} 입니다. 위 점검을 마치면 이 스킬로 시작해 줘."
    else:
        text += f"\n\n이 갈래({flow.get('name', flow['id'])})의 첫 단계: {step.get('name', step['id'])} - {step.get('hint', '')}".rstrip(" -")
    return text
