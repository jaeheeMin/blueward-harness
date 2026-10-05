"""MCP ADT 서버(테넌트)별 쓰기 차단과 데이터 추출 되묻기의 판정 로직(#148).

`mcp_source_guard.py` 가 부르는 순수 함수 모음이다 — 파일 읽기와 입출력은
호출부가 하고, 여기서는 "이 호출을 막을지, 되물을지, 그냥 둘지" 만 정한다.
그래서 훅을 띄우지 않고도 단위 테스트할 수 있다.

**입력 파일.** Project Repository 의 `env/adt-tiers.yaml`. 읽는 키:

    system: Z5U                       # 선택, 안내문에만 쓴다
    servers:
      <MCP 서버 이름>:
        client: "100"                 # 선택, 안내문에만 쓴다
        role: customizing             # 선택, 안내문에만 쓴다
        writes_allowed: false         # 필수, true/false
        data_access: ask              # 선택, ask(기본) 또는 deny — deny 면 data_tools 를 막는다
    write_tools: [setObjectSource, ...]   # 필수, 쓰기로 취급하는 도구 이름
    data_tools: [tableContents, runQuery] # 선택, 되묻는 도구 이름

그 밖의 키(host, proxy_port, tier, login_skill 등)는 사람이 보는 정보라 무시한다.
`atc_variant`(서버 항목의 선택 키)는 `/harness:atc` 스킬이 파일을 직접 읽어 쓰므로
이 해석기는 읽지도 거절하지도 않는다(#179).
어떤 도구가 쓰기인지는 코드에 박지 않고 이 파일에서 읽는다(CLAUDE.md 원칙 2).
파일이 없을 때 데이터 도구를 알아야 하므로 기본 `data_tools` 만
`mcp_default_tools.json` 에 둔다.

**YAML 해석기.** 훅은 `uv run --no-project` 로 돌아 PyYAML 이 없다(`mcp_source_guard.py`
의 stdlib 만 쓰는 이유와 같다). 이 파일이 쓰는 모양(맵, 맵 안의 맵, 글자 목록,
`[a, b]` 한 줄 목록, 주석, 따옴표 글자)만 읽는 작은 해석기를 둔다. 이 밖의 YAML
문법(앵커, 여러 줄 글자, 탭 들여쓰기 등)을 만나면 짐작하지 않고 `TiersError` 를
낸다 — 호출부는 그것을 검사 불능으로 거절한다(CLAUDE.md 원칙 7).

**도구 이름.** `mcp__<서버>__<도구>`. 서버 이름에 `__` 가 들어갈 수 있는지 문서에
근거가 없으므로 안전하게 나눈다 — 도구 이름은 ADT MCP 에서 모두 camelCase 라 `__`
가 없으니 "첫 `mcp__` 뒤부터 마지막 `__` 앞까지" 를 서버로, 마지막 `__` 뒤를 도구로
본다. 서버 이름에 `__` 가 있어도 맞게 나뉜다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

TIERS_RELATIVE_PATH = Path("env") / "adt-tiers.yaml"
DATA_ACCESS_VALUES = ("ask", "deny")
_DEFAULT_TOOLS_PATH = Path(__file__).with_name("mcp_default_tools.json")


class TiersError(Exception):
    """`env/adt-tiers.yaml` 을 읽거나 해석하지 못했다(검사 불능)."""


@dataclass(frozen=True)
class Tiers:
    system: str | None
    # 서버 이름 -> 표시 정보. writes_allowed 는 bool.
    servers: dict[str, dict] = field(default_factory=dict)
    write_tools: frozenset[str] = frozenset()
    data_tools: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Decision:
    kind: str  # "pass" | "deny" | "ask"
    reason: str = ""


PASS = Decision("pass")


# --- 도구 이름 ----------------------------------------------------------------

def split_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """`mcp__<서버>__<도구>` 를 (서버, 도구)로 나눈다. 이 모양이 아니면 None."""
    if not isinstance(name, str) or not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__"):]
    server, sep, tool = rest.rpartition("__")
    if not sep or not server or not tool:
        return None
    return server, tool


# --- 기본 목록 ----------------------------------------------------------------

def load_default_data_tools(path: Path = _DEFAULT_TOOLS_PATH) -> frozenset[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tools = raw.get("data_tools")
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise TiersError(f"{path.name} 의 data_tools 가 글자 목록이 아니다")
    return frozenset(tools)


# --- 파일 찾기 ----------------------------------------------------------------

def find_tiers_file(cwd: str | None) -> Path | None:
    """작업 폴더에서 위로 올라가며 `env/adt-tiers.yaml` 을 찾는다. 없으면 None.

    `.git` 이 있는 폴더(저장소 루트, 연결된 worktree 포함)까지만 올라간다 — 저장소
    밖의 우연한 파일을 기준으로 삼지 않는다.
    """
    start = Path(cwd) if cwd else Path(os.getcwd())
    try:
        start = start.resolve()
    except OSError:
        pass
    for parent in [start, *start.parents]:
        candidate = parent / TIERS_RELATIVE_PATH
        if candidate.is_file():
            return candidate
        if (parent / ".git").exists():
            return None
    return None


# --- 작은 YAML 해석기 ---------------------------------------------------------

def _strip_comment(line: str) -> str:
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _scalar(text: str, lineno: int):
    text = text.strip()
    if text == "":
        return None
    if text[0] in "\"'":
        if len(text) < 2 or text[-1] != text[0]:
            raise TiersError(f"{lineno}번째 줄: 따옴표가 닫히지 않았다")
        return text[1:-1]
    if text[0] == "[":
        if text[-1] != "]":
            raise TiersError(f"{lineno}번째 줄: [ 목록이 한 줄에서 닫히지 않았다")
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part, lineno) for part in inner.split(",")]
    if text[0] in "{&*!|>":
        raise TiersError(f"{lineno}번째 줄: 지원하지 않는 YAML 문법이다: {text[:20]}")
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def parse_simple_yaml(text: str) -> dict:
    """이 모듈이 아는 YAML 부분집합을 dict 로 읽는다. 모르는 문법은 `TiersError`."""
    lines: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        body = _strip_comment(raw).rstrip()
        if not body.strip():
            continue
        leading = body[: len(body) - len(body.lstrip())]
        if "\t" in leading:
            raise TiersError(f"{lineno}번째 줄: 들여쓰기에 탭을 쓸 수 없다")
        lines.append((len(leading), body.strip(), lineno))

    if not lines:
        raise TiersError("내용이 비어 있다(주석뿐이다)")

    def parse_block(i: int, indent: int):
        if lines[i][1].startswith("- ") or lines[i][1] == "-":
            return parse_list(i, indent)
        return parse_map(i, indent)

    def parse_list(i: int, indent: int):
        items = []
        while i < len(lines) and lines[i][0] == indent:
            content, lineno = lines[i][1], lines[i][2]
            if not (content.startswith("- ") or content == "-"):
                raise TiersError(f"{lineno}번째 줄: 목록 항목이 아니다: {content[:30]}")
            item = content[1:].strip()
            if ":" in item and not item.startswith(("\"", "'")):
                raise TiersError(f"{lineno}번째 줄: 목록 안의 맵은 지원하지 않는다")
            items.append(_scalar(item, lineno))
            i += 1
        if i < len(lines) and lines[i][0] > indent:
            raise TiersError(f"{lines[i][2]}번째 줄: 들여쓰기가 맞지 않는다")
        return items, i

    def parse_map(i: int, indent: int):
        result: dict = {}
        while i < len(lines) and lines[i][0] == indent:
            content, lineno = lines[i][1], lines[i][2]
            if content.startswith("- "):
                raise TiersError(f"{lineno}번째 줄: 맵 안에 목록 항목이 섞였다")
            m = re.match(r"""^("[^"]*"|'[^']*'|[^:\s][^:]*?)\s*:(?:\s+(.*))?$""", content)
            if not m:
                raise TiersError(f"{lineno}번째 줄: `키: 값` 모양이 아니다: {content[:30]}")
            key = m.group(1).strip()
            if key[0] in "\"'":
                key = key[1:-1]
            if key in result:
                raise TiersError(f"{lineno}번째 줄: 키가 겹친다: {key}")
            rest = m.group(2)
            i += 1
            if rest is None or rest.strip() == "":
                if i < len(lines) and lines[i][0] > indent:
                    result[key], i = parse_block(i, lines[i][0])
                elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                    # `key:` 아래에 같은 들여쓰기로 이어지는 목록(YAML 이 허용하는 모양)
                    result[key], i = parse_list(i, indent)
                else:
                    result[key] = None
            else:
                result[key] = _scalar(rest, lineno)
        if i < len(lines) and lines[i][0] > indent:
            raise TiersError(f"{lines[i][2]}번째 줄: 들여쓰기가 맞지 않는다")
        return result, i

    value, end = parse_block(0, lines[0][0])
    if end != len(lines):
        raise TiersError(f"{lines[end][2]}번째 줄: 최상위 들여쓰기가 맞지 않는다")
    if not isinstance(value, dict):
        raise TiersError("최상위가 `키: 값` 맵이 아니다")
    return value


