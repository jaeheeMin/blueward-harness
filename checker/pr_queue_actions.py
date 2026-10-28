"""열린 PR 의 병합 순서를 PR 코멘트·커밋 status·차례 알림으로 GitHub 에 남긴다(#370 3단계).

    python -m checker.pr_queue_actions --repo owner/repo [--event-path 이벤트.json] [--summary-file 요약.md]

`pr-checks.yml`·`pr-review.yml`·`main-checks.yml` 의 pr-queue 단계와 이 저장소의 `pr-queue-self.yml` 이 부른다. Claude 를 안 쓰는 사람도 같은 정보를 받게 하려는 것이다.
`checker.pr_queue.compute` 로 열린 PR 전체를 한 번 계산하고, 열린 PR 마다 다음을 한다(닫힌 PR 은 건드리지 않는다).

1. 코멘트 하나(github-actions 봇, 마커 `<!-- pr-queue -->`)를 만들거나 갱신한다. 시각 같은 흔들리는 값을
   넣지 않아, 내용이 같으면 쓰지 않는다.
2. 커밋 status `merge-order` 를 head 커밋에 단다. 앞 PR 이 열려 있으면 pending(노란 대기, PR 의 결함이
   아니라 순서 정보다), 없으면 success, 순서를 판정하지 못하면(순환 등) error 다 — 판정 불능을 success 로 두지 않는다(원칙 7). 이미 같은 상태·설명이
   달려 있으면 쓰지 않는다(커밋·context 당 status 수에 한도가 있다).
3. 차례 알림. 코멘트 안에 직전에 계산한 "앞 PR" 목록을 숨겨 두고(`<!-- pr-queue:after=… -->`), 이번에
   앞 PR 이 하나도 없게 됐고 그 앞 PR 이 모두 병합됐으면 "이제 #n 차례" 를 알린다. 이벤트가 병합인지에
   기대지 않는 것은, 병합이 만든 main push 실행이 병합 실행을 취소해 알림이 사라지는 일(concurrency)을
   막기 위해서다. 알림은 작성자를 @멘션하는 짧은 새 코멘트(마커 코멘트를 고치면 알림이 안 간다)와
   Teams 다. Teams 는 환경변수 `TEAMS_PLUGIN_ALERT_WEBHOOK` 이 있을 때만 보내고, 없으면 건너뛴다.

차례 알림 코멘트를 못 남기거나 앞 PR 의 병합 여부를 못 읽으면 마커의 `after=` 를 이전 값으로 두어 다음 실행에서 다시
시도한다. Teams 전송 여부는 알림 코멘트의 표식(`pr-queue-teams:sent`)으로 남겨, 코멘트는 갔는데 Teams 만 못 갔으면
다음 실행에서 Teams 만 다시 보낸다.

종료코드: 0 완료, 1 쓰기 실패가 있음, 2 GitHub 를 읽지 못해 계산하지 못했거나 처리 중 예상 못 한 오류(통과가 아니다, 원칙 7).
포크에서 온 PR 의 이벤트와 Dependabot 이 일으킨 이벤트는 토큰이 읽기 전용이라 쓰지 않고 계산 결과만 요약에 남긴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

from checker import pr_queue
from checker.pr_queue import BEHIND_ORDER_NOTE, BOT_LOGIN, CYCLE_NOTE, MERGEABLE, PR_LIMIT
from checker.risk_gate import MERGE_ORDER_CHECK, _defuse, fetch_pr_comments
from checker.ssot_approval import GhClient, GhError

MARKER = "<!-- pr-queue -->"
TURN_MARKER = "pr-queue-turn"
STATUS_CONTEXT = MERGE_ORDER_CHECK
DESCRIPTION_LIMIT = 140
TEAMS_ENV = "TEAMS_PLUGIN_ALERT_WEBHOOK"

EXIT_OK = 0
EXIT_WRITE_FAILED = 1
EXIT_CANNOT_READ = 2
EXIT_UNEXPECTED = 2  # 처리 중 예상 못 한 오류. 쓰기 실패(1)와 달리 어디까지 썼는지 모르므로 읽기 불능과 같은 코드를 쓴다

_AFTER_MARK = re.compile(r"<!--\s*pr-queue:after=([0-9,?]*)\s*-->")
# 차례 알림 코멘트의 Teams 표식. sent 는 Teams 로 보냈음, na 는 보낼 때 웹훅이 없었음(나중에 웹훅이 생겨도 늦게 보내지 않는다).
TEAMS_SENT = "<!-- pr-queue-teams:sent -->"
TEAMS_NA = "<!-- pr-queue-teams:na -->"
_TURN_TAG = re.compile(r"<!--\s*" + TURN_MARKER + r":([0-9,]*)\s*-->")
READ_ONLY_ACTORS = frozenset({"dependabot[bot]"})  # 이 계정이 일으킨 실행은 토큰이 읽기 전용이다


# --- 판정 ---------------------------------------------------------------------


def _safe(text: object, limit: int = 200) -> str:
    """코멘트에 넣는 비신뢰 문자열(PR 제목·검사 이름·detail): 한 줄로 줄이고 `@` 멘션과 HTML·백틱·대괄호(가짜 링크)를 무력화한다."""
    out = _defuse(text, limit).replace("<", "&lt;").replace(">", "&gt;").replace("`", "\\`")
    return out.replace("[", "\\[").replace("]", "\\]")


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def decide_status(item: dict, result: dict) -> tuple[str, str]:
    """(status state, description). state 는 success / pending(앞 PR 대기, 결함 아님) / error(판정 불능)."""
    n = item["number"]
    if item["order"] is None:
        why = "; ".join(x for x in item["notes"] if x.startswith(CYCLE_NOTE) or x.startswith(BEHIND_ORDER_NOTE))
        return "error", _clip(f"병합 순서 판정 불능: {why or '순서를 정하지 못함'}", DESCRIPTION_LIMIT)
    if item["after"]:
        firsts = ", ".join(f"#{m}" for m in item["after"])
        by_number = {it["number"]: it for it in result["prs"]}
        first = by_number.get(item["after"][0], {})
        suffix = f" ({_clip(first.get('title', ''), 40)})" if len(item["after"]) == 1 and first else ""
        return "pending", _clip(f"{firsts} 병합 대기{suffix}", DESCRIPTION_LIMIT)
    unread = set(result.get("unread_versions") or [])
    if unread and (item.get("version") is not None or n in unread):
        return "error", "병합 순서 판정 불능: plugin.json version 을 읽지 못함"
    if result["truncated"]:
        return "error", f"병합 순서 판정 불능: 열린 PR 이 {PR_LIMIT}개 이상"
    return "success", "앞에 병합할 PR 없음"


def _after_lines(item: dict, by_number: dict[int, dict], repo: str) -> list[str]:
    lines = []
    for m in item["after"]:
        other = by_number.get(m, {})
        prefix = f"#{m}: "
        reasons = [r[len(prefix):] for r in item["after_reasons"] if r.startswith(prefix)]
        why = _safe("; ".join(reasons) or "이유 불명", 300)
        link = pr_queue.pr_link(repo, m, other.get("url") or "")
        lines.append(f"  - {link} {_safe(other.get('title', ''), 50)} — {why}")
    return lines


def render_comment(item: dict, result: dict, after_mark: str | None = None) -> str:
    """PR 하나의 코멘트 본문. 같은 입력이면 늘 같은 문자열이다.

    `after_mark` 를 주면 숨김 표식의 앞 PR 목록을 계산값 대신 그것으로 둔다(차례 알림을 못 보냈을 때 이전 값을 유지).
    """
    by_number = {it["number"]: it for it in result["prs"]}
    total = len(result["prs"])
    if after_mark is None:
        after_mark = "?" if item["order"] is None else ",".join(str(m) for m in item["after"])
    lines = [MARKER, f"<!-- pr-queue:after={after_mark} -->", "## 병합 순서", ""]
    if item["order"] is None:
        lines.append(f"- 병합 순서: **판정 불능** (열린 PR {total}개)")
        for note in item["notes"]:
            if note.startswith(CYCLE_NOTE) or note.startswith(BEHIND_ORDER_NOTE):
                lines.append(f"  - {_safe(note, 300)}")
    else:
        lines.append(f"- 병합 순서: **{item['order']}번째** (열린 PR {total}개 중)")
    if item["after"]:
        lines.append("- 앞에 병합할 PR:")
        lines.extend(_after_lines(item, by_number, result["repo"]))
    elif item["order"] is not None:
        lines.append("- 앞에 병합할 PR: 없음")
    state = item["state"] + (f": {_safe(item['detail'], 300)}" if item["detail"] else "")
    lines.append(f"- 지금 상태: {state}")
    nxt = _safe(item["next"], 300)
    if item["after"] and item["state"] == MERGEABLE:
        nxt = f"앞의 PR 이 병합된 뒤 {nxt}"
    lines.append(f"- 다음 할 일: {nxt}")
    for note in item["notes"]:
        if not (note.startswith(CYCLE_NOTE) or note.startswith(BEHIND_ORDER_NOTE)):
            lines.append(f"- 참고: {_safe(note, 300)}")
    lines += [
        "",
        "순서가 틀렸으면 PR 본문의 `먼저: #번호` 줄을 고친다. 이 코멘트는 PR·리뷰·main 이벤트 때 갱신된다 — "
        "검사 결과는 다음 이벤트까지 낡을 수 있으니 정확한 지금 상태는 `/harness:prs` 로 본다. "
        "GitHub 의 `merge-order` 검사가 빨간불이어도 Merge 버튼은 잠기지 않는다(무료 요금제) — 순서를 지켜 병합한다.",
    ]
    return "\n".join(lines)


def previous_after_mark(comments: list[dict]) -> str | None:
    """직전 마커 코멘트에 숨겨 둔 `after=` 원문(예: "1,3", 비면 ""). 코멘트가 없거나 표식이 없으면 None."""
    mine = _marker_comment(comments)
    if mine is None:
        return None
    m = _AFTER_MARK.search(mine.get("body") or "")
    return m.group(1) if m else None


def previous_after(comments: list[dict]) -> set[int] | None:
    """직전 마커 코멘트에 숨겨 둔 앞 PR 목록. 코멘트가 없거나 판정 불능이었으면 None."""
    raw = previous_after_mark(comments)
    if raw is None or "?" in raw:
        return None
    return {int(x) for x in raw.split(",") if x}


def _marker_comment(comments: list[dict]) -> dict | None:
    found = [
        c for c in comments if ((c.get("user") or {}).get("login")) == BOT_LOGIN and MARKER in (c.get("body") or "")
    ]
    return found[-1] if found else None


# --- 알림 ---------------------------------------------------------------------


def turn_body(item: dict, merged: list[int], titles: dict[int, str], repo: str) -> str:
    done = ", ".join(f"{pr_queue.pr_link(repo, m)}({_safe(titles.get(m, ''), 30)})" for m in merged)
    tag = _turn_tag(merged)
    state = item["state"] + (f": {_safe(item['detail'], 300)}" if item["detail"] else "")
    me = pr_queue.pr_link(repo, item["number"], item.get("url") or "")
    return (
        f"{tag}\n@{item['author']} 이제 {me} 이 병합할 차례입니다. 앞에 있던 {done} 이 병합됐습니다.\n"
        f"지금 상태: {state}\n다음 할 일: {_safe(item['next'], 300)}"
    )


def _turn_tag(merged: list[int]) -> str:
    return f"<!-- {TURN_MARKER}:{','.join(str(m) for m in merged)} -->"


def teams_payload(item: dict, merged: list[int], repo: str) -> dict:
    heading = f"PR {pr_queue.pr_link(repo, item['number'], item.get('url') or '')}: 이제 병합할 차례"
    state = item["state"] + (f": {_safe(item['detail'], 300)}" if item["detail"] else "")
    done = ", ".join(pr_queue.pr_link(repo, m) for m in merged)
    details = (
        f"{_safe(item['title'], 200)} — 작성자 {item['author']}. 앞의 {done} 이 병합됐다. "
        f"지금 상태: {state}. 다음 할 일: {_safe(item['next'], 300)}"
    )
    body = [
        {"type": "TextBlock", "text": heading, "weight": "Bolder", "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": details, "wrap": True},
    ]
    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if item.get("url"):
        card["actions"] = [{"type": "Action.OpenUrl", "title": "PR 열기", "url": item["url"]}]
    return {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}],
    }


class TeamsError(Exception):
    """Teams 전송 실패. `reason` 은 요약에 그대로 나가도 되는 짧은 말(HTTP 상태코드나 예외 종류)뿐이다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def post_teams(webhook: str, payload: dict) -> None:
    """Teams 웹훅으로 보낸다. 2xx 가 아니면 예외. 웹훅 URL 은 비밀이라 어떤 예외든 메시지를 싣지 않고 종류만 남긴다."""
    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - 웹훅 URL 은 저장소 시크릿
            status = resp.status
    except urllib.error.HTTPError as exc:
        raise TeamsError(f"HTTP {exc.code}") from None
    except Exception as exc:  # noqa: BLE001 - 메시지에 URL 이 들어 있을 수 있어 종류만 남긴다
        raise TeamsError(type(exc).__name__) from None
    if not 200 <= status < 300:
        raise TeamsError(f"HTTP {status}")


