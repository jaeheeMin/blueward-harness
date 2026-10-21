"""열린 PR 의 상태와 병합 순서를 GitHub 에서 한 번 계산해 보여 준다(#370).

    python -m checker.pr_queue --repo owner/repo [--mine | --all] [--json] [--quiet-empty] [--verbose]

팀원이 자기 PR 이 어디까지 왔는지, 무엇부터 병합해야 하는지 모른다. 여러 세션에서 PR 을 만들면
세션끼리도 모른다. 세션 시작 훅과 `/harness:prs` 와 deliver 가 이 모듈 한 곳에서 같은 계산을 받는다.

PR 상태(우선순위대로 하나만 고르고, 나머지는 보조로 덧붙인다):
초안 > 충돌 > 검사 시작 전(롤업이 비어 있음) > 검사 실패 > 검사 중 > 승인 대기 > 충돌 여부 확인 중 >
뒤처짐·병합 막힘·검사 불안정(mergeStateStatus BEHIND·BLOCKED·UNSTABLE) > 병합 가능(CLEAN·HAS_HOOKS 뿐).
`mergeable` 이 UNKNOWN 인 것은 GitHub 가 아직 계산 중이라는 뜻이지 충돌이 없다는 뜻이 아니다.
`risk-gate` 실패를 곧바로 승인 대기로 말하지 않는다. 실패한 PR 만 github-actions 봇의 마지막
`<!-- risk-gate -->` 코멘트를 읽어, "승인이 필요합니다" 일 때만 승인 대기(리뷰를 읽어 head 커밋 기준
남은 승인자 계산)로 말한다. 다른 사유면 "risk-gate: 사유 요약", 코멘트를 못 읽으면 "risk-gate 실패
(사유는 PR 코멘트)" 다. `ssot-approval` 실패는 SRS 승인 대기이므로 리뷰로 판정한다(전체 PR 에 판정을
돌리지 않는다).

병합 순서(앞 PR 이 병합돼야 뒤 PR 이 의미 있는 관계):
  (a) PR 의 base 브랜치가 다른 열린 PR 의 head 브랜치이면 그 PR 뒤.
  (b) 본문의 `먼저: #n, #m` 줄에 적은 열린 PR 뒤.
  (c) 같은 DEV 번호면 SRS → Spec → 개발 순. SRS PR 은 `docs/ssot/SRS.md` 를 바꾼 PR, Spec PR 은
      `docs/spec/DEV-xxx-*.md` 를 바꾼 PR, 개발 PR 은 제목·브랜치에 DEV 번호가 있는 그 밖의 PR 이다.
      DEV 번호는 제목(끝 `(DEV-n, DEV-m)` 포함)·브랜치·바꾼 Spec 파일 이름의 `DEV-n`·`REQ-n` 에서 읽고(REQ-n == DEV-n),
      모두 비면 본문에서 처음 나온 번호 하나만 쓴다(#407. 본문에 스쳐 지나간 번호로 묶으면 상관없는 DEV 가 막힌다).
      SRS 파일의 diff 는 읽지 않는다.
  (d) plugin.json 을 바꾼 PR 끼리(하네스 저장소)는 head 의 version 이 낮은 쪽 먼저.
위상 정렬하고 동률은 PR 번호 오름차순이다. 실제 순환(강연결 성분)의 구성원만 "순서 판정 불능(순환)" 이고,
그 뒤에 기다리는 PR 은 "앞 PR 순서 판정 불능 #…" 으로 남긴다.
같은 파일을 고친 PR 쌍은 순서를 바꾸지 않고 경고만 한다.

`--pr N` 은 PR 한 건보다 먼저 병합해야 하는 열린 PR 만 묻는다(병합 직전 훅용, 상태 판정은 하지 않는다).
종료코드 0 앞 PR 없음, 1 있음, 2 확인 불능(순환·순서 판정 불능 포함).

GitHub 를 읽지 못하면 "PR 상태 확인 불능" 이고 종료코드 2 다(통과도 문제없음도 아니다, 원칙 7).
PR 한 건의 승인·version 만 못 읽으면 그 PR 만 "확인 불능" 으로 두고 나머지는 계산한다. 예상 못 한
예외도 "확인 불능(예상 못 한 오류 <종류>)" 종료코드 2 로 낸다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from checker.plugin_version import PLUGIN_JSON, parse_version
from checker.risk_gate import MERGE_ORDER_CHECK, PR_QUEUE_CHECK, _check_group, _is_excluded_check, _run_state, fetch_pr_comments
from checker.ssot_approval import (
    NO_APPROVER_FOR_AUTHOR,
    GhClient,
    GhError,
    approvers_for,
    fetch_approver_rules,
    fetch_human_merge_paths,
    fetch_pr_reviews,
    human_merge_hits,
    judge_by_rules,
)

EXIT_OK = 0
EXIT_BEFORE_OPEN = 1  # --pr: 먼저 병합해야 하는 열린 PR 이 있다
EXIT_CANNOT_CHECK = 2

PR_LIMIT = 100
GATE_GROUPS = frozenset({"risk-gate", "ssot-approval"})
PR_FIELDS = (
    "number,title,author,baseRefName,headRefName,headRefOid,isDraft,mergeable,"
    "mergeStateStatus,statusCheckRollup,files,body,url"
)

# 상태 이름. 사람용 표와 JSON 이 같은 값을 쓴다.
DRAFT = "초안"
CONFLICT = "충돌"
CHECK_FAILED = "검사 실패"
CHECKING = "검사 중"
WAITING_APPROVAL = "승인 대기"
MERGE_UNKNOWN = "충돌 여부 확인 중"
MERGEABLE = "병합 가능"
UNKNOWN = "확인 불능"
NOT_STARTED = "검사 시작 전"
BEHIND = "base 보다 뒤처짐"
BLOCKED = "병합 막힘"
UNSTABLE = "검사 불안정"
CYCLE_NOTE = "순서 판정 불능(순환)"
BEHIND_ORDER_NOTE = "앞 PR 순서 판정 불능"
RISK_GATE_MARKER = "<!-- risk-gate -->"
BOT_LOGIN = "github-actions[bot]"
MAX_ROWS_NOTE_LIMIT = 3

_FIRST_LINE = re.compile(r"^\s*먼저\s*[:：]\s*(.+)$", re.MULTILINE)
_PR_REF = re.compile(r"#(\d+)")
_DEV_REF = re.compile(r"(?:DEV|REQ)-0*(\d+)", re.IGNORECASE)
_SPEC_FILE = re.compile(r"^docs/spec/DEV-0*(\d+)-", re.IGNORECASE)
SRS_PATH = "docs/ssot/SRS.md"
_STAGE_NAME = {0: "SRS", 1: "Spec", 2: "개발"}


# --- 읽기 ---------------------------------------------------------------------


def _load_prs(client: GhClient, repo: str) -> list[dict]:
    raw = client.run(
        ["pr", "list", "--repo", repo, "--state", "open", "--limit", str(PR_LIMIT), "--json", PR_FIELDS]
    )
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise GhError(f"gh pr list 의 출력을 해석하지 못했다: {exc}") from exc
    if not isinstance(data, list):
        raise GhError("gh pr list 의 출력이 목록이 아니다")
    return data


def _login(client: GhClient) -> str:
    user = client.get_json("user")
    login = (user or {}).get("login") if isinstance(user, dict) else None
    if not login:
        raise GhError("gh api user 에서 로그인 계정을 읽지 못했다")
    return login


def _default_repo(client: GhClient) -> str:
    out = client.run(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()
    if not out:
        raise GhError("현재 폴더의 GitHub 저장소를 알아내지 못했다")
    return out


def _head_plugin_version(client: GhClient, repo: str, sha: str) -> str:
    import base64

    data = client.get_json_or_none_404(f"repos/{repo}/contents/{PLUGIN_JSON}?ref={sha}")
    if not data:
        raise GhError(f"head({sha[:7]}) 에서 {PLUGIN_JSON} 를 찾지 못했다")
    try:
        text = base64.b64decode(data.get("content", "") or "").decode("utf-8", errors="replace")
        version = json.loads(text)["version"]
        parse_version(version)
    except (ValueError, KeyError, TypeError) as exc:
        raise GhError(f"head({sha[:7]}) 의 {PLUGIN_JSON} version 을 읽지 못했다: {exc}") from exc
    return version


# --- 상태 판정 ----------------------------------------------------------------


def _norm_check(entry: dict) -> dict:
    """statusCheckRollup 항목(CheckRun, StatusContext)을 risk_gate 가 읽는 모양으로."""
    if "context" in entry and "name" not in entry:
        state = (entry.get("state") or "").upper()
        if state == "SUCCESS":
            return {"name": entry["context"], "status": "completed", "conclusion": "success"}
        if state in ("PENDING", "EXPECTED"):
            return {"name": entry["context"], "status": "in_progress", "conclusion": ""}
        return {"name": entry["context"], "status": "completed", "conclusion": "failure"}
    return {
        "name": entry.get("name") or "",
        "status": (entry.get("status") or "").lower(),
        "conclusion": (entry.get("conclusion") or "").lower(),
    }


def _latest_runs(entries: list[dict]) -> list[dict]:
    """같은 검사(워크플로+이름, 커밋 status 는 context)는 가장 최근 실행 하나만 남긴다(#375).

    다시 돌린 검사의 앞 실행(취소 등)이 롤업에 남아 실패로 세지는 것을 막는다. 같은 검사 가운데
    시작·끝 시각을 모르는 실행이 있으면 어느 것이 최신인지 알 수 없으니 그 검사는 줄이지 않는다.
    """
    groups: dict[tuple, list[dict]] = {}
    for e in entries:
        if "context" in e and "name" not in e:
            key = ("status", e.get("context") or "")
        else:
            key = ("check", e.get("workflowName") or "", e.get("name") or "")
        groups.setdefault(key, []).append(e)
    kept: list[dict] = []
    for group in groups.values():
        times = [e.get("startedAt") or e.get("completedAt") or "" for e in group]
        if len(group) == 1 or not all(times):
            kept.extend(group)
            continue
        kept.append(group[max(range(len(group)), key=lambda i: times[i])])
    return kept


def _short_names(runs: list[dict], limit: int = 3) -> str:
    names = [r["name"] or "이름 없는 검사" for r in runs]
    return ", ".join(names[:limit]) + (f" 등 {len(names)}개" if len(names) > limit else "")


class _Context:
    """저장소 단위로 한 번만 읽는 값들."""

    def __init__(self, client: GhClient, repo: str):
        self.client = client
        self.repo = repo
        self._rules: dict[str, Any] = {}
        self._human: dict[str, list[str]] = {}

    def rules(self, base: str):
        if base not in self._rules:
            self._rules[base] = fetch_approver_rules(self.client, self.repo, base)
        return self._rules[base]

    def human_paths(self, base: str) -> list[str]:
        if base not in self._human:
            self._human[base] = fetch_human_merge_paths(self.client, self.repo, base)
        return self._human[base]


def _approval_state(ctx: _Context, raw: dict, author: str) -> dict:
    """게이트 검사가 실패한 PR 의 승인 여부. 승인됐으면 {"approved": True}."""
    base = raw.get("baseRefName") or "main"
    head = raw.get("headRefOid") or None
    if not head:
        raise GhError("PR 의 head 커밋을 읽지 못했다")
    rules = ctx.rules(base)
    reviews = fetch_pr_reviews(ctx.client, ctx.repo, raw["number"])
    approved, reason, stale = judge_by_rules(author, reviews, rules, head)
    if approved:
        return {"approved": True}
    if rules.has_entries:
        eligible = sorted(approvers_for(rules, author))
    else:
        eligible = []
    return {
        "approved": False,
        "reason": reason,
        "eligible": eligible,
        "anyone": not rules.has_entries,
        "stale": [s["login"] for s in stale],
        "no_approver": reason == NO_APPROVER_FOR_AUTHOR,
    }


def _risk_gate_view(ctx: _Context, number: int) -> tuple[str, str]:
    """risk-gate 봇 코멘트(마지막 것)를 읽어 (종류, 사유 요약) 을 낸다.

    종류: approval(승인이 필요), unable(위험도 검사 불능), approved(코멘트는 승인됨), other(그 밖),
    missing(코멘트가 없음). 코멘트를 못 읽으면 GhError.
    """
    comments = fetch_pr_comments(ctx.client, ctx.repo, number)
    mine = [
        c
        for c in comments
        if ((c.get("user") or {}).get("login")) == BOT_LOGIN and RISK_GATE_MARKER in (c.get("body") or "")
    ]
    if not mine:
        return "missing", ""
    body = mine[-1].get("body") or ""
    reasons: list[str] = []
    in_reasons = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("이유"):
            in_reasons = True
        elif in_reasons and stripped.startswith("- "):
            reasons.append(stripped[2:].strip())
        elif in_reasons and not stripped:
            if reasons:
                break
    summary = ""
    if reasons:
        summary = _clip(reasons[0], 60) + (f" 외 {len(reasons) - 1}건" if len(reasons) > 1 else "")
    if "검사 불능" in body:
        return "unable", "위험도 검사 불능(저장소 소유자에게 알려야 함)"
    if "사람의 승인이 필요합니다" in body:
        return "approval", summary
    if "승인됨" in body:
        return "approved", "코멘트는 승인됨이나 검사는 실패 — 최신 실행을 확인"
    return "other", summary


def _approval_result(
    ctx: _Context, raw: dict, author: str, gate_names: str, reason_text: str, notes: list[str]
) -> dict:
    def out(state: str, detail: str, nxt: str) -> dict:
        return {"state": state, "detail": detail, "next": nxt, "notes": notes, "human_merge": False}

    try:
        appr = _approval_state(ctx, raw, author)
    except GhError as exc:
        return out(UNKNOWN, f"승인 여부를 읽지 못함: {exc}", "잠시 뒤 다시 확인")
    if appr["approved"]:
        return out(
            CHECK_FAILED,
            gate_names,
            "승인은 받았지만 게이트가 실패 — PR 의 검사 결과에서 사유를 확인",
        )
    if appr["no_approver"]:
        who = "이 작성자의 PR 을 승인할 사람이 정해져 있지 않음"
        nxt = "사람이 .github/ssot-approvers 를 확인"
    else:
        names = "누구든(작성자 제외)" if appr["anyone"] else ", ".join(appr["eligible"])
        who = f"{names} 의 승인 필요"
        if appr["stale"]:
            who += f" — 낡은 승인 포함({', '.join(appr['stale'])}: 새 커밋 뒤 다시 승인 필요)"
        nxt = "승인자에게 최신 커밋을 보고 Approve 해 달라고 요청"
    if reason_text:
        who += f" — 이유: {reason_text}"
    return out(WAITING_APPROVAL, who, nxt)


def classify(ctx: _Context, raw: dict) -> dict:
    """PR 하나의 상태를 정한다. {"state", "detail", "next", "notes", "human_merge"}."""
    author = ((raw.get("author") or {}).get("login")) or ""
    checks = [_norm_check(e) for e in _latest_runs(raw.get("statusCheckRollup") or [])]
    mergeable = (raw.get("mergeable") or "").upper()
    merge_state = (raw.get("mergeStateStatus") or "").upper()
    notes: list[str] = []

    def out(state: str, detail: str, nxt: str, human: bool = False) -> dict:
        return {"state": state, "detail": detail, "next": nxt, "notes": notes, "human_merge": human}

    if raw.get("isDraft"):
        return out(DRAFT, "", "준비되면 GitHub 에서 Ready for review 로 바꾸기")
    if mergeable == "CONFLICTING" or merge_state == "DIRTY":
        return out(CONFLICT, "", "/harness:sync 로 base 를 당겨받아 충돌을 풀고 다시 푸시")

    # `merge-order` status(pr-queue 워크플로, #370)는 순서 표시일 뿐이라 검사 상태로 세지 않는다.
    # 앞 PR 이 열려 있어 pending(#401 전엔 failure)이면 GitHub 가 mergeStateStatus 를 UNSTABLE 로 보이는데, 그것도 같은 사유다.
    merge_order = [c for c in checks if _check_group(c["name"]) == MERGE_ORDER_CHECK]
    checks = [c for c in checks if _check_group(c["name"]) not in (MERGE_ORDER_CHECK, PR_QUEUE_CHECK)]
    if merge_state == "UNSTABLE" and any(_run_state(c) in ("fail", "pending") for c in merge_order):
        merge_state = "CLEAN"
    if not checks:
        return out(NOT_STARTED, "아직 시작된 검사가 없음", "검사가 시작될 때까지 기다리기(오래 걸리면 다시 푸시)")

    gate_failed = [c for c in checks if _check_group(c["name"]) in GATE_GROUPS and _run_state(c) == "fail"]
    others = [c for c in checks if not (_is_excluded_check(c["name"]) or _is_excluded_alert(c["name"]))]
    failed = [c for c in others if _run_state(c) == "fail"]
    pending = [c for c in checks if _run_state(c) == "pending" and not _is_excluded_alert(c["name"])]

    if failed:
        return out(CHECK_FAILED, _short_names(failed), "실패한 검사의 로그를 보고 고쳐 다시 푸시")
    if pending:
        return out(CHECKING, _short_names(pending), "검사가 끝날 때까지 기다리기")
    if gate_failed:
        gate_names = _short_names(gate_failed)
        reason_text = ""
        if any(_check_group(c["name"]) == "risk-gate" for c in gate_failed):
            # risk-gate 실패가 곧 승인 대기는 아니다. 봇 코멘트의 사유를 읽어 가른다.
            try:
                kind, summary = _risk_gate_view(ctx, raw["number"])
            except GhError:
                kind, summary = "unreadable", ""
            if kind in ("missing", "unreadable"):
                return out(CHECK_FAILED, "risk-gate 실패(사유는 PR 코멘트)", "PR 의 risk-gate 코멘트와 검사 결과를 확인")
            if kind != "approval":
                return out(CHECK_FAILED, f"risk-gate: {summary or '사유는 PR 코멘트'}", "PR 의 risk-gate 코멘트를 보고 처리")
            reason_text = summary
        return _approval_result(ctx, raw, author, gate_names, reason_text, notes)
    if mergeable in ("UNKNOWN", ""):
        return out(MERGE_UNKNOWN, "GitHub 가 계산 중(충돌 없음이 아님)", "잠시 뒤 다시 확인")
    if merge_state == "BEHIND":
        return out(BEHIND, "", "/harness:sync 로 base 를 당겨받고 다시 푸시")
    if merge_state == "BLOCKED":
        return out(BLOCKED, "필수 리뷰나 검사 등 병합 조건이 남음", "PR 의 병합 조건(Checks·Reviews)을 확인")
    if merge_state == "UNSTABLE":
        return out(UNSTABLE, "일부 검사가 실패했거나 진행 중", "PR 의 검사 결과를 확인")
    if merge_state not in ("CLEAN", "HAS_HOOKS"):
        return out(MERGE_UNKNOWN, f"mergeStateStatus {merge_state or '없음'}", "잠시 뒤 다시 확인")

    base = raw.get("baseRefName") or "main"
    try:
        hits = human_merge_hits([f["path"] for f in raw.get("files") or []], ctx.human_paths(base))
    except GhError as exc:
        notes.append(f"사람이 병합할 경로인지 확인 불능({exc})")
        hits = []
    if hits:
        return out(MERGEABLE, "사람이 GitHub 에서 병합", "사람이 GitHub 에서 병합", human=True)
    return out(MERGEABLE, "", "병합하기")


def _is_excluded_alert(name: str) -> bool:
    """rollup 이름은 `pr-tamper-alert / alert` 처럼 워크플로 이름이 앞에 붙는다. 알림 job 은 검사가 아니다."""
    return (name or "").rsplit(" / ", 1)[-1].strip() == "alert"


# --- 순서 ---------------------------------------------------------------------


def _dev_numbers(raw: dict) -> set[int]:
    text = " ".join([raw.get("title") or "", raw.get("headRefName") or "", raw.get("body") or ""])
    nums = {int(m) for m in _DEV_REF.findall(text)}
    for f in raw.get("files") or []:
        m = _SPEC_FILE.match(f.get("path") or "")
        if m:
            nums.add(int(m.group(1)))
    return nums


def _order_devs(raw: dict) -> set[int]:
    """순서 계산용으로 PR 이 실제로 속한 DEV 번호들(#407). 제목 끝 `(DEV-xxx, DEV-yyy)` 전부, 제목·브랜치의 번호, 바꾼 Spec
    파일 번호. 모두 비면 본문에서 처음 나온 번호 하나만 쓴다. 본문에 스쳐 지나간 번호("main 의 REQ-001~004 는 그대로")로
    묶으면 상관없는 DEV 의 PR 이 앞 PR 로 잡히기 때문이다."""
    title = raw.get("title") or ""
    nums: set[int] = set()
    end = _title_end_devs(title)
    if end:
        nums.update(end[0])
    nums.update(int(m) for m in _DEV_REF.findall(title + " " + (raw.get("headRefName") or "")))
    for f in raw.get("files") or []:
        sm = _SPEC_FILE.match(f.get("path") or "")
        if sm:
            nums.add(int(sm.group(1)))
    if not nums:
        found = _DEV_REF.findall(raw.get("body") or "")
        if found:
            nums.add(int(found[0]))
    return nums


def _primary_dev(raw: dict) -> int | None:
    """PR 하나가 속한 DEV 번호 하나(줄기 묶기용, #390). `_dev_numbers` 는 본문에서 스쳐 지나간 번호까지 모으므로(결함 PR 이
    "DEV-007 과 같은 결함" 이라 적는 식) 가장 작은 번호를 쓰면 틀린다. 우선순위: 제목 끝 `(DEV-xxx)` > 제목 맨 앞 번호 >
    브랜치 > 바꾼 Spec 파일 `docs/spec/DEV-xxx-*.md`(여럿이면 작은 번호) > 본문에서 처음 나온 번호."""
    title = raw.get("title") or ""
    end = _title_end_devs(title)
    if end:
        return end[0][0]
    for text in (title, raw.get("headRefName") or ""):
        found = _DEV_REF.findall(text)
        if found:
            return int(found[0])
    specs = []
    for f in raw.get("files") or []:
        sm = _SPEC_FILE.match(f.get("path") or "")
        if sm:
            specs.append(int(sm.group(1)))
    if specs:
        return min(specs)
    found = _DEV_REF.findall(raw.get("body") or "")
    return int(found[0]) if found else None


def _stage(raw: dict) -> int | None:
    """0 SRS, 1 Spec, 2 개발. DEV 단계가 아닌 PR 은 None."""
    paths = [f.get("path") or "" for f in raw.get("files") or []]
    if SRS_PATH in paths:
        return 0
    if any(_SPEC_FILE.match(p) for p in paths):
        return 1
    title_branch = (raw.get("title") or "") + " " + (raw.get("headRefName") or "")
    if _DEV_REF.search(title_branch):
        return 2
    return None


def build_order(prs: list[dict], versions: dict[int, str]) -> tuple[dict[int, set[int]], dict[int, list[str]]]:
    """(앞서야 하는 PR 집합, 각 PR 이 그렇게 된 이유) 를 만든다."""
    by_number = {p["number"]: p for p in prs}
    before: dict[int, set[int]] = {n: set() for n in by_number}
    why: dict[int, list[str]] = {n: [] for n in by_number}

    def link(first: int, then: int, reason: str) -> None:
        if first == then or first not in by_number or then not in by_number:
            return
        if first not in before[then]:
            before[then].add(first)
        why[then].append(f"#{first}: {reason}")

    heads: dict[str, list[int]] = {}
    for p in prs:
        heads.setdefault(p.get("headRefName") or "", []).append(p["number"])

    for p in prs:
        n = p["number"]
        for first in heads.get(p.get("baseRefName") or "", []):
            link(first, n, "base 브랜치가 그 PR 의 브랜치")
        for line in _FIRST_LINE.findall(p.get("body") or ""):
            for m in _PR_REF.findall(line):
                link(int(m), n, "본문의 먼저: 줄")

    infos = {p["number"]: (_stage(p), _order_devs(p)) for p in prs}
    for a in prs:
        for b in prs:
            sa, da = infos[a["number"]]
            sb, db = infos[b["number"]]
            if sa is None or sb is None or sa >= sb:
                continue
            shared = sorted(da & db)
            if shared:
                link(a["number"], b["number"], f"같은 DEV-{shared[0]:03d} 의 {_STAGE_NAME[sa]} 단계")

    groups: dict[tuple[int, ...], list[int]] = {}
    for n, v in versions.items():
        groups.setdefault(parse_version(v), []).append(n)
    keys = sorted(groups)
    for lo, hi in zip(keys, keys[1:]):
        for first in groups[lo]:
            for then in groups[hi]:
                link(first, then, f"plugin.json version 이 더 낮음({versions[first]} < {versions[then]})")
    return before, why


def reduce_edges(before: dict[int, set[int]]) -> dict[int, set[int]]:
    """다른 앞 PR 을 거쳐 이미 앞서는 PR 은 뺀다(#244 → #248 → #252 이면 #252 의 앞은 #248 만)."""
    memo: dict[int, set[int]] = {}
    in_progress: set[int] = set()

    def ancestors(n: int) -> tuple[set[int], bool]:
        """(n 보다 앞서는 모든 PR, 순환을 건너뛰지 않았는가). 완전한 결과만 메모한다."""
        if n in memo:
            return memo[n], True
        in_progress.add(n)
        out: set[int] = set()
        complete = True
        for d in before.get(n, ()):
            if d == n:
                continue
            if d in in_progress:
                complete = False  # 순환은 건너뛴다(순환 판정은 topo_order 가 한다)
                continue
            out.add(d)
            sub, sub_complete = ancestors(d)
            out |= sub
            complete = complete and sub_complete
        in_progress.discard(n)
        if complete:
            memo[n] = out
        return out, complete

    reduced: dict[int, set[int]] = {}
    for n, deps in before.items():
        via: set[int] = set()
        for d in deps:
            via |= ancestors(d)[0]
        via.discard(n)
        reduced[n] = {d for d in deps if d not in via}
    return reduced


def _cycle_members(remaining: dict[int, set[int]]) -> set[int]:
    """Kahn 정렬에서 남은 PR 중 실제 순환(크기 2 이상의 강연결 성분)에 든 것(Tarjan)."""
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    members: set[int] = set()
    counter = [0]

    def visit(v: int) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in remaining[v]:  # w 는 v 보다 앞서야 하는 PR 이다
            if w not in remaining:
                continue
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                members.update(comp)

    for v in sorted(remaining):
        if v not in index:
            visit(v)
    return members


def topo_order(numbers: list[int], before: dict[int, set[int]]) -> tuple[list[int], list[int], dict[int, list[int]]]:
    """(정렬된 번호, 순환 구성원, {순환 뒤에 기다리는 PR: 앞 PR 중 판정 불능인 번호}). 동률은 번호 오름차순."""
    remaining = {n: set(before.get(n, ())) & set(numbers) for n in numbers}
    ordered: list[int] = []
    while remaining:
        ready = sorted(n for n, deps in remaining.items() if not deps)
        if not ready:
            break
        n = ready[0]
        ordered.append(n)
        del remaining[n]
        for deps in remaining.values():
            deps.discard(n)
    cyclic = _cycle_members(remaining)
    blocked = {n: sorted(deps & set(remaining)) for n, deps in remaining.items() if n not in cyclic}
    return ordered, sorted(cyclic), blocked


def shared_file_warnings(prs: list[dict], position: dict[int, int | None]) -> list[dict]:
    files = {p["number"]: {f.get("path") for f in p.get("files") or [] if f.get("path")} for p in prs}
    nums = sorted(files)
    out: list[dict] = []
    for i, a in enumerate(nums):
        for b in nums[i + 1 :]:
            common = sorted(files[a] & files[b])
            if not common:
                continue
            pa, pb = position.get(a), position.get(b)
            first, second = (b, a) if (pa is not None and pb is not None and pb < pa) else (a, b)
            out.append({"first": first, "second": second, "files": common})
    return out


# --- 계산 전체 ----------------------------------------------------------------


def _read_versions(client: GhClient, repo: str, raws: list[dict]) -> tuple[dict[int, str], list[int], list[str]]:
    """plugin.json 을 바꾼 PR 의 head version. (version, 못 읽은 PR 번호, 경고)."""
    versions: dict[int, str] = {}
    unread: list[int] = []
    warnings: list[str] = []
    for raw in raws:
        if any(f.get("path") == PLUGIN_JSON for f in raw.get("files") or []) and raw.get("headRefOid"):
            try:
                versions[raw["number"]] = _head_plugin_version(client, repo, raw["headRefOid"])
            except GhError as exc:
                unread.append(raw["number"])
                warnings.append(f"#{raw['number']} 의 plugin.json version 을 읽지 못해 version 순서에서 뺐다({exc})")
    return versions, unread, warnings


def compute_before(client: GhClient, repo: str, number: int) -> dict:
    """PR 하나보다 먼저 병합해야 하는 열린 PR 을 낸다(병합 직전 검사용, #370).

    상태 판정(승인·검사 조회)은 하지 않아 `compute` 보다 싸다. 순서를 확정할 수 없으면
    ("status": "cannot_check") 앞 PR 이 없다고 말하지 않는다. 확정할 수 없는 경우: 그 PR 이 열린
    목록에 없음, 열린 PR 이 PR_LIMIT 개 이상, 순환에 들었거나 순환 뒤에 기다림, 그 PR 이
    plugin.json 을 바꿨는데 열린 PR 의 version 을 못 읽음.
    """
    raws = _load_prs(client, repo)
    by_number = {r["number"]: r for r in raws}
    if number not in by_number:
        return cannot_check(f"PR #{number} 가 열린 PR 목록에 없다(이미 닫혔거나 병합됐거나 목록이 잘림)")
    if len(raws) >= PR_LIMIT:
        return cannot_check(f"열린 PR 이 {PR_LIMIT}개 이상이라 앞 PR 을 모두 확인하지 못한다")
    versions, unread, _ = _read_versions(client, repo, raws)
    touches_plugin = any(f.get("path") == PLUGIN_JSON for f in by_number[number].get("files") or [])
    if touches_plugin and unread:
        names = ", ".join(f"#{n}" for n in unread)
        return cannot_check(f"{names} 의 plugin.json version 을 읽지 못해 version 순서를 정하지 못한다")
    before, why = build_order(raws, versions)
    _, cyclic, blocked = topo_order([r["number"] for r in raws], before)
    if number in cyclic:
        return cannot_check(f"PR #{number} 는 {CYCLE_NOTE} — 먼저: 줄·base 브랜치·version 이 서로 앞서라고 한다")
    if number in blocked:
        deps = ", ".join(f"#{d}" for d in blocked[number])
        return cannot_check(f"PR #{number} 는 {BEHIND_ORDER_NOTE} {deps} 뒤에 있다")
    firsts = sorted(reduce_edges(before).get(number, ()))
    entries = []
    for m in firsts:
        prefix = f"#{m}: "
        reasons = [w[len(prefix) :] for w in why.get(number, []) if w.startswith(prefix)]
        entries.append(
            {
                "number": m,
                "title": by_number[m].get("title") or "",
                "url": pr_url(repo, m, by_number[m].get("url") or ""),
                "reasons": reasons,
            }
        )
    return {
        "status": "ok",
        "repo": repo,
        "pr": number,
        "title": by_number[number].get("title") or "",
        "url": pr_url(repo, number, by_number[number].get("url") or ""),
        "before": entries,
    }


def compute(client: GhClient, repo: str, login: str | None = None, mine: bool = False) -> dict:
    """열린 PR 을 읽어 상태·순서를 계산한다. GitHub 를 읽지 못하면 GhError 를 던진다."""
    raws = _load_prs(client, repo)
    truncated = len(raws) >= PR_LIMIT
    ctx = _Context(client, repo)
    versions, version_unread, warnings = _read_versions(client, repo, raws)

    before, why = build_order(raws, versions)
    ordered, cyclic, blocked = topo_order([r["number"] for r in raws], before)
    direct = reduce_edges(before)
    position: dict[int, int | None] = {n: i + 1 for i, n in enumerate(ordered)}
    for n in [*cyclic, *blocked]:
        position[n] = None

    items: list[dict] = []
    for raw in raws:
        n = raw["number"]
        info = classify(ctx, raw)
        notes = list(info["notes"])
        if n in cyclic:
            notes.append(CYCLE_NOTE)
        elif n in blocked:
            notes.append(f"{BEHIND_ORDER_NOTE} {', '.join(f'#{d}' for d in blocked[n])}")
        items.append(
            {
                "number": n,
                "sha": raw.get("headRefOid") or "",
                "title": raw.get("title") or "",
                "author": ((raw.get("author") or {}).get("login")) or "",
                "url": pr_url(repo, n, raw.get("url") or ""),
                "base": raw.get("baseRefName") or "",
                "head": raw.get("headRefName") or "",
                "state": info["state"],
                "detail": info["detail"],
                "next": info["next"],
                "notes": notes,
                "human_merge": info["human_merge"],
                "order": position.get(n),
                "after": sorted(direct.get(n, ())),
                "after_reasons": why.get(n, []),
                "version": versions.get(n),
                "devs": sorted(_dev_numbers(raw)),
                "dev": _primary_dev(raw),
            }
        )
    items.sort(key=lambda it: (it["order"] is None, it["order"] or 0, it["number"]))

    shared = shared_file_warnings(raws, position)
    result = {
        "status": "ok",
        "repo": repo,
        "login": login,
        "truncated": truncated,
        "prs": items,
        "shared_files": shared,
        "warnings": warnings,
        "unread_versions": version_unread,
    }
    if mine:
        result = filter_mine(result, login or "")
    return result


def filter_mine(result: dict, login: str) -> dict:
    """내 PR 과, 그 앞에 병합돼야 하는 남의 PR(앞의 앞까지)만 남긴다."""
    login_l = login.lower()
    by_number = {it["number"]: it for it in result["prs"]}
    keep = {n for n, it in by_number.items() if it["author"].lower() == login_l}
    stack = list(keep)
    while stack:
        for dep in by_number[stack.pop()]["after"]:
            if dep in by_number and dep not in keep:
                keep.add(dep)
                stack.append(dep)
    mine_set = {n for n, it in by_number.items() if it["author"].lower() == login_l}
    out = dict(result)
    out["prs"] = [it for it in result["prs"] if it["number"] in keep]
    out["mine_count"] = len(mine_set)
    for it in out["prs"]:
        it["mine"] = it["number"] in mine_set
    out["shared_files"] = [
        w for w in result["shared_files"] if (w["first"] in mine_set or w["second"] in mine_set)
    ]
    return out


# --- 출력 ---------------------------------------------------------------------


def _clip(text: str, limit: int = 28) -> str:
    text = text.strip()
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    # 표 칸과 마크다운 링크를 깨지 않게: 제목이 `[#1](https://evil)` 이어도 가짜 링크가 되지 않는다.
    return text.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def pr_url(repo: str, number: int, url: str = "") -> str:
    """PR 주소. gh 가 준 url 이 없으면 저장소와 번호로 만든다(#386)."""
    return url or f"https://github.com/{repo}/pull/{number}"


def pr_link(repo: str, number: int, url: str = "") -> str:
    """`[#303](https://github.com/<repo>/pull/303)` — 저장소가 여럿이어도 링크로 어디 PR 인지 드러난다."""
    return f"[#{number}]({pr_url(repo, number, url)})"


# 할 일 분류(#390). 기존 state 문자열에서 옮길 뿐 새 상태를 만들지 않는다.
TODO_MERGE = "병합하기"
TODO_FIX = "고치기"
TODO_WAIT = "기다리기"
_TODO_ORDER = {TODO_MERGE: 0, TODO_FIX: 1, TODO_WAIT: 2}
SYMBOLS = {
    MERGEABLE: "✅",
    WAITING_APPROVAL: "⏳",
    CHECKING: "⏳",
    NOT_STARTED: "⏳",
    MERGE_UNKNOWN: "⏳",
    CHECK_FAILED: "❌",
    CONFLICT: "❌",
    BEHIND: "❌",
    DRAFT: "📝",
    BLOCKED: "❓",
    UNSTABLE: "❓",
    UNKNOWN: "❓",
}
UNJUDGEABLE_SYMBOL = "❓"
NO_CHAIN = "줄기 없음"


def _symbol(it: dict) -> str:
    if it["order"] is None:  # 순환이거나 순환 뒤에 기다려 순서를 정하지 못함
        return UNJUDGEABLE_SYMBOL
    return SYMBOLS.get(it["state"], UNJUDGEABLE_SYMBOL)


def _approvers_short(detail: str) -> str:
    """승인 대기 사유("a, b 의 승인 필요 — …")에서 승인자 이름만 짧게."""
    if " 의 승인 필요" in detail:
        names = "·".join(n.strip() for n in detail.split(" 의 승인 필요")[0].split(",") if n.strip())
        out = f"{_clip(names, 60)} 승인"
        return out + "(새 커밋 뒤 재승인)" if "낡은 승인" in detail else out
    if "승인할 사람이 정해져" in detail:
        return "승인할 사람 미지정"
    return "승인 대기"


def _todo(it: dict, link) -> tuple[str, str]:
    """(할 일, 짧은 사유). 병합하기 = 병합 가능이고 앞 PR 없음, 고치기 = 사람이 손볼 것(검사 실패·충돌·판정 불능 등),
    기다리기 = 시간이나 남이 해결(승인·검사 중·앞 PR·초안)."""
    state, detail = it["state"], it["detail"]
    if it["order"] is None:
        notes = [n for n in it["notes"] if n.startswith((CYCLE_NOTE, BEHIND_ORDER_NOTE))]
        return TODO_FIX, "; ".join(notes) or "순서 판정 불능"
    if state == MERGEABLE:
        if it["after"]:
            return TODO_WAIT, "앞 " + ", ".join(link(n) for n in it["after"]) + " 대기"
        return TODO_MERGE, "사람이 GitHub 에서 병합" if it["human_merge"] else ""
    fixes = {
        CONFLICT: "충돌",
        BEHIND: "base 보다 뒤처짐",
        BLOCKED: "병합 막힘",
        UNSTABLE: "검사 불안정",
    }
    if state == CHECK_FAILED:
        return TODO_FIX, "검사 실패: " + _clip(detail, 50)
    if state in fixes:
        return TODO_FIX, fixes[state]
    waits = {CHECKING: "검사 중", NOT_STARTED: "검사 시작 전", MERGE_UNKNOWN: "충돌 여부 확인 중", DRAFT: "초안"}
    if state == WAITING_APPROVAL:
        return TODO_WAIT, _approvers_short(detail)
    if state in waits:
        return TODO_WAIT, waits[state]
    return TODO_FIX, f"{state}: {_clip(detail, 40)}" if detail else state


def _extra_notes(it: dict) -> str:
    """순서 판정 불능 말고 상태 판정에 붙은 주의(예: 사람이 병합할 경로인지 확인 불능). 표에서 빠지면 안 된다."""
    notes = [n for n in it["notes"] if not n.startswith((CYCLE_NOTE, BEHIND_ORDER_NOTE))]
    return "".join(f" / {_clip(n, 60)}" for n in notes)


def _components(prs: list[dict]) -> list[list[dict]]:
    """`after` 로 이어진 PR 묶음(약하게 연결된 성분). 번호 오름차순으로 낸다."""
    by_number = {it["number"]: it for it in prs}
    neighbors: dict[int, set[int]] = {n: set() for n in by_number}
    for it in prs:
        for d in it["after"]:
            if d in by_number:
                neighbors[it["number"]].add(d)
                neighbors[d].add(it["number"])
    seen: set[int] = set()
    comps: list[list[dict]] = []
    for n in sorted(by_number):
        if n in seen:
            continue
        stack, comp = [n], []
        seen.add(n)
        while stack:
            cur = stack.pop()
            comp.append(by_number[cur])
            for m in neighbors[cur]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        comps.append(sorted(comp, key=lambda it: it["number"]))
    return comps


_TITLE_END_DEV = re.compile(
    r"[(\[]\s*((?:DEV|REQ)-0*\d+(?:\s*[,/·]\s*(?:DEV|REQ)-0*\d+)*)\s*[)\]]\s*[.。]?\s*$", re.IGNORECASE
)


def _title_end_devs(title: str) -> tuple[list[int], int] | None:
    """제목 끝의 `(DEV-004)`·`[DEV-004]`·`(DEV-004, DEV-005)` 의 번호들(적힌 순서)과 그 괄호가 시작하는 위치. 뒤의 `.` 는 허용."""
    m = _TITLE_END_DEV.search(title or "")
    if not m:
        return None
    return [int(n) for n in _DEV_REF.findall(m.group(1))], m.start()
_TYPE_PREFIX = re.compile(r"^\s*\w+(\([^)]*\))?!?\s*:\s*")
_NAME_CUTS = (" Spec", " SRS", "·", " 에 ")
_SPEC_LEAD = re.compile(r"^(?:Spec|SRS)\b")
CHAIN_NAME_LIMIT = 24


def _dev_of(it: dict) -> int | None:
    """PR 의 DEV 번호. 제목 끝의 `(DEV-xxx)`·`[DEV-xxx]`, 없으면 제목 맨 앞의 번호, 없으면 브랜치에서 읽은 번호를 우선한다.
    그것도 없으면 엔진이 본문·Spec 파일까지 읽어 둔 `devs` 중 가장 작은 번호다. 둘 이상이어도 하나만 쓴다."""
    if "dev" in it:  # compute 가 제목·브랜치·Spec 파일·본문 순으로 이미 정했다(_primary_dev)
        return it["dev"]
    title = it["title"] or ""
    end = _title_end_devs(title)
    if end:
        return end[0][0]
    for text in (title, it.get("head") or ""):
        found = _DEV_REF.findall(text)
        if found:
            return int(found[0])
    devs = it.get("devs") or []
    return min(devs) if devs else None


def _groups(pool: list[dict]) -> list[tuple[int | None, list[dict]]]:
    """줄기 후보 [(DEV 번호 또는 None, PR 들)]. 번호가 같은 PR 이 한 줄기다. 번호 없는 PR 은 번호 없는 PR 끼리 앞 PR
    관계로 이은 묶음 단위로 보고, 그 묶음이 닿는 DEV 줄기가 하나뿐이면 전부 그 줄기에 넣는다. 둘 이상에 닿거나 하나도
    안 닿으면 따로 둔다. 가장 작은 PR 번호 순."""
    by_dev: dict[int, list[dict]] = {}
    free: list[dict] = []
    dev_of: dict[int, int] = {}
    for it in pool:
        dev = _dev_of(it)
        if dev is None:
            free.append(it)
        else:
            by_dev.setdefault(dev, []).append(it)
            dev_of[it["number"]] = dev
    neighbors: dict[int, set[int]] = {}
    for it in pool:
        for d in it["after"]:
            neighbors.setdefault(it["number"], set()).add(d)
            neighbors.setdefault(d, set()).add(it["number"])
    alone: list[dict] = []
    for comp in _components(free):
        touched = {dev_of[n] for it in comp for n in neighbors.get(it["number"], ()) if n in dev_of}
        if len(touched) == 1:
            by_dev[next(iter(touched))].extend(comp)
        else:
            alone.extend(comp)
    groups: list[tuple[int | None, list[dict]]] = [
        (dev, sorted(members, key=lambda it: it["number"])) for dev, members in by_dev.items()
    ]
    groups += [(None, comp) for comp in _components(alone)]
    groups.sort(key=lambda g: g[1][0]["number"])
    return groups


def _pr_cell(it: dict, mine_nums: set[int], link, group_of: dict[int, int]) -> str:
    """`**[#n](url)** ⏳(앞: [#m](url))` — 내 PR 은 굵게, 다른 줄기에 있는 앞 PR 은 꼬리표로."""
    text = link(it["number"])
    if it["number"] in mine_nums:
        text = f"**{text}**"
    outside = [d for d in it["after"] if group_of.get(d, group_of[it["number"]]) != group_of[it["number"]]]
    tail = f"(앞: {', '.join(link(d) for d in outside)})" if outside else ""
    warn = "⚠" if it["notes"] else ""  # 상태에 붙은 주의는 표 아래 "주의:" 줄에 있다
    return f"{text} {_symbol(it)}{warn}{tail}"


def _chain_name(dev: int | None, members: list[dict]) -> str:
    """`DEV-007(제목)`. 제목: ① 제목 끝이 `(DEV-xxx)` 인 PR 의 제목에서 `feat: ` 같은 접두어와 `(DEV-xxx)` 를 뗀 것,
    ② 없으면 `DEV-xxx` 뒤 문구를 ` Spec`·` SRS`·`·`·` 에 ` 앞에서 자른 것, ③ 없으면 줄기에서 가장 먼저인 PR 의 제목(접두어 뗌),
    ④ 그것도 비면 번호만. 번호 없는 줄기는 맨 앞 PR 제목."""
    ordered = sorted(members, key=lambda it: (it["order"] is None, it["order"] or 0, it["number"]))
    if dev is None:
        return _clip(ordered[0]["title"], 28)
    label = f"DEV-{dev:03d}"
    def without_end(title: str) -> str:
        end = _title_end_devs(title)
        return title[: end[1]] if end else title

    own_number = re.compile(rf"^[(\[]?(?:DEV|REQ)-0*{dev}\b[\])]?\s*[:：\-–—]*\s*", re.IGNORECASE)  # 이름에 번호가 겹치지 않게
    for it in ordered:
        end = _title_end_devs(it["title"] or "")
        if end and dev in end[0]:
            title = own_number.sub("", _TYPE_PREFIX.sub("", without_end(it["title"])).strip())
            if title and not _SPEC_LEAD.match(title):  # `DEV-004 Spec 에 …` 는 이름이 아니라 문서 종류다
                return f"{label}({_clip(title, CHAIN_NAME_LIMIT)})"
    pattern = re.compile(rf"(?:DEV|REQ)-0*{dev}\b[\]\)]*\s*[:：\-–—]*\s*(.*)$", re.IGNORECASE)
    for it in ordered:
        m = pattern.search(without_end(it["title"] or ""))
        if not m:
            continue
        rest = m.group(1)
        if _SPEC_LEAD.match(rest):
            continue
        cut = min((rest.find(c) for c in _NAME_CUTS if rest.find(c) >= 0), default=len(rest))
        title = rest[:cut].strip(" ]):：-–—,.")
        if title:
            return f"{label}({_clip(title, CHAIN_NAME_LIMIT)})"
    first = own_number.sub("", _TYPE_PREFIX.sub("", without_end(ordered[0]["title"] or "")).strip())
    return f"{label}({_clip(first, CHAIN_NAME_LIMIT)})" if first else label


def _chain_cell(comp: list[dict], mine_nums: set[int], link, group_of: dict[int, int]) -> str:
    """줄기 안에서만 위상 순서의 깊이(앞 PR 을 거친 가장 긴 길이)가 같은 PR 을 한 칸으로 묶어 `→` 로 잇는다.
    갈래는 `(#a, #b)`. 줄기 밖의 앞 PR 은 줄을 합치지 않고 그 PR 뒤에 `(앞: …)` 꼬리표로만 단다."""

    def cell(it: dict) -> str:
        return _pr_cell(it, mine_nums, link, group_of)

    ordered = sorted((it for it in comp if it["order"] is not None), key=lambda it: (it["order"], it["number"]))
    depth: dict[int, int] = {}
    layers: dict[int, list[dict]] = {}
    for it in ordered:
        ds = [depth[d] for d in it["after"] if d in depth]
        depth[it["number"]] = 1 + max(ds) if ds else 0
        layers.setdefault(depth[it["number"]], []).append(it)
    groups = [layers[k] for k in sorted(layers)]
    unordered = sorted((it for it in comp if it["order"] is None), key=lambda it: it["number"])
    if unordered:
        groups.append(unordered)  # 순환·순환 뒤 대기는 순서를 못 정했으니 끝에 따로
    parts = []
    for group in groups:
        cells = [cell(it) for it in sorted(group, key=lambda it: it["number"])]
        parts.append(cells[0] if len(cells) == 1 else "(" + ", ".join(cells) + ")")
    return " → ".join(parts)


def _render_detail(result: dict, mine: bool, urls: dict[int, str], note_limit: int) -> list[str]:
    """`--verbose` 일 때 표 아래에 덧붙이는 예전 형식(상태 사유 전문, 다음 할 일, 같은 파일 주의)."""
    repo = result["repo"]
    lines = ["", "## 자세히(--verbose)", "", "| 순서 | PR | 상태 | 다음 할 일 | 먼저 병합할 PR |", "|---|---|---|---|---|"]
    for it in result["prs"]:
        order = str(it["order"]) if it["order"] is not None else "?"
        who = "" if (not mine or it.get("mine")) else f" (@{it['author']})"
        state = it["state"]
        if it["detail"]:
            state += f": {it['detail']}"
        for note in it["notes"]:
            state += f" / {note}"
        nxt = it["next"]
        if it["after"] and it["state"] == MERGEABLE:
            nxt = f"앞의 PR 이 병합된 뒤 {nxt}"
        after = ", ".join(pr_link(repo, n, urls.get(n, "")) for n in it["after"]) or "-"
        me = pr_link(repo, it["number"], it.get("url") or "")
        lines.append(f"| {order} | {me} {_clip(it['title'])}{who} | {state} | {nxt} | {after} |")
    for w in result["shared_files"][:note_limit]:
        sample = ", ".join(w["files"][:2]) + (" 등" if len(w["files"]) > 2 else "")
        lines.append(
            f"주의: {pr_link(repo, w['first'], urls.get(w['first'], ''))} 병합 뒤 "
            f"{pr_link(repo, w['second'], urls.get(w['second'], ''))} 를 다시 맞춰야 할 수 있음(같은 파일: {sample})"
        )
    if len(result["shared_files"]) > note_limit:
        lines.append(f"주의: 같은 파일을 고친 PR 쌍이 {len(result['shared_files']) - note_limit}개 더 있음")
    return lines


def render(
    result: dict,
    mine: bool,
    max_rows: int | None = None,
    verbose: bool = False,
    full: dict | None = None,
) -> str:
    """사람이 읽는 출력(#390): 내가 지금 할 일 표(--mine) + 줄기 표.

    `result` 는 보여 줄 PR(--mine 이면 내 PR 과 그 앞 PR)이고, `full` 은 저장소의 열린 PR 전체다. 줄기는
    `full` 로 묶어 내 PR 이 든 줄기는 내 뒤에 병합될 남의 PR 까지 보인다(없으면 `result` 로 묶는다).
    `max_rows` 는 줄기 표의 줄기 수 제한이다("… 외 n개 줄기", 훅용). `verbose` 면 사유 전문과 같은 파일 주의를 덧붙인다.
    """
    prs = result["prs"]
    repo = result["repo"]
    pool = (full or result)["prs"]
    urls = {it["number"]: it.get("url") or "" for it in pool}
    note_limit = 10 if max_rows is None else MAX_ROWS_NOTE_LIMIT

    def link(n: int) -> str:
        return pr_link(repo, n, urls.get(n, ""))

    lines: list[str] = []
    scope = "내 PR" if mine else "열린 PR"
    count = result.get("mine_count", len(prs)) if mine else len(prs)
    lines.append(f"{repo} {scope} {count}개")
    if not prs:
        lines.append("내 열린 PR 이 없다." if mine else "열린 PR 이 없다.")
        return "\n".join(lines)

    mine_nums = {it["number"] for it in prs if it.get("mine")} if mine else set()

    if mine:
        todos = [(_todo(it, link), it) for it in prs if it["number"] in mine_nums]
        todos.sort(key=lambda t: (_TODO_ORDER[t[0][0]], t[1]["number"]))
        lines.append("")
        lines.append("## 내가 지금 할 수 있는 일")
        if not any(t[0][0] != TODO_WAIT for t in todos):
            lines.append("지금 할 수 있는 일: 없음(모두 기다리는 중)")
        if todos:
            lines.append("")
            lines.append("| 할 일 | PR |")
            lines.append("|---|---|")
            for (kind, why), it in todos:
                text = f"{link(it['number'])} {_clip(it['title'])}"
                if why:
                    text += f" — {why}"
                lines.append(f"| {kind} | {text}{_extra_notes(it)} |")

    groups = _groups(pool)
    group_of = {it["number"]: i for i, (_, members) in enumerate(groups) for it in members}
    chains = [g for g in groups if len(g[1]) > 1 and (not mine or any(it["number"] in mine_nums for it in g[1]))]
    singles = sorted(
        (g[1][0] for g in groups if len(g[1]) == 1 and (not mine or g[1][0]["number"] in mine_nums)),
        key=lambda it: it["number"],
    )
    shown = chains if max_rows is None else chains[:max_rows]
    lines.append("")
    lines.append("## 내 PR 과 그 줄기" if mine else "## 열린 PR 과 줄기")
    lines.append("")
    lines.append("| 줄기 | 순서 |")
    lines.append("|---|---|")
    for dev, members in shown:
        lines.append(f"| {_chain_name(dev, members)} | {_chain_cell(members, mine_nums, link, group_of)} |")
    if singles:
        cells = [_pr_cell(it, mine_nums, link, group_of) for it in singles]
        lines.append(f"| {NO_CHAIN} | {' · '.join(cells)} |")
    if len(chains) > len(shown):
        lines.append(f"… 외 {len(chains) - len(shown)}개 줄기 — /harness:prs")
    # 상태에 붙은 주의(예: 사람이 병합할 경로인지 확인 불능)는 --verbose 가 없어도 표 바로 아래에 낸다(원칙 7).
    # 표에서 잘린 줄기와 남의 PR 도 포함한다.
    noted = [it for _, members in chains for it in members] + singles
    noted = sorted((it for it in noted if it["notes"]), key=lambda it: it["number"])
    note_lines = [f"주의: {link(it['number'])} {note}" for it in noted for note in it["notes"]]
    lines.extend(note_lines[:note_limit])
    if len(note_lines) > note_limit:
        lines.append(f"주의: PR 주의가 {len(note_lines) - note_limit}건 더 있음")
    lines.append("")
    lines.append("✅ 병합 가능 · ⏳ 기다리는 중 · ❌ 고쳐야 함 · 📝 초안 · ❓ 판정 불능 · ⚠ 주의 있음(아래 줄)")

    if verbose:
        lines.extend(_render_detail(result, mine, urls, note_limit))
    for warning in result["warnings"][:note_limit]:
        lines.append(f"주의: {warning}")
    if len(result["warnings"]) > note_limit:
        lines.append(f"주의: 경고가 {len(result['warnings']) - note_limit}개 더 있음")
    if result["truncated"]:
        lines.append(f"주의: 열린 PR 이 {PR_LIMIT}개 이상이라 일부만 읽었다. 순서와 목록이 완전하지 않다.")
    return "\n".join(lines)


def cannot_check(message: str) -> dict:
    return {"status": "cannot_check", "message": f"PR 상태 확인 불능 — {message}"}


# --- CLI ----------------------------------------------------------------------


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="checker.pr_queue", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/repo (없으면 현재 폴더의 저장소)")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--mine", action="store_true", help="내 PR 과 그 앞에 병합돼야 하는 PR 만")
    scope.add_argument("--all", action="store_true", help="저장소의 열린 PR 전체(기본)")
    parser.add_argument("--json", action="store_true", help="구조화된 출력")
    parser.add_argument(
        "--pr",
        type=int,
        help="이 PR 보다 먼저 병합해야 하는 열린 PR 만 묻는다(병합 직전 검사용). 종료코드 0 앞 PR 없음, 1 있음, 2 확인 불능",
    )
    parser.add_argument("--max-rows", type=int, help="줄기 표에 싣는 줄기를 이 수까지로 줄인다(나머지는 '외 n개 줄기')")
    parser.add_argument("--verbose", action="store_true", help="승인 사유 전문·다음 할 일·같은 파일 주의를 표 아래에 덧붙인다")
    parser.add_argument("--quiet-empty", action="store_true", help="--mine 에서 내 PR 이 없으면 아무것도 내지 않는다")
    return parser


def render_before(result: dict) -> str:
    if result["status"] != "ok":
        return result["message"]
    repo = result["repo"]
    me = pr_link(repo, result["pr"], result.get("url") or "")
    if not result["before"]:
        return f"{me} 보다 먼저 병합할 열린 PR 은 없다."
    lines = [f"{me} 보다 먼저 병합해야 하는 열린 PR:"]
    for e in result["before"]:
        why = "; ".join(e["reasons"]) or "이유 불명"
        lines.append(f"- {pr_link(repo, e['number'], e.get('url') or '')} {_clip(e['title'], 40)} — {why}")
    return "\n".join(lines)


def run(args: argparse.Namespace, client: GhClient | None = None) -> tuple[int, str]:
    client = client or GhClient()
    try:
        repo = args.repo or _default_repo(client)
        if args.pr is not None:
            res = compute_before(client, repo, args.pr)
            code = EXIT_CANNOT_CHECK if res["status"] != "ok" else (EXIT_BEFORE_OPEN if res["before"] else EXIT_OK)
            return code, json.dumps(res, ensure_ascii=False) if args.json else render_before(res)
        login = _login(client) if args.mine else None
        full = compute(client, repo, login, mine=False)
        result = filter_mine(full, login or "") if args.mine else full
    except GhError as exc:
        res = cannot_check(str(exc))
        return EXIT_CANNOT_CHECK, json.dumps(res, ensure_ascii=False) if args.json else res["message"]
    except Exception as exc:  # noqa: BLE001 - 어떤 오류도 통과·문제없음으로 보이면 안 된다(원칙 7)
        res = cannot_check(f"예상 못 한 오류 {type(exc).__name__}")
        return EXIT_CANNOT_CHECK, json.dumps(res, ensure_ascii=False) if args.json else res["message"]
    if args.mine and args.quiet_empty and not result["prs"]:
        return EXIT_OK, ""
    if args.json:
        return EXIT_OK, json.dumps(result, ensure_ascii=False)
    return EXIT_OK, render(result, args.mine, max_rows=args.max_rows, verbose=args.verbose, full=full)


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    code, text = run(args)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
