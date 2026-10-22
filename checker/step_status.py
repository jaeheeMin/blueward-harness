"""pr-checks job 의 단계 결과를 옛 검사 이름의 commit status 로 단다(#417).

PR 검사를 한 job(`pr-checks / check`)의 단계로 합치면 GitHub 에는 check run 이름이 하나만
뜬다. 그런데 엔진(`risk_gate` 의 `checks` 기준, `pr_queue.GATE_GROUPS`, `pr_approvals`)과
훅(`pre-bash-git-guard.sh`)은 옛 이름(`gitleaks`·`doc-guard`·`ssot-approval`·`risk-gate`)으로
검사를 읽는다. 그래서 각 단계가 끝나면 그 이름 그대로 이 스크립트로 commit status 를 단다
(#412). pr-queue 가 `merge-order` status 를 다는 것과 같은 방식이다. status 는 job 이 아니라
Actions 분이 과금되지 않고, 같은 sha·context 의 최신값이 읽히므로 재실행에도 맞다.

결과 → state: `pass` → success, `fail` → failure, `unknown` → error. `unknown` 은 검사
불능이다(CLAUDE.md 원칙 7) — 통과도 위반도 아니라 error 로 달아 읽는 쪽이 실패로 센다.

`GH_TOKEN` 은 환경에서 읽는다(`gh` 가 쓴다). status 를 달지 못하면 조용히 넘어가지 않고
종료코드 2 와 stderr 사유를 낸다.

종료코드: 0 status 를 달았다, 2 달지 못했다(gh 실패, 잘못된 인자).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

STATE_FOR_RESULT = {"pass": "success", "fail": "failure", "unknown": "error"}
EXIT_OK = 0
EXIT_CANNOT_POST = 2
DESCRIPTION_LIMIT = 140  # GitHub 가 description 을 140자로 자른다


class StatusError(Exception):
    """status 를 달지 못한 사유."""


def state_for(result: str) -> str:
    try:
        return STATE_FOR_RESULT[result]
    except KeyError:
        raise StatusError(f"모르는 result 다: {result!r} (pass, fail, unknown 중 하나)") from None


def post_status(
    repo: str,
    sha: str,
    context: str,
    result: str,
    description: str = "",
    target_url: str = "",
) -> str:
    """sha 에 context 이름의 commit status 를 달고 달린 state 를 돌려준다."""
    state = state_for(result)
    args = [
        "gh", "api", "-X", "POST", f"repos/{repo}/statuses/{sha}",
        "-f", f"state={state}", "-f", f"context={context}",
    ]
    if description:
        args += ["-f", f"description={description[:DESCRIPTION_LIMIT]}"]
    if target_url:
        args += ["-f", f"target_url={target_url}"]
    try:
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StatusError(f"gh 실행에 실패했다: {exc}") from exc
    if done.returncode != 0:
        raise StatusError(f"gh api 가 종료코드 {done.returncode} 로 실패했다: {done.stderr.strip()}")
    return state


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="pr-checks 단계 결과를 commit status 로 단다")
    p.add_argument("--repo", required=True, help="owner/repo")
    p.add_argument("--sha", required=True)
    p.add_argument("--context", required=True, help="status 이름(gitleaks, doc-guard, ssot-approval, risk-gate)")
    p.add_argument("--result", required=True, help="pass | fail | unknown")
    p.add_argument("--description", default="")
    p.add_argument("--target-url", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state = post_status(args.repo, args.sha, args.context, args.result, args.description, args.target_url)
    except StatusError as exc:
        print(f"status 를 달지 못했다({args.context}): {exc}", file=sys.stderr)
        return EXIT_CANNOT_POST
    print(f"{args.context}: {state}")
    return EXIT_OK
