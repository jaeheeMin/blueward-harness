"""마크다운 문서의 한 절 아래 표가 정한 형식을 따르는지 본다(#287).

Spec 의 `## 사용 객체` 표처럼, 기계가 읽어야 하는 표의 열 이름, 열별 허용 값, 값 패턴을
검사한다. 어느 절의 어떤 열이 무엇이어야 하는지는 전부 규칙 파일의 데이터이고 이 모듈은
Spec 을 모른다.

params (한글 키, 영문 키도 받는다):
  절 / section      표가 있는 `##` 절 제목 (필수)
  열 / columns      표 머리 열 이름. 순서까지 같아야 한다 (필수)
  값 / values       {열: [허용 값...]}. 칸은 이 중 하나와 정확히 같아야 한다
  패턴 / patterns   {열: 정규식}. 칸 전체가 맞아야 한다
  필수 / required   true 면 절이 없는 것도 위반. 기본 false (선택 절 — 절이 없으면 통과)
  조건_필수 / required_if
                    [{열: 칸을 채워야 하는 열, 조건: {다른 열: [값...]}}...]. 행의 조건 열 값(백틱 벗김)이
                    목록 중 하나이고(조건 열이 여럿이면 모두) `열` 의 칸이 비었으면 위반. 값에 ""
                    를 넣으면 "비어 있을 때" 를 뜻한다. 예: 검사 방식이 `검사 안 함` 이면 비고 필수(#361)

판단:
- 절이 없다 → `필수` 가 아니면 통과. 템플릿에서 새로 생긴 절이라도 이미 쓰인 문서를 깨지 않는다.
- 절은 있는데 표가 없다 → 위반. 절을 만들었다면 표를 써야 기계가 읽는다.
- 머리만 있고 행이 없거나, 칸이 모두 빈 행(템플릿 자리표시 줄) → 위반 아님. 개발 건이 쓰는 객체가
  없을 수도 있고, 비웠다는 사실은 형식 문제가 아니다.
- 칸이 일부만 비었다 → 그 칸은 허용 값·패턴에 맞지 않으므로 위반.
- 파일을 읽지 못함 → ConfigError(종료코드 2, 검사 불능). 통과도 위반도 아니다.
- `|` 로 시작하고 바로 다음 줄이 정렬 줄(`|---|`)인 첫 표만 본다. 칸 안의 `|` 는 `\\|` 로 쓴다(백틱 안 `|` 도 칸 구분으로 본다). 코드 펜스 안은 예시라 보지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

from checker.model import ConfigError, Violation
from checker.rules import rule

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_H2 = re.compile(r"^##\s+(.*?)\s*#*\s*$")
_SEPARATOR = re.compile(r":?-{2,}:?")
_ALLOWED = {
    "절", "section", "열", "columns", "값", "values", "패턴", "patterns", "필수", "required",
    "조건_필수", "required_if",
}


def _get(params: dict, *names: str):
    for n in names:
        if params.get(n) is not None:
            return params[n]
    return None


def _cells(line: str) -> list[str]:
    """`|` 로 칸을 나눈다. `\\|` 는 칸 구분이 아니라 글자 `|` 다.

    한계: 백틱 안의 `|` 는 GFM 과 달리 칸 구분으로 본다. 칸 안에 `|` 를 쓰려면 `\\|` 로 쓴다.
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _section_lines(text: str, title: str) -> list[str] | None:
    """`## title` 아래 줄들(다음 `##` 이상 제목 전까지). 코드 펜스 안은 제목이 아니다."""
    lines: list[str] = []
    found = False
    fence: str | None = None
    for line in text.splitlines():
        fm = _FENCE.match(line)
        if fm:
            fence = None if fence == fm.group(1)[0] else (fence or fm.group(1)[0])
            if found:
                lines.append(line)
            continue
        if fence is None:
            m = _H2.match(line)
            if m:
                if found:
                    break
                found = m.group(1).strip() == title
                continue
            if found and re.match(r"^#\s", line):
                break
        if found:
            lines.append(line)
    return lines if found else None


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return line.lstrip().startswith("|") and any(cells) and all(
        _SEPARATOR.fullmatch(c) for c in cells if c
    )


