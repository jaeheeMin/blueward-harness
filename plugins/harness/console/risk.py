"""도구 호출이 묻지 않고 허용해도 되는 일인지 가른다(#649). 순수 함수 — 파일 목록(safe_tools.json) 외에 읽는 것이 없다.

classify(tool_name, tool_input, cwd) -> (판정, 사유)
  safe          확실히 안전하다고 아는 일(읽기, 작업 폴더 안 고치기, git add/commit 등)
  irreversible  되돌릴 수 없거나 밖으로 나가는 일(지우기, 올리기, 설치, 작업 폴더 밖 쓰기, SAP 쓰기)
  unknown       목록에 없거나 해석하지 못한 것. 허용으로 뭉개지 않고 사람에게 묻는다(CLAUDE.md 7).
원칙: 애매하면 unknown. safe 명령은 옵션 허용 목록 방식이라 목록에 없는 옵션이 하나라도 있으면 unknown 이다.
셸 명령은 ; && || | 와 줄바꿈으로 조각을 나눠 조각이 모두 safe 일 때만 safe 다. 따옴표 밖의 $( ` 리디렉션은 해석하지 않고 unknown 이다.
heredoc 본문은 데이터라 건너뛴다. 줄바꿈은 ; 와 같아서 여러 줄 명령도 줄마다 판정하고(#971), 조각 하나라도 되돌릴 수 없으면 irreversible 이다.
읽기 명령의 경로 인자가 작업 폴더 밖이거나 비밀값 모양·읽기 보호(.git·.claude·.mcp.json·.env) 파일이면 unknown 이다. 경로 인자에 백슬래시가 있을 때만 그 때문에 판정하지 않는다.
하네스 자체 읽기 전용 스크립트·엔진 모듈(safe_tools.json 의 harness_scripts·harness_modules)은 설치본 폴더(read_roots) 아래일 때만 safe 다(#1018).
"""
from __future__ import annotations

import fnmatch
import importlib.util
import ipaddress
import json
import os
import posixpath
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path

import platform_compat

SAFE, IRREVERSIBLE, UNKNOWN = "safe", "irreversible", "unknown"
RULES_FILE = Path(__file__).with_name("safe_tools.json")
MAX_COMMAND = 2000  # heredoc 본문을 뺀 길이가 이보다 긴 명령은 해석하지 않는다
MAX_WITH_HEREDOC = 100_000  # heredoc 본문까지 센 길이 상한


