"""CAP·UI5 개발 표준(`conventions/cap-ui5.md`) 기계 검사(#944).

고객사마다 개발 표준이 다르므로 켤지 말지와 규칙별 심각도는 코드가 아니라 데이터다(CLAUDE.md 원칙 2). 엔진 쪽
`checker/ui5_checks.yaml` 이 규칙 목록(id·제목·기본 심각도·고치는 법)을 갖고, Project Repository 의
`conventions/cap-ui5.yaml` 이 켜고(파일이 있을 때만 켜진다) 규칙별 심각도·예외 경로를 정한다. 이 모듈이 읽어 판정한다.
UI5 코드를 쓰기 직전 훅(`pre_write_guard.py`)과 PR 검사(`scripts/check_changed.py`)가 부른다.

파일 모양(예시는 `plugins/harness/conventions/cap-ui5.example.yaml`):

    규칙: {UI5-105: off, UI5-104: violation}    # 규칙별 심각도 violation | warn | off (없으면 엔진 기본값)
    예외: [app/legacyApp/**]                    # 이 경로의 파일은 검사하지 않는다(사람이 결정해 넣는다)
    i18n_제외_키: [appTitle, appDescription]    # UI5-108 이 보지 않는 키

대상 파일(이름 끝으로만 판정한다. abapGit 메타 `.clas.xml` 같은 것은 절대 걸리지 않는다):
`**/webapp/**/*.js`(UI5 JS, CAP `srv/` JS 는 대상이 아니다), `*.view.xml`, `*.fragment.xml`, `**/i18n/*.properties`.

**추가·변경된 줄만 본다.** 기존 위반 때문에 파일을 고치는 일이 막히면 안 된다. PR 은 `git diff -U0` 의 `@@ +N,M` 줄 집합으로,
훅은 디스크 내용과 저장할 내용의 차이 줄로 finding 을 거른다. 새 파일은 전체 줄이 대상이다. 줄 집합을 못 얻으면(diff 를 못
읽음) 파일 전체 검사로 넘어가지 않고 검사 불능이다.

JS 규칙은 `checker.code_rules._mask_c_like` 로 주석·문자열·템플릿·정규식을 길이를 지키며 지운 글에서 찾는다.
i18n 규칙처럼 문자열 안을 봐야 하는 규칙은 지우기 전 원문을 쓴다.

종료코드: 0 통과(또는 검사 안 함, 경고만 있어도 0), 1 위반, 2 검사 불능(설정 오류·파일을 읽지 못함·XML 이 깨짐·diff 를 읽지 못함).
"""
from __future__ import annotations

import argparse
import bisect
import functools
import json
import re
import sys
from pathlib import Path
from xml.parsers import expat

import yaml

from checker.code_rules import _line_starts, _mask_c_like, _offset_to_linecol
from checker.risk_gate import added_lines

CONFIG_RELATIVE_PATH = "conventions/cap-ui5.yaml"

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_CANNOT_CHECK = 2

LEVEL_VIOLATION = "violation"
LEVEL_WARN = "warn"
LEVEL_OFF = "off"
_CONFIG_LEVELS = (LEVEL_VIOLATION, LEVEL_WARN, LEVEL_OFF)

_TOP_KEYS = {"규칙", "예외", "i18n_제외_키"}
DEFAULT_I18N_EXCLUDED = ("appTitle", "appDescription", "flpTitle", "flpSubtitle")

# 코드가 구현한 규칙. ui5_checks.yaml 과 하나라도 어긋나면 엔진 설정 오류다.
IMPLEMENTED_RULES = frozenset(
    {
        "UI5-001", "UI5-002", "UI5-003", "UI5-004", "UI5-101", "UI5-102", "UI5-103",
        "UI5-104", "UI5-105", "UI5-106", "UI5-108", "UI5-109", "UI5-110",
    }
)


class Ui5ConfigError(RuntimeError):
    """설정(프로젝트의 `cap-ui5.yaml` 또는 엔진의 `ui5_checks.yaml`)을 읽을 수 없다. 통과도 위반도 아닌 검사 불능이다."""


class Ui5CannotCheck(RuntimeError):
    """파일 하나를 검사할 수 없다(읽지 못함, XML 이 깨짐). 결과는 통과도 위반도 아닌 검사 불능이다."""


