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

import base64
import re
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
from checker.ssot_approval import GhError

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


def annotate(client, repo: str, items: list[dict]) -> None:
    """내 PR(`mine`)마다 `ledger` 를 채운다. 대표 이슈가 걸린 PR 만 GitHub 를 더 읽는다."""
    for it in items:
        if not it.get("mine") or not it.get("closes"):
            continue
        try:
            it["ledger"] = judge(client, repo, it["closes"], it.get("sha") or "")
        except GhError as exc:
            it["ledger"] = [{"dev": "", "issue": None, "title": "", "status": UNKNOWN, "state": "", "file": "", "reason": str(exc)}]
