"""SRS 요구사항 상세 절이 다른 요구사항 번호를 말하면 관계 줄을 요구한다(#261).

한 개발이 REQ 두 개로 쪼개지면 새 REQ 의 상세 절에 다른 번호("REQ-002", "DEV-002 개발 중")가
적힌다. 정말 별개인 요구사항이면 그 이유를 `관계: 별개 — <이유>` 줄로 남기게 하고, 같은 개발이면
새 REQ 를 만들지 말고 기존 REQ 의 범위를 넓히게 한다.

관계 줄은 `### REQ-n` 제목과 첫 `####` 소제목 사이에 둔다. 엑셀 산출(`checker/export.py`)은
그 자리의 줄을 읽지 않으므로 산출과 충돌하지 않는다. 소제목 아래에 두면 그 칸의 값으로 엑셀에
섞여 나가기 때문에 인정하지 않는다.

접두어(`관계_접두어`)와 제외 패턴(`제외_패턴`, 번호 앞 문맥)은 규칙 파일의 데이터다.
"""
from __future__ import annotations

import re
from pathlib import Path

from checker.model import ConfigError, Violation
from checker.rules import rule

# 파이썬 `\b` 는 한글도 단어 문자로 봐서 `REQ-001의` 를 못 잡는다. ASCII 영숫자 기준으로 경계를 건다.
_NUM = re.compile(r"(?<![A-Za-z0-9])(REQ|DEV)-(\d+)(?![0-9])")
_H12 = re.compile(r"^#{1,2}\s")
_H3 = re.compile(r"^###\s+(.+?)\s*$")
_H4 = re.compile(r"^####\s")
_REQ_TITLE = re.compile(r"^REQ-(\d+)(?![A-Za-z0-9])")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

DEFAULT_PREFIX = "관계:"
DEFAULT_EXCLUDE = [r"옛\s*$"]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _excluded(line: str, start: int, patterns: list[re.Pattern]) -> bool:
    before = line[:start]
    return any(p.search(before) for p in patterns)


def parse_sections(text: str) -> list[tuple[str, list[str]]]:
    """`### REQ-n` 상세 절을 (REQ-n, 제목 아래 줄들) 로 나눈다. 코드 펜스 안은 예시라 뺀다.

    risk-gate 의 쪼개짐 의심 기준(#278)도 같은 파싱을 쓴다 — 두 벌로 만들지 않는다.
    """
    sections: list[tuple[str, list[str]]] = []
    cur: tuple[str, list[str]] | None = None
    fence: str | None = None  # 열린 펜스의 문자(` 또는 ~)
    for line in text.splitlines():
        fm = _FENCE.match(line)
        if fm:
            if fence is None:
                fence = fm.group(1)[0]
            elif fm.group(1)[0] == fence:
                fence = None
            continue
        if fence is not None:  # 코드 펜스 안은 예시이므로 제목도 번호 언급도 보지 않는다
            continue
        if _H12.match(line) or _H3.match(line):
            cur = None
            m = _H3.match(line)
            t = _REQ_TITLE.match(m.group(1)) if m else None
            if t:
                cur = (t.group(0), [])
                sections.append(cur)
            continue
        if cur is not None:
            cur[1].append(line)
    return sections


def collect_mentions(
    rid: str, body: list[str], prefix: str, excludes: list[re.Pattern]
) -> tuple[list[str], bool, bool]:
    """상세 절 본문에서 (다른 번호 언급, 관계 줄 인정 여부, 관계 줄이 소제목 아래라 거부됐는지)."""
    own = rid.split("-")[1]
    relation_ok = False
    relation_misplaced = False
    seen_h4 = False
    others: list[str] = []
    for line in body:
        if _H4.match(line):
            seen_h4 = True
        stripped = line.strip().lstrip("-*").strip()
        if stripped.startswith(prefix):
            if stripped[len(prefix):].strip().lstrip("—–-:").strip():
                if seen_h4:
                    relation_misplaced = True
                else:
                    relation_ok = True
            continue  # 관계 줄 안의 번호(이유)는 언급으로 세지 않는다
        for m in _NUM.finditer(line):
            kind, num = m.group(1), m.group(2)
            if int(num) == int(own):  # 자기 번호(REQ-n, DEV-n)는 다른 번호가 아니다
                continue
            if _excluded(line, m.start(), excludes):
                continue
            label = f"{kind}-{num}"
            if label not in others:
                others.append(label)
    return others, relation_ok, relation_misplaced


@rule("req_cross_reference")
def check(path: Path, params: dict) -> list[Violation]:
    prefix = str(params.get("관계_접두어") or params.get("relation_prefix") or DEFAULT_PREFIX).strip()
    raw = params.get("제외_패턴") or params.get("exclude_patterns") or DEFAULT_EXCLUDE
    try:
        excludes = [re.compile(p) for p in raw]
    except (re.error, TypeError) as exc:
        raise ConfigError(f"req_cross_reference 규칙의 '제외_패턴' 이 올바른 정규식 목록이 아니다: {exc}") from exc

    sections = parse_sections(_text(path))

    violations: list[Violation] = []
    for rid, body in sections:
        others, relation_ok, relation_misplaced = collect_mentions(rid, body, prefix, excludes)
        if not others or relation_ok:
            continue
        hint = (
            f"같은 개발이면 새 REQ 대신 그 REQ 의 범위를 넓힌다. 별개면 `{prefix} 별개 — <이유>` 를 "
            f"`### {rid}` 제목 바로 아래, 첫 `####` 소제목 앞에 일반 줄로 적는다(인용 `>` 이나 소제목 아래는 인정하지 않는다)"
        )
        if relation_misplaced:
            hint += " (지금 관계 줄은 소제목 아래에 있어 엑셀 칸으로 섞여 나가므로 인정하지 않는다)"
        elif any(l.strip().lstrip("-*").strip().startswith(prefix) for l in body):
            hint += " (관계 줄에 이유가 비어 있다)"
        violations.append(
            Violation(
                rule="req_cross_reference",
                expected=f"{prefix} 별개 — <이유>",
                actual=", ".join(others),
                message=f"{rid} 상세 절이 다른 번호({', '.join(others)})를 말하는데 관계 줄이 없다. {hint}",
            )
        )
    return violations
