"""도구 호출이 묻지 않고 허용해도 되는 일인지 가른다(#649). 순수 함수 — 파일 목록(safe_tools.json) 외에 읽는 것이 없다.

classify(tool_name, tool_input, cwd) -> (판정, 사유)
  safe          확실히 안전하다고 아는 일(읽기, 작업 폴더 안 고치기, git add/commit 등)
  irreversible  되돌릴 수 없거나 밖으로 나가는 일(지우기, 올리기, 설치, 작업 폴더 밖 쓰기, SAP 쓰기)
  unknown       목록에 없거나 해석하지 못한 것. 허용으로 뭉개지 않고 사람에게 묻는다(CLAUDE.md 7).
원칙: 애매하면 unknown. safe 명령은 옵션 허용 목록 방식이라 목록에 없는 옵션이 하나라도 있으면 unknown 이다.
셸 명령은 ; && || | 와 줄바꿈으로 조각을 나눠 조각이 모두 safe 일 때만 safe 다. 따옴표 밖의 $( ` 리디렉션은 해석하지 않고 unknown 이다.
heredoc 본문은 데이터라 건너뛴다. 그 밖에서 줄바꿈 뒤에 명령이 더 있으면 unknown 이지만, 조각 하나라도 되돌릴 수 없으면 irreversible 이다.
읽기 명령의 경로 인자가 작업 폴더 밖이거나 비밀값 모양 파일이면 unknown 이다.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import ipaddress
import json
import os
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
    따옴표 밖 줄바꿈은 ; 처럼 명령을 나누는 "\\n" 연산자다(#951). heredoc 본문은 건너뛰고, 그 밖에서 줄바꿈 뒤에 명령이 더 있으면
    "여러 줄 명령" 사유를 남긴다 — 사유가 있어도 조각은 끝까지 나눠 두어 뒤 줄의 되돌릴 수 없는 명령을 가려낸다."""
    tokens: list[Token] = []
    cur: list[str] = []
    has_word = False
    spaced = True
    unsafe = ""
    heredocs: list = []  # 이 줄에서 열린 (끝 표시, <<- 인가, 따옴표로 막았나)
    body_chars = 0
    i, n = 0, len(command)

    def flush():
        nonlocal cur, has_word
        if has_word:
            tokens.append(("word", "".join(cur), spaced_at[0]))
        cur, has_word = [], False

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
            if command[i + 1:].strip():
                unsafe = unsafe or "여러 줄 명령이야"
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
                cur.append(command[i + 1]); has_word = True; i += 2; continue
            unsafe = unsafe or "줄을 잇는 \\ 가 있어"
            i += 1; continue
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
    """(조각별 낱말 목록, 조각 사이 연산자 목록(ops[i] 는 i번 조각 뒤), 해석 못 할 사유, heredoc 본문 글자 수)."""
    tokens, unsafe, body_chars = tokenize(command)
    segs: list[list[str]] = [[]]
    ops: list[str] = []
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
            else:
                unsafe = unsafe or "파일로 쓰거나 읽는 리디렉션(> <)이 있어"
        k += 1
    if any(not s for s in segs):
        unsafe = unsafe or "빈 조각이 있어"
    return segs, ops, unsafe, body_chars


# ---- 경로 ----
_WILD = re.compile(r"[*?\[]")


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


def _name_blocked(token: str) -> bool:
    """git 위치 인자(리비전 또는 경로, <rev>:<경로>)가 비밀값이거나 보호 경로를 가리키는가. 이름만 본다."""
    cands = [token] + ([token.split(":", 1)[1]] if ":" in token else [])
    return any(c and (_is_secret(c) or _protected(c)) for c in cands)


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