# --- 파일 -> Tiers ------------------------------------------------------------

def _string_list(value, name: str, required: bool) -> frozenset[str]:
    if value is None:
        if required:
            raise TiersError(f"필수 키 {name} 가 없거나 비어 있다")
        return frozenset()
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise TiersError(f"{name} 는 도구 이름 글자의 목록이어야 한다")
    return frozenset(value)


def parse_tiers(text: str) -> Tiers:
    data = parse_simple_yaml(text)

    servers_raw = data.get("servers")
    if not isinstance(servers_raw, dict) or not servers_raw:
        raise TiersError("필수 키 servers 가 없거나 서버가 하나도 없다")
    servers: dict[str, dict] = {}
    for name, info in servers_raw.items():
        if not isinstance(info, dict):
            raise TiersError(f"servers.{name} 가 맵이 아니다")
        allowed = info.get("writes_allowed")
        if not isinstance(allowed, bool):
            raise TiersError(f"servers.{name}.writes_allowed 가 없거나 true/false 가 아니다")
        data_access = info["data_access"] if "data_access" in info else "ask"
        if data_access not in DATA_ACCESS_VALUES:  # 글자가 아닌 값(None, bool 등)도 여기서 걸린다
            raise TiersError(
                f"servers.{name}.data_access 가 ask 또는 deny 가 아니다: {data_access!r}"
            )
        servers[name] = {
            "writes_allowed": allowed,
            "data_access": data_access,
            "client": None if info.get("client") is None else str(info["client"]),
            "role": None if info.get("role") is None else str(info["role"]),
        }

    write_tools = _string_list(data.get("write_tools"), "write_tools", required=True)
    data_tools = _string_list(data.get("data_tools"), "data_tools", required=False)
    system = data.get("system")
    return Tiers(
        system=None if system is None else str(system),
        servers=servers,
        write_tools=write_tools,
        data_tools=data_tools,
    )