def _teams_failure_reason(exc: Exception) -> str:
    """요약에 남길 Teams 실패 사유. 예외 메시지는 쓰지 않는다(웹훅 값이 들어 있을 수 있다)."""
    return exc.reason if isinstance(exc, TeamsError) else type(exc).__name__


# --- 쓰기 ---------------------------------------------------------------------


def _write_comment(client: Any, repo: str, number: int, body: str, existing: dict | None) -> str:
    if existing is not None:
        if (existing.get("body") or "") == body:
            return "unchanged"
        client.run(["api", "-X", "PATCH", f"repos/{repo}/issues/comments/{existing['id']}", "-f", f"body={body}"])
        return "updated"
    client.run(["api", "-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f", f"body={body}"])
    return "created"


def _write_status(client: Any, repo: str, sha: str, state: str, description: str) -> str:
    try:
        combined = client.get_json(f"repos/{repo}/commits/{sha}/status") or {}
        for s in combined.get("statuses") or []:
            if s.get("context") == STATUS_CONTEXT and s.get("state") == state and (s.get("description") or "") == description:
                return "unchanged"
    except GhError:
        pass  # 현재 상태를 못 읽어도 쓰는 쪽이 안전하다(같은 값이면 한 번 더 쓸 뿐)
    client.run(
        [
            "api", "-X", "POST", f"repos/{repo}/statuses/{sha}",
            "-f", f"state={state}", "-f", f"context={STATUS_CONTEXT}", "-f", f"description={description}",
        ]
    )
    return "written"