# --- 엔진 규칙 목록 ---------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def load_engine_rules() -> dict[str, dict]:
    path = Path(__file__).with_name("ui5_checks.yaml")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Ui5ConfigError(f"ui5_checks.yaml 을 읽을 수 없다: {exc}") from exc
    except yaml.YAMLError as exc:
        raise Ui5ConfigError(f"ui5_checks.yaml 이 올바른 YAML 이 아니다: {exc}") from exc
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, dict) or not rules:
        raise Ui5ConfigError("ui5_checks.yaml 의 rules 가 없다")
    for rule_id, info in rules.items():
        if not isinstance(info, dict) or info.get("level") not in (LEVEL_VIOLATION, LEVEL_WARN):
            raise Ui5ConfigError(f"ui5_checks.yaml 의 {rule_id}.level 은 violation 또는 warn 이어야 한다")
        if info.get("targets") not in ("js", "xml", "properties") or not info.get("title"):
            raise Ui5ConfigError(f"ui5_checks.yaml 의 {rule_id} 에 title 이나 targets 가 올바르지 않다")
    if set(rules) != IMPLEMENTED_RULES:
        diff = sorted(set(rules) ^ IMPLEMENTED_RULES)
        raise Ui5ConfigError(f"ui5_checks.yaml 의 규칙 목록이 코드와 다르다: {', '.join(diff)}")
    return rules


# --- 프로젝트 설정 ---------------------------------------------------------------


class Ui5Config:
    def __init__(self, path: Path, levels: dict[str, str], exceptions: list[str], i18n_excluded: frozenset[str]):
        self.path = path
        self.levels = levels  # 규칙 id → 최종 심각도(off 포함)
        self.exceptions = exceptions
        self.i18n_excluded = i18n_excluded

    @property
    def root(self) -> Path:
        """설정 파일이 든 저장소 루트(`<루트>/conventions/cap-ui5.yaml`)."""
        return self.path.parent.parent


def find_config(start: Path) -> Path | None:
    """`start` 에서 위로 올라가며 `conventions/cap-ui5.yaml` 을 찾는다. `.git` 이 있는 폴더까지만 본다."""
    try:
        start = start.resolve()
    except OSError:
        pass
    for parent in [start, *start.parents]:
        candidate = parent / CONFIG_RELATIVE_PATH
        if candidate.is_file():
            return candidate
        if (parent / ".git").exists():
            return None
    return None


def parse_config(text: str, path: Path) -> Ui5Config:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 이 올바른 YAML 이 아니다: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 의 최상위는 키와 값의 목록이어야 한다")
    unknown = sorted(str(k) for k in set(data) - _TOP_KEYS)
    if unknown:
        raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 에 알 수 없는 키가 있다: {', '.join(unknown)}")

    engine = load_engine_rules()
    levels = {rule_id: info["level"] for rule_id, info in engine.items()}
    overrides = data.get("규칙") or {}
    if not isinstance(overrides, dict):
        raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 의 규칙은 규칙 id 와 심각도의 목록이어야 한다")
    for raw_id, value in overrides.items():
        rule_id = str(raw_id).strip().upper()
        if rule_id not in engine:
            raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 의 규칙 '{raw_id}' 는 알 수 없는 규칙 id 다")
        if value is False:  # YAML 은 따옴표 없는 off 를 거짓으로 읽는다
            value = LEVEL_OFF
        if value not in _CONFIG_LEVELS:
            raise Ui5ConfigError(
                f"{CONFIG_RELATIVE_PATH} 의 규칙 {rule_id} 값은 {' · '.join(_CONFIG_LEVELS)} 중 하나여야 한다(지금 값: {value!r})"
            )
        levels[rule_id] = value

    exceptions = data.get("예외") or []
    if not isinstance(exceptions, list) or not all(isinstance(e, str) and e.strip() for e in exceptions):
        raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 의 예외는 경로 문자열 목록이어야 한다")

    if "i18n_제외_키" in data and data["i18n_제외_키"] is not None:
        excluded = data["i18n_제외_키"]
        if not isinstance(excluded, list) or not all(isinstance(k, str) and k.strip() for k in excluded):
            raise Ui5ConfigError(f"{CONFIG_RELATIVE_PATH} 의 i18n_제외_키는 키 문자열 목록이어야 한다")
    else:
        excluded = list(DEFAULT_I18N_EXCLUDED)
    return Ui5Config(path, levels, [e.strip() for e in exceptions], frozenset(k.strip() for k in excluded))


