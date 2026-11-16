"""비밀처럼 보이는 값 가리기(#1018). 규칙은 secret_rules.json 데이터다. 순수 함수 — trouble.py(글 저장 전 검사)와 store.py(세션 제목·기록·대화 저장 전)가 함께 쓴다.
브라우저의 BHLogic.maskSecrets(static/flow-logic.js)와 같은 규칙이다. 규칙 파일을 못 읽으면 아무것도 가리지 못한다(글은 그대로 나간다)."""
from __future__ import annotations

import json
import re
from pathlib import Path

RULES_FILE = Path(__file__).with_name("secret_rules.json")


def _load() -> dict:
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_RULES = _load()
MASK = _RULES.get("mask") or "••••••••"  # 가린 값. PLACEHOLDER 에 걸리므로 비밀로 치지 않는다(가린 글은 저장할 수 있다).
SECRET_NAME = _RULES.get("name") or r"(?!)"
SECRET_ASSIGN = re.compile(str(_RULES.get("assign") or r"(?!)").replace("NAME", SECRET_NAME), re.I)
SECRET_OTHER = [(re.compile(str(o["pattern"]), re.I if o.get("ignore_case") else 0), str(o.get("label") or ""), bool(o.get("url_password")))
                for o in _RULES.get("other", []) if isinstance(o, dict) and o.get("pattern")]
PLACEHOLDER = re.compile(str(_RULES.get("placeholder") or r"(?!)"), re.I)


def mask_secrets(text) -> str:
    """비밀처럼 보이는 값을 MASK 로 바꾼 글. 이름과 `=`·`:` 는 남기고 값만 바꾼다."""
    def assign(m):
        g = 2 if m.group(2) else 3 if m.group(3) else 4
        if PLACEHOLDER.match((m.group(g) or "").strip()):
            return m.group(0)
        return m.group(0)[:m.start(g) - m.start()] + MASK + m.group(0)[m.end(g) - m.start():]
    out = SECRET_ASSIGN.sub(assign, str(text or ""))
    for rx, _label, url_password in SECRET_OTHER:
        out = rx.sub("://" + MASK + "@" if url_password else MASK, out)
    return out
