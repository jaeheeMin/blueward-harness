"""세션 기억(context) 사용량(#648). 대화 기록 jsonl 의 끝에서 거꾸로 읽어 마지막 사용량을 얻고, 창 크기를 알 때만 %를 낸다.

사용량: 마지막 `type: "assistant"` 줄(isSidechain 아님)의 message.usage 의
input_tokens + cache_creation_input_tokens + cache_read_input_tokens (output_tokens 는 더하지 않는다).

창 크기는 jsonl 에 없다. 공식 문서(https://code.claude.com/docs/en/model-config, 2026-11-04 확인)에 적힌 것만 쓴다.
  - "Fable 5.1, Fable 5, Sonnet 5 and later, Haiku 5.5, and Opus 4.7 and later run with the 1M window by default, with no [1m] suffix needed."
  - "Opus 4.6 and Sonnet 4.6 reach 1M only through their [1m] variant" — [1m] 이 없으면 200K.
  문서에 없는 모델(예: Haiku 4.5, 옛 이름)은 창 크기를 모른다 → % 없이 토큰 수만 보인다.
  한계: CLAUDE_CODE_DISABLE_1M_CONTEXT=1 처럼 세션 쪽 설정으로 창을 줄였는지는 알 수 없다(그 값은 훅 입력에도 없다).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

WINDOW_200K = 200_000
WINDOW_1M = 1_000_000
CHUNK = 256 * 1024
MAX_SCAN = 64 * 1024 * 1024  # 이만큼 거꾸로 읽어도 사용량 줄이 없으면 확인 못 함
MAX_PATH = 2000
_MODEL = re.compile(r"(opus|sonnet|haiku|fable)[-_ ]?(\d{1,2})(?!\d)(?:[-.](\d{1,2})(?!\d))?")
_cache: dict[str, tuple[int, int, dict | None]] = {}  # 경로 -> (mtime_ns, 크기, 읽은 결과)


def valid_path(value: Any) -> str:
    """훅이 알려 준 transcript_path 로 쓸 수 있는 값만 돌려준다(절대 경로의 .jsonl). 아니면 빈 문자열."""
    if isinstance(value, str) and 0 < len(value) <= MAX_PATH and value.lower().endswith(".jsonl") and os.path.isabs(value):
        return value
    return ""


def window_for(*names: str) -> int | None:
    """모델 이름(들)에서 창 크기를 정한다. 문서로 확인된 모델만, 모르면 None. 이름에 [1m] 이 있으면 1M."""
    texts = [n.lower() for n in names if isinstance(n, str) and n]
    for t in texts:
        m = _MODEL.search(t)
        if not m:
            continue
        family, ver = m.group(1), (int(m.group(2)), int(m.group(3) or 0))
        one_m = "[1m]" in t or any("[1m]" in x for x in texts)
        if family == "fable" and ver >= (5, 0):
            return WINDOW_1M
        if family == "sonnet" and ver >= (5, 0):
            return WINDOW_1M
        if family == "haiku" and ver >= (5, 5):
            return WINDOW_1M
        if family == "opus" and ver >= (4, 7):
            return WINDOW_1M
        if family in ("opus", "sonnet") and ver == (4, 6):
            return WINDOW_1M if one_m else WINDOW_200K
        return None
    return None


def _usage_of(line: bytes) -> dict | None:
    if b'"usage"' not in line or b'"assistant"' not in line:
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None  # 깨진 줄(쓰는 도중 잘린 줄 등)은 건너뛴다
    if not isinstance(row, dict) or row.get("type") != "assistant" or row.get("isSidechain") is True:
        return None
    msg = row.get("message")
    usage = msg.get("usage") if isinstance(msg, dict) else None
    if not isinstance(usage, dict) or msg.get("model") == "<synthetic>":
        return None
    parts = [usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    if not all(isinstance(p, int) and not isinstance(p, bool) and p >= 0 for p in parts if p is not None):
        return None
    total = sum(p for p in parts if p is not None)
    if total <= 0:
        return None
    return {"tokens": total, "model": msg.get("model") if isinstance(msg.get("model"), str) else ""}


def read_last_usage(path: str) -> dict | None:
    """jsonl 을 끝에서 거꾸로 읽어 마지막 사용량({tokens, model}). 못 읽거나 없으면 None. 파일이 바뀌었을 때만 다시 읽는다."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    found = None
    try:
        with open(path, "rb") as f:
            pos, tail, scanned = st.st_size, b"", 0
            while pos > 0 and scanned < MAX_SCAN and found is None:
                size = min(CHUNK, pos)
                pos -= size
                f.seek(pos)
                data = f.read(size) + tail
                scanned += size
                lines = data.split(b"\n")
                tail = lines[0]  # 앞이 잘렸을 수 있는 첫 조각은 다음 덩어리와 붙인다
                for line in reversed(lines[1:]):
                    found = _usage_of(line)
                    if found:
                        break
            if found is None and pos == 0:
                found = _usage_of(tail)
    except OSError:
        return None
    if len(_cache) > 200:
        _cache.clear()
    _cache[path] = (st.st_mtime_ns, st.st_size, found)
    return found


def for_session(s: dict) -> dict:
    """화면용 {tokens, window, pct}. 모르는 값은 None(지어내지 않는다)."""
    path = s.get("transcriptPath")
    usage = read_last_usage(path) if isinstance(path, str) and path else None
    if not usage:
        return {"tokens": None, "window": None, "pct": None}
    window = window_for(usage["model"], s.get("model", ""), s.get("modelChoice", ""))
    pct = min(100, round(usage["tokens"] * 100 / window)) if window else None
    return {"tokens": usage["tokens"], "window": window, "pct": pct}