def load_config(path: Path) -> Ui5Config:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Ui5ConfigError(f"{path} 을 읽지 못했다: {exc}") from exc
    return parse_config(text, path)


# --- 대상 판정 -------------------------------------------------------------------


def target_kind(path: str) -> str | None:
    """경로가 검사 대상이면 종류(js·xml·properties), 아니면 None. 이름 끝으로만 판정한다."""
    posix = path.replace("\\", "/")
    lowered = posix.lower()
    parts = lowered.split("/")
    name = parts[-1]
    if name.endswith(".view.xml") or name.endswith(".fragment.xml"):
        return "xml"
    if name.endswith(".properties") and len(parts) >= 2 and parts[-2] == "i18n":
        return "properties"
    if name.endswith(".js") and not name.endswith(".min.js") and "webapp" in parts[:-1]:
        return "js"
    return None


def _glob_regex(glob: str) -> re.Pattern[str]:
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _relative_to_root(path: str, root: Path) -> str:
    posix = path.replace("\\", "/")
    p = Path(path)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            return posix
    return posix[2:] if posix.startswith("./") else posix


def is_excepted(path: str, cfg: Ui5Config) -> bool:
    rel = _relative_to_root(path, cfg.root)
    return any(_glob_regex(g).match(rel) for g in cfg.exceptions)


# --- JS 규칙 ---------------------------------------------------------------------

_CONSOLE_RE = re.compile(r"(?<![\w$.])(?:window\s*\.\s*)?console\s*\.\s*([A-Za-z_]\w*)")
_LOOSE_EQ_RE = re.compile(r"(?<![=!<>+\-*/%&|^])([=!])=(?!=)")
_DOM_RE = re.compile(r"\bdocument\s*\.\s*(getElementById|querySelectorAll|querySelector)\b")
_DOM_JQUERY_WRAP_RE = re.compile(r"(?:jQuery|\$)\s*\(\s*(?:window\s*\.\s*)?$")
_PRIVATE_MEMBER_RE = re.compile(r"(?<![\w$.\)\]])([A-Za-z_$][\w$]*)\s*\.\s*(_{1,2}[A-Za-z]\w*)")
_OWN_PRIVATE_DEFS = [
    re.compile(r"(?<![\w$.])(_{1,2}[A-Za-z]\w*)\s*:"),
    re.compile(r"\b(?:this|that|self|me)\s*\.\s*(_{1,2}[A-Za-z]\w*)\s*="),
    re.compile(r"\.\s*prototype\s*\.\s*(_{1,2}[A-Za-z]\w*)\s*="),
    re.compile(r"(?<![\w$.])(_{1,2}[A-Za-z]\w*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>)"),
    re.compile(r"(?m)^[ \t]*(?:async[ \t]+)?(_{1,2}[A-Za-z]\w*)[ \t]*\([^)]*\)[ \t]*\{"),
]
_PRIVATE_RECEIVERS = frozenset({"this", "that", "self", "me"})
_DECL_RE = re.compile(r"\b(var|let|const)\s+([A-Za-z_$][\w$]*)")
_FUNCTION_INIT_RE = re.compile(r"\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)")
_PREFIX_NAME_RE = re.compile(r"^(?:\$.*|(?:fn|[soimadfbrvp])(?:[A-Z0-9_$].*)?)$")
_CONSTANT_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_NAME_OK = frozenset({"that", "self"})


