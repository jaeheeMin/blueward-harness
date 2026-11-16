"""막힘 카드·AI 에게 보내는 글에서 우회 안내 문장 빼기(#1018). 목록은 bypass_phrases.json 데이터다. 순수 함수.
훅이 "DELIVER=1 을 붙여 다시 실행하십시오" 처럼 우회를 알리는 문장은 AI 가 읽는 용도라 훅 문구는 그대로 두고, 화면과 "그렇게 고쳐 줘" 로 가는 글에서만 문장을 뺀다."""
from __future__ import annotations

import json
import re
from pathlib import Path

RULES_FILE = Path(__file__).with_name("bypass_phrases.json")


def _load() -> list:
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        return [re.compile(str(p), re.I) for p in data.get("patterns", []) if isinstance(p, str)]
    except (OSError, ValueError, re.error, AttributeError):
        return []


PATTERNS = _load()
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")


def strip_bypass(text) -> str:
    """우회 안내가 든 문장을 뺀 글. 줄은 그대로 두고 줄 안에서 문장 단위로 뺀다. 빈 줄이 된 줄은 버린다."""
    out = []
    for line in str(text or "").split("\n"):
        kept = [s for s in _SENTENCE_END.split(line) if not any(p.search(s) for p in PATTERNS)]
        joined = " ".join(kept).strip()
        if joined or not line.strip():
            out.append(joined)
    return "\n".join(out).strip()