class Report:
    def __init__(self) -> None:
        self.comments = {"created": 0, "updated": 0, "unchanged": 0}
        self.statuses = {"written": 0, "unchanged": 0}
        self.notified: list[str] = []
        self.skipped: list[str] = []
        self.read_errors: list[str] = []
        self.write_errors: list[str] = []
        self.rows: list[str] = []

    def exit_code(self) -> int:
        if self.read_errors:
            return EXIT_CANNOT_READ
        return EXIT_WRITE_FAILED if self.write_errors else EXIT_OK

    def render(self, repo: str, read_only_reason: str | None) -> str:
        lines = ["## pr-queue", ""]
        if read_only_reason:
            lines.append(f"- 쓰지 않음: {read_only_reason}")
        lines.append(
            f"- 코멘트: 만듦 {self.comments['created']}, 갱신 {self.comments['updated']}, "
            f"변경 없음 {self.comments['unchanged']}"
        )
        lines.append(f"- merge-order status: 씀 {self.statuses['written']}, 이미 같음 {self.statuses['unchanged']}")
        for text in self.notified:
            lines.append(f"- 차례 알림: {text}")
        for text in self.skipped:
            lines.append(f"- 건너뜀: {text}")
        if self.rows:
            lines += ["", "| PR | 순서 | merge-order |", "|---|---|---|", *self.rows]
        for text in self.read_errors:
            lines.append(f"- 읽기 실패: {text}")
        for text in self.write_errors:
            lines.append(f"- 쓰기 실패: {text}")
        if self.write_errors:
            lines.append(
                "- 쓰기 실패가 403 이면 caller 의 permissions 에 pull-requests: write, issues: write, "
                "statuses: write 가 있는지 본다."
            )
        return "\n".join(lines)