def _js_findings(text: str) -> list[tuple[str, int, int, str]]:
    masked = _mask_c_like(text)
    starts = _line_starts(text)
    out: list[tuple[str, int, int, str]] = []

    def add(rule: str, offset: int, detail: str = "") -> None:
        line, col = _offset_to_linecol(offset, starts)
        out.append((rule, line, col, detail))

    for m in _CONSOLE_RE.finditer(masked):
        add("UI5-001", m.start(), f"console.{m.group(1)}")
    for m in _LOOSE_EQ_RE.finditer(masked):
        add("UI5-002", m.start(), f"{m.group(1)}=")
    for m in _DOM_RE.finditer(masked):
        if _DOM_JQUERY_WRAP_RE.search(masked[max(0, m.start() - 40):m.start()]):
            continue
        add("UI5-103", m.start(), f"document.{m.group(1)}")

    own = {name for rx in _OWN_PRIVATE_DEFS for name in rx.findall(masked)}
    for m in _PRIVATE_MEMBER_RE.finditer(masked):
        receiver, member = m.group(1), m.group(2)
        if receiver in _PRIVATE_RECEIVERS or member in own:
            continue
        add("UI5-104", m.start(), f"{receiver}.{member}")

    for m in _DECL_RE.finditer(masked):
        name = m.group(2)
        bare = name.lstrip("_")
        if (
            len(bare) <= 1
            or name in _NAME_OK
            or _CONSTANT_RE.match(bare)
            or bare[0].isupper()  # 모듈·클래스 이름(UpperCamel)
            or _PREFIX_NAME_RE.match(bare)
            or (name.startswith("_") and _FUNCTION_INIT_RE.match(masked, m.end()))  # 내부 함수는 `_` 로 시작한다
            or _FUNCTION_INIT_RE.match(masked, m.end())
        ):
            continue
        add("UI5-106", m.start(2), name)

    out.extend(_indent_findings(masked, text))
    return out


def _indent_findings(masked: str, text: str) -> list[tuple[str, int, int, str]]:
    """UI5-105. 줄 첫 글자가 공백인 코드 줄. 주석·문자열 안은 마스킹으로 비어 있어 건너뛴다."""
    out = []
    for no, (mline, tline) in enumerate(zip(masked.split("\n"), text.split("\n")), 1):
        if mline.strip() and tline.startswith(" "):
            out.append(("UI5-105", no, 1, ""))
    return out


def _file_indent_is_space(masked: str, text: str, exclude: set[int] | None) -> bool:
    """파일의 기존 줄(`exclude` 밖) 대부분이 공백 들여쓰기인가. 그러면 UI5-105 는 파일 안 기존 방식을 따른다."""
    if exclude is None:
        return False  # 전체 줄이 새 줄이다(새 파일). 따를 기존 방식이 없다
    space = tab = 0
    for no, (mline, tline) in enumerate(zip(masked.split("\n"), text.split("\n")), 1):
        if exclude is not None and no in exclude:
            continue
        if not mline.strip() or not tline or tline[0] not in " \t":
            continue
        if tline[0] == " ":
            space += 1
        else:
            tab += 1
    return space > tab


# --- XML 규칙 --------------------------------------------------------------------

_HANGUL_RE = re.compile(r"[가-힣]")
_ICON_URL_OK_RE = re.compile(r"^(?:sap-icon://|https?:|data:|/|\./|\.\./)|\.(?:png|svg|jpe?g|gif|ico|webp)(?:[?#].*)?$", re.I)
_XHTML_PREFIXES = ("html:", "xhtml:")


def _attribute_positions(data: bytes, start: int) -> tuple[bytes, dict[str, int], int]:
    """`start` 에서 시작하는 시작 태그의 원문 바이트, 속성 이름 → 태그 안 위치, 태그 끝 위치(`>` 다음)."""
    i, quote, n = start, None, len(data)
    while i < n:
        c = data[i:i + 1]
        if quote:
            if c == quote:
                quote = None
        elif c in (b'"', b"'"):
            quote = c
        elif c == b">":
            break
        i += 1
    tag = data[start:i + 1]
    positions: dict[str, int] = {}
    for m in re.finditer(rb"""(?<=[\s"'])([^\s=/<>"']+)\s*=\s*(?:"[^"]*"|'[^']*')""", tag):
        positions.setdefault(m.group(1).decode("utf-8", "replace"), m.start())
    return tag, positions, i + 1