def load_tiers(path: Path) -> Tiers:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise TiersError(f"파일을 읽지 못했다: {exc}") from exc
    return parse_tiers(text)


# --- 판정 ---------------------------------------------------------------------

# `SELECT *`, `SELECT SINGLE *`, 새 문법 `FROM t FIELDS *` 를 모두 CR-003 대상으로
# 본다. 엔진(`checker/code_rules.py`)의 CR-003 도 `FIELDS` 뒤 필드 목록을 보므로 같다.
_SELECT_STAR_RE = re.compile(
    r"\bSELECT\s+(?:(?:SINGLE|DISTINCT)\s+)*\*|\bFIELDS\s+\*", re.IGNORECASE
)


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)


def has_select_star(tool_input: object) -> bool:
    """입력의 어느 글자 값에든 SELECT * 가 있으면 True. 쿼리 칸 이름(`sqlQuery` 등)에
    기대지 않고 모든 글자 값을 본다 — 칸 이름이 바뀌어도 놓치지 않는다."""
    return any(_SELECT_STAR_RE.search(s) for s in _iter_strings(tool_input))


def _server_label(name: str, info: dict) -> str:
    extra = " ".join(x for x in (info.get("client"), info.get("role")) if x)
    return f"{name}({extra})" if extra else name


