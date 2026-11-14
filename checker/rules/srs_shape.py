"""SRS 모양 검사(#975) — 여럿이 동시에 고쳐도 문서가 깨진 채 합쳐지지 않게 한다.

두 PR 이 같은 REQ 번호를 표의 서로 다른 자리에 넣으면 git 은 충돌 없이 합쳐 같은 행이 두 개 생긴다.
그런 모양을 PR 검사에서 거절한다. 세 가지를 본다.

1. 문서 머리(제목 아래 첫 `##` 앞)의 `버전:` 줄이 정확히 1개. 산출(`export._head_meta`)이 읽는 범위와 같다.
2. `## 요구사항` 표의 REQ 번호 집합 = `### REQ-n` 상세 절 번호 집합. 한쪽에만 있는 번호를 각각 밝힌다.
3. 표 행에서 같은 REQ 가 두 번, `### REQ-n` 제목이 두 번 나오지 않는다.

표·절은 `pairing.section_span`·`table_indexed`, 상세 절은 `req_cross_reference.parse_sections`(코드 펜스 안은 뺀다)로
읽는다 — 파서를 새로 만들지 않는다.

검사 불능(ConfigError, 종료코드 2 — 통과도 위반도 아니다):
- 파일을 읽지 못함, `## 요구사항` 절이 없음.
- 요구사항 표 머리(`ID` 열)를 못 찾는데 REQ 번호가 있음(표 행이나 상세 절).
작성 전 SRS(요구사항 절에 표도 상세 절도 없음)는 비교할 대상이 없으니 번호 검사는 통과로 두고 버전 줄만 본다
(`pairing._load_srs` 와 같은 기준 — 새로 scaffold 한 저장소가 처음부터 멈추지 않게).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from checker.model import ConfigError, Violation
from checker.pairing import section_span, table_indexed
from checker.rules import rule
from checker.rules.req_cross_reference import parse_sections

# export._META_LINE 과 같은 모양(머리의 `이름: 값` 줄). 이름이 `버전` 인 줄만 센다.
_META = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?([^:：*|#]{1,30}?)(?:\*\*)?\s*[:：]\s*(?:\*\*)?(.*?)(?:\*\*)?\s*$")
_REQ_ID = re.compile(r"^REQ-(\d+)(?![A-Za-z0-9])")
_REQ_ANY = re.compile(r"REQ-\d+")
_SECTION = "요구사항"


def _label(n: int) -> str:
    return f"REQ-{n:03d}"


def _head_version_lines(text: str) -> list[str]:
    """머리(첫 `##` 앞)에서 값이 있는 `버전:` 줄들. `export._head_meta` 와 같은 범위·같은 읽기."""
    found: list[str] = []
    for line in re.split(r"\r\n|\n|\r", text):
        if re.match(r"^##\s", line):
            break
        if line.lstrip().startswith("#"):
            continue
        m = _META.match(line)
        if m and m.group(2) and unicodedata.normalize("NFC", m.group(1)).strip() == "버전":
            found.append(line.strip())
    return found


def _dups(numbers: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for n in numbers:
        if n in seen and n not in out:
            out.append(n)
        seen.add(n)
    return out


@rule("srs_shape")
def check(path: Path, params: dict) -> list[Violation]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name} 를 읽지 못해 SRS 모양을 검사할 수 없다: {exc}") from exc

    span = section_span(text, _SECTION)
    if span is None:
        raise ConfigError(f"{path.name} 에서 `## {_SECTION}` 절을 찾지 못해 SRS 모양을 검사할 수 없다")
    section = text.splitlines()[span[0]:span[1]]
    sections = parse_sections(text)  # [(REQ-n, 본문)] — 문서 전체의 `### REQ-n` 상세 절
    table = table_indexed(section)
    if table is None and (sections or any(_REQ_ANY.search(l) for l in section if l.lstrip().startswith("|"))):
        raise ConfigError(f"{path.name} 의 요구사항 표 머리(`ID` 열)를 찾지 못해 SRS 모양을 검사할 수 없다")

    violations: list[Violation] = []

    versions = _head_version_lines(text)
    if len(versions) != 1:
        violations.append(
            Violation(
                rule="srs_shape",
                expected="문서 머리에 `버전:` 줄 1개",
                actual=f"{len(versions)}개" + (f" ({'; '.join(versions)})" if versions else ""),
                message=(
                    "문서 머리(제목 아래 첫 `##` 앞)에 `버전:` 줄이 없다. 한 줄 적는다."
                    if not versions
                    else f"문서 머리에 `버전:` 줄이 {len(versions)}개다. 하나만 남기고 지운다(두 PR 이 각자 줄을 넣어 합쳐졌을 수 있다)."
                ),
            )
        )

    if table is None:  # 작성 전(표도 상세 절도 없음) — 번호 비교 대상이 없다
        return violations
    header, rows = table
    id_col = header.index("ID")
    table_nums: list[int] = []
    for _, cells in rows:
        m = _REQ_ID.match(cells[id_col]) if id_col < len(cells) else None
        if m:
            table_nums.append(int(m.group(1)))
    detail_nums = [int(rid.split("-")[1]) for rid, _ in sections]

    for n in _dups(table_nums):
        violations.append(
            Violation(
                rule="srs_shape",
                expected="요구사항 표에 REQ 번호마다 행 1개",
                actual=f"{_label(n)} 행이 {table_nums.count(n)}개",
                message=f"요구사항 표에 {_label(n)} 행이 {table_nums.count(n)}개다. 하나로 합치고, 다른 요구사항이었다면 번호를 새로 받는다.",
            )
        )
    for n in _dups(detail_nums):
        violations.append(
            Violation(
                rule="srs_shape",
                expected="`### REQ-n` 상세 절은 번호마다 1개",
                actual=f"`### {_label(n)}` 제목이 {detail_nums.count(n)}개",
                message=f"`### {_label(n)}` 상세 절이 {detail_nums.count(n)}번 나온다. 하나로 합치고, 다른 요구사항이었다면 번호를 새로 받는다.",
            )
        )

    only_table = sorted(set(table_nums) - set(detail_nums))
    only_detail = sorted(set(detail_nums) - set(table_nums))
    if only_table:
        names = ", ".join(_label(n) for n in only_table)
        violations.append(
            Violation(
                rule="srs_shape",
                expected="표의 모든 REQ 에 `### REQ-n` 상세 절",
                actual=f"표에만 있음: {names}",
                message=f"요구사항 표에는 있는데 `### REQ-n` 상세 절이 없다: {names}. 상세 절을 쓰거나 표 행을 지운다.",
            )
        )
    if only_detail:
        names = ", ".join(_label(n) for n in only_detail)
        violations.append(
            Violation(
                rule="srs_shape",
                expected="모든 `### REQ-n` 상세 절에 표 행",
                actual=f"상세 절에만 있음: {names}",
                message=f"`### REQ-n` 상세 절은 있는데 요구사항 표에 행이 없다: {names}. 표 행을 더하거나 상세 절을 지운다.",
            )
        )
    return violations