def _xml_findings(text: str) -> list[tuple[str, int, int, str]]:
    data = text.lstrip("﻿").encode("utf-8")
    nl_starts = [0] + [i + 1 for i, b in enumerate(data) if b == 0x0A]

    def line_col(byte_offset: int) -> tuple[int, int]:
        idx = bisect.bisect_right(nl_starts, byte_offset) - 1
        return idx + 1, len(data[nl_starts[idx]:byte_offset].decode("utf-8", "replace")) + 1

    out: list[tuple[str, int, int, str]] = []
    parser = expat.ParserCreate("utf-8")

    def start_element(name: str, attrs: dict[str, str]) -> None:
        if name.lower().startswith(_XHTML_PREFIXES):
            return
        start = parser.CurrentByteIndex
        tag, positions, _ = _attribute_positions(data, start)

        def attr_line_col(attr: str) -> tuple[int, int]:
            return line_col(start + positions.get(attr, 0))

        local = name.split(":")[-1]
        for attr, value in attrs.items():
            if attr == "id" and "-" in value and "{" not in value:
                line, col = attr_line_col(attr)
                out.append(("UI5-003", line, col, f'id="{value}"'))
            if value and not value.lstrip().startswith("{") and _HANGUL_RE.search(value):
                line, col = attr_line_col(attr)
                out.append(("UI5-004", line, col, f'{attr}="{value}"'))
            if value.strip() and "{" not in value and (attr == "icon" or (attr == "src" and local == "Icon")):
                if not _ICON_URL_OK_RE.search(value.strip()):
                    line, col = attr_line_col(attr)
                    out.append(("UI5-101", line, col, f'{attr}="{value}"'))
        m = re.search(rb"[^\s/<][ \t]+/>$", tag)
        if m:
            line, col = line_col(start + m.start() + 1)
            out.append(("UI5-102", line, col, ""))

    parser.StartElementHandler = start_element
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise Ui5CannotCheck(f"XML 을 읽지 못했다({expat.ErrorString(exc.code)}, {exc.lineno}줄)") from exc
    return out


# --- properties 규칙 -------------------------------------------------------------

_I18N_KEY_RE = re.compile(r"^[a-z][A-Za-z0-9_]*\.[a-z][A-Za-z0-9_]*\.[a-z][A-Za-z0-9_]*$")
_TYPE_COMMENT_RE = re.compile(r"^#(?:X|Y)[A-Z]{3}")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_BAD_ENDING_RE = re.compile(r"(?:세요|주시오)\.$")


def _logical_entries(lines: list[str]) -> list[tuple[int, str, str]]:
    """properties 의 (첫 줄 번호, 키, 값). 이어 쓰기(`\\`)를 합치고 주석·빈 줄은 뺀다."""
    entries: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.lstrip()
        if not stripped or stripped[0] in "#!":
            i += 1
            continue
        first = i + 1
        logical = stripped
        while _ends_with_continuation(logical) and i + 1 < len(lines):
            logical = logical[:-1] + lines[i + 1].lstrip()
            i += 1
        i += 1
        m = re.match(r"((?:\\.|[^=:\s\\])*)\s*[=:]?\s*(.*)$", logical, re.S)
        if m:
            entries.append((first, m.group(1), m.group(2)))
    return entries


def _ends_with_continuation(line: str) -> bool:
    count = len(line) - len(line.rstrip("\\"))
    return count % 2 == 1


def _decode_value(value: str) -> str:
    return _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), value)


def _properties_findings(text: str, excluded_keys: frozenset[str]) -> list[tuple[str, int, int, str]]:
    lines = text.lstrip("﻿").split("\n")
    lines = [ln.rstrip("\r") for ln in lines]
    out: list[tuple[str, int, int, str]] = []
    for line_no, key, value in _logical_entries(lines):
        if key not in excluded_keys and not _I18N_KEY_RE.match(key):
            out.append(("UI5-108", line_no, 1, key))
        above = lines[line_no - 2].strip() if line_no >= 2 else ""
        if not _TYPE_COMMENT_RE.match(above):
            out.append(("UI5-109", line_no, 1, key))
        decoded = _decode_value(value).strip()
        if _HANGUL_RE.search(decoded) and _BAD_ENDING_RE.search(decoded):
            out.append(("UI5-110", line_no, 1, key))
    return out


# --- 파일 검사 -------------------------------------------------------------------


def parse_line_spec(spec: str) -> set[int]:
    """`1,2,5-9` 꼴의 줄 번호 목록."""
    lines: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo, hi = part.split("-", 1)
                lines.update(range(int(lo), int(hi) + 1))
            else:
                lines.add(int(part))
        except ValueError as exc:
            raise ValueError(f"줄 번호 목록 '{spec}' 을 해석하지 못했다") from exc
    return lines