def _first_table(lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    """첫 표의 (머리, 본문 행들). GFM 처럼 머리 바로 다음 줄이 정렬 줄(`|---|`)이어야 표다."""
    fence: str | None = None
    start: int | None = None
    for i, line in enumerate(lines):
        fm = _FENCE.match(line)
        if fm:
            fence = None if fence == fm.group(1)[0] else (fence or fm.group(1)[0])
            continue
        if fence is not None or not line.lstrip().startswith("|"):
            continue
        if i + 1 < len(lines) and _is_separator(lines[i + 1]):
            start = i
            break
    if start is None:
        return None
    rows: list[list[str]] = []
    for line in lines[start + 2:]:
        if not line.lstrip().startswith("|"):
            break
        rows.append(_cells(line))
    return _cells(lines[start]), rows


def _plain(cell: str) -> str:
    """이름 칸을 `이름` 처럼 백틱으로 감싸 써도 같은 값으로 본다."""
    return cell[1:-1].strip() if len(cell) >= 2 and cell[0] == cell[-1] == "`" else cell


def read_section_table(text: str, title: str) -> tuple[bool, tuple[list[str], list[list[str]]] | None]:
    """`## title` 절의 첫 표를 읽는다. (절이 있는가, (머리, 본문 행들) 또는 표 없음).

    규칙 밖에서(예: Spec 끼리 객체 겹침, `checker.overlap`) 같은 표 파서를 쓰게 공개한다.
    칸은 앞뒤 공백이 없고, 백틱으로 감싼 이름은 `plain_cell` 로 벗길 수 있다.
    """
    lines = _section_lines(text, title)
    if lines is None:
        return False, None
    return True, _first_table(lines)


def plain_cell(cell: str) -> str:
    return _plain(cell)


@rule("md_table")
def check(path: Path, params: dict) -> list[Violation]:
    title = _get(params, "절", "section")
    columns = _get(params, "열", "columns")
    if not title or not columns:
        raise ConfigError("md_table 규칙에는 '절' 과 '열' 이 모두 있어야 한다")
    columns = [str(c) for c in columns]
    values = _get(params, "값", "values") or {}
    patterns = _get(params, "패턴", "patterns") or {}
    required = bool(_get(params, "필수", "required"))
    required_if = _get(params, "조건_필수", "required_if") or []

    stray = [k for k in params if k not in _ALLOWED and not str(k).startswith("_")]
    if stray:
        raise ConfigError(
            f"md_table 규칙에 모르는 키가 있다: {', '.join(map(str, stray))} "
            f"(쓸 수 있는 키: 절, 열, 값, 패턴, 필수, 조건_필수)"
        )
    if not isinstance(columns, list):
        raise ConfigError("md_table 규칙의 '열' 은 목록이어야 한다")
    if not isinstance(values, dict) or not isinstance(patterns, dict):
        raise ConfigError("md_table 규칙의 '값' 과 '패턴' 은 {열: ...} 모양이어야 한다")
    for col, allowed in values.items():
        if not isinstance(allowed, list):
            raise ConfigError(f"md_table 규칙의 값['{col}'] 은 목록이어야 한다")
    for col, pat in patterns.items():
        if not isinstance(pat, str):
            raise ConfigError(f"md_table 규칙의 패턴['{col}'] 은 문자열이어야 한다")

    unknown = [c for c in list(values) + list(patterns) if c not in columns]
    if unknown:
        raise ConfigError(f"md_table 규칙의 값·패턴이 '열' 에 없는 열을 가리킨다: {', '.join(unknown)}")
    conditions = _parse_required_if(required_if, columns)
    try:
        compiled = {c: re.compile(p) for c, p in patterns.items()}
    except re.error as exc:
        raise ConfigError(f"md_table 규칙의 패턴이 올바른 정규식이 아니다: {exc}") from exc

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name} 를 읽지 못해 '{title}' 표를 검사할 수 없다: {exc}") from exc

    lines = _section_lines(text, str(title))
    if lines is None:
        if not required:
            return []
        return [_v(f"'{title}' 절", "없음", f"'{title}' 절이 문서에 없다")]

    table = _first_table(lines)
    if table is None:
        return [_v(f"'{title}' 절의 표(머리: {' | '.join(columns)})", "표 없음",
                   f"'{title}' 절은 있는데 표가 없다")]

    header, rows = table
    if header != columns:
        return [_v(columns, header, f"'{title}' 표의 머리 열이 정한 것과 다르다")]

    out: list[Violation] = []
    for i, cells in enumerate(rows, start=1):
        if not any(cells):
            continue  # 템플릿 자리표시 줄
        if len(cells) != len(columns):
            out.append(_v(f"{len(columns)}칸", f"{len(cells)}칸",
                          f"'{title}' 표 {i}번째 행의 칸 수가 머리와 다르다(칸 안의 | 는 \\| 로 쓴다)"))
            continue
        for col, cell in zip(columns, cells):
            cell = _plain(cell)
            if col in values and cell not in values[col]:
                out.append(_v(f"{col}: {' / '.join(map(str, values[col]))}", cell or "빈 칸",
                              f"'{title}' 표 {i}번째 행의 '{col}' 값이 허용 목록에 없다"))
            elif col in compiled and not compiled[col].fullmatch(cell):
                out.append(_v(f"{col}: {patterns[col]}", cell or "빈 칸",
                              f"'{title}' 표 {i}번째 행의 '{col}' 값이 형식에 맞지 않는다"))
        by_col = dict(zip(columns, (_plain(c) for c in cells)))
        reported: set[str] = set()  # 같은 칸을 여러 조건이 가리켜도 한 번만 알린다
        for target, when in conditions:
            if target not in reported and not by_col[target] and all(by_col[c] in vals for c, vals in when.items()):
                reported.add(target)
                shown = " 이고 ".join(f"'{c}' 가 {' / '.join(repr(v) if v else '빈 칸' for v in vals)}"
                                      for c, vals in when.items())
                out.append(_v(f"{target}: 내용", "빈 칸",
                              f"'{title}' 표 {i}번째 행은 {shown} 이라 '{target}' 칸을 채워야 한다"))
    return out


def _parse_required_if(raw, columns: list[str]) -> list[tuple[str, dict[str, list[str]]]]:
    if not isinstance(raw, list):
        raise ConfigError("md_table 규칙의 '조건_필수' 는 목록이어야 한다")
    parsed = []
    for item in raw:
        target = _get(item, "열", "column") if isinstance(item, dict) else None
        when = _get(item, "조건", "when") if isinstance(item, dict) else None
        if not target or not isinstance(when, dict) or not when:
            raise ConfigError("md_table 규칙의 '조건_필수' 항목에는 '열' 과 '조건'({열: [값...]}) 이 있어야 한다")
        if target not in columns or any(c not in columns for c in when):
            raise ConfigError("md_table 규칙의 '조건_필수' 가 '열' 에 없는 열을 가리킨다")
        if not all(isinstance(v, list) for v in when.values()):
            raise ConfigError("md_table 규칙의 '조건_필수' 조건 값은 목록이어야 한다")
        parsed.append((target, {c: ["" if v is None else str(v) for v in vals] for c, vals in when.items()}))
    return parsed


def _v(expected, actual, message: str) -> Violation:
    return Violation(rule="md_table", expected=expected, actual=actual, message=message)