def apply(
    client: Any,
    repo: str,
    result: dict,
    *,
    write: bool = True,
    webhook: str = "",
    teams: Callable[[str, dict], None] = post_teams,
) -> Report:
    """계산 결과를 GitHub 에 쓴다. PR 한 건의 읽기·쓰기가 실패해도 다음 PR 로 넘어간다."""
    report = Report()
    prs = result["prs"]
    by_number = {it["number"]: it for it in prs}
    titles = {it["number"]: it["title"] for it in prs}
    merged_cache: dict[int, bool] = {}

    def is_merged(m: int) -> bool:
        if m not in merged_cache:
            data = client.get_json(f"repos/{repo}/pulls/{m}") or {}
            merged_cache[m] = bool(data.get("merged"))
            if data.get("title"):
                titles[m] = data["title"]  # 병합돼 열린 목록에서 사라진 PR 의 제목
        return merged_cache[m]

    for item in prs:
        n = item["number"]
        state, description = decide_status(item, result)
        report.rows.append(f"| #{n} | {item['order'] if item['order'] is not None else '?'} | {state}: {description} |")
        if not write:
            continue
        try:
            comments = fetch_pr_comments(client, repo, n)
        except GhError as exc:
            report.read_errors.append(f"#{n} 의 코멘트를 읽지 못함: {exc}")
            continue
        prev = previous_after(comments)
        keep_mark: str | None = None  # 알림을 못 보냈으면 이전 after= 를 유지해 다음 실행에서 다시 시도되게 한다

        # 차례 알림: 앞 PR 이 있었는데 이제 없다 + 사라진 앞 PR 이 모두 병합됐다.
        if prev and item["order"] is not None and not item["after"]:
            try:
                all_merged = all(is_merged(m) for m in prev)
            except GhError as exc:
                report.skipped.append(f"#{n} 차례 알림 — 앞 PR 의 병합 여부를 읽지 못함({exc}), 다음 실행에서 다시 시도")
                all_merged = False
                keep_mark = previous_after_mark(comments)
            if all_merged and not _notify_turn(
                client, repo, item, sorted(prev), comments, titles, webhook, teams, report
            ):
                keep_mark = previous_after_mark(comments)
        # 알림 코멘트는 남았는데 Teams 만 못 보낸 것(웹훅이 있을 때)을 다시 보낸다.
        _retry_teams(client, repo, item, comments, webhook, teams, report)

        body = render_comment(item, result, keep_mark)
        try:
            outcome = _write_comment(client, repo, n, body, _marker_comment(comments))
            report.comments[outcome] += 1
        except GhError as exc:
            report.write_errors.append(f"#{n} 코멘트: {exc}")
        sha = item.get("sha")
        if not sha:
            report.write_errors.append(f"#{n} status: head 커밋을 읽지 못함")
            continue
        try:
            report.statuses[_write_status(client, repo, sha, state, description)] += 1
        except GhError as exc:
            report.write_errors.append(f"#{n} status: {exc}")
    return report