def _path_ok(p: str, ctx: dict) -> bool:
    """읽어도 되는 경로인가: 작업 폴더 안이고, 변수·~ 확장이 없고, 비밀값·보호 경로(.git 포함)가 아니다. 심볼릭 링크는 실제 이름도 본다."""
    base = ctx.get("base") or ""
    if not base or ctx.get("bs"):
        return False
    if not p:
        return True
    if "$" in p or "`" in p or re.search(r"%[^%\s]+%", p) or p.startswith("~"):
        return False
    full = p if _is_abs(p) else os.path.join(ctx["cur"][0], p)
    parts = re.split(r"[\\/]", full)
    wild = next((k for k, part in enumerate(parts) if _WILD.search(part)), None)
    if wild is not None:
        if ".." in parts[wild:]:
            return False
        full = os.sep.join(parts[:wild]) or os.sep
        if _is_abs(p) and wild == 0:
            return False
    if not platform_compat.is_within(full, base):
        return False
    try:
        rel = os.path.relpath(os.path.realpath(full), os.path.realpath(base))
    except ValueError:
        return False
    return not (_is_secret(p) or _is_secret(rel) or _protected(rel))


# ---- git ----
def _base(word: str) -> str:
    name = re.split(r"[\\/]", word)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _clusters(args: list[str]) -> str:
    """-am 같은 짧은 옵션 묶음의 글자를 모은다(--긴옵션은 제외)."""
    return "".join(a[1:] for a in args if re.fullmatch(r"-[A-Za-z]+", a))


def _git(args: list[str]):
    verdict, why = _git_sub(args)
    lead, i = [], 0
    while i < len(args) and args[i].startswith("-"):
        step = 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        lead += args[i:i + step]
        i += step
    # git -c / -C / --exec-path 같은 전역 옵션은 다른 명령을 실행시키거나 다른 곳을 읽게 해서 읽기여도 판정 못 함으로 낮춘다
    if verdict == SAFE and any(a not in _names("git_global_options_ok") for a in lead):
        return UNKNOWN, "git 전역 옵션이 붙어 판정 못 했어"
    return verdict, why


def _git_sub(args: list[str]):
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
        if any(_name_blocked(a) for a in _positionals(rest, value_opts)):
            return UNKNOWN, "비밀값이나 보호 경로를 가리키는 인자가 있어"
        return SAFE, "git 으로 상태를 읽기만 해"
    if sub == "push":
        return IRREVERSIBLE, "GitHub에 코드를 올리려 해"
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
        if rest[:1] == [new] and 2 <= len(rest) <= 3 and not any(a.startswith("-") for a in rest[1:]):
            return SAFE, "새 브랜치를 만들 뿐이야"
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
    if spec.get("paths") and not all(_path_ok(a, ctx) for a in pos):
        return UNKNOWN, "작업 폴더 밖이거나 비밀값·보호 경로, 또는 변수를 쓴 경로라 판정 못 했어"
    if spec.get("no_dir_args") and any(os.path.isdir(a if _is_abs(a) else os.path.join(ctx["cur"][0], a)) for a in pos):
        return UNKNOWN, f"{cmd} 가 폴더를 통째로 읽어"
    return SAFE, "읽기만 하는 명령이야"


def _sed(args: list[str], ctx: dict):
    script = RULES.get("sed_script")
    if args[:1] != ["-n"] or len(args) < 2 or not isinstance(script, str) or not re.fullmatch(script, args[1]):
        return UNKNOWN, "sed 는 줄 번호 출력(sed -n '3,5p')만 읽기로 봐"
    files = args[2:]
    if any(a.startswith("-") for a in files) or not all(_path_ok(a, ctx) for a in files):
        return UNKNOWN, "작업 폴더 밖이거나 비밀값 모양 파일이라 판정 못 했어"
    return SAFE, "줄 번호로 읽기만 해"


def _cd(args: list[str], ctx: dict):
    """safe 는 맨 앞 `cd <폴더> && 명령` 꼴이고 그 폴더가 실제로 있는 작업 폴더 안일 때만이다."""
    if ctx.get("idx") != 0 or ctx.get("ops", [])[:1] != ["&&"]:
        return UNKNOWN, "cd 는 명령 맨 앞의 `cd 폴더 && 명령` 꼴만 판정해"
    if len(args) != 1 or args[0].startswith("-") or not _path_ok(args[0], ctx):
        return UNKNOWN, "cd 가 작업 폴더 밖이거나 어디로 가는지 몰라"
    target = args[0] if _is_abs(args[0]) else os.path.join(ctx["cur"][0], args[0])
    if not os.path.isdir(target):
        return UNKNOWN, "cd 할 폴더가 실제로 없어"
    ctx["cur"][0] = os.path.normpath(target)
    return SAFE, "작업 폴더 안에서 옮겨 다닐 뿐이야"