def check_text(kind: str, text: str, display: str, cfg: Ui5Config, lines: set[int] | None) -> list[dict]:
    """파일 하나의 finding. `lines` 가 None 이면 전체 줄, 아니면 그 줄 번호의 것만."""
    engine = load_engine_rules()
    if kind == "js":
        raw = _js_findings(text)
        if _file_indent_is_space(_mask_c_like(text), text, lines):
            raw = [r for r in raw if r[0] != "UI5-105"]
    elif kind == "xml":
        raw = _xml_findings(text)
    else:
        raw = _properties_findings(text, cfg.i18n_excluded)

    findings = []
    seen = set()
    for rule, line, col, detail in raw:
        level = cfg.levels.get(rule, engine[rule]["level"])
        if level == LEVEL_OFF:
            continue
        if lines is not None and line not in lines:
            continue
        key = (rule, line, col, detail)
        if key in seen:
            continue
        seen.add(key)
        title = engine[rule]["title"]
        findings.append(
            {
                "rule": rule,
                "level": level,
                "file": display,
                "line": line,
                "col": col,
                "message": f"{title} — {detail}" if detail else title,
                "fix": engine[rule]["fix"],
            }
        )
    # 들여쓰기는 줄마다 내면 파일 하나가 수십 건이 된다. 첫 줄 하나에 건수를 담는다.
    indent = [f for f in findings if f["rule"] == "UI5-105"]
    if len(indent) > 1:
        first = indent[0]
        first["message"] = f"{engine['UI5-105']['title']} — 공백으로 시작하는 줄 {len(indent)}개"
        findings = [f for f in findings if f["rule"] != "UI5-105"] + [first]
    findings.sort(key=lambda f: (f["line"], f["col"], f["rule"]))
    return findings


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Ui5CannotCheck(f"파일을 읽지 못했다({exc})") from exc


def build_result(findings: list[dict], unchecked: list[dict], checked: int, config: Path | None) -> dict:
    violations = [f for f in findings if f["level"] == LEVEL_VIOLATION]
    if unchecked:
        status = "cannot_check"
    elif violations:
        status = "violation"
    else:
        status = "pass"
    result = {
        "status": status,
        "checked": checked,
        "findings": findings,
        "unchecked": unchecked,
        "config": str(config) if config else None,
    }
    if unchecked:
        result["message"] = "; ".join(f"{u['file']}: {u['reason']}" for u in unchecked)
    return result


def diff_added_lines(diff_text: str) -> dict[str, set[int]]:
    """`git diff -U0 --no-renames` 출력에서 파일별로 추가된 줄 번호의 집합. 파서는 `risk_gate.added_lines` 를 쓴다."""
    files: list[dict] = []
    current: dict | None = None
    in_hunk = False
    for raw in diff_text.split("\n"):
        raw = raw.rstrip("\r")
        if raw.startswith("diff --git "):
            current = None
            in_hunk = False
            continue
        if not in_hunk and raw.startswith("+++ "):
            name = raw[4:].split("\t")[0]
            if name == "/dev/null":
                current = None
            else:
                if name.startswith('"') and name.endswith('"'):
                    name = name[1:-1]
                if name.startswith("b/"):
                    name = name[2:]
                current = {"filename": name, "patch": ""}
                files.append(current)
            continue
        if raw.startswith("@@ "):
            in_hunk = True
        if current is not None and in_hunk:
            current["patch"] += raw + "\n"
    result: dict[str, set[int]] = {}
    for name, lineno, _content in added_lines(files):
        result.setdefault(name, set()).add(lineno)
    for entry in files:
        result.setdefault(entry["filename"], set())
    return result