def load_rules(path: Path = RULES_FILE) -> dict:
    """목록 파일을 읽는다. 못 읽으면 빈 목록이라 아무것도 safe 가 되지 않는다(전부 묻는다)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


RULES = load_rules()


def _names(key: str) -> frozenset[str]:
    v = RULES.get(key)
    return frozenset(x for x in v if isinstance(x, str)) if isinstance(v, list) else frozenset()


def _table(key: str) -> dict[str, frozenset[str]]:
    v = RULES.get(key)
    return {k: frozenset(x for x in subs if isinstance(x, str)) for k, subs in v.items() if isinstance(subs, list)} if isinstance(v, dict) else {}


def _regexes(items) -> list:
    return [re.compile(x) for x in items if isinstance(x, str)] if isinstance(items, list) else []


def _opts_ok(args: list[str], patterns: list) -> bool:
    """-로 시작하는 낱말이 모두 허용 목록(정규식 전체 일치)에 있어야 한다."""
    return all(any(p.fullmatch(a) for p in patterns) for a in args if a.startswith("-"))


# ---- 셸 조각 나누기 ----
_OPS = set(";&|")
Token = tuple  # (종류 "word" | "op" | "redir" | "heredoc", 글, 앞에 공백이 있었는가)


class _Word(str):
    """낱말 글. esc 는 따옴표 밖의 \\ 이스케이프로 글자가 바뀌었는가(그러면 글이 실제 경로와 다를 수 있어 경로로는 못 믿는다, #1018)."""
    esc = False


_HEREDOC_STOP = set(" \t\r\n;&|()<>")


def _heredoc_word(command: str, i: int):
    """<< 바로 뒤(i)의 끝 표시 낱말을 읽는다. (끝 표시, 따옴표로 막았는가, 다음 위치). 못 읽으면 끝 표시가 ""."""
    n = len(command)
    while i < n and command[i] in " \t":
        i += 1
    buf, quoted = [], False
    while i < n and command[i] not in _HEREDOC_STOP:
        c = command[i]
        if c in "'\"":
            j = command.find(c, i + 1)
            if j < 0:
                return "", True, n
            buf.append(command[i + 1:j]); quoted = True; i = j + 1; continue
        if c == "\\" and i + 1 < n:
            buf.append(command[i + 1]); quoted = True; i += 2; continue
        buf.append(c); i += 1
    return "".join(buf), quoted, i


def _heredoc_bodies(command: str, i: int, heredocs: list):
    """줄바꿈(i) 다음 줄부터 heredoc 본문을 차례로 건너뛴다(본문은 명령이 아니라 데이터다).
    (마지막 닫는 줄 끝의 줄바꿈 위치 또는 끝, 해석 못 할 사유). 끝 표시를 따옴표로 막지 않은 본문은 $ 와 백틱을 풀어 쓰니(명령 실행 포함) 사유가 된다."""
    n = len(command)
    nl = command.find("\n", i)
    pos = nl + 1 if nl >= 0 else n
    why, last = "", n
    for delim, strip_tabs, quoted in heredocs:
        start = pos
        while True:
            if pos >= n:
                return n, "heredoc 이 닫히지 않았어"
            end = command.find("\n", pos)
            line_end = end if end >= 0 else n
            line = command[pos:line_end].rstrip("\r")
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                body = command[start:pos]
                if not quoted and ("`" in body or "$" in body):
                    why = why or "heredoc 본문에 변수나 다른 명령 실행($ 또는 백틱)이 있어"
                last, pos = line_end, line_end + 1
                break
            pos = line_end + 1
    return last, why


def tokenize(command: str):
    """(토큰 목록, 해석 못 할 사유, heredoc 본문 글자 수). 따옴표 밖의 $( ·백틱·괄호가 있거나 따옴표가 안 닫히면 사유가 있다.
    따옴표 밖 줄바꿈은 bash 처럼 ; 와 같은 "\\n" 연산자다(#951). heredoc 본문은 건너뛰고, 줄마다 다른 조각으로 판정한다(#971).
    줄 잇기 \\·주석·heredoc·따옴표 안 줄바꿈은 따로 다룬다. 사유가 있어도 조각은 끝까지 나눠 두어 뒤 줄의 되돌릴 수 없는 명령을 가려낸다."""
    tokens: list[Token] = []
    cur: list[str] = []
    has_word = False
    spaced = True
    unsafe = ""
    heredocs: list = []  # 이 줄에서 열린 (끝 표시, <<- 인가, 따옴표로 막았나)
    body_chars = 0
    i, n = 0, len(command)

    esc_cur = [False]

    def flush():
        nonlocal cur, has_word
        if has_word:
            word = _Word("".join(cur))
            word.esc = esc_cur[0]
            tokens.append(("word", word, spaced_at[0]))
        cur, has_word = [], False
        esc_cur[0] = False

    spaced_at = [True]
    while i < n:
        c = command[i]
        if c in "\r\n":
            flush(); spaced = True
            if tokens and not (tokens[-1][0] == "op" and tokens[-1][1] not in "()"):  # a &&<줄바꿈> b 처럼 연산자 뒤 줄바꿈은 나누지 않는다
                tokens.append(("op", "\n", True))
            if heredocs:
                end, why = _heredoc_bodies(command, i, heredocs)
                body_chars += end - i
                heredocs = []
                unsafe = unsafe or why
                i = end; continue
            i += 1; continue
        if c in " \t":
            flush(); spaced = True; i += 1; continue
        if c == "#" and not has_word:  # 낱말 첫머리 # 는 줄 끝까지 주석이다. 그 안의 << 로 heredoc 을 열면 다음 줄 명령을 본문으로 건너뛴다(#955 점검)
            unsafe = unsafe or "주석(#)이 있어"
            j = command.find("\n", i)
            i = n if j < 0 else j; continue
        if not has_word:
            spaced_at[0] = spaced
        if c == "\\":
            if i + 1 < n and command[i + 1] not in "\r\n":
                cur.append(command[i + 1]); has_word = True; esc_cur[0] = True; i += 2; continue
            unsafe = unsafe or "줄을 잇는 \\ 가 있어"
            # 줄 잇기: \ 바로 뒤 \n 은 명령을 나누지 않는다(bash 는 두 줄을 한 명령으로 잇는다, #971).
            # \ 뒤가 \r\n 이면 bash 는 \r 만 이스케이프하고 \n 에서 끊으니 그대로 나눈다(#972 점검)
            i += 1
            if i < n and command[i] == "\n":
                i += 1
            continue
        if c == "'":
            j = command.find("'", i + 1)
            if j < 0:
                return tokens, "따옴표가 안 닫혔어", 0
            cur.append(command[i + 1:j]); has_word = True; spaced = False; i = j + 1; continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and command[j] != '"':
                if command[j] == "\\" and j + 1 < n and command[j + 1] in '"\\$`':
                    buf.append(command[j + 1]); j += 2; continue
                if command[j] == "`" or (command[j] == "$" and command.startswith("$(", j)):
                    unsafe = unsafe or "명령 안에서 다른 명령을 실행해($( 또는 백틱)"
                buf.append(command[j]); j += 1
            if j >= n:
                return tokens, "따옴표가 안 닫혔어", 0
            cur.append("".join(buf)); has_word = True; spaced = False; i = j + 1; continue
        if c == "`" or (c == "$" and command.startswith("$(", i)):
            unsafe = unsafe or "명령 안에서 다른 명령을 실행해($( 또는 백틱)"
            cur.append(c); has_word = True; spaced = False; i += 1; continue
        if c in "<>":
            if has_word and "".join(cur).isdigit() and not spaced:
                cur, has_word = [], False  # 2>&1 의 파일 번호
                esc_cur[0] = False
            else:
                flush()
            j = i
            while j < n and command[j] in "<>&":
                j += 1
            if command[i:j] == "<<":  # heredoc: 본문은 다음 줄부터, 끝 표시는 지금 읽어 둔다
                strip_tabs = j < n and command[j] == "-"
                delim, quoted, j = _heredoc_word(command, j + 1 if strip_tabs else j)
                if not delim:
                    unsafe = unsafe or "heredoc 끝 표시를 읽지 못했어"
                heredocs.append((delim, strip_tabs, quoted))
                tokens.append(("heredoc", "<<", spaced)); spaced = False; i = j; continue
            tokens.append(("redir", command[i:j], spaced)); spaced = False; i = j; continue
        if c in "();&|":
            flush()
            if c in "()":
                unsafe = unsafe or "괄호로 묶은 명령이야"
                tokens.append(("op", c, spaced)); i += 1; spaced = False; continue
            j = i
            while j < n and command[j] in _OPS:
                j += 1
            tokens.append(("op", command[i:j], spaced)); spaced = False; i = j; continue
        cur.append(c); has_word = True; spaced = False; i += 1
    flush()
    if heredocs:
        unsafe = unsafe or "heredoc 이 닫히지 않았어"
    if tokens and tokens[-1][:2] == ("op", "\n"):
        tokens.pop()  # 끝 줄바꿈은 명령을 나누지 않는다
    return tokens, unsafe, body_chars


def _segments(command: str):
    """(조각별 낱말 목록, 조각 사이 연산자 목록(ops[i] 는 i번 조각 뒤), 해석 못 할 사유, heredoc 본문 글자 수, > · >> 대상 목록)."""
    tokens, unsafe, body_chars = tokenize(command)
    segs: list[list[str]] = [[]]
    ops: list[str] = []
    reds: list[tuple[int, str]] = []  # (조각 번호, > · >> 의 대상). 대상이 작업 폴더 안인지는 classify_bash 가 그 조각의 기준 폴더로 본다(#1018)
    k = 0
    while k < len(tokens):
        kind, text, _ = tokens[k]
        if kind == "word":
            segs[-1].append(text)
        elif kind == "heredoc":
            pass  # 본문은 tokenize 가 건너뛰었다. 표준 입력으로 글을 넘길 뿐 파일을 읽거나 쓰지 않는다
        elif kind == "op":
            if text in ("(", ")"):
                pass
            else:
                if text == "&" or text.startswith("&") and text != "&&":
                    unsafe = unsafe or "백그라운드로 도는 명령이야"
                ops.append(text)
                segs.append([])
        else:  # 리디렉션: /dev/null 로 버리거나 출력을 합치는 것만 넘어간다(Windows 의 nul 은 POSIX 셸에서 파일을 만든다)
            nxt = tokens[k + 1] if k + 1 < len(tokens) else None
            if text.startswith(">&") and nxt and nxt[0] == "word" and nxt[1].isdigit():
                k += 1
            elif text in (">", ">>", "&>", "&>>") and nxt and nxt[0] == "word" and nxt[1] == "/dev/null":
                k += 1
            elif text in (">", ">>") and nxt and nxt[0] == "word" and _DEVICE_NAME.fullmatch(re.split(r"[\\/]", nxt[1])[-1]):
                # Windows 장치 이름(nul·con·aux·com1 …)은 OS 마다 뜻이 달라(POSIX 셸은 그 이름의 파일을 만든다) 어디서나 묻는다.
                unsafe = unsafe or "Windows 장치 이름(nul 등)으로 쓰는 리디렉션이야"
                k += 1
            elif text in (">", ">>") and nxt and nxt[0] == "word" and nxt[1]:
                reds.append((len(segs) - 1, nxt[1]))
                k += 1
            else:
                unsafe = unsafe or "파일로 쓰거나 읽는 리디렉션(> <)이 있어"
        k += 1
    if any(not s for s in segs):
        unsafe = unsafe or "빈 조각이 있어"
    return segs, ops, unsafe, body_chars, reds


# ---- 경로 ----
_WILD = re.compile(r"[*?\[]")
_DEVICE_NAME = re.compile(r"(?i)(nul|con|prn|aux|com[0-9]|lpt[0-9])(\.[^.]*)?")


def _is_abs(p: str) -> bool:
    return p.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:([\\/]|$)", p) is not None


def _is_secret(path: str) -> bool:
    """비밀값 모양 파일·폴더인가. 이름에 *? 가 있으면 그 글이 비밀값 이름과 맞을 수 있는지 본다."""
    norm = path.replace("\\", "/").lower()
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return False
    if any(p in _names("secret_dir_names") for p in parts):
        return True
    if any(norm.endswith(s.lower()) for s in _names("secret_path_suffixes")):
        return True
    name = parts[-1]
    if any(fnmatch.fnmatchcase(name, pat.lower()) for pat in _names("secret_name_patterns")):
        return True
    if _WILD.search(name):
        return any(fnmatch.fnmatchcase(s.lower(), name) for s in _names("secret_name_samples"))
    return False


def _read_protected(path: str) -> bool:
    """읽기에서도 막는 경로(safe_tools.json 의 read_protected): git·Claude 설정 폴더, .mcp.json, .env*. 쓰기 보호 목록 전체가 아니다(#1018)."""
    spec = RULES.get("read_protected")
    if not isinstance(spec, dict):
        return True  # 목록을 못 읽으면 읽기도 묻는다
    def names(key: str) -> frozenset[str]:
        v = spec.get(key)
        return frozenset(x.lower() for x in v if isinstance(x, str)) if isinstance(v, list) else frozenset()
    parts = [p.lower() for p in re.split(r"[\\/]", path) if p]
    if not parts:
        return False
    if any(p in names("dir_names") for p in parts):
        return True
    return parts[-1] in names("file_names") or any(parts[-1].startswith(pre) for pre in names("file_prefixes"))


def _name_blocked(token: str, read: bool = False) -> bool:
    """git 위치 인자(리비전 또는 경로, <rev>:<경로>)가 비밀값이거나 보호 경로를 가리키는가. 이름만 본다.
    read 이면 읽기 보호 목록만 본다(git 으로 읽을 때). add·commit 은 쓰기 보호 목록 전체를 본다."""
    cands = [token] + ([token.split(":", 1)[1]] if ":" in token else [])
    prot = _read_protected if read else _protected
    return any(c and (_is_secret(c) or prot(c)) for c in cands)


def _positionals(args: list[str], value_opts) -> list[str]:
    """옵션과, 옵션이 따로 받는 값을 뺀 위치 인자."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in value_opts:
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


_WINDOWS = os.name == "nt"
_GITBASH = re.compile(r"/([A-Za-z])(?:/(.*))?", re.DOTALL)


def _gitbash_path(p: str) -> str:
    """Windows 의 Git Bash 경로 /c/Users/x 를 C:/Users/x 로 바꾼다. 다른 글은 그대로(#1018)."""
    m = _GITBASH.fullmatch(p) if _WINDOWS else None
    return f"{m.group(1).upper()}:/{m.group(2) or ''}" if m else p


def _path_why(p: str, ctx: dict) -> str:
    """읽어도 되는 경로면 "", 아니면 판정 못 하는 실제 이유. 작업 폴더 안이고, 변수·~ 확장이 없고, 비밀값·읽기 보호 경로(.git·.claude·.env)가 아니어야 한다.
    심볼릭 링크는 실제 이름도 본다. ctx["bs"] 면(셸 명령) 경로에 \\ 가 있거나 따옴표 밖 \\ 이스케이프가 있었을 때 판정하지 않는다(#1018)."""
    base = ctx.get("base") or ""
    if not base:
        return "작업 폴더를 몰라서 판정 못 했어"
    if not p:
        return ""
    if ctx.get("bs") and (getattr(p, "esc", False) or "\\" in p):
        return "경로에 \\ 가 있어 어디를 읽는지 판정 못 했어"
    if "$" in p or "`" in p or re.search(r"%[^%\s]+%", p) or p.startswith("~"):
        return "변수나 ~ 를 쓴 경로라 어디를 읽는지 알 수 없어"
    p = _gitbash_path(p)
    full = p if _is_abs(p) else os.path.join(ctx["cur"][0], p)
    parts = re.split(r"[\\/]", full)
    wild = next((k for k, part in enumerate(parts) if _WILD.search(part)), None)
    if wild is not None:
        if ".." in parts[wild:]:
            return "와일드카드 뒤에 .. 가 있어 어디를 읽는지 알 수 없어"
        full = os.sep.join(parts[:wild]) or os.sep
        if _is_abs(p) and wild == 0:
            return "작업 폴더 밖 경로야"
    if not platform_compat.is_within(full, base):
        return "작업 폴더 밖 경로야"
    try:
        rel = os.path.relpath(os.path.realpath(full), os.path.realpath(base))
    except ValueError:
        return "작업 폴더 밖 경로야"
    if _is_secret(p) or _is_secret(rel):
        return "비밀값 모양 이름(.env·키·토큰 등)이라 열지 않아"
    if _read_protected(rel):
        return "git·Claude 설정 폴더나 .mcp.json·.env 라 열지 않아"
    return ""


def _write_target_why(p: str, ctx: dict) -> str:
    """> · >> 로 쓸 파일이 괜찮으면 "", 아니면 이유. 작업 폴더 안이고 변수·확장·와일드카드가 없고 쓰기 보호(훅·설정·지시)·비밀값 경로가 아니어야 한다.
    Write 도구로 폴더 안 파일을 쓰는 것과 같은 기준이다. 폴더 밖(/tmp 포함)은 쓰지 않는다(#1018)."""
    base = ctx.get("base") or ""
    if not base:
        return "작업 폴더를 몰라서 판정 못 했어"
    if getattr(p, "esc", False) or "\\" in p:
        return "경로에 \\ 가 있어 어디에 쓰는지 판정 못 했어"
    if "$" in p or "`" in p or "%" in p or p.startswith("~") or _WILD.search(p):
        return "변수·~·와일드카드를 쓴 경로라 어디에 쓰는지 알 수 없어"
    p = _gitbash_path(p)
    full = p if _is_abs(p) else os.path.join(ctx["cur"][0], p)
    if not platform_compat.is_within(full, base):
        return "작업 폴더 밖에 쓰려 해"
    try:
        rel = os.path.relpath(os.path.realpath(full), os.path.realpath(base))
    except ValueError:
        return "작업 폴더 밖에 쓰려 해"
    if _is_secret(p) or _is_secret(rel):
        return "비밀값 모양 이름의 파일이야"
    if _protected(rel):
        return "훅·설정·실행 설정 같은 파일이라 판정 못 했어"
    return ""


def _path_ok(p: str, ctx: dict) -> bool:
    return not _path_why(p, ctx)


# ---- git ----
def _base(word: str) -> str:
    name = re.split(r"[\\/]", word)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _clusters(args: list[str]) -> str:
    """-am 같은 짧은 옵션 묶음의 글자를 모은다(--긴옵션은 제외)."""
    return "".join(a[1:] for a in args if re.fullmatch(r"-[A-Za-z]+", a))


def _local_branch_exists(ctx, name: str) -> bool:
    """지금 기준 폴더가 속한 git 저장소에 로컬 브랜치 refs/heads/<name> 이 있는가(느슨한 ref 파일 또는 packed-refs). git 을 실행하지 않고 파일만 읽는다."""
    try:
        d = os.path.realpath((ctx or {}).get("cur", [""])[0] or "")
        for _ in range(40):
            dot = os.path.join(d, ".git")
            if os.path.isdir(dot):
                git_dir = dot
                break
            if os.path.isfile(dot):  # worktree: "gitdir: <경로>"
                line = Path(dot).read_text(encoding="utf-8", errors="replace").strip()
                if not line.startswith("gitdir:"):
                    return False
                git_dir = os.path.normpath(os.path.join(d, line[7:].strip()))
                break
            parent = os.path.dirname(d)
            if parent == d:
                return False
            d = parent
        else:
            return False
        common = git_dir
        cf = os.path.join(git_dir, "commondir")
        if os.path.isfile(cf):
            common = os.path.normpath(os.path.join(git_dir, Path(cf).read_text(encoding="utf-8", errors="replace").strip()))
        if os.path.isfile(os.path.join(common, "refs", "heads", *name.split("/"))):
            return True
        packed = os.path.join(common, "packed-refs")
        if os.path.isfile(packed):
            want = " refs/heads/" + name
            return any(line.rstrip("\r\n").endswith(want) and not line.startswith(("#", "^")) for line in Path(packed).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return False
    return False


def _git(args: list[str], ctx=None):
    verdict, why = _git_sub(args, ctx)
    lead, i = [], 0
    while i < len(args) and args[i].startswith("-"):
        step = 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        lead += args[i:i + step]
        i += step
    # git -c / -C / --exec-path 같은 전역 옵션은 다른 명령을 실행시키거나 다른 곳을 읽게 해서 읽기여도 판정 못 함으로 낮춘다
    if verdict == SAFE and any(a not in _names("git_global_options_ok") for a in lead):
        return UNKNOWN, "git 전역 옵션이 붙어 판정 못 했어"
    return verdict, why


def _git_sub(args: list[str], ctx=None):
    i, n = 0, len(args)
    while i < n and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= n:
        return UNKNOWN, "git 명령을 읽지 못했어"
    sub, rest = args[i], args[i + 1:]
    flags = _clusters(rest)
    reads = RULES.get("git_read_options")
    value_opts = _names("git_value_options")
    if isinstance(reads, dict) and sub in reads:
        if not _opts_ok(rest, _regexes(reads[sub])):
            return UNKNOWN, f"git {sub} 에 목록에 없는 옵션이 있어"
        if any(_name_blocked(a, read=True) for a in _positionals(rest, value_opts)):
            return UNKNOWN, "비밀값이나 읽기 보호 경로(.git·.claude·.env)를 가리키는 인자가 있어"
        return SAFE, "git 으로 상태를 읽기만 해"
    if sub == "worktree":  # 작업 사본 목록 보기만. add·remove·prune 은 목록에 없다(#1018)
        if rest[:1] == ["list"] and _opts_ok(rest[1:], _regexes(RULES.get("git_worktree_list_options"))) and len(rest) <= 2:
            return SAFE, "작업 사본(worktree) 목록을 읽기만 해"
        return UNKNOWN, "git worktree 는 list 만 판정해"  # #1018
    if sub == "pull":  # 하네스 절차(start 스킬)가 쓰는 pull · pull --rebase 도 되돌릴 수 있어 허용. 단독 merge·rebase 명령은 그대로 묻는다(#1018)
        if not _opts_ok(rest, _regexes(RULES.get("git_pull_options"))):
            return UNKNOWN, "git pull 에 목록에 없는 옵션이 있어"
        pos = [a for a in rest if not a.startswith("-")]
        if len(pos) > 2 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*" if k == 0 else r"[A-Za-z0-9][A-Za-z0-9._/-]*", a)
                               or ".." in a for k, a in enumerate(pos)):
            return UNKNOWN, "git pull 은 원격 이름과 브랜치 이름만 판정해"
        return SAFE, "원격의 새 커밋을 내 브랜치 뒤에 이어 붙이기만 해(합치기·rebase 없이)"
    if sub == "push":
        return IRREVERSIBLE, "GitHub에 코드를 올리려 해"
    if sub == "fetch":  # 원격 변경을 받아 원격 추적 브랜치만 바꾼다. 작업 사본·내 브랜치는 그대로(#953)
        if not _opts_ok(rest, _regexes(RULES.get("git_fetch_options"))):
            return UNKNOWN, "git fetch 에 목록에 없는 옵션이 있어"
        pos = [a for a in rest if not a.startswith("-")]
        # 원격 이름과 브랜치 이름만. 주소(://·@·경로)나 refspec(: +)은 내 브랜치를 바꾸거나 다른 곳에서 받을 수 있어 판정하지 않는다
        if len(pos) > 2 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*" if k == 0 else r"[A-Za-z0-9][A-Za-z0-9._/-]*", a)
                               or ".." in a for k, a in enumerate(pos)):
            return UNKNOWN, "git fetch 는 원격 이름과 브랜치 이름만 판정해"
        return SAFE, "원격 변경을 받아 오기만 해(작업 중인 파일은 안 바뀌어)"
    if sub == "clean":
        if "f" in flags or "--force" in rest:
            return IRREVERSIBLE, "추적하지 않는 파일을 지우려 해"
        if rest and all(a in ("-n", "--dry-run", "-d", "-nd", "-dn") for a in rest):
            return SAFE, "git 으로 지울 파일을 미리 보기만 해"
        return UNKNOWN, "git clean 은 -n · --dry-run · -d 만 있을 때만 판정해"
    if sub == "reset":
        return (IRREVERSIBLE, "저장하지 않은 변경을 버리려 해") if "--hard" in rest else (UNKNOWN, "git reset 은 판정 못 했어")
    if sub == "restore":
        return (UNKNOWN, "git restore --staged 는 판정 못 했어") if "--staged" in rest and "--worktree" not in rest else (IRREVERSIBLE, "저장하지 않은 변경을 버리려 해")
    if sub == "stash":
        what = rest[0] if rest else ""
        if what in ("drop", "clear"):
            return IRREVERSIBLE, "맡겨 둔 변경(stash)을 지우려 해"
        return (SAFE, "맡겨 둔 변경 목록을 읽기만 해") if what == "list" and len(rest) == 1 else (UNKNOWN, "git stash 는 판정 못 했어")
    if sub == "branch":
        if "-D" in rest or "-d" in rest or "--delete" in rest or any(re.fullmatch(r"-[A-Za-z]*[dD][A-Za-z]*", a) for a in rest):
            return IRREVERSIBLE, "브랜치를 지우려 해"
        readonly = {"-a", "-r", "-v", "-vv", "--list", "-l", "--show-current", "--merged", "--no-merged", "--contains", "--all", "--remotes", "--verbose"}
        return (SAFE, "브랜치 목록을 읽기만 해") if all(a in readonly or not a.startswith("-") and "--list" in rest for a in rest) else (UNKNOWN, "git branch 는 판정 못 했어")
    if sub in ("add", "commit"):
        if sub == "commit":  # 메시지를 표준 입력(heredoc)으로 받는 -F - 만 허용한다. -F <파일> 은 목록에 없어 판정 못 함(#951)
            rest = [a for k, a in enumerate(rest) if not (a in ("-F", "--file") and rest[k + 1:k + 2] == ["-"])
                    and not (a == "-" and k > 0 and rest[k - 1] in ("-F", "--file")) and a != "--file=-"]
        if not _opts_ok(rest, _regexes(RULES.get("git_add_options" if sub == "add" else "git_commit_options"))):
            return UNKNOWN, f"git {sub} 에 목록에 없는 옵션이 있어"
        if sub == "add" and any(_name_blocked(a) for a in _positionals(rest, value_opts)):
            return UNKNOWN, "비밀값이나 보호 경로를 git add 하려 해"
        if sub == "commit" and any(_name_blocked(a) for a in _positionals(rest, value_opts)):
            return UNKNOWN, "비밀값이나 보호 경로를 commit 하려 해"
        return SAFE, f"git {sub} 는 되돌릴 수 있어"
    if sub in ("checkout", "switch"):
        force = _names("git_force_flags")
        if any(a in force or a.startswith("--force") or (re.fullmatch(r"-[A-Za-z]{2,}", a) and set(a[1:]) & {"f", "m", "B", "C"}) for a in rest):
            return IRREVERSIBLE, "저장하지 않은 변경을 덮어쓸 수 있어"
        if sub == "checkout" and ("--" in rest or rest[:1] == ["."]):
            return IRREVERSIBLE, "저장하지 않은 변경을 버리려 해"
        new = "-b" if sub == "checkout" else "-c"
        if (rest[:1] == [new] and 2 <= len(rest) <= 3 and not any(a.startswith("-") for a in rest[1:])
                and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", a) and ".." not in a for a in rest[1:])):  # 이름은 브랜치 이름 모양만(시작점 하나까지)
            return SAFE, "새 브랜치를 만들 뿐이야"
        # 이미 있는 로컬 브랜치로 옮기기: 이름 하나이고 이 저장소의 refs/heads 에 있을 때만. 파일 이름이면 파일 되돌리기와 헷갈리므로 묻는다(#1018)
        if len(rest) == 1 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", rest[0]) and ".." not in rest[0] and _local_branch_exists(ctx, rest[0]):
            return SAFE, "있는 로컬 브랜치로 옮길 뿐이야(저장하지 않은 변경은 덮어쓰지 않아)"
        return UNKNOWN, f"git {sub} 는 판정 못 했어"
    return UNKNOWN, f"git {sub} 는 목록에 없어"


def _gh_flags_write(args: list[str]) -> bool:
    for k, a in enumerate(args):
        if a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith(("--field=", "--raw-field=", "--input=")):
            return True
        if a.startswith(("-f", "-F")) and not a.startswith("--"):
            return True
        method = ""
        if a in ("-X", "--method"):
            method = args[k + 1] if k + 1 < len(args) else "?"
        elif a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a.startswith("-X"):
            method = a[2:]
        if method and method.upper() != "GET":
            return True
    return False


def _gh(args: list[str]):
    pos = [a for a in args if not a.startswith("-")]
    if not pos:
        return UNKNOWN, "gh 명령을 읽지 못했어"
    area, sub = pos[0], pos[1] if len(pos) > 1 else ""
    if area == "api":
        return (IRREVERSIBLE, "GitHub 에 쓰는 API 호출이야") if _gh_flags_write(args) else (UNKNOWN, "gh api 읽기는 판정 못 했어")
    if sub in _table("gh_write").get(area, frozenset()):
        return IRREVERSIBLE, "GitHub 의 PR·이슈를 바꾸려 해" if area in ("pr", "issue") else "GitHub 에 쓰려 해"
    if sub in _table("gh_read").get(area, frozenset()):
        if any(a in _table("gh_read_blocked_flags").get(area, frozenset()) for a in args):
            return UNKNOWN, f"gh {area} {sub} 에 비밀값을 보이는 옵션이 있어"  # gh auth status --show-token
        return SAFE, "GitHub 정보를 읽기만 해"
    return UNKNOWN, f"gh {area} {sub} 는 목록에 없어".replace("  ", " ")


# ---- 읽기 명령 ----
# pytest 는 safe 가 아니다: 써 둔 시험 파일·conftest 로 임의 코드가 돈다(2차 검토).
def _read_command(cmd: str, args: list[str], ctx: dict):
    spec = RULES["bash_read"][cmd]
    if not isinstance(spec, dict) or not _opts_ok(args, _regexes(spec.get("options"))):
        return UNKNOWN, f"{cmd} 에 목록에 없거나 폴더를 통째로 읽는 옵션이 있어"
    vals = frozenset(x for x in spec.get("value_options", []) if isinstance(x, str))
    pos = _positionals(args, vals)  # 옵션이 따로 받는 값(-n 5, -g 글롭)은 경로가 아니다
    if spec.get("pattern_first") and "-e" not in args and pos:
        pos = pos[1:]  # 첫 낱말은 찾을 글이지 경로가 아니다
    if spec.get("needs_path") and not pos:
        return UNKNOWN, f"{cmd} 에 파일 경로가 없으면 폴더를 통째로 읽어"
    if isinstance(spec.get("max_positional"), int) and len(pos) > spec["max_positional"]:
        return UNKNOWN, f"{cmd} 의 마지막 낱말은 파일을 쓸 수 있어"
    if spec.get("paths"):
        for a in pos:
            why = _path_why(a, ctx)
            if why and not _harness_read_ok(a, ctx):
                return UNKNOWN, f"{cmd} 의 {a[:60]}: {why}"
    if spec.get("no_dir_args") and any(os.path.isdir(_gitbash_path(a) if _is_abs(_gitbash_path(a)) else os.path.join(ctx["cur"][0], a)) for a in pos):
        return UNKNOWN, f"{cmd} 가 폴더를 통째로 읽어"
    return SAFE, "읽기만 하는 명령이야"


def _sed(args: list[str], ctx: dict):
    script = RULES.get("sed_script")
    if args[:1] != ["-n"] or len(args) < 2 or not isinstance(script, str) or not re.fullmatch(script, args[1]):
        return UNKNOWN, "sed 는 줄 번호 출력(sed -n '3,5p')만 읽기로 봐"
    files = args[2:]
    if any(a.startswith("-") for a in files):
        return UNKNOWN, "sed 에 옵션이 더 있어"
    for a in files:
        why = _path_why(a, ctx)
        if why and not _harness_read_ok(a, ctx):
            return UNKNOWN, f"sed 의 {a[:60]}: {why}"
    return SAFE, "줄 번호로 읽기만 해"


def _cd(args: list[str], ctx: dict):
    """safe 는 맨 앞 `cd <폴더> && 명령` 꼴이고 그 폴더가 실제로 있는 작업 폴더 안일 때만이다."""
    if ctx.get("idx") != 0 or ctx.get("ops", [])[:1] != ["&&"]:
        return UNKNOWN, "cd 는 명령 맨 앞의 `cd 폴더 && 명령` 꼴만 판정해"
    if len(args) != 1 or args[0].startswith("-"):
        return UNKNOWN, "cd 에 옵션이 있거나 갈 곳이 하나가 아니야"
    why = _path_why(args[0], ctx)
    if why:
        return UNKNOWN, f"cd {args[0][:60]}: {why}"
    native = _gitbash_path(args[0])
    target = native if _is_abs(native) else os.path.join(ctx["cur"][0], native)
    if not os.path.isdir(target):
        return UNKNOWN, "cd 할 폴더가 실제로 없어"
    ctx["cur"][0] = os.path.normpath(target)
    return SAFE, "작업 폴더 안에서 옮겨 다닐 뿐이야"


# ---- 하네스 자체 스크립트·엔진(#1018) ----
# 스킬 문서에 나오는 읽기 전용 스크립트(uv run --no-project python <설치본>/hooks/x.py)와 엔진 모듈(uvx --from git+…@v숫자 python -P -m checker.x)만.
# 무엇을 어떤 인자로 허용하는지는 safe_tools.json 의 harness_scripts · harness_modules 에 있다. 쓰는 스크립트·모듈은 목록에 없다.
_ENGINE_ANY = re.compile(r'(?:^|&&|;|\n|\|\|)(\s*)([A-Za-z_][A-Za-z0-9_]*)="\$\(uv run --no-project python "([^"`$\n]+)"\)"')
_ENGINE_MARK = "@@engine@@"
_CD_LEAD = re.compile(r'\s*cd[ \t]+(?:"[^"`$\n]*"|[^\s;&|"\'`$<>()\\]+)[ \t]*&&[ \t]*\n?\s*')
_VAR_ASSIGN = re.compile(r'\s*([A-Za-z_][A-Za-z0-9_]*)="([^"\n]*)"[ \t]*(?:;|&&|\n)\s*')


def _assign_name_ok(name: str) -> bool:
    """셸 동작을 바꾸는 변수 이름(PATH·IFS·BASH_ENV·ENV·LD_*·PS4·CDPATH·HOME 등, safe_tools.json assign_blocked_*)은 쓰지 않는다."""
    return name not in _names("assign_blocked_names") and not any(name.startswith(p) for p in _names("assign_blocked_prefixes"))
_VERSION_DIR = re.compile(r"\d+\.\d+\.\d+")


def _norm_path(p: str) -> str:
    return posixpath.normpath(_gitbash_path(p).replace("\\", "/"))


def _harness_parts(path: str, ctx: dict):
    """path 가 하네스 설치본 폴더(ctx["harness_roots"]) 안이면 그 아래 조각들(설치본 판 폴더는 뗀다), 아니면 None.
    설치본(<설정 폴더>/plugins/cache/<마켓>/harness)이면 바로 아래에 <숫자.숫자.숫자> 판 폴더가 있어야 한다. .. 는 풀어서 본다."""
    if not path or any(c in path for c in "$`*?[%") or path.startswith("~") or getattr(path, "esc", False):
        return None
    norm = _norm_path(path)
    fold = (lambda s: s.lower()) if _WINDOWS else (lambda s: s)
    for root in ctx.get("harness_roots") or ():
        if not isinstance(root, str) or not root:
            continue
        rn = _norm_path(root).rstrip("/")
        if fold(norm) != fold(rn) and not fold(norm).startswith(fold(rn) + "/"):
            continue
        parts = [p for p in norm[len(rn):].split("/") if p]
        rp = rn.split("/")
        if len(rp) >= 3 and rp[-1].lower() == "harness" and rp[-3].lower() == "cache":  # 설치본
            if not parts or not _VERSION_DIR.fullmatch(parts[0]):
                continue
            parts = parts[1:]
        return parts
    return None


def _harness_read_ok(p: str, ctx: dict) -> bool:
    """Bash 읽기 명령의 경로가 하네스 설치본(판 폴더 포함) 안이면 True(#1018, Read 도구의 #953 과 같은 기준).
    설치본 폴더를 기준으로 읽기 보호·비밀값 검사를 그대로 하고, 링크를 푼 실제 경로도 그 폴더 안이어야 한다. 상대 경로·와일드카드·변수는 아니다."""
    if not p or not _is_abs(_gitbash_path(p)) or _harness_parts(p, ctx) is None:
        return False
    for root in ctx.get("harness_roots") or ():
        if root and not _path_why(p, {"base": root, "cur": [root], "bs": ctx.get("bs")}) and _real_within(_gitbash_path(p), root):
            return True
    return False


def _check_args(spec, args: list[str], ctx: dict):
    """스크립트·모듈 인자를 목록(spec)대로 확인한다. options 정규식에 없는 -옵션, 변수·명령 실행($ 백틱), 목록 밖 위치 인자, 경로 값이 작업 폴더 밖이면 unknown."""
    if not isinstance(spec, dict):
        return UNKNOWN, "목록에 없어"
    subs = spec.get("subcommands")
    if isinstance(subs, dict):
        if not args or args[0] not in subs:
            return UNKNOWN, "목록에 없는 하위 명령이야"
        spec, args = subs[args[0]], args[1:]
        if not isinstance(spec, dict):
            return UNKNOWN, "목록에 없어"
    options = _regexes(spec.get("options"))
    patterns = spec.get("value_patterns") if isinstance(spec.get("value_patterns"), dict) else {}
    path_opts = frozenset(x for x in spec.get("path_options", []) if isinstance(x, str))
    root_opts = frozenset(x for x in spec.get("root_options", []) if isinstance(x, str))
    vals = frozenset(x for x in spec.get("value_options", []) if isinstance(x, str)) | frozenset(patterns) | path_opts | root_opts
    pos: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if "$" in a or "`" in a:
            return UNKNOWN, "인자에 변수나 명령 실행($ 또는 백틱)이 있어"
        if a in vals:
            v = args[i + 1] if i + 1 < len(args) else ""
            if not v or v.startswith("-") or "$" in v or "`" in v:
                return UNKNOWN, f"{a} 의 값을 읽지 못했어"
            if a in patterns and not re.fullmatch(str(patterns[a]), v):
                return UNKNOWN, f"{a} 의 값이 목록의 모양이 아니야"
            if a in path_opts:
                why = _path_why(v, ctx)
                if why:
                    return UNKNOWN, f"{a} {v[:60]}: {why}"
            if a in root_opts and _harness_parts(v, ctx) != []:
                return UNKNOWN, f"{a} 가 하네스 설치본 폴더가 아니야"
            i += 2
            continue
        if a.startswith("-"):
            if not any(p.fullmatch(a) for p in options):
                return UNKNOWN, f"{a} 는 목록에 없는 옵션이야"
        else:
            pos.append(a)
        i += 1
    limit = spec.get("max_positional", 0)
    if not isinstance(limit, int) or len(pos) > limit:
        return UNKNOWN, "목록에 없는 위치 인자가 있어"
    if spec.get("paths"):
        for a in pos:
            why = _path_why(a, ctx)
            if why:
                return UNKNOWN, f"{a[:60]}: {why}"
    return SAFE, ""


def _uv(args: list[str], ctx: dict):
    if args[:3] != ["run", "--no-project", "python"] or len(args) < 4:
        return UNKNOWN, "uv 는 하네스 스크립트 실행(uv run --no-project python <설치본>/…)만 판정해"
    parts = _harness_parts(args[3], ctx)
    scripts = RULES.get("harness_scripts")
    rel = "/".join(parts) if parts else ""
    if not rel or not isinstance(scripts, dict) or rel not in scripts or not rel.endswith(".py"):
        return UNKNOWN, "하네스 설치본의 목록에 있는 스크립트가 아니라 판정 못 했어"
    verdict, why = _check_args(scripts[rel], args[4:], ctx)
    return (SAFE, f"하네스 {rel} 를 읽기만 하게 실행해") if verdict == SAFE else (verdict, f"{rel}: {why}")


def _uvx(args: list[str], ctx: dict):
    if len(args) < 6 or args[0] != "--from" or args[2:5] != ["python", "-P", "-m"]:
        return UNKNOWN, "uvx 는 하네스 엔진 실행(uvx --from <엔진 주소> python -P -m checker.<모듈>)만 판정해"
    src, mod = args[1], args[5]
    url = RULES.get("harness_engine_url")
    var = (ctx.get("engine_var") or "") if ctx.get("engine_seen") else ""
    if getattr(src, "esc", False) or not (var and src == "$" + var or isinstance(url, str) and re.fullmatch(url, src)):
        return UNKNOWN, "엔진 주소가 하네스 저장소의 v숫자 판도 아니고, engine_spec.py 로 정한 값도 아니야"
    m = re.fullmatch(r"checker\.([a-z_][a-z0-9_]*)", mod)
    modules = RULES.get("harness_modules")
    if not m or not isinstance(modules, dict) or m.group(1) not in modules:
        return UNKNOWN, f"{mod} 는 읽기만 하는 엔진 모듈 목록에 없어"
    verdict, why = _check_args(modules[m.group(1)], args[6:], ctx)
    return (SAFE, f"하네스 엔진의 {m.group(1)} 로 읽고 판정만 해") if verdict == SAFE else (verdict, f"{m.group(1)}: {why}")


def _engine_group_ok(segs: list[list[str]], ops: list[str], i: int, ctx: dict) -> bool:
    """`… || { echo "<글>" >&2; exit 1; }` 꼴(스킬 문서의 엔진 판 실패 꼬리)의 i번 조각(`{` 로 시작)이 그 꼴인가."""
    if i == 0 or i + 2 >= len(segs) or ops[i - 1] != "||" or ops[i] != ";" or ops[i + 1] != ";":
        return False
    if len(segs[i]) != 3 or segs[i][:2] != ["{", "echo"] or segs[i + 1] != ["exit", "1"] or segs[i + 2] != ["}"]:
        return False
    return _command(["echo", segs[i][2]], ctx)[0] == SAFE


def _segment(words: list[str], ctx: dict):
    var = ctx.get("engine_var")
    if var and list(words) == [f"{var}={_ENGINE_MARK}"]:
        if ctx.get("engine_seen"):
            return UNKNOWN, "엔진 판 대입이 두 번이야"
        ctx["engine_seen"] = True  # 이 조각 뒤에서만 "$변수" 를 인정한다
        return SAFE, "하네스 engine_spec.py 로 엔진 판을 정할 뿐이야"
    # 앞에 붙은 환경변수(A=1 cmd)는 떼고 본다. 지우기·올리기는 그대로 위험이고, 읽기는 판정 못 함으로 낮춘다.
    skipped = 0
    while skipped < len(words) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[skipped]):
        skipped += 1
    words = words[skipped:]
    if not words:
        return UNKNOWN, "환경변수만 있는 명령이야"
    verdict, why = _command(words, ctx)
    if skipped and verdict == SAFE:
        return UNKNOWN, "환경변수를 붙인 명령이라 판정 못 했어"
    return verdict, why


def _command(words: list[str], ctx: dict):
    cmd, args = _base(words[0]), words[1:]
    if cmd in _names("bash_delete_commands"):
        return IRREVERSIBLE, "파일이나 폴더를 지우려 해"
    if cmd in _names("bash_install_commands"):
        return IRREVERSIBLE, "프로그램을 설치하려 해"
    if cmd in ("npm", "pnpm", "yarn"):
        if args[:1] and args[0] in ("install", "i", "add", "uninstall", "remove", "update") or "-g" in args or "--global" in args:
            return IRREVERSIBLE, "프로그램을 설치하거나 지우려 해"
        return UNKNOWN, f"{cmd} 는 목록에 없어"
    if cmd in ("pip", "pip3") or (cmd in ("python", "python3", "py") and args[:3] == ["-m", "pip", "install"]):
        return (IRREVERSIBLE, "프로그램을 설치하려 해") if "install" in args or "uninstall" in args else (UNKNOWN, "pip 는 목록에 없어")
    if cmd == "uv":
        if args[:2] == ["tool", "install"] or args[:2] == ["pip", "install"]:
            return IRREVERSIBLE, "프로그램을 설치하려 해"
        return _uv(args, ctx)
    if cmd == "uvx":
        return _uvx(args, ctx)
    if cmd == "timeout":  # `timeout 30 명령` 은 뒤 명령을 그대로 판정한다(지우기·올리기면 그대로 위험)
        if len(args) >= 2 and re.fullmatch(r"\d{1,4}", args[0]):
            return _command(words[2:], ctx)
        return UNKNOWN, "timeout 은 `timeout 초 명령` 꼴만 판정해"
    if cmd == "[":
        var = ctx.get("engine_var")
        if var and ctx.get("engine_seen") and list(words) == ["[", "-n", "$" + var, "]"]:
            return SAFE, "엔진 판이 정해졌는지만 확인해"
        return UNKNOWN, "[ 는 엔진 판 확인(`[ -n \"$변수\" ]`)만 판정해"
    if cmd == "git":
        return _git(args, ctx)
    if cmd == "gh":
        return _gh(args)
    if cmd == "node":
        if len(args) == 2 and args[0] in ("--check", "-c") and not args[1].startswith("-") and _path_ok(args[1], ctx):
            return SAFE, "문법만 확인해"
        return UNKNOWN, "node 는 문법 확인(--check 파일)만 읽기로 봐"
    if cmd == "find" and "-delete" in args:
        return IRREVERSIBLE, "찾은 파일을 지우려 해"
    if cmd == "cd":
        return _cd(args, ctx)
    if cmd == "sed":
        return _sed(args, ctx)
    plain = RULES.get("bash_plain_commands")
    if isinstance(plain, dict) and cmd in plain and isinstance(plain[cmd], list):
        dashed = [a for a in args if a.startswith("-")]
        if cmd not in _names("bash_dash_text_commands") and not all(a in plain[cmd] for a in dashed):  # echo 는 -[neE]+ 말고는 --- 같은 낱말도 글이다(#1018)
            return UNKNOWN, f"{cmd} 에 목록에 없는 옵션이 있어"
        # echo "exit=$?" 처럼 직전 명령의 종료 코드 $? 만은 글이다. 다른 $ 확장·% ~ 백틱은 그대로 묻는다(#1018)
        if cmd in ("echo", "printf") and any(c in (a.replace("$?", "") if cmd == "echo" else a) for a in args for c in "$%~`"):
            return UNKNOWN, f"{cmd} 인자에 변수·~ 확장이나 형식 문자가 있어"
        return SAFE, "읽기만 하는 명령이야"
    reads = RULES.get("bash_read")
    if isinstance(reads, dict) and cmd in reads:
        return _read_command(cmd, args, ctx)
    return UNKNOWN, f"{words[0]} 는 목록에 없어"


def classify_bash(command: str, cwd: str = "", powershell: bool = False, harness_roots=()):
    if not command.strip():
        return UNKNOWN, "빈 명령이야"
    if len(command) > MAX_WITH_HEREDOC:
        return UNKNOWN, "명령이 너무 길어서 읽지 못했어"
    ctx = {"base": cwd, "cur": [cwd], "bs": True, "ops": [], "idx": 0, "harness_roots": tuple(harness_roots or ())}  # bs: 경로 인자에 \ 가 있으면 그 경로는 판정하지 않는다
    # 맨 앞의 e="$(uv run --no-project python "<설치본>/hooks/engine_spec.py")" 만 따로 읽어 표지로 바꾼다. 따옴표 안의 따옴표라 토크나이저가 못 읽는다(#1018)
    # 대입은 명령 맨 앞이거나 맨 앞 `cd <폴더> &&` 바로 다음 조각일 때만 받는다(한 번만). cd 자체는 아래에서 따로 판정한다(작업 폴더 안일 때만 safe)
    cdm = _CD_LEAD.match(command)
    head, rest = (command[:cdm.end()], command[cdm.end():]) if cdm else ("", command)
    # 엔진 대입(정확한 그 모양, 안쪽이 설치본 engine_spec.py)은 명령 안 어느 조각 위치든 한 번 받는다. "$변수" 는 그 조각 뒤에서만 인정한다(_segment)
    engine = None
    if not powershell and _ENGINE_MARK not in command:
        engine = next((m for m in _ENGINE_ANY.finditer(command) if _harness_parts(m.group(3), ctx) == ["hooks", "engine_spec.py"]), None)
    if engine:
        ctx["engine_var"] = engine.group(2)
        command = command[:engine.start(2)] + f"{engine.group(2)}={_ENGINE_MARK}" + command[engine.end():]
    else:
        # NAME="<글자 그대로의 하네스 설치본 경로>" 한 번만 풀어 뒤 조각의 $NAME 을 그 값으로 바꿔 판정한다(#1018).
        # 값이 설치본 밖이거나 변수·확장 글자가 있거나 위험한 이름(PATH 등)이면 그대로 둬서 unknown 이 된다. 바꾼 경로도 읽기 판정(설치본 안)으로만 safe 다
        var = _VAR_ASSIGN.match(rest)
        if var and not powershell and _assign_name_ok(var.group(1)) and not re.search(r"[$`%~*?\[]", var.group(2)) and _harness_parts(var.group(2), ctx) is not None:
            name, value = var.group(1), var.group(2)
            command = head + re.sub(r"\$\{" + name + r"\}|\$" + name + r"(?![A-Za-z0-9_])", lambda _m: value, rest[var.end():])
    segs, ops, unsafe, body_chars, reds = _segments(command)
    if len(command) - body_chars > MAX_COMMAND:  # heredoc 본문(PR·커밋 글)은 길이에 세지 않는다(#951)
        return UNKNOWN, "명령이 너무 길어서 읽지 못했어"
    ctx["ops"] = ops
    results = []
    done = 0  # 엔진 판 실패 꼬리 `|| { echo …; exit 1; }` 로 이미 판정한 조각 수
    for i, w in enumerate(segs):
        ctx["idx"] = i
        if done:
            done -= 1
            verdict, why = SAFE, "엔진 판을 못 정했을 때 멈추는 꼬리일 뿐이야"
        elif w[:1] == ["{"] and _engine_group_ok(segs, ops, i, ctx):
            done = 2
            verdict, why = SAFE, "엔진 판을 못 정했을 때 멈추는 꼬리일 뿐이야"
        else:
            verdict, why = _segment(w, ctx)
        if verdict == SAFE:  # > · >> 로 파일에 쓰는 조각: 대상이 작업 폴더 안이고 쓰기 보호·비밀값 경로가 아닐 때만(Write 도구와 같은 기준, #1018)
            for _, target in (r for r in reds if r[0] == i):
                bad = _write_target_why(target, ctx)
                if bad:
                    verdict, why = UNKNOWN, f"리디렉션 대상 {str(target)[:60]}: {bad}"
                    break
        results.append((verdict, why))
    for verdict, why in results:
        if verdict == IRREVERSIBLE:
            return verdict, why
    if powershell:
        return UNKNOWN, "PowerShell 명령은 지우기·올리기만 가려내고 나머지는 판정 못 해"
    if unsafe:
        return UNKNOWN, "해석하지 못했어 · " + unsafe
    if not results:
        return UNKNOWN, "명령을 읽지 못했어"
    for verdict, why in results:
        if verdict == UNKNOWN:
            return verdict, why
    return SAFE, results[0][1] if len(results) == 1 else "읽기·되돌릴 수 있는 명령만 이어 붙였어"


# ---- 파일 도구 ----
def _path_of(tool_input) -> str:
    if isinstance(tool_input, dict):
        for key in ("file_path", "notebook_path", "path"):
            v = tool_input.get(key)
            if isinstance(v, str) and v:
                return v
    return ""


def _resolve(path: str, cwd: str) -> str:
    return path if os.path.isabs(path) else os.path.join(cwd, path)


def _protected(path: str) -> bool:
    """고치면 다음 실행에 영향을 주는 파일(훅·설정·지시·실행 설정). 작업 폴더 기준 상대 경로를 본다. 대소문자는 무시한다."""
    parts = [p.lower() for p in re.split(r"[\\/]", path) if p]
    if any(p in _names("protected_dir_names") for p in parts):
        return True
    if not parts:
        return False
    for pair in RULES.get("protected_dir_pairs", []):  # 예: .github/workflows
        if isinstance(pair, list) and len(pair) == 2 and any(parts[k:k + 2] == [x.lower() for x in pair] for k in range(len(parts) - 1)):
            return True
    name = parts[-1]
    if name in _names("protected_file_names") or any(name.startswith(pre) for pre in _names("protected_file_prefixes")):
        return True
    if any(name.endswith(suf) for suf in _names("protected_file_suffixes")):
        return True
    hooks = RULES.get("protected_parent_suffixes")  # 예: **/hooks/*.py
    return isinstance(hooks, dict) and len(parts) >= 2 and isinstance(hooks.get(parts[-2]), list) and any(name.endswith(s) for s in hooks[parts[-2]])


def _is_scratchpad(real_path: str) -> bool:
    """Claude 세션의 임시 폴더: 이 PC 임시 폴더(tempfile.gettempdir 의 realpath) 아래 claude/<폴더>/<폴더>/scratchpad/<파일…> 구조.
    글자 조각이 아니라 실제 기준 경로와 깊이로 가린다. real_path 는 realpath 로 푼 경로를 넘긴다."""
    try:
        root = os.path.join(os.path.realpath(tempfile.gettempdir()), "claude")
        if not platform_compat.is_within(real_path, root):
            return False
        parts = [p for p in re.split(r"[\\/]", os.path.relpath(real_path, os.path.realpath(root))) if p]
    except (OSError, ValueError):
        return False
    return len(parts) >= 4 and os.path.normcase(parts[2]) == os.path.normcase("scratchpad") and ".." not in parts


def _public_web_url(url) -> bool:
    """WebFetch 주소가 공개 http(s) 호스트 이름인가. localhost·사설·링크로컬·IP 글자 그대로·.local 같은 안쪽 이름·점 없는 이름은 아니다."""
    if not isinstance(url, str):
        return False
    try:
        u = urllib.parse.urlsplit(url.strip())
        host = (u.hostname or "").rstrip(".").lower()
        u.port  # noqa: B018 - 이상한 포트는 여기서 예외
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not host or u.username is not None or u.password is not None:
        return False
    try:
        ipaddress.ip_address(host)
        return False  # IP 글자 그대로는 공개든 사설이든 묻는다
    except ValueError:
        pass
    if "." not in host or re.fullmatch(r"[0-9a-fx.]+", host):  # 점 없는 이름, 10진·16진으로 쓴 IP
        return False
    if host == "localhost" or any(host.endswith(s) for s in _names("webfetch_blocked_suffixes")):
        return False
    return True


_TIERS = {}


def _tier_servers(cwd: str) -> frozenset[str]:
    """cwd 의 env/adt-tiers.yaml 에 적힌 SAP MCP 서버 이름. 못 읽으면 빈 집합이다(그 서버들은 묻는다)."""
    if not cwd:
        return frozenset()
    try:
        mod = _TIERS.get("mod")
        if mod is None:
            path = Path(__file__).resolve().parents[1] / "hooks" / "adt_tiers.py"
            spec = importlib.util.spec_from_file_location("_harness_adt_tiers", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod  # dataclass 가 모듈 이름으로 자기 모듈을 찾는다
            spec.loader.exec_module(mod)
            _TIERS["mod"] = mod
        text = (Path(cwd) / "env" / "adt-tiers.yaml").read_text(encoding="utf-8")
        return frozenset(mod.parse_tiers(text).servers)
    except Exception:  # noqa: BLE001 - 어떤 이유로든 못 읽으면 서버를 모르는 것으로 본다
        return frozenset()


def _classify_mcp(name: str, cwd: str):
    parts = name.split("__")
    server, tool = (parts[1], parts[-1]) if len(parts) >= 3 else ("", parts[-1])
    if tool in _names("sap_write_tools"):
        return IRREVERSIBLE, "SAP 시스템에 쓰려 해"
    if tool in _names("sap_read_tools"):
        if server and server in _tier_servers(cwd):  # env/adt-tiers.yaml 에 정확히 같은 이름이 있을 때만
            return SAFE, "SAP 에서 읽기만 해"
        return UNKNOWN, f"{server or '이'} 서버는 env/adt-tiers.yaml 의 서버 목록에서 확인하지 못했어"
    return UNKNOWN, f"{tool} 는 목록에 없어"


def plan_dir_of(config_dir) -> str:
    """설정 폴더 아래 계획 파일 폴더(safe_tools.json 의 plan_dir_name). 이름이 비면 "" (계획 파일을 safe 로 보지 않는다)."""
    name = RULES.get("plan_dir_name")
    return os.path.join(str(config_dir), name) if isinstance(name, str) and name and config_dir else ""


def _is_plan_file(real_path: str, plan_dir: str, cwd: str = "", config_roots=()) -> bool:
    """계획 모드의 계획 파일: <설정 폴더>/plans/ 바로 아래의 .md 파일 하나(#878). 하위 폴더·다른 확장자는 아니다.
    real_path 는 realpath 로 푼 경로를 넘긴다. plans 폴더가 링크여도 된다(Orca 프로필은 ~/.claude/plans 로 링크한다).
    다만 링크로 다른 곳을 계획 폴더처럼 쓰지 못하게, 링크가 가리키는 폴더도 이름이 plans 여야 하고 작업 폴더 안이면 안 되며,
    훅·설정·지시 파일 이름(보호 경로)은 계획 파일로 보지 않는다(#909 리뷰: plans → 작업 폴더 Junction 으로 CLAUDE.md 쓰기)."""
    try:
        root = os.path.realpath(plan_dir)
        if os.path.normcase(os.path.basename(root.rstrip("\\/"))) != os.path.normcase(os.path.basename(os.path.abspath(plan_dir).rstrip("\\/"))):
            return False
        if cwd and platform_compat.is_within(root, os.path.realpath(cwd)):
            return False
        # 링크 대상도 설정 폴더 바로 아래의 plans 여야 한다(#911): 부모가 원래 설정 폴더(링크가 아닌 경우)이거나, 호출한 쪽이 넘긴
        # 실제 설정 폴더(CLAUDE_CONFIG_DIR·~/.claude 의 realpath) 중 하나. 폴더 이름(.claude)만 보지 않는다 — 다른 저장소의 .claude/plans 로
        # 미리 링크해 두고 그 안 .md 를 계획 파일인 척 쓰지 못하게(#919 리뷰). Orca 프로필(<conf>/plans → ~/.claude/plans)은 그대로 된다
        parent = os.path.normcase(os.path.dirname(root.rstrip("\\/")))
        allowed = {os.path.normcase(os.path.realpath(os.path.dirname(os.path.abspath(plan_dir).rstrip("\\/"))))}
        allowed |= {os.path.normcase(os.path.realpath(str(c))) for c in config_roots if c}
        if parent not in allowed:
            return False
        if not platform_compat.is_within(real_path, root):
            return False
        parts = [p for p in re.split(r"[\\/]", os.path.relpath(real_path, root)) if p]
    except (OSError, ValueError):
        return False
    if len(parts) != 1 or parts[0] in (".", "..") or _protected(parts[0]):
        return False
    return any(parts[0].lower().endswith(s) for s in _names("plan_file_suffixes"))


def _opened_paths(name: str, tool_input, cwd: str) -> list[str]:
    """읽기 도구가 실제로 열 경로(절대 경로). 상대 경로는 작업 폴더 기준이고, Glob 의 pattern 은 path(없으면 작업 폴더) 기준이다(#960)."""
    if not isinstance(tool_input, dict):
        return []
    out = []
    for k in ("file_path", "notebook_path", "path"):
        v = tool_input.get(k)
        if isinstance(v, str) and v:
            out.append(v if _is_abs(v) else os.path.join(cwd, v))
    if name == "Glob" and isinstance(tool_input.get("pattern"), str) and tool_input["pattern"]:
        pat = tool_input["pattern"]
        base = next((p for p in out), cwd)
        out.append(pat if _is_abs(pat) else os.path.join(base, pat))
    return out


def _real_within(path: str, root: str) -> bool:
    """링크를 모두 푼 실제 경로(글롭이면 글롭 앞까지)가 root 의 실제 경로 안인가."""
    parts = re.split(r"[\\/]", path)
    wild = next((k for k, part in enumerate(parts) if _WILD.search(part)), None)
    fixed = os.sep.join(parts[:wild]) if wild is not None else path
    try:
        return bool(fixed) and platform_compat.is_within(os.path.realpath(fixed), os.path.realpath(root))
    except (OSError, ValueError):
        return False


def classify(tool_name, tool_input, cwd, plan_dir: str = "", config_roots=(), read_roots=()) -> tuple[str, str]:
    """plan_dir 는 계획 모드인 세션에서만 넘긴다(<설정 폴더>/plans). 그 폴더 바로 아래 계획 파일 쓰기만 safe 로 본다.
    config_roots 는 plans 가 링크일 때 받아 줄 실제 설정 폴더들(CLAUDE_CONFIG_DIR·~/.claude). 순수 함수라 환경은 호출한 쪽이 읽는다.
    read_roots 는 작업 폴더 밖이어도 읽기 도구(Read·Glob·Grep)로 읽어도 되는 폴더(하네스 플러그인 폴더, #953)."""
    name = tool_name if isinstance(tool_name, str) else ""
    cwd = cwd if isinstance(cwd, str) else ""
    if name.startswith("mcp__"):
        return _classify_mcp(name, cwd)
    if name in ("Bash", "PowerShell"):
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return UNKNOWN, "명령을 읽지 못했어"
        return classify_bash(command, cwd, powershell=name == "PowerShell", harness_roots=read_roots)
    if name in _names("edit_tools"):
        path = _path_of(tool_input)
        if not path:
            return UNKNOWN, "고칠 파일을 읽지 못했어"
        if not cwd:
            return UNKNOWN, "작업 폴더를 몰라서 판정 못 했어"
        full = _resolve(path, cwd)
        real = os.path.realpath(full)
        if _is_scratchpad(real):
            return SAFE, "Claude 의 임시 폴더에 쓸 뿐이야"
        if plan_dir and _is_plan_file(real, plan_dir, cwd, config_roots):
            return SAFE, "계획 모드에서 계획 파일을 쓸 뿐이야"
        if not platform_compat.is_within(full, cwd):
            return IRREVERSIBLE, "작업 폴더 밖 파일을 쓰려 해"
        if _protected(os.path.relpath(real, os.path.realpath(cwd))):
            return UNKNOWN, "훅·설정·실행 설정 같은 파일이라 판정 못 했어"
        return SAFE, "작업 폴더 안 파일을 고쳐"
    if name in _names("path_tools"):
        if not cwd:
            return UNKNOWN, "작업 폴더를 몰라서 판정 못 했어"
        paths = [v for k, v in (tool_input.items() if isinstance(tool_input, dict) else []) if k in ("file_path", "notebook_path", "path") and isinstance(v, str) and v]
        if name == "Glob" and isinstance(tool_input, dict) and isinstance(tool_input.get("pattern"), str):
            paths.append(tool_input["pattern"])
        whys = [(p, _path_why(p, {"base": cwd, "cur": [cwd], "bs": False})) for p in paths]
        if not any(why for _, why in whys):
            return SAFE, "읽기만 해"
        # 하네스 플러그인 폴더 안 읽기(스킬이 자기 플러그인의 다른 스킬 문서를 읽는 일, #953). 읽기 도구만이고 쓰기는 그대로 묻는다.
        # 도구가 실제로 열 경로로 본다: 상대 경로는 작업 폴더(Glob 의 pattern 은 path) 기준으로 붙이고, 링크를 푼 실제 경로도 그 폴더 안이어야 한다
        # (작업 폴더 안 Junction 이 밖을 가리키면 상대 경로가 밖을 읽는다, #960 점검). 훅·설정 같은 보호 경로와 비밀값 모양은 여기서도 묻는다
        if read_roots and paths:
            opened = _opened_paths(name, tool_input, cwd)
            for root in read_roots:
                if root and opened and all(_path_ok(p, {"base": root, "cur": [root], "bs": False}) and _real_within(p, root) for p in opened):
                    return SAFE, "하네스 플러그인 문서를 읽기만 해"
        bad, why = next((p, w) for p, w in whys if w)
        return UNKNOWN, f"{bad[:80]}: {why}"
    if name == "WebFetch":
        url = tool_input.get("url") if isinstance(tool_input, dict) else None
        return (SAFE, "공개 웹 주소를 읽기만 해") if _public_web_url(url) else (UNKNOWN, "공개 웹 주소가 아니거나 읽지 못해 판정 못 했어")
    if name in _names("stateless_tools"):
        return SAFE, "읽기만 해"
    return UNKNOWN, f"{name or '이 도구'} 는 목록에 없어"