def _segment(words: list[str], ctx: dict):
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
        return UNKNOWN, "uv 는 목록에 없어"
    if cmd == "git":
        return _git(args)
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
        if not all(a in plain[cmd] for a in dashed):
            return UNKNOWN, f"{cmd} 에 목록에 없는 옵션이 있어"
        if cmd in ("echo", "printf") and any(c in a for a in args for c in "$%~`"):
            return UNKNOWN, f"{cmd} 인자에 변수·~ 확장이나 형식 문자가 있어"
        return SAFE, "읽기만 하는 명령이야"
    reads = RULES.get("bash_read")
    if isinstance(reads, dict) and cmd in reads:
        return _read_command(cmd, args, ctx)
    return UNKNOWN, f"{words[0]} 는 목록에 없어"


def classify_bash(command: str, cwd: str = "", powershell: bool = False):
    if not command.strip():
        return UNKNOWN, "빈 명령이야"
    if len(command) > MAX_WITH_HEREDOC:
        return UNKNOWN, "명령이 너무 길어서 읽지 못했어"
    segs, ops, unsafe, body_chars = _segments(command)
    if len(command) - body_chars > MAX_COMMAND:  # heredoc 본문(PR·커밋 글)은 길이에 세지 않는다(#951)
        return UNKNOWN, "명령이 너무 길어서 읽지 못했어"
    ctx = {"base": cwd, "cur": [cwd], "bs": "\\" in command, "ops": ops, "idx": 0}  # \ 는 Windows 경로일 수 있어 경로를 읽는 명령은 판정하지 않는다
    results = []
    for i, w in enumerate(segs):
        ctx["idx"] = i
        results.append(_segment(w, ctx))
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


def classify(tool_name, tool_input, cwd, plan_dir: str = "", config_roots=()) -> tuple[str, str]:
    """plan_dir 는 계획 모드인 세션에서만 넘긴다(<설정 폴더>/plans). 그 폴더 바로 아래 계획 파일 쓰기만 safe 로 본다.
    config_roots 는 plans 가 링크일 때 받아 줄 실제 설정 폴더들(CLAUDE_CONFIG_DIR·~/.claude). 순수 함수라 환경은 호출한 쪽이 읽는다."""
    name = tool_name if isinstance(tool_name, str) else ""
    cwd = cwd if isinstance(cwd, str) else ""
    if name.startswith("mcp__"):
        return _classify_mcp(name, cwd)
    if name in ("Bash", "PowerShell"):
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return UNKNOWN, "명령을 읽지 못했어"
        return classify_bash(command, cwd, powershell=name == "PowerShell")
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
        ctx = {"base": cwd, "cur": [cwd], "bs": False}
        paths = [v for k, v in (tool_input.items() if isinstance(tool_input, dict) else []) if k in ("file_path", "notebook_path", "path") and isinstance(v, str) and v]
        if name == "Glob" and isinstance(tool_input, dict) and isinstance(tool_input.get("pattern"), str):
            paths.append(tool_input["pattern"])
        if not all(_path_ok(p, ctx) for p in paths):
            return UNKNOWN, "작업 폴더 밖이거나 비밀값 모양 파일을 읽으려 해"
        return SAFE, "읽기만 해"
    if name == "WebFetch":
        url = tool_input.get("url") if isinstance(tool_input, dict) else None
        return (SAFE, "공개 웹 주소를 읽기만 해") if _public_web_url(url) else (UNKNOWN, "공개 웹 주소가 아니거나 읽지 못해 판정 못 했어")
    if name in _names("stateless_tools"):
        return SAFE, "읽기만 해"
    return UNKNOWN, f"{name or '이 도구'} 는 목록에 없어"