def evaluate_files(
    paths: list[str],
    root: Path,
    added: dict[str, set[int]] | None = None,
    config_path: Path | None = None,
) -> dict:
    """`root` 에서 설정을 찾아 파일들을 검사한다. 설정이 없으면 `not_applicable`, 못 읽으면 `cannot_check`.

    `added` 는 파일별 검사할 줄 번호다(없으면 전체 줄). 목록에 있는데 `added` 에 없는 파일은 바뀐 줄이 없는 것이다.
    """
    config_path = config_path or find_config(root)
    if config_path is None:
        return {"status": "not_applicable"}
    try:
        cfg = load_config(config_path)
    except Ui5ConfigError as exc:
        return {"status": "cannot_check", "message": str(exc), "findings": [], "unchecked": [], "checked": 0}
    try:
        load_engine_rules()
    except Ui5ConfigError as exc:
        return {"status": "cannot_check", "message": str(exc), "findings": [], "unchecked": [], "checked": 0}

    findings: list[dict] = []
    unchecked: list[dict] = []
    checked = 0
    for raw in paths:
        posix = raw.replace("\\", "/")
        kind = target_kind(posix)
        if kind is None or is_excepted(posix, cfg):
            continue
        lines = None
        if added is not None:
            lines = added.get(posix)
            if lines is None:
                continue
        path = Path(raw)
        if not path.is_absolute():
            path = root / raw
        try:
            text = _read_text(path)
            findings.extend(check_text(kind, text, posix, cfg, lines))
            checked += 1
        except Ui5CannotCheck as exc:
            unchecked.append({"file": posix, "reason": str(exc)})
    return build_result(findings, unchecked, checked, config_path)


def exit_code_for(result: dict) -> int:
    status = result.get("status")
    if status == "cannot_check":
        return EXIT_CANNOT_CHECK
    if status == "violation":
        return EXIT_VIOLATION
    return EXIT_PASS


# --- CLI -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ui5_rules", description="CAP·UI5 개발 표준(conventions/cap-ui5.yaml)을 검사한다.")
    sub = p.add_subparsers(dest="command", required=True)
    many = sub.add_parser("files", help="경로 목록 파일(한 줄에 하나)을 검사한다")
    many.add_argument("listing", help="경로 목록 파일")
    many.add_argument("--diff", help="git diff -U0 --no-renames 출력 파일. 있으면 추가된 줄만 본다")
    many.add_argument("--root", default=".", help="설정을 찾기 시작할 폴더이자 목록 경로의 기준")
    many.add_argument("--json", action="store_true", help="JSON 으로 출력한다(기본값과 같다)")
    one = sub.add_parser("check", help="파일 하나를 검사한다")
    one.add_argument("file")
    one.add_argument("--lines", help="이 줄만 본다(1,2,5-9). 없으면 전체")
    one.add_argument("--as", dest="display", help="이 파일의 원래 경로(대상 판정·예외·표시에 쓴다). 훅이 임시 파일을 검사할 때 쓴다")
    one.add_argument("--root", help="설정을 찾기 시작할 폴더. 기본은 원래 경로의 폴더")
    one.add_argument("--json", action="store_true", help="JSON 으로 출력한다(기본값과 같다)")
    return p


def _cannot(message: str) -> dict:
    return {"status": "cannot_check", "message": message, "findings": [], "unchecked": [], "checked": 0}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)

    if args.command == "files":
        try:
            names = [ln.strip() for ln in Path(args.listing).read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, UnicodeDecodeError) as exc:
            result = _cannot(f"목록 {args.listing} 를 읽지 못했다: {exc}")
        else:
            added = None
            diff_error = None
            if args.diff:
                try:
                    added = diff_added_lines(Path(args.diff).read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError) as exc:
                    diff_error = f"diff {args.diff} 를 읽지 못했다: {exc}"
            result = _cannot(diff_error) if diff_error else evaluate_files(names, Path(args.root), added)
    else:
        display = (args.display or args.file).replace("\\", "/")
        root = Path(args.root) if args.root else Path(display).parent
        config_path = find_config(root)
        kind = target_kind(display)
        if config_path is None or kind is None:
            result = {"status": "not_applicable"}
        else:
            try:
                lines = parse_line_spec(args.lines) if args.lines is not None else None
            except ValueError as exc:
                result = _cannot(str(exc))
            else:
                try:
                    cfg = load_config(config_path)
                    load_engine_rules()
                except Ui5ConfigError as exc:
                    result = _cannot(str(exc))
                else:
                    if is_excepted(display, cfg):
                        result = build_result([], [], 0, config_path)
                    else:
                        try:
                            text = _read_text(Path(args.file))
                            result = build_result(check_text(kind, text, display, cfg, lines), [], 1, config_path)
                        except Ui5CannotCheck as exc:
                            result = build_result([], [{"file": display, "reason": str(exc)}], 0, config_path)
    print(json.dumps(result, ensure_ascii=False))
    return exit_code_for(result)


if __name__ == "__main__":
    raise SystemExit(main())
