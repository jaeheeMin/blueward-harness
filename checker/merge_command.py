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


def _parse_segment(seg: list[str]) -> dict | None:
    i = 0
    while i < len(seg) and _ENV_ASSIGN.match(seg[i]):
        i += 1
    if i >= len(seg) or _basename(seg[i]) != "gh":
        return None
    i += 1

    # gh 뒤의 첫 두 비옵션 토큰이 pr, merge 여야 한다(옛 gh_is_pr_merge 와 같은 뜻).
    want = ["pr", "merge"]
    while want and i < len(seg):
        tok = seg[i]
        i += 1
        if tok.startswith("-"):
            continue
        if tok != want[0]:
            return None
        want.pop(0)
    if want:
        return None

    repo = None
    prref = None
    expect_repo = False
    for tok in seg[i:]:
        if expect_repo:
            repo, expect_repo = tok, False
        elif tok in ("-R", "--repo"):
            expect_repo = True
        elif tok.startswith("--repo="):
            repo = tok[len("--repo="):]
        elif tok.startswith("-R="):
            repo = tok[len("-R="):]
        elif tok.startswith("-"):
            continue
        elif prref is None:
            prref = tok
    return {"repo": repo or None, "prref": prref}


def find_merges(command: str) -> list[dict]:
    """명령 안의 실제 `gh pr merge` 호출마다 `{"repo", "prref"}` 를 돌려준다."""
    tokens = _tokenize(strip_heredocs(command))
    merges: list[dict] = []
    seg: list[str] = []
    for tok in tokens + [";"]:
        if _is_punct(tok):
            if seg:
                found = _parse_segment(seg)
                if found is not None:
                    merges.append(found)
            seg = []
        else:
            seg.append(tok)
    return merges


def _force_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> int:
    _force_utf8()
    command = sys.stdin.read()
    try:
        merges = find_merges(command)
    except MergeCommandError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps({"merges": merges}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
