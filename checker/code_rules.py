"""공통 개발 규칙 CR-001(이름에 한글 금지)과 CR-002(반복문 안 DB 조회 금지)를 코드에서
기계로 검사한다(#54, `plugins/harness/conventions/common.md`).

문서 검사(`checker.engine`)와는 관할이 다르다. 문서 쪽은 템플릿과 규칙 파일을 요구하지만,
이 두 규칙은 어느 Project Repository, 어느 기준 폴더(`templates/` 와 `rules/` 를 함께
가진 폴더)에서나 항상 같다 — 기준 폴더별 `rules.yaml` 로 켜고 끄는 대상이 아니다.
그래서 `checker.engine` 의 관할(glob)·규칙(rule kind) 틀을 쓰지 않고 이 파일 하나에
CLI 까지 둔다. 다만 "규칙은 코드가 아니라 데이터" 라는 원칙은
그대로 지킨다 — 어느 언어에서 어느 규칙을 적용하는지는 `code_checks.yaml` 에 있고, 여기
있는 것은 언어별 주석·문자열·반복문을 알아보는 스캐너뿐이다.

**판정 불가를 통과로 뭉개지 않는다(CLAUDE.md 원칙 7).** 파일을 읽지 못했거나(존재하지
않음, 디코딩 실패) 언어를 모르면(확장자 불명) 그것을 "위반 없음" 으로 답하지 않는다.
읽지 못한 파일은 종료코드 2(검사 불능)로 끝나 절대 0(통과)이 되지 않고, 확장자를 모르는
파일은 "skipped" 로 따로 세어 통과 판정과 섞이지 않는다.

**예외(`harness:allow`).** 규칙마다 오탐이 있을 수 있으므로, 같은 줄이나 바로 위 줄의
주석에 `harness:allow CR-001 <이유>` 처럼 이유와 함께 적으면 그 발견은 위반이 아니라
"allowed" 로 보고한다. 이유 없이(`harness:allow CR-002` 만) 적으면 예외로 인정하지 않고
위반으로 남기며, 이유가 없다는 사실을 note 로 덧붙인다 — 말없이 다 통과시키는 탈출구가
되는 것을 막기 위해서다.

**스캐너는 정밀 파서가 아니라 휴리스틱이다.** ABAP 은 문(statement)을 마침표로 가르고
LOOP/DO/WHILE/SELECT…ENDSELECT 의 중첩만 센다. 체인 문장(`SELECT ... : a, b.`)이나
여러 줄에 걸친 문자열 리터럴 같은 드문 모양은 놓칠 수 있다. JS/TS(CAP) 의 CR-002 는
`for`/`while`/`.forEach`/`.map` 뒤에 오는 `{ ... }` 블록만 반복문 몸통으로 보므로, 중괄호
없는 한 줄 반복문은 못 잡는다. 두 한계 모두 놓치는 쪽(false negative)으로 기울여 두었다 —
과검출로 정상 코드를 막는 편보다 낫다고 판단했다. 오탐이 보이면 규칙 코드를 고치지 말고
`harness:allow` 로 개별 예외를 남기고, 스캐너 자체의 결함이면 이 파일을 고친다.
"""
from __future__ import annotations

import argparse
import bisect
import functools
import json
import re
import sys
from pathlib import Path

import yaml

from checker.model import ConfigError

# --- 설정 ---------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_config() -> dict:
    """`code_checks.yaml` 을 읽는다. 언어 종류와 규칙-언어 대응이 여기 있다."""
    config_path = Path(__file__).with_name("code_checks.yaml")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"code_checks.yaml 을 읽을 수 없다: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"code_checks.yaml 이 올바른 YAML 이 아니다: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("code_checks.yaml 의 최상위는 사전이어야 한다")
    return raw