def _notify_turn(
    client: Any,
    repo: str,
    item: dict,
    merged: list[int],
    comments: list[dict],
    titles: dict[int, str],
    webhook: str,
    teams: Callable[[str, dict], None],
    report: Report,
) -> bool:
    """차례 알림 코멘트를 남기고 Teams 로 보낸다. 알림 코멘트가 (이미든 지금이든) 남았으면 True, 못 남겼으면 False."""
    n = item["number"]
    tag = _turn_tag(merged)
    if _bot_comments_with(comments, tag):
        return True  # 같은 알림을 이미 했다(Teams 가 빠졌으면 _retry_teams 가 다시 보낸다)
    body = turn_body(item, merged, titles, repo) + "\n" + (TEAMS_NA if not webhook else "")
    body = body.rstrip("\n")
    try:
        out = client.run(["api", "-X", "POST", f"repos/{repo}/issues/{n}/comments", "-f", f"body={body}"])
    except GhError as exc:
        report.write_errors.append(f"#{n} 차례 알림 코멘트: {exc}")
        return False
    sent = ["PR 코멘트"]
    if webhook:
        if _send_teams(item, merged, webhook, teams, report, repo):
            sent.append("Teams")
            _mark_teams_sent(client, repo, n, out, body, tag, report)
    else:
        report.skipped.append(f"#{n} Teams 알림 — {TEAMS_ENV} 이 비어 있다")
    report.notified.append(f"#{n} @{item['author']} ({', '.join(sent)})")
    return True


