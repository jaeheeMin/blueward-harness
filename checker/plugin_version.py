"""`plugins/harness/` 를 바꾼 PR 이 plugin.json version 을 올렸는지 검사한다(#136).

CLAUDE.md 원칙 8 — version 이 같으면 팀원 PC 의 설치본이 갱신되지 않는다. 사람이
기억해서 올리던 것을 PR 검사로 기계가 확인한다.

판정(`judge`)은 입력만 보는 순수 함수이고, git 을 읽는 일은 `main` 이 한다.

종료코드: 0 통과(Plugin 이 안 바뀜, 또는 version 이 올랐음), 1 version 을 안 올림,
2 판정 불가. 읽지 못한 것을 통과로 답하지 않는다(원칙 7).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass

PLUGIN_DIR = "plugins/harness/"
PLUGIN_JSON = "plugins/harness/.claude-plugin/plugin.json"


@dataclass(frozen=True)
class Verdict:
    code: int
    message: str


def parse_version(text: object) -> tuple[int, ...]:
    """`0.10.17` 을 `(0, 10, 17)` 로. 점으로 나눈 정수만 받는다(`0.10.9 < 0.10.17`)."""
    if not isinstance(text, str):
        raise ValueError(f"version 이 문자열이 아니다: {text!r}")
    parts = text.strip().split(".")
    if not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError(f"version 형식이 점으로 나눈 정수가 아니다: {text!r}")
    return tuple(int(p) for p in parts)


def judge(changed_files: list[str], base_version: str, head_version: str) -> Verdict:
    if not any(f.startswith(PLUGIN_DIR) for f in changed_files):
        return Verdict(0, "plugins/harness/ 가 바뀌지 않아 version 을 확인하지 않는다.")
    try:
        base = parse_version(base_version)
        head = parse_version(head_version)
    except ValueError as e:
        return Verdict(
            2,
            f"version 을 읽지 못해 검사하지 못했다({e}). 통과시키지 않는다. "
            f"다음: {PLUGIN_JSON} 의 version 을 `0.10.17` 같은 모양으로 고치십시오.",
        )
    if head > base:
        return Verdict(0, f"plugin.json version 이 올랐다: {base_version} -> {head_version}")
    return Verdict(
        1,
        f"plugins/harness/ 를 바꿨는데 plugin.json version 이 base 보다 오르지 않았다"
        f"(base {base_version}, 지금 {head_version}). 올리지 않으면 팀원 PC 설치본이 갱신되지 않는다. "
        f"다음: {PLUGIN_JSON} 의 version 을 {base_version} 보다 큰 값으로 올리십시오.",
    )


class GitError(Exception):
    pass


def _git(*args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git 을 실행하지 못했다: {e}") from e
    if done.returncode != 0:
        raise GitError(f"git {' '.join(args)} 실패: {done.stderr.strip()}")
    return done.stdout


def _version_of(text: str, where: str) -> str:
    try:
        return json.loads(text)["version"]
    except (ValueError, KeyError, TypeError) as e:
        raise GitError(f"{where} 의 plugin.json 에서 version 을 읽지 못했다: {e}") from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="plugins/harness/ 변경 시 plugin.json version 올림 검사")
    ap.add_argument("--base", required=True, help="비교할 base ref 또는 커밋(예: origin/main)")
    args = ap.parse_args(argv)
    try:
        # base...HEAD: base 와의 공통 조상 이후 이 브랜치가 바꾼 파일.
        names = _git("diff", "--name-only", "-z", f"{args.base}...HEAD").split("\0")
        changed = [n for n in names if n]
        base_text = _git("show", f"{args.base}:{PLUGIN_JSON}")
        base_version = _version_of(base_text, f"base({args.base})")
        with open(PLUGIN_JSON, encoding="utf-8") as f:
            head_version = _version_of(f.read(), "HEAD")
    except (GitError, OSError) as e:
        print(
            f"plugin version 검사 불능: {e}. 통과시키지 않는다. "
            f"다음: base ref 를 읽을 수 있는지(git fetch, fetch-depth) 확인하고 다시 돌리십시오.",
            file=sys.stderr,
        )
        return 2
    verdict = judge(changed, base_version, head_version)
    print(verdict.message, file=sys.stderr if verdict.code else sys.stdout)
    return verdict.code


if __name__ == "__main__":
    raise SystemExit(main())
