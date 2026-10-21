"""내 승인을 기다리는 열린 PR 을 병합 순서대로 보여 준다(#391).

    python -m checker.pr_approvals [--repo owner/repo] [--json] [--quiet-empty]

승인자는 남의 PR 에 Approve 를 달아야 순서가 풀리는데, 어떤 PR 이 내 승인을 기다리는지는 GitHub 에서
하나씩 열어 봐야 안다. 이 모듈은 `pr_queue.compute` 의 상태·병합 순서를 그대로 쓰고(판정을 다시 만들지
않는다), 그 가운데 "승인 대기" 인 PR 에서 내 승인이 필요한 것만 고른다.

내 승인이 필요하다 = 상태가 승인 대기이고, 작성자가 내가 아니고, 승인자 설정이 나를 그 작성자의 승인자로
정했고, 내 승인이 head 커밋 기준으로 없다(없거나 낡았다). 승인자 설정은 `ssot_approval.judge_by_rules` 와
같이 읽는다: `.github/ssot-approvers` 가 없거나 비어 있으면 작성자가 아닌 누구든 승인할 수 있다(나도 승인자).
내용이 있는데 내 이름이 어느 작성자 줄에도 없을 때만 "승인자가 아님" 이다. 승인 규칙·낡은 승인 판정은
`pr_queue._approval_state` 가 한다.

결과 구분(원칙 7):
  - 승인자 설정에 내가 없다 → "이 저장소에서 나는 승인자가 아님"(승인할 PR 없음과 다르다).
  - 승인자인데 승인 대기 PR 중에 기다리는 것이 없다 → "승인 대기 상태인 PR 중에는 내 승인을 기다리는 PR 없음".
  - 읽지 못했거나(승인자 파일을 404 가 아닌 오류로 못 읽음·해석 못 함 포함) 판정할 수 없다 →
    "승인 대기 PR 확인 불능" 이고 종료코드 2.
검사 중·실패·충돌이라 아직 승인 대기가 아닌데 내 승인도 필요해 보이는 PR 은 표 아래에 따로 센다.
이 모듈은 읽기만 한다. Approve 는 사람이 GitHub 에서 한다.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys

from checker import pr_queue
from checker.pr_queue import (
    CHECK_FAILED,
    CHECKING,
    CONFLICT,
    EXIT_CANNOT_CHECK,
    EXIT_OK,
    GATE_GROUPS,
    NOT_STARTED,
    UNKNOWN,
    WAITING_APPROVAL,
    _approval_state,
    _clip,
    _Context,
    _default_repo,
    _latest_runs,
    _load_prs,
    _login,
    _norm_check,
    _risk_gate_view,
    pr_link,
)
from checker.risk_gate import _check_group, _run_state
from checker.ssot_approval import GhClient, GhError, ParsedApprovers, approvers_for, parse_approvers, touches_ssot

NOT_APPROVER = "이 저장소에서 나는 승인자가 아님"
NONE_WAITING = "승인 대기 상태인 PR 중에는 내 승인을 기다리는 PR 없음"
ANYONE_NOTE = "승인자 파일이 없어 작성자 아닌 누구든 승인할 수 있다"
SRS_REASON = "SRS 변경(docs/ssot)"
ONLY_ME = "내 승인만 남음"
# 아직 승인 대기까지 오지 못한 상태. 이 상태의 PR 도 내 승인이 필요할 수 있다.
NOT_YET_STATES = frozenset({CHECKING, CHECK_FAILED, CONFLICT, NOT_STARTED})


def cannot_check(message: str) -> dict:
    return {"status": "cannot_check", "message": f"승인 대기 PR 확인 불능 — {message}"}


def _read_rules(ctx: _Context, base: str) -> ParsedApprovers:
    """승인자 파일을 읽는다. 404(파일 없음)는 "파일 없음", 그 밖의 읽기·해석 실패는 GhError.

    `pr_queue` 의 읽기는 해석 실패를 "내용 없음" 으로 삼켜 "누구든" 으로 풀리므로, 여기서는 먼저
    엄격하게 읽어 `ctx` 에 넣는다(`_approval_state` 도 같은 값을 쓴다).
    """
    if base in ctx._rules:
        return ctx._rules[base]
    data = ctx.client.get_json_or_none_404(f"repos/{ctx.repo}/contents/.github/ssot-approvers?ref={base}")
    if not data:
        rules = parse_approvers(None)
    else:
        try:
            text = base64.b64decode(data.get("content", "") or "").decode("utf-8")
        except (ValueError, TypeError, AttributeError) as exc:
            raise GhError(f"{base} 의 .github/ssot-approvers 를 해석하지 못했다: {exc}") from exc
        rules = parse_approvers(text)
    ctx._rules[base] = rules
    return rules


def _may_approve(rules: ParsedApprovers, login_l: str, author: str) -> bool:
    """이 작성자의 PR 을 내가 승인할 수 있는가. 파일이 비면 작성자 아닌 누구든."""
    if author.lower() == login_l:
        return False
    if not rules.has_entries:
        return True
    return login_l in approvers_for(rules, author)


def _gate_groups(raw: dict) -> set[str]:
    checks = [_norm_check(e) for e in _latest_runs(raw.get("statusCheckRollup") or [])]
    return {_check_group(c["name"]) for c in checks if _check_group(c["name"]) in GATE_GROUPS and _run_state(c) == "fail"}


def _why(ctx: _Context, raw: dict) -> str:
    """왜 승인이 필요한가. risk-gate 는 봇 코멘트의 사유, ssot-approval 은 SRS 변경."""
    groups = _gate_groups(raw)
    parts: list[str] = []
    if "risk-gate" in groups:
        try:
            _, summary = _risk_gate_view(ctx, raw["number"])
        except GhError:
            summary = ""
        parts.append(summary or "risk-gate(사유는 PR 코멘트)")
    if "ssot-approval" in groups:
        parts.append(SRS_REASON)
    return " / ".join(parts) or "승인 필요(사유는 PR 코멘트)"


def _needs_approval_hint(ctx: _Context, raw: dict) -> bool:
    """아직 승인 대기가 아닌 PR 이 승인을 요구할 징후가 있는가. 코멘트를 못 읽으면 GhError."""
    if touches_ssot([f.get("path") or "" for f in raw.get("files") or []]):
        return True
    kind, _ = _risk_gate_view(ctx, raw["number"])
    return kind == "approval"


def _bases(raws: list[dict]) -> list[str]:
    return sorted({r.get("baseRefName") or "main" for r in raws}) or ["main"]


def compute(client: GhClient, repo: str, login: str) -> dict:
    """내 승인을 기다리는 PR. GitHub 를 읽지 못하면 GhError 를 던진다."""
    login_l = login.lower()
    queue = pr_queue.compute(client, repo, login)
    loaded = _load_prs(client, repo)
    raws = {r["number"]: r for r in loaded}
    ctx = _Context(client, repo)
    urls = {it["number"]: it.get("url") or "" for it in queue["prs"]}

    rules_by_base = {base: _read_rules(ctx, base) for base in _bases(loaded)}
    anyone = any(not r.has_entries for r in rules_by_base.values())
    is_approver = anyone or any(login_l in r.everyone() for r in rules_by_base.values())
    warnings = list(queue["warnings"])
    if queue["truncated"]:
        warnings.append(f"열린 PR 이 {pr_queue.PR_LIMIT}개 이상이라 일부만 읽었다. 목록이 완전하지 않다.")
    result = {
        "status": "ok",
        "repo": repo,
        "login": login,
        "approver": is_approver,
        "anyone": anyone,
        "prs": [],
        "not_yet": [],
        "not_yet_unreadable": False,
        "unknown": [],
        "unchecked": [],
        "warnings": warnings,
    }
    if not is_approver:
        return result

    for it in queue["prs"]:
        author = it["author"]
        rules = rules_by_base.get(it["base"] or "main") or _read_rules(ctx, it["base"] or "main")
        if not _may_approve(rules, login_l, author):
            continue  # 내 PR 이거나 내 몫이 아닌 작성자의 PR
        number = it["number"]
        raw = raws.get(number)
        if raw is None:
            # 두 번 읽는 사이 생긴 PR 이라 상세를 모른다. 없는 것으로 치지 않고 드러낸다.
            result["unchecked"].append(number)
            continue
        if it["state"] == UNKNOWN:
            result["unknown"].append(number)
            continue
        if it["state"] in NOT_YET_STATES:
            try:
                hinted = _needs_approval_hint(ctx, raw)
            except GhError:
                result["not_yet_unreadable"] = True
                continue
            if hinted:
                result["not_yet"].append({"number": number, "url": it["url"], "state": it["state"]})
            continue
        if it["state"] != WAITING_APPROVAL:
            continue
        appr = _approval_state(ctx, raw, author)
        if appr["approved"]:
            continue  # 이 사이 승인됨
        stale = [s.lower() for s in appr["stale"]]
        others = [a for a in appr["eligible"] if a != login_l]
        remaining: list[str] = []
        if (raw.get("mergeStateStatus") or "").upper() == "BEHIND":
            remaining.append("base 보다 뒤처짐")
        if it["after"]:
            remaining.append("앞 " + ", ".join(pr_link(repo, n, urls.get(n, "")) for n in it["after"]) + " 병합 대기")
        remaining.extend(it["notes"])
        result["prs"].append(
            {
                "number": number,
                "title": it["title"],
                "url": it["url"],
                "author": author,
                "order": it["order"],
                "after": it["after"],
                "why": _why(ctx, raw),
                "other_approvers": others,
                "other_anyone": appr["anyone"],
                "other_stale": [s for s in stale if s != login_l],
                "my_stale": login_l in stale,
                "only_me": not remaining,
                "remaining": remaining,
                "human_merge": it["human_merge"],
            }
        )
    if result["unknown"]:
        names = ", ".join(f"#{n}" for n in result["unknown"])
        warnings.append(f"{names} 는 승인 여부를 읽지 못해 내 승인이 필요한지 판정하지 못했다")
    if result["unchecked"]:
        names = ", ".join(f"#{n}" for n in result["unchecked"])
        warnings.append(f"{names} 는 목록을 읽는 사이 새로 생겨 확인하지 못했다(다시 실행)")
    return result


# --- 출력 ---------------------------------------------------------------------


def render(result: dict) -> str:
    repo = result["repo"]
    lines: list[str] = []
    prs = result["prs"]
    if not result["approver"]:
        lines.append(f"{repo}: {NOT_APPROVER}(.github/ssot-approvers 에 내용이 있는데 {result['login']} 가 없음)")
    else:
        if result["anyone"]:
            lines.append(f"{repo}: {ANYONE_NOTE}.")
        if not prs:
            lines.append(f"{repo}: {NONE_WAITING}")
        else:
            lines.append(f"{repo}: 내 승인을 기다리는 PR {len(prs)}개 (병합 순서)")
            lines.append("")
            lines.append("| 순서 | PR | 왜 승인이 필요한가 | 다른 승인자 | 남은 것 | 낡은 승인 |")
            lines.append("|---|---|---|---|---|---|")
            for it in prs:
                order = str(it["order"]) if it["order"] is not None else "?"
                me = pr_link(repo, it["number"], it["url"])
                others = ", ".join(it["other_approvers"])
                if it["other_anyone"]:
                    others = "누구든(작성자 제외)"
                others = others or "없음(나만)"
                left = ONLY_ME if it["only_me"] else "내 승인 외에 남음: " + " · ".join(it["remaining"])
                if it["human_merge"]:
                    left += " · 사람이 GitHub 에서 병합"
                stale = []
                if it["my_stale"]:
                    stale.append("내 승인이 낡음(새 커밋 뒤 다시 승인)")
                if it["other_stale"]:
                    stale.append(", ".join(it["other_stale"]) + " 의 승인이 낡음")
                lines.append(
                    f"| {order} | {me} {_clip(it['title'])} (@{it['author']}) | {_clip(it['why'], 60)} | "
                    f"{others} | {left} | {'; '.join(stale) or '-'} |"
                )
            lines.append("")
            lines.append("승인은 GitHub 에서 사람이 한다(이 도구는 Approve 를 대신 하지 않는다).")
        if result["not_yet_unreadable"]:
            lines.append("내 승인도 필요하지만 검사 중·실패·충돌이라 아직 차례가 아닌 PR: 셀 수 없음(코멘트를 읽지 못함)")
        elif result["not_yet"]:
            links = ", ".join(pr_link(repo, e["number"], e["url"]) for e in result["not_yet"])
            lines.append(
                f"내 승인도 필요하지만 검사 중·실패·충돌이라 아직 차례가 아닌 PR {len(result['not_yet'])}건: {links}"
            )
    for warning in result["warnings"]:
        lines.append(f"주의: {warning}")
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="checker.pr_approvals", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/repo (없으면 현재 폴더의 저장소)")
    parser.add_argument("--json", action="store_true", help="구조화된 출력")
    parser.add_argument(
        "--quiet-empty",
        action="store_true",
        help="승인자가 아니거나 기다리는 PR 이 없으면 아무것도 내지 않는다(경고·아직 차례 아닌 PR 이 있으면 낸다)",
    )
    return parser


def run(args: argparse.Namespace, client: GhClient | None = None) -> tuple[int, str]:
    client = client or GhClient()
    try:
        repo = args.repo or _default_repo(client)
        result = compute(client, repo, _login(client))
    except GhError as exc:
        res = cannot_check(str(exc))
        return EXIT_CANNOT_CHECK, json.dumps(res, ensure_ascii=False) if args.json else res["message"]
    except Exception as exc:  # noqa: BLE001 - 어떤 오류도 통과·없음으로 보이면 안 된다(원칙 7)
        res = cannot_check(f"예상 못 한 오류 {type(exc).__name__}")
        return EXIT_CANNOT_CHECK, json.dumps(res, ensure_ascii=False) if args.json else res["message"]
    if (result["unknown"] or result["unchecked"]) and not result["prs"]:
        # 확인 못 한 PR 이 있는데 "없음" 이라 말할 수 없다.
        res = cannot_check(result["warnings"][-1])
        return EXIT_CANNOT_CHECK, json.dumps(res, ensure_ascii=False) if args.json else res["message"]
    if args.quiet_empty and not result["prs"] and not result["warnings"] and not result["not_yet"] and not result["not_yet_unreadable"]:
        return EXIT_OK, ""
    if args.json:
        return EXIT_OK, json.dumps(result, ensure_ascii=False)
    return EXIT_OK, render(result)


def main(argv: list[str] | None = None) -> int:
    pr_queue._force_utf8()
    args = build_parser().parse_args(argv)
    code, text = run(args)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