def _bot_comments_with(comments: list[dict], tag: str) -> list[dict]:
    """봇이 쓴 코멘트 중 `tag` 가 든 것. 다른 사람이 표식을 흉내 내 알림을 막지 못하게 작성자를 본다."""
    return [c for c in comments if ((c.get("user") or {}).get("login")) == BOT_LOGIN and tag in (c.get("body") or "")]


def _send_teams(
    item: dict, merged: list[int], webhook: str, teams: Callable[[str, dict], None], report: Report, repo: str = ""
) -> bool:
    try:
        teams(webhook, teams_payload(item, merged, repo))
        return True
    except Exception as exc:  # noqa: BLE001 - Teams 실패는 코멘트 알림이 남은 뒤의 일이라 경고로만 두고 다음 실행에서 다시 보낸다
        report.skipped.append(f"#{item['number']} Teams 전송 실패({_teams_failure_reason(exc)}), 다음 실행에서 다시 시도")
        return False


def _mark_teams_sent(client: Any, repo: str, n: int, post_out: Any, body: str, tag: str, report: Report) -> None:
    """알림 코멘트에 Teams 전송 표식을 덧붙인다. 코멘트 id 는 POST 응답에서, 없으면 코멘트를 다시 읽어 찾는다."""
    cid = None
    try:
        cid = json.loads(post_out).get("id") if post_out else None
    except (ValueError, AttributeError):
        cid = None
    try:
        if cid is None:
            found = _bot_comments_with(fetch_pr_comments(client, repo, n), tag)
            cid = found[-1].get("id") if found else None
        if cid is None:
            raise GhError("알림 코멘트를 찾지 못함")
        client.run(
            ["api", "-X", "PATCH", f"repos/{repo}/issues/comments/{cid}", "-f", f"body={body}\n{TEAMS_SENT}"]
        )
    except GhError as exc:
        report.skipped.append(f"#{n} Teams 전송 표식을 못 남김({exc}) — 다음 실행에서 Teams 가 다시 갈 수 있다")


def _retry_teams(
    client: Any,
    repo: str,
    item: dict,
    comments: list[dict],
    webhook: str,
    teams: Callable[[str, dict], None],
    report: Report,
) -> None:
    """차례 알림 코멘트는 있는데 Teams 전송 표식이 없으면(웹훅이 있을 때) Teams 만 다시 보낸다."""
    if not webhook:
        return
    n = item["number"]
    for c in comments:
        body = c.get("body") or ""
        if ((c.get("user") or {}).get("login")) != BOT_LOGIN or TEAMS_SENT in body or TEAMS_NA in body:
            continue
        m = _TURN_TAG.search(body)
        if not m or c.get("id") is None:
            continue
        merged = [int(x) for x in m.group(1).split(",") if x]
        if _send_teams(item, merged, webhook, teams, report, repo):
            report.notified.append(f"#{n} @{item['author']} (Teams 재전송)")
            _mark_teams_sent(client, repo, n, json.dumps({"id": c["id"]}), body, _turn_tag(merged), report)


