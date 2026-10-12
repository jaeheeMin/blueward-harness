"""셸 명령 문자열에서 실제 `gh pr merge` 호출만 골라낸다(#101).

merge 가드(plugins/harness/hooks/pre-bash-git-guard.sh)는 예전에 명령 문자열
전체를 공백으로 쪼개 `-R`, PR 번호를 훑었다. 그래서 두 가지가 틀어졌다.

1. `gh pr merge 100; gh pr merge 51 -R other/repo` 처럼 한 명령에 merge 가
   둘이면 두 번째의 `-R` 이 첫 번째 PR 에 적용됐다.
2. `gh issue create --body "... gh pr merge ..."` 나 heredoc 본문에 든 글자도
   merge 로 읽었다.

이 모듈은 따옴표·heredoc 본문을 명령으로 보지 않고, `;`·`&&`·`||`·`|`·개행
등으로 명령을 나눈 뒤 조각마다 자기 인자만 짝지어 돌려준다. 훅은 bash 3.2
호환을 지켜야 해서 이런 파싱을 셸에서 하기 어렵기 때문에 엔진(파이썬)에 둔다.

저장소(repo)는 `-R`/`--repo` 로 지정한 것만 돌려준다. `.../pull/N` URL 에서
owner/name 을 뽑는 일은 훅이 예전처럼 prref 로부터 한다(URL 은 prref 에 그대로
남는다).

`--mutations` 로 부르면 merge 뿐 아니라 edit·close·reopen·comment·review·ready 도 골라
`{"mutations": [{"sub", "repo", "prref"}]}` 로 돌려준다(#150, 작성자가 다른 PR 을 막는 데 쓴다).

한계(훅의 다른 검사와 같은 성격): 변수로 감춘 명령(`x=merge; gh pr $x`),
큰따옴표 안의 `$(...)`·백틱 치환은 알아보지 못한다. 대신 확실히 나누지
못하는 명령(따옴표 불균형)은 MergeCommandError 로 알려 훅이 막게 한다 —
CLAUDE.md 원칙 7 에 따라 "나누지 못함" 을 "merge 아님" 으로 뭉개지 않는다.
"""

from __future__ import annotations

import json
import re
import shlex
import sys


class MergeCommandError(Exception):
    """명령을 믿을 만하게 나누지 못했다."""


# 명령을 끊는 문자. 개행도 명령 구분이므로 넣고, 백틱은 명령 치환의 시작·끝이다.
_PUNCT = ";&|()<>\n`"

_HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([^\s'\"|&;()<>]+)\2")


def _outside_quotes(text: str, pos: int) -> bool:
    """text[pos] 가 따옴표 밖인지(근사). 따옴표 안의 `<<` 는 heredoc 이 아니다."""
    prefix = text[:pos]
    return prefix.count("'") % 2 == 0 and prefix.count('"') % 2 == 0


def strip_heredocs(command: str) -> str:
    """heredoc 본문과 PowerShell here-string 본문을 지운다.

    본문은 명령이 아니라 데이터인데 "gh pr merge" 같은 글자가 들어 있을 수
    있다. 여는 줄의 `<<WORD` 는 함께 지운다(뒤에 `| gh ...` 같은 진짜 명령이
    이어질 수 있어 그 줄의 나머지는 남긴다).
    """
    lines = command.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1

        # PowerShell here-string: 줄 끝의 @' / @" 부터 줄 첫머리의 '@ / "@ 까지.
        stripped = line.rstrip()
        if stripped.endswith("@'") or stripped.endswith('@"'):
            closer = stripped[-1] + "@"
            out.append(stripped[:-2])
            while i < len(lines) and not lines[i].startswith(closer):
                i += 1
            if i < len(lines):
                out.append(lines[i][2:])  # 닫는 줄의 나머지(`'@ | gh ...`)는 남긴다.
                i += 1
            continue

        # bash heredoc. 한 줄에 여럿일 수 있어 나오는 순서대로 본문을 소비한다.
        pending: list[tuple[bool, str]] = []
        kept = []
        last = 0
        for m in _HEREDOC.finditer(line):
            if not _outside_quotes(line, m.start()):
                continue
            kept.append(line[last:m.start()])
            last = m.end()
            pending.append((m.group(1) == "-", m.group(3)))
        kept.append(line[last:])
        out.append("".join(kept))

        for dash, word in pending:
            # 닫는 구분자가 없으면 bash 도 끝까지를 본문으로 본다.
            while i < len(lines):
                body = lines[i].rstrip("\r")
                i += 1
                if (body.lstrip("\t") if dash else body) == word:
                    break
    return "\n".join(out)


def _protect_backslashes(text: str) -> str:
    """Windows 경로의 `\\` 가 shlex 이스케이프로 사라지지 않게 미리 겹친다.

    `C:\\tools\\gh.exe` 를 그대로 넘기면 `C:toolsgh.exe` 가 된다. 따옴표·공백·
    `$`·백틱·역슬래시 앞의 `\\` 만 진짜 이스케이프로 두고 나머지는 겹친다.
    """
    return re.sub(
        r"\\(.?)",
        lambda m: m.group(0) if m.group(1) and m.group(1) in "\"' \t\\$`\n" else "\\\\" + m.group(1),
        text,
        flags=re.DOTALL,
    )


def _tokenize(text: str) -> list[str]:
    lex = shlex.shlex(_protect_backslashes(text), posix=True, punctuation_chars=_PUNCT)
    # 개행을 공백으로 삼키면 명령 경계가 사라진다.
    lex.whitespace = " \t\r"
    lex.commenters = ""
    # punctuation_chars 모드에서는 whitespace_split 를 켤 수 없어, 기본 단어
    # 문자에 없는 `:`(URL, 드라이브 문자)·`@`·`%` 나 한글이 토큰을 쪼갠다.
    # 따옴표·공백·명령 구분자를 뺀 나머지는 모두 단어 문자로 넣는다.
    extra = "".join(
        chr(c)
        for c in list(range(0x21, 0x7F)) + list(range(0xA0, 0xD800)) + list(range(0xE000, 0x10000))
        if chr(c) not in _PUNCT and chr(c) not in "'\"\\"
    )
    lex.wordchars += extra
    try:
        return list(lex)
    except ValueError as e:  # 따옴표 불균형 등
        raise MergeCommandError(f"명령을 나누지 못했습니다: {e}") from e


def _is_punct(tok: str) -> bool:
    return all(c in _PUNCT for c in tok)


def _basename(tok: str) -> str:
    base = re.split(r"[/\\]", tok)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


# PR 을 바꾸는 gh pr 하위 명령(#150). merge 도 포함한다.
MUTATING_SUBS = ("merge", "edit", "close", "reopen", "comment", "review", "ready")

# 하위 명령별 옵션 표(gh 2.100.0 의 `gh pr <sub> --help` 기준). 같은 글자가 하위 명령마다
# 뜻이 다르다(`merge -m` 은 값 없는 --merge, `edit -m` 은 값을 받는 --milestone,
# `review -c` 는 값 없는 --comment, `close -c` 는 값을 받는 --comment). 그래서 표를 따로 둔다.
# (값을 받는 옵션, 값 없는 옵션). 이름 앞의 대시를 포함한 긴 이름과 짧은 이름을 모두 적는다.
_SUB_FLAGS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "merge": (
        frozenset({"-A", "--author-email", "-b", "--body", "-F", "--body-file",
                   "--match-head-commit", "-t", "--subject"}),
        frozenset({"--admin", "--auto", "-d", "--delete-branch", "--disable-auto",
                   "-m", "--merge", "-r", "--rebase", "-s", "--squash"}),
    ),
    "edit": (
        frozenset({"--add-assignee", "--add-label", "--add-project", "--add-reviewer", "--attach",
                   "-B", "--base", "-b", "--body", "-F", "--body-file", "-m", "--milestone",
                   "--remove-assignee", "--remove-label", "--remove-project", "--remove-reviewer",
                   "-t", "--title"}),
        frozenset({"--remove-milestone"}),
    ),
    "close": (frozenset({"-c", "--comment"}), frozenset({"-d", "--delete-branch"})),
    "reopen": (frozenset({"-c", "--comment"}), frozenset()),
    "comment": (
        frozenset({"--attach", "-b", "--body", "-F", "--body-file"}),
        frozenset({"--create-if-none", "--delete-last", "--edit-last", "-e", "--editor",
                   "-w", "--web", "--yes"}),
    ),
    "review": (
        frozenset({"-b", "--body", "-F", "--body-file"}),
        frozenset({"-a", "--approve", "-c", "--comment", "-r", "--request-changes"}),
    ),
    "ready": (frozenset(), frozenset({"--undo"})),
}

# 모든 하위 명령에 공통인 옵션.
_COMMON_BOOL = frozenset({"--help", "-h", "--version", "--no-color"})
_REPO_FLAGS = ("-R", "--repo")


def _parse_segment(seg: list[str], subs: tuple[str, ...] = ("merge",)) -> dict | None:
    i = 0
    repo = None
    while i < len(seg) and _ENV_ASSIGN.match(seg[i]):
        name, _, value = seg[i].partition("=")
        if name == "GH_REPO" and value:
            repo = value  # 환경 변수로 정한 저장소. 아래 -R 이 있으면 -R 이 이긴다.
        i += 1
    if i >= len(seg) or _basename(seg[i]) != "gh":
        return None
    i += 1

    # gh 뒤의 첫 두 비옵션 토큰이 pr, <하위 명령> 이어야 한다. 그 앞(gh 와 pr 사이, pr 와
    # 하위 명령 사이)에 오는 -R/--repo 는 저장소로 읽는다. 그 밖의 해석 못 하는 옵션은
    # 그 옵션이 값을 받는지 알 수 없어 PR 지정이 틀어질 수 있으므로, 대상 하위 명령으로
    # 확인되면 MergeCommandError 로 알려 훅이 검사 불능으로 막게 한다.
    stage = 0  # 0: pr 를 기다림, 1: 하위 명령을 기다림
    sub = None
    unknown_before = None
    explicit_repo = None
    while i < len(seg):
        tok = seg[i]
        i += 1
        if tok in _REPO_FLAGS:
            if i < len(seg):
                explicit_repo = seg[i]
                i += 1
            continue
        if tok.startswith("--repo="):
            explicit_repo = tok[len("--repo="):]
            continue
        if tok.startswith("-R="):
            explicit_repo = tok[len("-R="):]
            continue
        if tok.startswith("-"):
            if tok not in _COMMON_BOOL:
                unknown_before = tok
            continue
        if stage == 0:
            if tok != "pr":
                return None
            stage = 1
            continue
        if tok not in subs:
            return None
        sub = tok
        break
    if sub is None:
        return None
    if unknown_before is not None:
        raise MergeCommandError(
            f"gh 와 {sub} 사이에 해석할 수 없는 옵션 {unknown_before} 이 있어 대상 PR 을 확정할 수 없습니다"
        )

    values, bools = _SUB_FLAGS[sub]
    shorts = {f for f in values | bools if len(f) == 2}
    prref = None
    expect_repo = False
    skip_value = False
    unknown_flag = None
    for tok in seg[i:]:
        if expect_repo:
            explicit_repo, expect_repo = tok, False
        elif skip_value:
            skip_value = False
        elif tok in _REPO_FLAGS:
            expect_repo = True
        elif tok.startswith("--repo="):
            explicit_repo = tok[len("--repo="):]
        elif tok.startswith("-R="):
            explicit_repo = tok[len("-R="):]
        elif tok in values:
            skip_value = True
        elif tok in bools or tok in _COMMON_BOOL:
            continue
        elif tok.startswith("--"):
            if "=" in tok and tok.split("=", 1)[0] in values:
                continue  # --body=값 처럼 값이 붙은 형태
            unknown_flag = tok
        elif tok.startswith("-") and len(tok) > 2:
            # 묶인 짧은 옵션(-sd) 또는 값이 붙은 짧은 옵션(-bvalue). 글자마다 표에 있어야 한다.
            ok = True
            for k, ch in enumerate(tok[1:]):
                flag = "-" + ch
                if flag in values:
                    if k == len(tok) - 2:
                        skip_value = True  # 마지막 글자가 값을 받으면 값은 다음 토큰
                    break  # 값을 받는 글자 뒤는 그 값이다
                if flag not in shorts:
                    ok = False
                    break
            if not ok:
                unknown_flag = tok
        elif tok.startswith("-"):
            unknown_flag = tok
        elif unknown_flag is not None:
            # 해석 못 하는 옵션 뒤의 위치 인자는 그 옵션의 값일 수도 PR 지정일 수도 있다.
            raise MergeCommandError(
                f"옵션 {unknown_flag} 을 해석할 수 없어 뒤의 {tok} 가 PR 지정인지 확정할 수 없습니다"
            )
        elif prref is None:
            prref = tok
    return {"sub": sub, "repo": explicit_repo or repo or None, "prref": prref}


def _find(command: str, subs: tuple[str, ...]) -> list[dict]:
    tokens = _tokenize(strip_heredocs(command))
    found_all: list[dict] = []
    seg: list[str] = []
    for tok in tokens + [";"]:
        if _is_punct(tok):
            if seg:
                found = _parse_segment(seg, subs)
                if found is not None:
                    found_all.append(found)
            seg = []
        else:
            seg.append(tok)
    return found_all


def find_merges(command: str) -> list[dict]:
    """명령 안의 실제 `gh pr merge` 호출마다 `{"repo", "prref"}` 를 돌려준다."""
    return [{"repo": m["repo"], "prref": m["prref"]} for m in _find(command, ("merge",))]


def find_pr_mutations(command: str) -> list[dict]:
    """PR 을 바꾸는 `gh pr` 호출마다 `{"sub", "repo", "prref"}` 를 돌려준다(#150)."""
    return _find(command, MUTATING_SUBS)


def _force_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> int:
    _force_utf8()
    command = sys.stdin.read()
    mutations_mode = "--mutations" in sys.argv[1:]
    try:
        if mutations_mode:
            result = {"mutations": find_pr_mutations(command)}
        else:
            result = {"merges": find_merges(command)}
    except MergeCommandError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