def decide(
    tool_name: str,
    tool_input: object,
    tiers: Tiers | None,
    default_data_tools: frozenset[str],
) -> Decision:
    """테넌트 관점의 판정. `pass` 면 호출부가 기존 코드 규칙(CR) 검사로 넘어간다.

    `tiers` 가 None 이면 `env/adt-tiers.yaml` 이 없는 것이다 — 쓰기 도구는 건드리지
    않고(`pass`), 기본 데이터 도구만 되묻는다(2026-10-04 결정, #148).
    `data_access: deny` 인 서버의 데이터 도구는 거절한다. 키가 없거나 `ask` 면, 그리고
    `servers` 에 없는 서버면 되묻는다(모르는 서버는 쓰기와 달리 바꾸지 않았다, #161).
    파일이 있으나 깨진 경우는 호출부가 `TiersError` 로 처리한다(여기까지 오지 않는다).
    """
    parsed = split_mcp_tool_name(tool_name)
    if parsed is None:
        return PASS
    server, tool = parsed

    data_tools = default_data_tools if tiers is None else (default_data_tools | tiers.data_tools)

    if tiers is not None and tool in tiers.write_tools:
        info = tiers.servers.get(server)
        if info is None:
            known = ", ".join(sorted(tiers.servers)) or "(없음)"
            return Decision("deny", (
                f"harness: MCP 서버 {server!r} 는 env/adt-tiers.yaml 의 servers 에 없어 쓰기 "
                f"도구 {tool} 를 허용할 수 없습니다. 모르는 서버는 쓰기 허용으로 보지 않습니다.\n"
                f"파일에 있는 서버: {known}\n\n"
                + _next_for_writable(tiers, extra=(
                    f"{server!r} 가 맞는 서버라면 env/adt-tiers.yaml 의 servers 에 추가하고 "
                    "writes_allowed 를 정하십시오(사람이 할 일)."
                ))
            ))
        if info["writes_allowed"] is not True:
            return Decision("deny", (
                f"harness: MCP 서버 {_server_label(server, info)} 는 writes_allowed: false 라 "
                f"쓰기 도구 {tool} 를 부를 수 없습니다(env/adt-tiers.yaml).\n\n"
                + _next_for_writable(tiers, exclude=server)
            ))
        return PASS

    if tool in data_tools:
        info = None if tiers is None else tiers.servers.get(server)
        if info is not None and info["data_access"] == "deny":
            return Decision("deny", (
                f"harness: MCP 서버 {_server_label(server, info)} 는 data_access: deny 라 데이터 "
                f"도구 {tool} 를 부를 수 없습니다(env/adt-tiers.yaml). 이 서버의 테이블 데이터는 "
                "대화에 싣지 않습니다.\n\n"
                "다음: 멈추고 사람에게 알리십시오. 이 서버에서 데이터를 꺼내야 하는지, 필요하면 "
                "data_access 를 바꿀지는 사람이 정합니다(사람이 할 일). 사람이 정하기 전에는 다른 "
                "서버로 옮겨 다시 시도하지 마십시오."
            ))
        reason = (
            f"harness: {server} 의 {tool} 는 SAP 테이블 데이터를 꺼내 대화에 싣습니다. 개인정보나 "
            "기밀이 섞일 수 있으니 필요한 테이블·필드·행 수만 가져오는지 확인하고 허용하십시오."
        )
        if has_select_star(tool_input):
            reason += (
                "\n쿼리에 SELECT *(또는 FIELDS *)가 있습니다 — 공통 개발 규칙 CR-003 은 필요한 "
                "필드만 조회하라고 합니다. 필드를 줄여 다시 요청하게 하려면 거절하십시오."
            )
        if tiers is None:
            reason += (
                "\n(env/adt-tiers.yaml 이 없어 테넌트별 쓰기 차단은 꺼져 있고, 데이터 도구는 "
                "기본 목록으로 되묻습니다.)"
            )
        return Decision("ask", reason)

    return PASS


def _next_for_writable(tiers: Tiers, exclude: str | None = None, extra: str | None = None) -> str:
    writable = [
        _server_label(n, i) for n, i in tiers.servers.items()
        if i["writes_allowed"] is True and n != exclude
    ]
    if writable:
        text = (
            "다음: 멈추고 사람에게 알리십시오. 다른 서버(쓰기 허용: " + ", ".join(writable)
            + ")에서 해야 하는 작업인지는 사람이 정합니다(사람이 할 일). 사람이 정하기 전에는 "
            "다른 서버로 옮겨 다시 시도하지 마십시오."
        )
    else:
        text = (
            "다음: 멈추고 사람에게 알리십시오. env/adt-tiers.yaml 에 writes_allowed: true 인 "
            "서버가 없습니다. 쓰기가 필요하면 사람이 파일을 확인해 개발 서버의 writes_allowed 를 "
            "정하십시오(사람이 할 일)."
        )
    if extra:
        text += "\n" + extra
    return text


def load_error_reason(path: Path, exc: Exception) -> str:
    return (
        "harness: env/adt-tiers.yaml 을 읽거나 해석하지 못해 이 MCP 호출이 어느 테넌트에 "
        "쓰는지 확인할 수 없었습니다. 확인되지 않는 상태로 통과시키지 않습니다.\n"
        f"파일: {path}\n사유: {exc}\n\n"
        "다음: 사람이 env/adt-tiers.yaml 을 고치십시오 — 필수 키는 servers(서버마다 "
        "writes_allowed: true/false)와 write_tools(도구 이름 목록)입니다. data_access 를 적었다면 ask 또는 deny 여야 합니다. 예시는 harness "
        "플러그인 README 의 \"테넌트별 쓰기 차단\" 절에 있습니다."
    )