# --- CLI ----------------------------------------------------------------------


def fork_reason(event_path: str | None, repo: str) -> str | None:
    """이벤트의 PR 이 포크에서 왔거나 읽기 전용 토큰을 쓰는 계정(Dependabot)이 일으켰으면 쓰지 않는 사유를 낸다.

    이벤트를 못 읽으면 None(쓰기를 시도한다).
    """
    if not event_path or not os.path.isfile(event_path):
        return None
    try:
        with open(event_path, encoding="utf-8") as fh:
            event = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(event, dict):
        return None
    sender = event.get("sender")
    actor = (sender.get("login") if isinstance(sender, dict) else None) or os.environ.get("GITHUB_ACTOR") or ""
    if str(actor).lower() in READ_ONLY_ACTORS:
        return f"{actor} 가 일으킨 실행이라 토큰이 읽기 전용이다. 코멘트·status 는 다음 PR 이벤트(이 PR 의 다음 푸시나 다른 PR 의 열기·닫기)에서 갱신된다"
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        return None
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    if head_repo is None or head_repo.lower() != repo.lower():
        return "포크에서 온 PR 의 이벤트라 토큰이 읽기 전용이다. 코멘트·status 는 다음 PR 이벤트(이 PR 의 다음 푸시나 다른 PR 의 열기·닫기)에서 갱신된다"
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="checker.pr_queue_actions", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/repo")
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"), help="이벤트 payload JSON")
    parser.add_argument("--summary-file", default=os.environ.get("GITHUB_STEP_SUMMARY"), help="요약을 덧붙일 파일")
    return parser


def _write_summary(path: str | None, text: str) -> None:
    print(text)
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError as exc:
            print(f"요약 파일을 쓰지 못했다: {exc}", file=sys.stderr)


def run(args: argparse.Namespace, client: Any = None, teams: Callable[[str, dict], None] = post_teams) -> int:
    client = client or GhClient()
    if not args.repo:
        _write_summary(args.summary_file, "## pr-queue\n\n- PR 순서 확인 불능 — 저장소(--repo)를 알 수 없다. 통과로 보지 않는다.")
        return EXIT_CANNOT_READ
    try:
        result = pr_queue.compute(client, args.repo)
    except GhError as exc:
        _write_summary(args.summary_file, f"## pr-queue\n\n- PR 순서 확인 불능 — {exc}. 통과로 보지 않는다.")
        return EXIT_CANNOT_READ
    except Exception as exc:  # noqa: BLE001 - 어떤 오류도 통과로 보이면 안 된다(원칙 7)
        _write_summary(
            args.summary_file,
            f"## pr-queue\n\n- PR 순서 확인 불능 — 예상 못 한 오류 {type(exc).__name__}. 통과로 보지 않는다.",
        )
        return EXIT_CANNOT_READ
    reason = fork_reason(args.event_path, args.repo)
    try:
        report = apply(
            client,
            args.repo,
            result,
            write=reason is None,
            webhook=os.environ.get(TEAMS_ENV, ""),
            teams=teams,
        )
    except Exception as exc:  # noqa: BLE001 - 쓰기 실패(1)와 구분한다. 어떤 오류도 통과로 보이면 안 된다(원칙 7)
        _write_summary(
            args.summary_file,
            f"## pr-queue\n\n- PR 순서 처리 중 예상 못 한 오류 {type(exc).__name__}. 통과로 보지 않는다.",
        )
        return EXIT_UNEXPECTED
    _write_summary(args.summary_file, report.render(args.repo, reason))
    return report.exit_code()


def main(argv: list[str] | None = None) -> int:
    pr_queue._force_utf8()
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