def _suffix_language_map(cfg: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for lang, info in (cfg.get("languages") or {}).items():
        for suffix in (info or {}).get("suffixes") or []:
            mapping[str(suffix).lower()] = lang
    return mapping


def language_for_suffix(path: Path, cfg: dict | None = None) -> str | None:
    """파일 확장자로 언어를 정한다. 모르는 확장자면 None(=검사 대상 아님)."""
    cfg = cfg if cfg is not None else _load_config()
    return _suffix_language_map(cfg).get(path.suffix.lower())


# --- 위치 계산 ------------------------------------------------------------------


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _offset_to_linecol(offset: int, line_starts: list[int]) -> tuple[int, int]:
    idx = bisect.bisect_right(line_starts, offset) - 1
    idx = max(idx, 0)
    return idx + 1, offset - line_starts[idx] + 1


# --- 마스킹: 주석·문자열의 내용을 공백으로 지운다(길이와 줄바꿈은 그대로 둔다) -------
#
# 마스킹한 뒤 문자열은 원문과 길이가 같고 줄바꿈 위치도 같다. 그래서 마스킹한 문자열에서
# 얻은 오프셋을 원문의 줄·칸으로 그대로 옮길 수 있다. CR-001(이름) 과 CR-002(반복문) 가
# 이 하나의 마스킹 결과를 함께 쓴다.


def _mask_abap(text: str) -> str:
    """ABAP 의 주석과 문자열 내용을 지운다.

    줄 첫 칸의 `*` 는 그 줄 전체가 주석이다(ABAP 은 들여쓴 `*` 를 주석으로 보지 않는다).
    `"` 는 그 지점부터 줄 끝까지 주석이다. 문자열은 `'...'`(작은따옴표 두 번으로 이스케이프),
    `` `...` ``(고정 문자열), `|...|`(문자열 템플릿, `||` 로 이스케이프) 세 가지이고, 그 안의
    `"`, `'` 같은 글자는 주석이나 다른 문자열의 시작으로 보지 않는다. 템플릿 안의
    `{ 표현식 }` 도 CR-001 목적으로는 문자열의 일부로 보고 통째로 지운다 — 실제로는 코드지만,
    거기 한글이 있어도 이 규칙이 잡을 대상(선언된 이름)이 아니라 값이기 쉽고, 무엇보다 중괄호
    안까지 별도로 파싱하는 것은 이 스캐너의 몫을 넘는다.

    문자열은 한 줄을 넘지 않는다고 본다 — ABAP 실무에서 따옴표 문자열이 줄을 넘는 일은 없다.
    """
    out_lines = []
    for line in text.split("\n"):
        if line[:1] == "*":
            out_lines.append(" " * len(line))
            continue
        chars = list(line)
        i, n = 0, len(chars)
        in_string: str | None = None
        while i < n:
            c = chars[i]
            if in_string == "'":
                if c == "'":
                    if i + 1 < n and chars[i + 1] == "'":
                        i += 2
                        continue
                    in_string = None
                    i += 1
                    continue
                chars[i] = " "
                i += 1
                continue
            if in_string == "`":
                if c == "`":
                    in_string = None
                    i += 1
                    continue
                chars[i] = " "
                i += 1
                continue
            if in_string == "|":
                if c == "|":
                    if i + 1 < n and chars[i + 1] == "|":
                        chars[i] = chars[i + 1] = " "
                        i += 2
                        continue
                    in_string = None
                    i += 1
                    continue
                chars[i] = " "
                i += 1
                continue
            # 문자열 밖.
            if c == '"':
                for k in range(i, n):
                    chars[k] = " "
                i = n
                continue
            if c in "'`|":
                in_string = c
                i += 1
                continue
            i += 1
        out_lines.append("".join(chars))
    return "\n".join(out_lines)


def _mask_c_like(text: str) -> str:
    """JS/TS 와 CDS 가 함께 쓰는 마스킹.

    `//` 줄 주석, `/* ... */` 블록 주석(여러 줄에 걸칠 수 있다 — 줄바꿈은 지우지 않는다),
    `'...'`/`"..."`(`\\` 로 이스케이프), `` `...` `` 템플릿 리터럴(`${}` 포함 통째로 문자열로
    본다, ABAP `|...|` 와 같은 이유)을 지운다.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            end = text.find("\n", i)
            end = n if end == -1 else end
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        if two == "/*":
            close = text.find("*/", i + 2)
            end = n if close == -1 else close + 2
            for k in range(i, end):
                if text[k] != "\n":
                    out[k] = " "
            i = end
            continue
        c = text[i]
        if c in "'\"`":
            quote = c
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                if text[j] == "\n" and quote != "`":
                    # 닫히지 않은 작은/큰따옴표 문자열. 정상 코드라면 안 생긴다.
                    break
                j += 1
            for k in range(i, min(j, n)):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _mask_bdef(text: str) -> str:
    """RAP 동작 정의(BDEF)의 주석과 문자열 내용을 지운다(#72).

    `//` 줄 주석, `/* ... */` 블록 주석(여러 줄에 걸칠 수 있다 — 줄바꿈은 지우지
    않는다)은 JS/CDS 가 함께 쓰는 `_mask_c_like` 와 같은 모양이라 그 처리를
    그대로 옮겨 왔다. 다만 문자열은 그대로 재사용하지 않았다 — `_mask_c_like` 는
    `"`, `` ` `` 도 문자열(또는 그 시작)로 본다. BDEF 문법에는 `"` 로 시작하는
    ABAP 식 주석도, `` ` `` 고정 문자열도 없으므로 그대로 쓰면 문법에 없는
    것까지 지워 실제로는 코드인 자리를 놓치게 된다(모듈 docstring의 "스캐너는
    정밀 파서가 아니라 휴리스틱이다" 원칙과 반대 방향의 실수). BDEF 의 문자열은
    드물게 나오는 `'...'` 하나뿐이고, ABAP 리터럴과 같이 작은따옴표 두 번으로
    이스케이프한다고 보며 줄을 넘지 않는다고 본다(ABAP 문자열과 같은 가정,
    `_mask_abap` 참고).
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            end = text.find("\n", i)
            end = n if end == -1 else end
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        if two == "/*":
            close = text.find("*/", i + 2)
            end = n if close == -1 else close + 2
            for k in range(i, end):
                if text[k] != "\n":
                    out[k] = " "
            i = end
            continue
        c = text[i]
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                if text[j] == "\n":
                    # 닫히지 않은 문자열. 정상 BDEF 라면 안 생긴다(ABAP 과 같은 가정).
                    break
                j += 1
            for k in range(i, min(j, n)):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


_MASKERS = {"abap": _mask_abap, "js": _mask_c_like, "cds": _mask_c_like, "bdef": _mask_bdef}


# --- CR-001: 이름에 한글 등 비ASCII 문자 ------------------------------------------

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _has_non_ascii_letter(word: str) -> bool:
    return any(ord(ch) > 127 and ch.isalpha() for ch in word)


def _scan_cr001(masked: str) -> list[tuple[str, int, str]]:
    """마스킹한(=주석·문자열이 지워진) 텍스트에서 비ASCII 문자를 포함한 이름을 찾는다."""
    findings = []
    for m in _WORD_RE.finditer(masked):
        word = m.group()
        if _has_non_ascii_letter(word):
            findings.append(("CR-001", m.start(), f"이름 '{word}' 에 한글 등 비ASCII 문자가 있다."))
    return findings


# --- CR-002 (ABAP): LOOP/DO/WHILE/SELECT...ENDSELECT 안의 DB 조회 -----------------

_ABAP_STMT_END_RE = re.compile(r"\.(?=\s|$)")
_ABAP_KEYWORD_RE = re.compile(r"(\s*)([A-Za-z_][A-Za-z0-9_]*)")


def _abap_statements(masked: str) -> list[tuple[int, int]]:
    """마침표로 문을 가른다. 문자열·주석은 이미 지워져 있으므로 그 안의 마침표는 없다."""
    statements = []
    start = 0
    for m in _ABAP_STMT_END_RE.finditer(masked):
        statements.append((start, m.end()))
        start = m.end()
    if start < len(masked) and masked[start:].strip():
        statements.append((start, len(masked)))
    return statements


def _scan_abap_cr002(masked: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    stack: list[str] = []  # "loop" | "do" | "while" | "select"

    for start, end in _abap_statements(masked):
        segment = masked[start:end]
        km = _ABAP_KEYWORD_RE.match(segment)
        if not km:
            continue
        keyword = km.group(2).upper()
        keyword_offset = start + len(km.group(1))

        if keyword == "LOOP":
            stack.append("loop")
        elif keyword == "ENDLOOP":
            if stack:
                stack.pop()
        elif keyword == "DO":
            stack.append("do")
        elif keyword == "ENDDO":
            if stack:
                stack.pop()
        elif keyword == "WHILE":
            stack.append("while")
        elif keyword == "ENDWHILE":
            if stack:
                stack.pop()
        elif keyword == "ENDSELECT":
            if stack and stack[-1] == "select":
                stack.pop()
        elif keyword == "SELECT":
            from_itab = bool(re.search(r"FROM\s+@", segment, re.IGNORECASE))
            if stack and not from_itab:
                findings.append((
                    "CR-002", keyword_offset,
                    "SELECT 문이 반복문(LOOP/DO/WHILE/SELECT) 안에 있다.",
                ))
            # `SELECT SINGLE` 은 한 줄만 가져오므로 ENDSELECT 가 필요 없다. `INTO TABLE`
            # 이 없는 그 밖의 SELECT 는 결과를 한 줄씩 훑는 SELECT...ENDSELECT 반복문을
            # 연다 — 그 뒤 ENDSELECT 까지는 이 반복문 안이다. 이 구분이 없으면
            # `SELECT SINGLE ... .` 문 하나마다 반복문이 하나씩 열린 것으로 잘못 세어,
            # 짝이 맞는 ENDSELECT 가 없으니 스택이 영영 비지 않는다.
            is_single = bool(re.match(r"\s*SELECT\s+SINGLE\b", segment, re.IGNORECASE))
            if not is_single and not re.search(r"INTO\s+TABLE", segment, re.IGNORECASE):
                stack.append("select")
        elif keyword == "OPEN":
            om = re.match(r"\s*OPEN\s+(\w+)", segment, re.IGNORECASE)
            if om and om.group(1).upper() == "CURSOR" and stack:
                findings.append((
                    "CR-002", keyword_offset,
                    "OPEN CURSOR 가 반복문 안에 있다. 커서는 반복문 밖에서 한 번만 연다.",
                ))

    return findings


# --- CR-002 (JS/TS, CAP): for/while/forEach/map 안의 DB 조회 (휴리스틱) -----------

_JS_FOR_WHILE_RE = re.compile(r"\bfor\s+await\s*\(|\bfor\s*\(|\bwhile\s*\(")
_JS_CALLBACK_RE = re.compile(r"\.\s*forEach\s*\(|\.\s*map\s*\(")
_JS_DB_CALL_RE = re.compile(
    r"\bSELECT\s*\.\s*(from|one)\b"
    r"|\bcds\s*\.\s*run\s*\("
    r"|\.\s*run\s*\(\s*SELECT\b"
    r"|\bINSERT\s*\."
    r"|\bUPSERT\s*\."
    r"|\bUPDATE\s*\("
    r"|\bDELETE\s*\.",
    re.IGNORECASE,
)


def _matching_brace(text: str, open_pos: int) -> int:
    """`text[open_pos]` 가 여는 괄호라고 보고 짝이 맞는 위치를 찾는다. 못 찾으면 len(text)."""
    opener = text[open_pos]
    closer = {"(": ")", "{": "}"}[opener]
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _js_loop_body_spans(masked: str) -> list[tuple[int, int]]:
    """`for(...)`/`while(...)`/`.forEach(...)`/`.map(...)` 의 몸통 `{ ... }` 를 찾는다.

    `for`/`while` 은 조건절 `(...)` 뒤에 몸통이 오지만, `.forEach(...)`/`.map(...)` 은
    콜백(몸통을 포함한 함수 전체)이 그 괄호 **안**에 있다 — 둘을 같은 방법으로 찾을 수
    없어 나눈다.

    중괄호 없이 한 줄로 쓴 반복문(`for (...) doSomething();`)이나 이름만 넘긴 콜백
    (`orders.forEach(processOrder)`)은 몸통을 못 찾아 건너뛴다 — 놓치는 쪽으로 기운
    휴리스틱이다(모듈 docstring 참고).
    """
    spans = []
    n = len(masked)

    for m in _JS_FOR_WHILE_RE.finditer(masked):
        paren_start = masked.find("(", m.start())
        if paren_start == -1:
            continue
        paren_end = _matching_brace(masked, paren_start)
        if paren_end >= n:
            continue
        brace_start = _find_brace(masked, paren_end + 1, min(n, paren_end + 1 + 40))
        if brace_start is None:
            continue
        spans.append((brace_start, _matching_brace(masked, brace_start)))

    for m in _JS_CALLBACK_RE.finditer(masked):
        call_paren = masked.find("(", m.start())
        if call_paren == -1:
            continue
        call_end = _matching_brace(masked, call_paren)
        # 콜백의 몸통 `{` 는 매개변수 목록과 화살표(또는 `function` 키워드) 다음, 이
        # 호출의 닫는 괄호보다 앞에 있다.
        brace_start = _find_brace(masked, call_paren + 1, call_end)
        if brace_start is None:
            continue
        spans.append((brace_start, _matching_brace(masked, brace_start)))

    return spans


def _find_brace(text: str, start: int, end: int) -> int | None:
    idx = text.find("{", start, end)
    return idx if idx != -1 else None


def _scan_js_cr002(masked: str) -> list[tuple[str, int, str]]:
    spans = _js_loop_body_spans(masked)
    if not spans:
        return []
    findings = []
    for m in _JS_DB_CALL_RE.finditer(masked):
        if any(s <= m.start() < e for s, e in spans):
            findings.append((
                "CR-002", m.start(),
                "DB 조회로 보이는 호출이 반복문 안에 있다(JS 는 휴리스틱 판정).",
            ))
    return findings


# --- 예외: harness:allow --------------------------------------------------------

_ALLOW_RE = re.compile(r"harness:allow\s+(CR-\d{3})(.*)", re.IGNORECASE)


def _check_allow(rule: str, line_no: int, raw_lines: list[str]) -> tuple[bool, str | None]:
    """같은 줄이나 바로 위 줄에서 `harness:allow CR-00N <이유>` 를 찾는다.

    이유가 없으면 예외로 인정하지 않는다(허수아비 면제를 막기 위해서) — 대신 위반 그대로
    두고, 이유가 없어 무시했다는 note 를 붙인다.
    """
    candidates = []
    if 1 <= line_no <= len(raw_lines):
        candidates.append(raw_lines[line_no - 1])
    if 0 <= line_no - 2 < len(raw_lines):
        candidates.append(raw_lines[line_no - 2])

    for cand in candidates:
        m = _ALLOW_RE.search(cand)
        if m and m.group(1).upper() == rule:
            reason = (m.group(2) or "").strip(" \t-:*/`|\"#")
            if reason:
                return True, None
            return False, "예외 주석(harness:allow)에 이유가 없어 인정하지 않았다. 이유를 적어야 한다."
    return False, None


# --- 공개 API --------------------------------------------------------------------


def check_source(path_str: str, text: str, language: str | None = None) -> list[dict]:
    """소스 텍스트 하나를 검사해 발견(finding) 목록을 낸다.

    언어를 모르면(확장자 불명) 빈 목록을 낸다 — 이것은 "위반 없음" 이 아니라 "이 검사의
    대상이 아니다" 이다. 호출부(CLI, 훅)가 언어 판정과 검사 대상 여부를 따로 다룬다.
    """
    cfg = _load_config()
    if language is None:
        language = language_for_suffix(Path(path_str), cfg)
    if language is None:
        return []

    mask_fn = _MASKERS.get(language)
    if mask_fn is None:
        return []
    masked = mask_fn(text)

    rules_cfg = cfg.get("rules") or {}
    raw_findings: list[tuple[str, int, str]] = []

    cr001 = rules_cfg.get("CR-001") or {}
    if language in (cr001.get("languages") or []):
        raw_findings.extend(_scan_cr001(masked))

    cr002 = rules_cfg.get("CR-002") or {}
    if language in (cr002.get("languages") or []):
        if language == "abap":
            raw_findings.extend(_scan_abap_cr002(masked))
        elif language == "js":
            raw_findings.extend(_scan_js_cr002(masked))

    line_starts = _line_starts(text)
    raw_lines = text.split("\n")

    findings = []
    for rule, offset, message in raw_findings:
        line, col = _offset_to_linecol(offset, line_starts)
        allowed, note = _check_allow(rule, line, raw_lines)
        finding = {
            "rule": rule,
            "line": line,
            "col": col,
            "message": message,
            "fix": (rules_cfg.get(rule) or {}).get("fix", ""),
            "allowed": allowed,
        }
        if note:
            finding["note"] = note
        findings.append(finding)

    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings


# --- CLI -------------------------------------------------------------------------

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_CANNOT_CHECK = 2


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _check_file(path: Path) -> dict:
    cfg = _load_config()
    language = language_for_suffix(path, cfg)
    if language is None:
        return {
            "file": path.as_posix(),
            "language": None,
            "status": "skipped",
            "reason": "아는 언어의 확장자가 아니라 검사하지 않았다",
            "findings": [],
        }

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # 읽지 못한 파일은 절대 통과가 아니다(CLAUDE.md 원칙 7).
        return {
            "file": path.as_posix(),
            "language": language,
            "status": "error",
            "reason": f"파일을 읽지 못했다: {exc}",
            "findings": [],
        }

    findings = check_source(str(path), text, language=language)
    has_violation = any(not f["allowed"] for f in findings)
    return {
        "file": path.as_posix(),
        "language": language,
        "status": "violation" if has_violation else "pass",
        "findings": findings,
    }


def build_report(paths: list[Path]) -> dict:
    """파일 목록을 검사해 리포트를 낸다. CLI 와 `scripts/check_changed.py` 가 함께 쓴다.

    후자는 이 함수를 서브프로세스 없이 직접 부른다 — `checker.cli.main` 이 엔진
    (`checker.engine`)을 서브프로세스가 아니라 직접 부르는 것과 같은 이유다. 훅만
    `uvx` 로 이 모듈을 받아 부르는 것은 설치본에 엔진이 따라오지 않기 때문이고
    (모듈 docstring, #12 와 같은 사정), Actions 는 이 저장소를 그대로 체크아웃해
    쓰므로 그럴 필요가 없다.
    """
    files = [_check_file(p) for p in paths]

    checked = sum(1 for f in files if f["status"] in ("pass", "violation"))
    violation_files = sum(1 for f in files if f["status"] == "violation")
    allowed_findings = sum(
        1 for f in files for finding in f["findings"] if finding["allowed"]
    )
    skipped = sum(1 for f in files if f["status"] == "skipped")

    return {
        "summary": {
            "checked": checked,
            "violations": violation_files,
            "allowed": allowed_findings,
            "skipped": skipped,
        },
        "files": files,
    }


def exit_code_for(report: dict) -> int:
    """리포트에서 종료코드를 정한다. 읽지 못한 파일이 하나라도 있으면 절대 통과가 아니다."""
    files = report.get("files", [])
    if any(f.get("status") == "error" for f in files):
        return EXIT_CANNOT_CHECK
    if any(f.get("status") == "violation" for f in files):
        return EXIT_VIOLATION
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="python -m checker.code_rules",
        description="공통 개발 규칙 CR-001(한글 이름), CR-002(반복문 안 DB 조회)를 검사한다.",
    )
    parser.add_argument("--json", action="store_true", help="이 도구는 항상 JSON 을 낸다. 명시하고 싶을 때 쓴다")
    parser.add_argument("paths", nargs="+", type=Path, help="검사할 소스 파일")
    args = parser.parse_args(argv)

    report = build_report(args.paths)

    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
