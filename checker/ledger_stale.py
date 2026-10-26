"""내 열린 PR 이 대표 `[DEV-xxx]` 이슈를 Closes 하는데 PR head 의 원장 행이 `완료` 가 아닌지 본다(#454).

#445 부터 deliver 는 대표 이슈를 닫는 PR 의 원장 행을 처음부터 `완료` 로 담는다. 그 전 판으로 만든 열린 PR 은
원장이 `리뷰` 로 남아 있고, 팀원은 알아채지 못한다. `checker.pr_queue` 가 `--mine` 일 때 내 PR 마다 이 판정을
붙여 세션 시작 알림과 `/harness:prs` 가 Claude 에게 알리게 한다. 파일을 쓰지 않는다.

판정(PR 하나): 본문 `Closes|Fixes|Resolves #N` 이슈 중 제목이 `[DEV-xxx]` 로 시작하는 것(대표 이슈)마다 head 커밋의
`audit/ledger/*.md` 에서 그 DEV 행을 찾아 상태를 본다. 기준 함수는 `checker.ledger_complete` 의 것을 그대로 쓴다.
- `완료` 이면 아무것도 내지 않는다. 대표 이슈를 안 닫는 PR(하위 작업)과 `audit/ledger/` 가 없는 저장소도 조용히 건너뛴다.
- 완료가 아니면 `pending`, 읽지 못했거나(행 0개·2개 이상, 표 형식, 조회 실패) 하면 `unknown`(판정 불능, 원칙 7).
대표 이슈가 있는 PR 만 이슈·원장을 읽는다(PR 마다 GitHub 호출을 늘리지 않는다).
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from checker.ledger_complete import (
    DONE,
    Unknown,
    closing_issues,
    find_rows_text,
    ledger_file_hint,
    representative_id,
)
from checker.pairing import LEDGER_DIR
from checker.ssot_approval import GhClient, GhError, _force_utf8

PENDING = "pending"
UNKNOWN = "unknown"
_TITLE_PREFIX = re.compile(r"^\s*\[DEV-\d+\]\s*", re.IGNORECASE)


def _read_head_file(client, repo: str, path: str, sha: str) -> str:
    data = client.get_json_or_none_404(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={quote(sha, safe='')}")
    if not isinstance(data, dict) or not data.get("content"):
        raise Unknown(f"head({sha[:7]}) 에서 `{path}` 를 읽지 못했다")
    try:
        return base64.b64decode(data["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise Unknown(f"head({sha[:7]}) 의 `{path}` 를 해석하지 못했다: {exc}") from exc


def _judge_one(client, repo, sha, dev, issue, names: list[str], cache: dict[str, str]) -> dict:
    """대표 이슈 하나. {"dev","title","status","state","file","reason"} 또는 완료이면 None."""
    hint = ledger_file_hint(issue.get("body"), dev)
    if hint:
        if not hint.startswith(LEDGER_DIR + "/") or ".." in hint or hint not in names:
            raise Unknown(f"{dev} 이슈 본문이 가리킨 원장 파일 `{hint}` 이(가) head 에 없다")
        candidates = [hint]
    else:
        candidates = names
    hits: list[tuple[str, dict]] = []
    for path in candidates:
        if path not in cache:
            cache[path] = _read_head_file(client, repo, path, sha)
        for row in find_rows_text(cache[path], path, dev, skip_without_section=not hint):
            hits.append((path, row))
    where = f"`{hint}`" if hint else f"`{LEDGER_DIR}/*.md`"
    if not hits:
        raise Unknown(f"{dev} 행을 head 의 {where} 에서 찾지 못했다")
    if len(hits) > 1:
        places = ", ".join(f"`{p}`:{r['line'] + 1}" for p, r in hits)
        raise Unknown(f"{dev} 행이 둘 이상이다({places})")
    path, row = hits[0]
    if row["state"] == DONE:
        return None
    return {"status": PENDING, "state": row["state"], "file": path, "reason": ""}


def judge(client, repo: str, closes: list[int], sha: str) -> list[dict]:
    """PR 하나의 원장 판정. 알릴 것이 없으면 빈 목록. 항목: dev, title, status(pending·unknown), state, file, reason."""
    reps: list[tuple[str, str, dict]] = []
    out: list[dict] = []
    for n in closes:
        try:
            issue = client.get_json(f"repos/{repo}/issues/{n}") or {}
        except GhError as exc:
            out.append({"dev": "", "issue": n, "title": "", "status": UNKNOWN, "state": "", "file": "",
                        "reason": str(exc)})
            continue
        dev = representative_id(issue.get("title"))
        if dev:
            reps.append((dev, _TITLE_PREFIX.sub("", issue.get("title") or "").strip(), issue))
    if not reps:
        return out

    def unknown(dev: str, title: str, reason: str) -> dict:
        return {"dev": dev, "issue": None, "title": title, "status": UNKNOWN, "state": "", "file": "", "reason": reason}

    if not sha:
        return out + [unknown(d, t, "PR 의 head 커밋을 읽지 못했다") for d, t, _ in reps]
    try:
        listing = client.get_json_or_none_404(f"repos/{repo}/contents/{LEDGER_DIR}?ref={sha}")
    except GhError as exc:
        return out + [unknown(d, t, f"head 의 원장 폴더를 읽지 못했다: {exc}") for d, t, _ in reps]
    if listing is None:
        # head 에 폴더가 없다. 기본 브랜치(ref 없이)에도 없을 때만 원장을 안 쓰는 저장소다. 거기엔 있으면 head 를 못 읽은 것이다.
        try:
            default = client.get_json_or_none_404(f"repos/{repo}/contents/{LEDGER_DIR}")
        except GhError as exc:
            return out + [unknown(d, t, f"기본 브랜치의 원장 폴더를 읽지 못했다: {exc}") for d, t, _ in reps]
        if default is None:
            return out
        return out + [unknown(d, t, f"head 에는 `{LEDGER_DIR}` 가 없는데 기본 브랜치에는 있다(head 를 읽지 못함)")
                      for d, t, _ in reps]
    if not isinstance(listing, list):
        return out + [unknown(d, t, f"head 의 `{LEDGER_DIR}` 가 폴더가 아니다") for d, t, _ in reps]
    names = sorted(e["path"] for e in listing if isinstance(e, dict) and str(e.get("path", "")).endswith(".md")
                   and e.get("type") == "file")
    cache: dict[str, str] = {}
    for dev, title, issue in reps:
        try:
            found = _judge_one(client, repo, sha, dev, issue, names, cache)
        except (Unknown, GhError) as exc:
            out.append(unknown(dev, title, str(exc)))
            continue
        if found:
            out.append({"dev": dev, "issue": None, "title": title, **found})
    return out


MARKER = "<!-- ledger-ready -->"
EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_UNKNOWN = 2


def check_pr(client, repo: str, pr: int) -> dict:
    """병합 전 관문(#479). PR 하나의 본문·head 를 API 로 읽어 `judge` 를 부른다.

    status: ok(통과: 대표 이슈 없음·원장 없는 저장소·모두 완료) / violation(pending 이 있다) / unknown(판정 불능만 있다).
    pending 과 unknown 이 섞이면 violation 이다(고쳐야 할 것이 확실히 있다). GhError 는 부른 쪽이 unknown 으로 다룬다.
    """
    data = client.get_json(f"repos/{repo}/pulls/{pr}")
    head = data.get("head") if isinstance(data, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(data, dict) or not sha:
        raise GhError("PR 응답을 읽지 못했다(본문이나 head 커밋이 없다)")
    closes = closing_issues(data.get("body"))
    items = judge(client, repo, closes, sha) if closes else []
    if any(i["status"] == PENDING for i in items):
        status = "violation"
    elif items:
        status = "unknown"
    else:
        status = "ok"
    return {"status": status, "items": items}


def render_markdown(result: dict) -> str:
    """PR 코멘트·job 요약 본문. 통과이면 빈 문자열(코멘트를 달지 않고 있던 것은 지운다)."""
    if result["status"] == "ok":
        return ""
    lines = [MARKER, "## ledger-ready", ""]
    pending = [i for i in result["items"] if i["status"] == PENDING]
    unknown = [i for i in result["items"] if i["status"] == UNKNOWN]
    if pending:
        lines.append("⚠️ 진행 원장이 아직 완료가 아니라 병합할 수 없습니다.")
        lines.append("")
        for i in pending:
            lines.append(f"- 이 PR 은 {i['dev']}({i['title']}) 을 끝내는 PR 인데 진행 원장(`{i['file']}`)이 "
                         f"아직 '{i['state']}' 입니다. 병합 전에 '{DONE}'·#PR 번호로 고쳐야 합니다.")
        lines += ["", "Claude 에게 '원장 고쳐서 다시 올려줘' 라고 하면 됩니다. 원장을 고쳐 푸시하면 이 검사가 다시 돕니다.",
                  "PR 본문의 `Closes` 만 고친 경우에는 자동으로 다시 돌지 않으니, 새 커밋을 푸시하거나 이 검사를 다시 실행하세요."]
    if unknown:
        if pending:
            lines.append("")
        lines.append("⚠️ 원장 검사 불능 — 통과도 위반도 아닙니다. 아래 사유를 보고 다시 실행하거나 담당자에게 알리세요.")
        lines.append("")
        for i in unknown:
            who = f"{i['dev']}({i['title']})" if i["dev"] else (f"이슈 #{i['issue']}" if i.get("issue") else "대표 이슈")
            lines.append(f"- {who}: {i['reason']}")
    return "\n".join(lines) + "\n"


def cmd_check_pr(args) -> int:
    def unknown(reason: str) -> dict:
        return {"status": "unknown", "items": [{"dev": "", "issue": None, "title": "", "status": UNKNOWN,
                                                "state": "", "file": "", "reason": reason}]}

    # 위반(종료 1)은 pending 판정일 때만이다. 파이썬이 예외로 죽으면 종료코드가 1 이라 위반처럼 보이므로 모두 잡는다.
    try:
        result = check_pr(GhClient(), args.repo, args.pr)
    except GhError as exc:
        result = unknown(f"GitHub 를 읽지 못했다: {exc}")
    except Exception as exc:  # noqa: BLE001 — 뜻밖의 오류도 통과·위반이 아닌 판정 불능이다(원칙 7)
        result = unknown(f"뜻밖의 오류로 원장을 확인하지 못했다(이 PR 의 문제가 아니다): {type(exc).__name__}: {exc}")
    print(json.dumps(result, ensure_ascii=False))
    if args.markdown_file:
        try:
            Path(args.markdown_file).write_text(render_markdown(result), encoding="utf-8")
        except OSError as exc:
            print(f"코멘트 본문을 쓰지 못했다: {exc}", file=sys.stderr)
    return {"ok": EXIT_OK, "violation": EXIT_VIOLATION}.get(result["status"], EXIT_UNKNOWN)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger_stale", description="병합 전: 대표 이슈를 닫는 PR 의 원장 행이 완료인지 본다.")
    sub = parser.add_subparsers(dest="mode", required=True)
    ck = sub.add_parser("check-pr", help="PR 하나의 원장 완료 여부")
    ck.add_argument("--repo", required=True, help="owner/repo")
    ck.add_argument("--pr", required=True, type=int)
    ck.add_argument("--markdown-file", help="코멘트·요약 본문을 쓸 파일(통과이면 빈 파일)")
    ck.set_defaults(func=cmd_check_pr)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


def annotate(client, repo: str, items: list[dict]) -> None:
    """내 PR(`mine`)마다 `ledger` 를 채운다. 대표 이슈가 걸린 PR 만 GitHub 를 더 읽는다."""
    for it in items:
        if not it.get("mine") or not it.get("closes"):
            continue
        try:
            it["ledger"] = judge(client, repo, it["closes"], it.get("sha") or "")
        except GhError as exc:
            it["ledger"] = [{"dev": "", "issue": None, "title": "", "status": UNKNOWN, "state": "", "file": "", "reason": str(exc)}]
