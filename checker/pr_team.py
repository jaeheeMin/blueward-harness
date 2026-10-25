"""팀원별 진행·막힘·오류 현황(#438): `python -m checker.pr_queue --team [--days N] [--stale-days N] [--json]`.

어드민이 팀원 각자가 얼마나 진행했는지, 어디서 막혔는지, 오류는 없는지 한눈에 본다. 열린 PR 의 상태·병합 순서는
`checker.pr_queue.compute` 를 그대로 쓰고(새로 계산하지 않는다), 여기서는 사람별로 묶고 GitHub 에서 더 읽는다.

읽는 것(모두 읽기 전용, GraphQL 은 묶어서 불러 PR 수에 비례해 호출이 늘지 않는다):
  - 열린 PR 의 마지막 커밋·갱신 시각(GraphQL 1회), 병합한 PR(검색 1회), 열린 이슈와 담당자(GraphQL, 100개씩 쪽 넘김)
  - 검사 실패 PR 의 실패 사유(check run 의 annotations·title·summary): PR 15개씩 GraphQL 1회
  - 진행 원장 `audit/ledger/*.md`(main): 디렉터리 1회 + 파일마다 1회(파일 수는 프로그램 수이지 PR 수가 아니다)

읽지 못한 부분은 통과·없음으로 뭉개지 않고 `unknown` 목록에 사유와 함께 낸다(CLAUDE.md 원칙 7). 그 칸의 값은 `null` 이다.
원장 디렉터리가 아예 없는 저장소는 "원장 없음"(`ledger.status` == "none") 이고 확인 불능이 아니다. 원장을 읽다 실패하면
`ledger.status` == "unknown" 이다.

공통 원인: 같은 검사가 같은 사유로 PR 둘 이상에서 실패하면 맨 위 `common_causes` 에 한 번 싣고, 사람별 칸에는
`common_cause` 번호만 남긴다(예: Actions 결제 실패로 검사가 시작되지 않음).

"움직임 없음" 은 **사람이 마지막으로 손댄 때**로 판정한다. GitHub `updatedAt` 은 봇 코멘트·상태 갱신에도 바뀌므로 쓰지 않는다.
  - PR: 마지막 커밋 · 열린 때 · 사람(봇 제외)의 마지막 코멘트 · 리뷰 · 리뷰 코멘트 중 가장 늦은 시각.
  - 이슈: 사람의 마지막 코멘트, 없으면 생성 시각. (라벨·담당자 변경 같은 이벤트는 읽지 않는다 — 이슈마다 타임라인을 따로 읽어야 해
    호출이 이슈 수에 비례하기 때문. 한계로 status 기록에 적었다.)
지금과의 차가 기준일보다 **클 때**만 정체이고, 정확히 같으면 아직 아니다. 읽은 범위의 마지막 활동이 최근이면 정체가 아님이 확실하지만,
코멘트·리뷰가 많아 사람 활동을 다 읽지 못했거나 커밋 시각이 없으면 정체 여부를 단정하지 않고 "판정 불능" 이다(`updatedAt` 으로 대신하지 않는다).
"""
from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from checker import pr_queue
from checker.pairing import LEDGER_DIR, section_span, table_indexed
from checker.risk_gate import MERGE_ORDER_CHECK, PR_QUEUE_CHECK, _check_group, _run_state
from checker.ssot_approval import GhClient, GhError

# GitHub 아이디 형식. 밑줄은 Enterprise Managed Users 의 `name_shortcode` 형식 때문에 허용한다. 길이는 EMU 에서 더 길 수 있어 넉넉히 둔다.
GITHUB_LOGIN = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_]|-(?=[A-Za-z0-9_])){0,99}")
DEFAULT_DAYS = 7
DEFAULT_STALE_DAYS = 3
ISSUE_STALE_DAYS = 14
TIME_BUDGET_SEC = 150  # 이 시간을 넘기면 남은 읽기는 "시간 제한" 확인 불능으로 둔다
DETAIL_BATCH = 15
ISSUE_PAGES = 5
CONTEXT_PAGE = 50  # check 목록 한 쪽 크기
CONTEXT_EXTRA_PAGES = 4  # 50개를 넘는 PR 은 이만큼 더 넘겨 읽는다
KST = timezone(timedelta(hours=9))
HUMAN_WINDOW = 20  # PR·이슈마다 최근 코멘트·리뷰를 이만큼 읽는다
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
REASON_LIMIT = 300  # 이보다 길면 문장 끝에서 자르고 …
GENERIC_REASON_LEN = 20  # 이보다 짧은 사유("Failure" 등)는 흔한 문구로 본다

# 막힘 종류. 사람용 표와 JSON 이 같은 값을 쓴다.
K_CHECK = "check_failed"
K_CONFLICT = "conflict"
K_APPROVAL = "approval"
K_AFTER = "after"
K_OTHER = "other"
K_UNKNOWN = "unknown"
# 검사가 실패했거나 시작되지 못했을 수 있는 상태. 이 PR 들만 실패 사유를 읽는다.
TOO_MANY_CHECKS = f"검사가 {CONTEXT_PAGE * (CONTEXT_EXTRA_PAGES + 1)}개를 넘어 일부를 읽지 못함"
CHECK_READ_STATES = (pr_queue.CHECK_FAILED, pr_queue.NOT_STARTED, pr_queue.UNSTABLE, pr_queue.BLOCKED)

_DEV_ID = re.compile(r"^DEV-0*(\d+)$", re.IGNORECASE)


# --- 시간 ---------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def kst(dt: datetime | None) -> str:
    """KST 표기. 시각을 모르면 '시각 확인 불능'."""
    if dt is None:
        return "시각 확인 불능"
    return dt.astimezone(KST).strftime("%m-%d %H:%M KST")



# --- 읽기 ---------------------------------------------------------------------


class _Budget:
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise GhError(f"시간 제한({TIME_BUDGET_SEC}초)을 넘겨 읽지 못했다")


def graphql(client: GhClient, budget: _Budget, query: str, **variables: Any) -> dict:
    budget.check()
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += (["-F", f"{key}={value}"] if isinstance(value, int) else ["-f", f"{key}={value}"])
    raw = client.run(args)
    try:
        data = json.loads(raw or "null")
    except json.JSONDecodeError as exc:
        raise GhError(f"GraphQL 응답을 해석하지 못했다: {exc}") from exc
    if not isinstance(data, dict):
        raise GhError("GraphQL 응답이 객체가 아니다")
    if data.get("errors"):
        first = data["errors"][0] if isinstance(data["errors"], list) and data["errors"] else data["errors"]
        message = first.get("message") if isinstance(first, dict) else str(first)
        raise GhError(f"GraphQL 오류: {message}")
    body = data.get("data")
    if not isinstance(body, dict):
        raise GhError("GraphQL 응답에 data 가 없다")
    return body


def _split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise GhError(f"저장소 이름을 읽지 못했다: {repo}")
    return owner, name


def _login(node: dict | None) -> str:
    return ((node or {}).get("login")) or ""


# 봇은 `__typename == "Bot"` 이나 `[bot]` 접미사로 잡는다. 이름 목록은 GraphQL 이 봇의 login 에서 `[bot]` 을 떼어 주는 경우를 위한 것이라
# 그렇게 오는 것이 확인된 이 저장소 워크플로의 계정(GITHUB_TOKEN 의 github-actions, dependabot)만 둔다. `claude`·`copilot` 처럼
# 같은 이름의 사람 계정이 있을 수 있는 이름은 넣지 않는다 — 그런 봇은 __typename·접미사로 잡힌다.
BOT_LOGINS = frozenset({"github-actions", "dependabot"})


def _is_bot(node: dict | None, login: str) -> bool:
    low = login.lower()
    return (node or {}).get("__typename") == "Bot" or low.endswith("[bot]") or low in BOT_LOGINS


_WHO = "createdAt author{login __typename}"
_OPEN_META = (
    "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){"
    "pullRequests(states:OPEN,first:100,orderBy:{field:CREATED_AT,direction:DESC}){pageInfo{hasNextPage} nodes{"
    "number createdAt commits(last:1){nodes{commit{committedDate}}} "
    "comments(last:" + str(HUMAN_WINDOW) + "){totalCount nodes{" + _WHO + "}} "
    "reviews(last:" + str(HUMAN_WINDOW) + "){totalCount nodes{submittedAt " + _WHO + "}} "
    "reviewThreads(last:10){totalCount nodes{comments(last:1){nodes{" + _WHO + "}}}}"
    "}}}}"
)

KIND_LABEL = {"commit": "커밋", "opened": "PR 열기", "comment": "코멘트", "review": "리뷰", "review_comment": "리뷰 코멘트", "created": "이슈 생성"}


def latest_human(nodes: list | None, total: Any, key: str = "createdAt") -> tuple[datetime | None, bool]:
    """(사람이 남긴 가장 늦은 시각, 다 읽지 못했는가). `nodes` 는 가장 최근 것부터 잘라 온 창이라 거기 사람이 있으면 그게 가장 늦다.

    창에 사람이 하나도 없는데 창 밖에 더 있으면(전부 봇일 수 있다) 사람 활동을 다 읽지 못한 것이다.
    """
    best: datetime | None = None
    for n in nodes or []:
        if not n:
            continue
        author = n.get("author")
        if author and _is_bot(author, _login(author)):
            continue
        t = parse_time(n.get(key) or n.get("createdAt"))
        if t and (best is None or t > best):
            best = t
    return best, best is None and int(total or 0) > len(nodes or [])


def judge_activity(candidates: dict[str, datetime | None], incomplete: list[str], now: datetime, days: int) -> dict:
    """마지막 활동 {"at","kind","stale","unreadable"}. stale: True/False, 단정할 수 없으면 None(판정 불능).

    읽은 활동 중 가장 늦은 것이 기준일 안이면 정체 아님이 확실하다. 기준일을 넘었는데 읽지 못한 활동이 있으면 단정하지 않는다.
    """
    known = {k: v for k, v in candidates.items() if v is not None}
    unread = list(incomplete) + [k for k, v in candidates.items() if v is None and k in ("commit",)]
    if not known:
        return {"at": None, "kind": None, "stale": None, "unreadable": unread or ["활동"]}
    kind = max(known, key=lambda k: known[k])
    at = known[kind]
    if now - at <= timedelta(days=days):
        stale: bool | None = False
    elif unread:
        stale = None
    else:
        stale = True
    return {"at": at, "kind": kind, "stale": stale, "unreadable": unread}


def read_open_meta(client: GhClient, budget: _Budget, repo: str) -> tuple[dict[int, dict], bool]:
    """({PR 번호: 활동 시각 묶음}, 100개 뒤에 더 있는가).

    `gh pr list --limit 100`(기본 정렬 = 생성 최신순)이 읽는 집합과 같게 생성 최신순 100개를 읽는다. 어긋나는 PR 은
    호출한 쪽이 "판정 불능" 으로 올린다. 한 번의 GraphQL 로 커밋·코멘트·리뷰·리뷰 코멘트를 함께 읽는다.
    """
    owner, name = _split_repo(repo)
    data = graphql(client, budget, _OPEN_META, owner=owner, name=name)
    prs = ((data.get("repository") or {}).get("pullRequests")) or {}
    nodes = prs.get("nodes")
    if not isinstance(nodes, list):
        raise GhError("열린 PR 의 시각을 읽지 못했다(응답 모양이 다름)")
    out: dict[int, dict] = {}
    for n in nodes:
        commits = ((n.get("commits") or {}).get("nodes")) or []
        committed = ((commits[0].get("commit") or {}).get("committedDate")) if commits else None
        c, c_inc = latest_human((n.get("comments") or {}).get("nodes"), (n.get("comments") or {}).get("totalCount"))
        r, r_inc = latest_human((n.get("reviews") or {}).get("nodes"), (n.get("reviews") or {}).get("totalCount"), "submittedAt")
        threads = n.get("reviewThreads") or {}
        thread_comments = [x for t in (threads.get("nodes") or []) if t for x in ((t.get("comments") or {}).get("nodes") or [])]
        # 스레드는 위치순이라 창(최근 10개) 밖 스레드에 더 새로운 사람 답글이 있을 수 있다. 창 밖에 스레드가 있으면 보이는 사람 활동이
        # 있어도 일부를 못 읽은 것이다: 보이는 활동이 기준일 안이면 정체 아님이 확실하고(judge_activity), 넘었으면 단정하지 않는다.
        t_best, _ = latest_human(thread_comments, 0)
        t_inc = int(threads.get("totalCount") or 0) > len(threads.get("nodes") or [])
        out[n["number"]] = {
            "last_commit_at": committed,
            "created_at": n.get("createdAt"),
            "human": {"comment": c, "review": r, "review_comment": t_best},
            "incomplete": [k for k, v in (("comment", c_inc), ("review", r_inc), ("review_comment", t_inc)) if v],
        }
    return out, bool((prs.get("pageInfo") or {}).get("hasNextPage"))


def judge_pr(meta: dict, now: datetime, days: int) -> dict:
    cands = {
        "commit": parse_time(meta.get("last_commit_at")),
        "opened": parse_time(meta.get("created_at")),
        **meta["human"],
    }
    res = judge_activity(cands, [KIND_LABEL[k] for k in meta["incomplete"]], now, days)
    return res


_MERGED = """
query($q:String!){search(query:$q,type:ISSUE,first:100){issueCount nodes{
 ... on PullRequest{number title url mergedAt author{login __typename}}}}}
"""


def read_merged(client: GhClient, budget: _Budget, repo: str, since: datetime) -> tuple[list[dict], bool]:
    """(최근 병합 PR, 100개를 넘어 잘렸는가)."""
    query = f"repo:{repo} is:pr is:merged sort:updated-desc merged:>={since.astimezone(timezone.utc).strftime('%Y-%m-%d')}"
    data = graphql(client, budget, _MERGED, q=query)
    search = data.get("search")
    if not isinstance(search, dict) or not isinstance(search.get("nodes"), list):
        raise GhError("병합한 PR 목록을 읽지 못했다(응답 모양이 다름)")
    nodes = [n for n in search["nodes"] if n and n.get("number")]
    out = []
    for n in nodes:
        merged = parse_time(n.get("mergedAt"))
        if merged is None or merged < since:
            continue
        login = _login(n.get("author"))
        out.append(
            {
                "number": n["number"],
                "title": n.get("title") or "",
                "url": pr_queue.pr_url(repo, n["number"], n.get("url") or ""),
                "merged_at": n.get("mergedAt"),
                "author": login,
                "bot": _is_bot(n.get("author"), login),
            }
        )
    return out, int(search.get("issueCount") or 0) > len(nodes)


_ISSUES = """
query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
 issues(states:OPEN,first:100,after:$after,orderBy:{field:UPDATED_AT,direction:DESC}){
  pageInfo{hasNextPage endCursor}
  nodes{number title url createdAt assignees(first:10){nodes{login __typename}}
   comments(last:20){totalCount nodes{createdAt author{login __typename}}}}}}}
"""


def judge_issue(iss: dict, now: datetime, days: int) -> dict:
    """이슈의 마지막 사람 활동: 사람의 마지막 코멘트, 없으면 생성 시각(라벨·담당자 변경은 읽지 않는다)."""
    cands = {"comment": iss["human_comment_at"], "created": parse_time(iss["created_at"])}
    return judge_activity(cands, iss["incomplete"], now, days)


def read_issues(client: GhClient, budget: _Budget, repo: str) -> tuple[list[dict], bool]:
    """(열린 이슈, 쪽 수 제한으로 잘렸는가)."""
    owner, name = _split_repo(repo)
    out: list[dict] = []
    cursor = ""
    for _ in range(ISSUE_PAGES):
        variables = {"owner": owner, "name": name}
        if cursor:
            variables["after"] = cursor
        data = graphql(client, budget, _ISSUES, **variables)
        issues = (data.get("repository") or {}).get("issues")
        if not isinstance(issues, dict) or not isinstance(issues.get("nodes"), list):
            raise GhError("열린 이슈 목록을 읽지 못했다(응답 모양이 다름)")
        for n in issues["nodes"]:
            if not n or not n.get("number"):
                continue
            logins = [
                _login(a)
                for a in ((n.get("assignees") or {}).get("nodes")) or []
                if a and _login(a) and not _is_bot(a, _login(a))
            ]
            comments = n.get("comments") or {}
            human, human_inc = latest_human(comments.get("nodes"), comments.get("totalCount"))
            out.append(
                {
                    "number": n["number"],
                    "title": n.get("title") or "",
                    "url": n.get("url") or f"https://github.com/{repo}/issues/{n['number']}",
                    "created_at": n.get("createdAt"),
                    "human_comment_at": human,
                    "incomplete": ["코멘트"] if human_inc else [],
                    "assignees": logins,
                }
            )
        info = issues.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return out, False
        cursor = info.get("endCursor") or ""
        if not cursor:
            raise GhError("열린 이슈의 다음 쪽 위치를 읽지 못했다")
    return out, True


_CHECK_FIELDS = (
    "__typename ... on CheckRun{name status conclusion title summary annotations(first:10){nodes{message annotationLevel}}} "
    "... on StatusContext{context state description}"
)


def _detail_query(numbers: list[int]) -> str:
    aliases = " ".join(
        f"p{n}:pullRequest(number:{n}){{commits(last:1){{nodes{{commit{{statusCheckRollup{{contexts(first:{CONTEXT_PAGE}){{pageInfo{{hasNextPage endCursor}} nodes{{{_CHECK_FIELDS}}}}}}}}}}}}}}}"
        for n in numbers
    )
    return f"query($owner:String!,$name:String!){{repository(owner:$owner,name:$name){{{aliases}}}}}"


_MORE_CONTEXTS = (
    "query($owner:String!,$name:String!,$number:Int!,$after:String!){repository(owner:$owner,name:$name){"
    "pullRequest(number:$number){commits(last:1){nodes{commit{statusCheckRollup{contexts(first:" + str(CONTEXT_PAGE) + ",after:$after){"
    "pageInfo{hasNextPage endCursor} nodes{" + _CHECK_FIELDS + "}}}}}}}}}"
)


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _clean(text: str) -> str:
    """공백을 정리하고, REASON_LIMIT 를 넘으면 문장 끝(없으면 단어 끝)에서 잘라 …를 붙인다. 단어 중간에서 끊지 않는다."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= REASON_LIMIT:
        return text
    head = text[:REASON_LIMIT]
    ends = [m.end() for m in re.finditer(r"[.!?。](?=\s|$)", head)]
    if ends and ends[-1] >= REASON_LIMIT // 3:
        return head[: ends[-1]] + "…"
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(" ,;:") + "…"


def is_generic_reason(reason: str) -> bool:
    """어느 검사에서나 나올 흔한 사유인가. 이런 사유는 검사 이름까지 같아야 같은 원인으로 본다.

    `exit code N` 을 담았거나 20자보다 짧다(문구가 구체적이지 않다). 사유 문구가 없으면(None) 애초에 묶지 않는다.
    """
    return len(reason) < GENERIC_REASON_LEN or re.search(r"exit code \d+", reason, re.IGNORECASE) is not None


def _reason_of(node: dict) -> str | None:
    """check run 의 실패 사유 문구. 실패 등급 annotation(구체적인 문구 우선) > title > summary 첫 줄. 모두 비면 None(사유 문구 없음).

    경고·알림 등급(예: "Node.js 20 is deprecated")은 실패 이유가 아니라서 쓰지 않는다(#457). 등급이 없으면 실패로 본다.
    """
    if node.get("__typename") == "StatusContext":
        return _clean(node.get("description") or "") or None
    notes = ((node.get("annotations") or {}).get("nodes")) or []
    texts = []
    for note in notes:
        if (note or {}).get("annotationLevel") not in (None, "FAILURE"):
            continue
        text = _first_line((note or {}).get("message"))
        if text:
            texts.append(_clean(text))
    # "Process completed with exit code 1." 같은 흔한 문구보다 구체적인 실패 문구를 먼저 쓴다(#457).
    for text in texts:
        if not is_generic_reason(text):
            return text
    if texts:
        return texts[0]
    for text in (node.get("title"), _first_line(node.get("summary"))):
        if text and text.strip():
            return _clean(text)
    return None


def _failed_nodes(nodes: list[dict]) -> list[dict]:
    """pr_queue.classify 가 검사 실패로 세는 것과 같은 기준으로 실패한 검사만 남긴다."""
    out = []
    for node in nodes:
        if not node:
            continue
        entry = pr_queue._norm_check(
            {"context": node.get("context"), "state": node.get("state")}
            if node.get("__typename") == "StatusContext"
            else {"name": node.get("name"), "status": node.get("status"), "conclusion": node.get("conclusion")}
        )
        name = entry["name"]
        # classify 는 pr-checks 같은 합친 job 의 실패를 세지 않지만(단계가 옛 이름으로 따로 보고), Actions 결제 실패처럼 job 이
        # 시작되지 못한 사유는 그 job 의 annotation 에 있다. 그래서 여기서는 순서 표시·알림·승인 게이트만 뺀다.
        if _check_group(name) in (MERGE_ORDER_CHECK, PR_QUEUE_CHECK) or pr_queue._is_excluded_alert(name):
            continue
        if _check_group(name) in pr_queue.GATE_GROUPS:
            continue
        if _run_state(entry) == "fail":
            out.append({"name": name, "reason": _reason_of(node), "node": node})
    return out


def _contexts_of(pr: dict | None) -> dict:
    commits = ((pr or {}).get("commits") or {}).get("nodes") or []
    rollup = ((commits[0].get("commit") or {}).get("statusCheckRollup")) if commits else None
    contexts = (rollup or {}).get("contexts")
    if not isinstance(contexts, dict) or not isinstance(contexts.get("nodes"), list):
        raise GhError("검사 결과를 읽지 못했다(응답 모양이 다름)")
    return contexts


def read_failures(
    client: GhClient, budget: _Budget, repo: str, numbers: list[int]
) -> tuple[dict[int, list[dict]], dict[int, str], set[int]]:
    """검사 막힌 PR 의 실패 검사와 사유. ({번호: [{"name","reason"}]}, {읽지 못한 번호: 사유}, {검사가 너무 많아 일부를 못 읽은 번호}).

    검사가 한 쪽(50개)을 넘는 PR 은 쪽을 넘겨 더 읽고(최대 CONTEXT_EXTRA_PAGES 쪽), 그래도 남으면 일부를 못 읽은 것으로 표시한다.
    """
    owner, name = _split_repo(repo)
    found: dict[int, list[dict]] = {}
    failed: dict[int, str] = {}
    partial: set[int] = set()
    for i in range(0, len(numbers), DETAIL_BATCH):
        batch = numbers[i : i + DETAIL_BATCH]
        try:
            data = graphql(client, budget, _detail_query(batch), owner=owner, name=name)
            repo_data = data.get("repository") or {}
        except GhError as exc:
            for n in batch:
                failed[n] = str(exc)
            continue
        for n in batch:
            try:
                contexts = _contexts_of(repo_data.get(f"p{n}"))
                nodes = list(contexts["nodes"])
                info = contexts.get("pageInfo") or {}
                extra = 0
                while info.get("hasNextPage"):
                    if extra >= CONTEXT_EXTRA_PAGES or not info.get("endCursor"):
                        partial.add(n)
                        break
                    extra += 1
                    try:
                        more = _contexts_of(
                            graphql(client, budget, _MORE_CONTEXTS, owner=owner, name=name, number=n, after=info["endCursor"])
                            .get("repository", {})
                            .get("pullRequest")
                        )
                    except GhError:
                        partial.add(n)
                        break
                    nodes.extend(more["nodes"])
                    info = more.get("pageInfo") or {}
                found[n] = [{"name": f["name"], "reason": f["reason"]} for f in _failed_nodes(nodes)]
            except (GhError, AttributeError, KeyError, TypeError, IndexError) as exc:
                failed[n] = str(exc) or "검사 결과를 읽지 못했다"
    return found, failed, partial


# --- 진행 원장 ----------------------------------------------------------------


def _decode(data: Any, path: str) -> str:
    if not isinstance(data, dict) or "content" not in data:
        raise GhError(f"`{path}` 의 내용을 읽지 못했다")
    try:
        text = base64.b64decode(data.get("content", "") or "").decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise GhError(f"`{path}` 를 해석하지 못했다: {exc}") from exc
    return text[1:] if text.startswith("﻿") else text


def parse_ledger(text: str, path: str) -> list[dict]:
    """원장 파일 하나의 개발 건. 표를 읽지 못하면 GhError(사유 포함)."""
    span = section_span(text, "개발 건")
    if span is None:
        raise GhError(f"`{path}` 에서 `## 개발 건` 절을 찾지 못했다")
    table = table_indexed(text.splitlines()[span[0] : span[1]])
    if table is None:
        raise GhError(f"`{path}` 의 개발 건 표 머리(`ID` 열)를 찾지 못했다")
    header, rows = table
    if "상태" not in header:
        raise GhError(f"`{path}` 의 개발 건 표 머리에 `상태` 열이 없다")
    out = []
    for _, cells in rows:
        row = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
        m = _DEV_ID.match(row.get("ID", "").strip())
        if not m:
            continue  # 빈 줄(ID 칸이 비어 있는 서식 행)은 건너뛴다
        out.append(
            {
                "id": f"DEV-{int(m.group(1)):03d}",
                "title": row.get("내용", "").strip(),
                "owner": row.get("담당", "").strip().lstrip("@"),
                "status": row.get("상태", "").strip(),
                "last_pr": row.get("마지막 PR", "").strip().strip("-—–"),
                "file": path,
            }
        )
    return out


def read_default_branch(client: GhClient, budget: _Budget, repo: str) -> str:
    budget.check()
    info = client.get_json(f"repos/{repo}")
    branch = info.get("default_branch") if isinstance(info, dict) else None
    if not branch:
        raise GhError("저장소의 기본 브랜치를 읽지 못했다")
    return branch


ALIAS_PATH = ".github/harness-team.yaml"  # 승인자 파일(.github/ssot-approvers)처럼 Project Repository 의 .github 에 둔다


def read_aliases(client: GhClient, budget: _Budget, repo: str, branch: str | None) -> tuple[dict[str, str], list[str], str | None]:
    """기본 브랜치의 `.github/harness-team.yaml` 의 `별칭`(이름 → GitHub 아이디). (별칭, 경고들, 읽기 실패 사유).

    파일이 없으면(404) 별칭 없음이고 경고도 없다. 읽기 실패(GhError)는 경고에 더해 세 번째 값으로 사유를 돌려줘 호출한 쪽이 `unknown` 에
    올리게 한다. 형식 오류·아이디 형식이 아닌 값·대소문자만 다른 중복 이름은 경고만 내고 그 부분만 빼고(중복은 먼저 나온 것을 써) 계속한다.
    사람 묶기 전체를 확인 불능으로 만들지 않는다.
    """
    import yaml

    if not branch:
        return {}, [f"기본 브랜치를 읽지 못해 `{ALIAS_PATH}` 를 읽지 못했다(별칭 없이 계속)"], None
    try:
        budget.check()
        data = client.get_json_or_none_404(f"repos/{repo}/contents/{ALIAS_PATH}?ref={branch}")
        if data is None:
            return {}, [], None
        text = _decode(data, ALIAS_PATH)
    except GhError as exc:
        return {}, [f"`{ALIAS_PATH}` 를 읽지 못했다(별칭 없이 계속): {exc}"], str(exc)
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {}, [f"`{ALIAS_PATH}` 형식 오류(별칭 없이 계속): {str(exc).splitlines()[0] if str(exc) else exc}"], None
    if doc is None:
        return {}, [], None
    table = doc.get("별칭") if isinstance(doc, dict) else None
    if not isinstance(table, dict):
        return {}, [f"`{ALIAS_PATH}` 형식 오류(별칭 없이 계속): 최상위에 `별칭:` 아래 `이름: GitHub아이디` 목록이 있어야 한다"], None
    aliases: dict[str, str] = {}
    warns: list[str] = []
    for name, login in table.items():
        name, login = str(name).strip(), (str(login).strip().lstrip("@") if login is not None else "")
        if not GITHUB_LOGIN.fullmatch(login):
            warns.append(f"`{ALIAS_PATH}` 의 별칭 {name!r} 의 값 {login!r} 가 GitHub 아이디 형식이 아니다 — 이 별칭은 적용하지 않았다")
        elif name:
            if name.lower() in aliases:
                warns.append(f"`{ALIAS_PATH}` 에 대소문자만 다른 중복 이름 {name!r} 가 있다 — 먼저 나온 {aliases[name.lower()]!r} 를 쓴다")
            else:
                aliases[name.lower()] = login
    return aliases, warns, None


def read_ledger(client: GhClient, budget: _Budget, repo: str) -> dict:
    """{"status": "ok"|"none"|"unknown", "reason", "branch", "files", "items"}.

    저장소 기본 브랜치를 먼저 조회해 그 브랜치에서 읽는다. 기본 브랜치를 못 읽으면 원장 위치를 알 수 없으므로 "unknown" 이다.
    "none"(원장 없음)은 기본 브랜치를 읽은 뒤 `audit/ledger` 가 실제로 없을 때(404)만이다.
    """

    def result(status: str, reason: str = "", branch: str | None = None, files=(), items=()) -> dict:
        return {"status": status, "reason": reason, "branch": branch, "files": list(files), "items": list(items)}

    try:
        branch = read_default_branch(client, budget, repo)
    except GhError as exc:
        return result("unknown", f"기본 브랜치를 읽지 못해 원장 위치를 알 수 없음: {exc}")
    base = f"repos/{repo}/contents/{LEDGER_DIR}"
    try:
        budget.check()
        listing = client.get_json_or_none_404(f"{base}?ref={branch}")
    except GhError as exc:
        return result("unknown", f"원장 디렉터리를 읽지 못함: {exc}", branch)
    if listing is None:
        return result("none", "", branch)
    if not isinstance(listing, list):
        return result("unknown", f"`{LEDGER_DIR}` 가 디렉터리가 아니다", branch)
    paths = sorted(e["path"] for e in listing if isinstance(e, dict) and e.get("type") == "file" and str(e.get("path", "")).endswith(".md"))
    if not paths:
        return result("none", "", branch)
    items: list[dict] = []
    problems: list[str] = []
    for path in paths:
        try:
            budget.check()
            data = client.get_json_or_none_404(f"repos/{repo}/contents/{path}?ref={branch}")
            if data is None:
                raise GhError(f"`{path}` 를 찾지 못했다")
            items.extend(parse_ledger(_decode(data, path), path))
        except GhError as exc:
            problems.append(str(exc))
    if problems:
        return result("unknown", "; ".join(problems), branch, paths, items)
    return result("ok", "", branch, paths, items)


# --- 계산 ---------------------------------------------------------------------


def _blockers(it: dict, fail_info: dict | None, fail_err: str | None, partial: bool = False) -> dict | None:
    """열린 PR 하나의 막힘. 막힌 게 없으면 None, 있으면 PR 당 하나 {pr,title,url,author,reasons:[…]}.

    reasons 의 각 항목은 {kind,state,detail} 이고 검사 실패면 checks[], 앞 PR 대기면 after[] 가 붙는다.
    상태 이름은 pr_queue 의 것을 그대로 쓴다.
    """
    reasons: list[dict] = []
    state, detail = it["state"], it["detail"]
    found = [{"name": c["name"], "reason": c["reason"], "reason_status": "ok" if c["reason"] else "no_text"} for c in fail_info or []]
    if found and state in CHECK_READ_STATES:
        reasons.append({"kind": K_CHECK, "state": state, "detail": detail, "checks": found, "checks_truncated": partial})
    elif state == pr_queue.CHECK_FAILED:
        why = fail_err or (TOO_MANY_CHECKS if partial else "실패한 검사의 사유 문구를 찾지 못했다")
        checks = [{"name": detail or "검사", "reason": None, "reason_status": "unknown", "unknown_reason": why}]
        reasons.append({"kind": K_CHECK, "state": state, "detail": detail, "checks": checks, "checks_truncated": partial})
    elif state == pr_queue.CONFLICT:
        reasons.append({"kind": K_CONFLICT, "state": state, "detail": detail})
    elif state == pr_queue.WAITING_APPROVAL:
        reasons.append({"kind": K_APPROVAL, "state": state, "detail": detail})
    elif state == pr_queue.UNKNOWN:
        reasons.append({"kind": K_UNKNOWN, "state": state, "detail": detail})
    elif state in (pr_queue.NOT_STARTED, pr_queue.BEHIND, pr_queue.BLOCKED, pr_queue.UNSTABLE):
        if fail_err and state in CHECK_READ_STATES:
            detail = f"{detail} (실패한 검사가 있는지 확인 불능: {fail_err})".strip()
        elif partial and state in CHECK_READ_STATES:
            detail = f"{detail} ({TOO_MANY_CHECKS})".strip()
        reasons.append({"kind": K_OTHER, "state": state, "detail": detail})
    if it["order"] is None:
        notes = [n for n in it["notes"] if n.startswith((pr_queue.CYCLE_NOTE, pr_queue.BEHIND_ORDER_NOTE))]
        reasons.append({"kind": K_UNKNOWN, "state": "순서 판정 불능", "detail": "; ".join(notes)})
    elif it["after"]:
        reasons.append({"kind": K_AFTER, "state": "앞 PR 대기", "detail": "", "after": it["after"]})
    if not reasons:
        return None
    return {"pr": it["number"], "title": it["title"], "url": it["url"], "author": it["author"], "reasons": reasons}


def _all_checks(people: dict[str, dict]):
    for person in people.values():
        for b in person["blocked"] or []:
            for r in b["reasons"]:
                for c in r.get("checks", []):
                    yield b, c


def _cause_key(c: dict) -> tuple[str, str]:
    """공통 원인의 열쇠. 사유가 구체적이면 문구만(검사 이름은 목록으로 붙는다), 흔한 문구면 (검사 이름, 문구)."""
    return (c["name"] if is_generic_reason(c["reason"]) else "", c["reason"])


def _assign_common(people: dict[str, dict]) -> list[dict]:
    """같은 사유가 PR 둘 이상에서 실패하면 공통 원인으로 올린다. 사람별 칸에는 번호만 남긴다."""
    groups: dict[tuple[str, str], dict] = {}
    for b, c in _all_checks(people):
        if c["reason"]:
            g = groups.setdefault(_cause_key(c), {"prs": {}, "checks": set()})
            g["prs"][b["pr"]] = b
            g["checks"].add(c["name"])
    ids: dict[tuple[str, str], int] = {}
    causes: list[dict] = []
    for key, g in sorted(groups.items(), key=lambda kv: min(kv[1]["prs"])):
        if len(g["prs"]) < 2:
            continue
        cid = len(causes) + 1
        ids[key] = cid
        causes.append(
            {
                "id": cid,
                "mark": CIRCLED[cid - 1] if cid <= len(CIRCLED) else f"({cid})",
                "checks": sorted(g["checks"]),
                "reason": key[1],
                "prs": [{"number": n, "title": b["title"], "url": b["url"], "author": b["author"]} for n, b in sorted(g["prs"].items())],
            }
        )
    for _, c in _all_checks(people):
        c["common_cause"] = ids.get(_cause_key(c)) if c["reason"] else None
    return causes


def _person(login: str) -> dict:
    return {
        "login": login,
        "progress": {"merged": [], "merged_count": 0, "open": []},
        "blocked": [],
        "stale": {"prs": [], "issues": [], "unknown_prs": [], "unknown_issues": []},
        "dev_items": [],
    }


def compute_team(
    client: GhClient,
    repo: str,
    days: int = DEFAULT_DAYS,
    stale_days: int = DEFAULT_STALE_DAYS,
    issue_stale_days: int = ISSUE_STALE_DAYS,
    now: datetime | None = None,
) -> dict:
    """팀원별 현황. 열린 PR 목록 자체를 읽지 못하면 GhError 를 던지고(전체 확인 불능), 나머지는 칸마다 확인 불능으로 둔다."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    budget = _Budget(TIME_BUDGET_SEC)
    queue = pr_queue.compute(client, repo)  # GhError 는 호출한 쪽이 전체 확인 불능으로 낸다
    unknown: list[dict] = []
    warnings: list[str] = list(queue["warnings"])
    if queue["truncated"]:
        warnings.append(f"열린 PR 이 {pr_queue.PR_LIMIT}개 이상이라 일부만 읽었다.")

    def miss(item: str, exc: Exception | str) -> None:
        unknown.append({"item": item, "reason": str(exc)})

    truncated = {"open_prs": bool(queue["truncated"]), "merged": False, "issues": False}

    meta: dict[int, dict] | None
    try:
        meta, more_prs = read_open_meta(client, budget, repo)
        if more_prs:
            truncated["open_prs"] = True
            warnings.append(f"열린 PR 이 {pr_queue.PR_LIMIT}개를 넘어 시각을 일부만 읽었다.")
    except GhError as exc:
        meta = None
        miss("열린 PR 의 마지막 커밋·갱신 시각", exc)

    merged: list[dict] | None
    try:
        merged, truncated["merged"] = read_merged(client, budget, repo, now - timedelta(days=days))
        if truncated["merged"]:
            warnings.append("병합한 PR 이 100개를 넘어 최근에 갱신된 100개만 읽었다(병합 수는 적게 보일 수 있다).")
    except GhError as exc:
        merged = None
        miss(f"최근 {days}일 병합한 PR", exc)

    issues: list[dict] | None
    try:
        issues, truncated["issues"] = read_issues(client, budget, repo)
        if truncated["issues"]:
            warnings.append(f"열린 이슈가 {ISSUE_PAGES * 100}개를 넘어 최근에 갱신된 것만 읽었다. 오래 머문 이슈는 오래된 것부터 빠져 있다.")
    except GhError as exc:
        issues = None
        miss("열린 이슈와 담당자", exc)

    failing = sorted(it["number"] for it in queue["prs"] if it["state"] in CHECK_READ_STATES)
    fail_info, fail_err, fail_partial = ({}, {}, set())
    if failing:
        fail_info, fail_err, fail_partial = read_failures(client, budget, repo, failing)
        if fail_err:
            miss("검사 실패 사유", "; ".join(f"#{n}: {why}" for n, why in sorted(fail_err.items())))
        if fail_partial:
            miss("검사 목록 일부", "; ".join(f"#{n}: {TOO_MANY_CHECKS}" for n in sorted(fail_partial)))

    ledger = read_ledger(client, budget, repo)
    if ledger["status"] == "unknown":
        miss("진행 원장", ledger["reason"])

    aliases, alias_warnings, alias_error = read_aliases(client, budget, repo, ledger.get("branch"))
    warnings.extend(alias_warnings)
    if alias_error:  # 404 가 아닌 읽기 실패는 경고뿐 아니라 unknown 에도 올려 JSON 소비자가 놓치지 않게 한다
        miss("팀 별칭 파일", alias_error)
    aliases_applied: dict[str, dict] = {}

    people: dict[str, dict] = {}

    def person(login: str) -> dict:
        return people.setdefault(login, _person(login))

    open_prs = [it for it in queue["prs"] if it["author"] and not it["author"].endswith("[bot]")]
    no_time: list[str] = []
    for it in open_prs:
        p = person(it["author"])
        m = (meta or {}).get(it["number"])
        base = {"number": it["number"], "title": it["title"], "url": it["url"], "state": it["state"]}
        entry = {**base, "last_commit_at": m["last_commit_at"] if m else None, "last_activity_at": None, "last_activity_kind": None}
        p["progress"]["open"].append(entry)
        blocked = _blockers(it, fail_info.get(it["number"]), fail_err.get(it["number"]), it["number"] in fail_partial)
        if blocked:
            p["blocked"].append(blocked)
        if meta is None:
            continue  # 시각을 전혀 못 읽음: 위에서 한 번 확인 불능으로 올렸다
        if m is None:
            p["stale"]["unknown_prs"].append(it["number"])
            no_time.append(f"#{it['number']}(활동 시각 목록에 없음)")
            continue
        j = judge_pr(m, now, stale_days)
        if j["stale"] is None:  # 시각을 못 읽은 PR 을 정체 아님으로 두지 않는다
            p["stale"]["unknown_prs"].append(it["number"])
            no_time.append(f"#{it['number']}({', '.join(j['unreadable'])} 일부를 읽지 못함)")
            continue
        entry["last_activity_at"] = _iso(j["at"])
        entry["last_activity_kind"] = j["kind"]
        if j["stale"]:
            idle = (now - j["at"]).total_seconds() / 86400
            p["stale"]["prs"].append(
                {**base, "last_activity_at": _iso(j["at"]), "last_activity_kind": j["kind"], "idle_days": round(idle, 1)}
            )
    if no_time:
        miss("PR 활동 시각(정체 판정 불능)", "; ".join(no_time))
    if merged is not None:
        for m_pr in sorted(merged, key=lambda x: x["merged_at"] or "", reverse=True):
            if m_pr["bot"] or not m_pr["author"]:
                continue
            p = person(m_pr["author"])
            p["progress"]["merged"].append({k: m_pr[k] for k in ("number", "title", "url", "merged_at")})
        for p in people.values():
            if p["progress"]["merged"] is not None:
                p["progress"]["merged_count"] = len(p["progress"]["merged"])

    unassigned: list[dict] | None = None
    if issues is not None:
        unassigned = []
        issue_unknown: list[str] = []
        for iss in issues:
            if not iss["assignees"]:
                unassigned.append({k: iss[k] for k in ("number", "title", "url", "created_at")})
                continue
            j = judge_issue(iss, now, issue_stale_days)
            for login in iss["assignees"]:
                st = person(login)["stale"]
                if j["stale"] is None:
                    st["unknown_issues"].append(iss["number"])
                elif j["stale"]:
                    idle = (now - j["at"]).total_seconds() / 86400
                    st["issues"].append(
                        {"number": iss["number"], "title": iss["title"], "url": iss["url"], "last_activity_at": _iso(j["at"]),
                         "last_activity_kind": j["kind"], "idle_days": round(idle, 1)}
                    )
            if j["stale"] is None:
                issue_unknown.append(f"#{iss['number']}({', '.join(j['unreadable'])} 일부를 읽지 못함)")
        if issue_unknown:
            miss("이슈 활동 시각(정체 판정 불능)", "; ".join(issue_unknown))

    last_author = {n["number"]: n["author"] for n in open_prs}
    last_author.update({m_pr["number"]: m_pr["author"] for m_pr in merged or []})
    ledger_unowned: list[dict] | None = [] if ledger["status"] != "unknown" else None
    lower = {k.lower(): k for k in people}
    if ledger["status"] == "unknown":
        ledger_unowned = None
    elif ledger["status"] == "ok":
        for item in ledger["items"]:
            m = re.search(r"#(\d+)", item["last_pr"])
            if item["owner"]:
                # 담당이 적혀 있으면 이번 기간에 활동이 없어도 그 사람 칸을 만들어 배정한다.
                alias = aliases.get(item["owner"].lower())
                if alias:  # 별칭을 먼저 적용한다. 바꾼 담당은 아이디 형식 경고에서 뺀다.
                    entry = aliases_applied.setdefault(item["owner"], {"name": item["owner"], "login": alias, "items": []})
                    entry["items"].append(item["id"])
                    item = {**item, "owner": alias}
                elif not GITHUB_LOGIN.fullmatch(item["owner"]):
                    # 실명 등을 추측해 아이디와 합치지 않는다 — 원장 담당 칸을 GitHub 아이디로 고치게 알린다.
                    warnings.append(f"원장 {item['id']} 의 담당 {item['owner']!r} 가 GitHub 아이디 형식이 아니다 — 같은 사람이 따로 보일 수 있으니 원장 담당 칸을 GitHub 아이디로 고친다.")
                owner = lower.get(item["owner"].lower()) or item["owner"]
                lower[owner.lower()] = owner
            else:
                owner = last_author.get(int(m.group(1))) if m else None
            if owner:
                person(owner)["dev_items"].append({k: item[k] for k in ("id", "title", "owner", "status", "last_pr", "file")})
            else:
                ledger_unowned.append({k: item[k] for k in ("id", "title", "owner", "status", "last_pr", "file")})

    # 읽지 못한 칸은 비어 있는 것과 구별되게 null 로 둔다(원칙 7). 늦게 생긴 사람까지 모두 거친 뒤에 채운다.
    for p in people.values():
        if meta is None:
            for o in p["progress"]["open"]:
                o["last_commit_at"] = o["last_activity_at"] = o["last_activity_kind"] = None
            p["stale"]["prs"] = None
            p["stale"]["unknown_prs"] = None
        if merged is None:
            p["progress"]["merged"] = p["progress"]["merged_count"] = None
        if issues is None:
            p["stale"]["issues"] = p["stale"]["unknown_issues"] = None
        if ledger["status"] != "ok":
            p["dev_items"] = None

    causes = _assign_common(people)
    for p in people.values():
        p["progress"]["open"].sort(key=lambda o: o["number"])
        if p["stale"]["prs"]:
            p["stale"]["prs"].sort(key=lambda o: -o["idle_days"])
        if p["stale"]["issues"]:
            p["stale"]["issues"].sort(key=lambda o: -o["idle_days"])

    return {
        "status": "ok",
        "repo": repo,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "days": days,
        "stale_days": stale_days,
        "issue_stale_days": issue_stale_days,
        "common_causes": causes,
        "people": [people[k] for k in sorted(people, key=str.lower)],
        "unassigned_issues": unassigned,
        "ledger": {"status": ledger["status"], "reason": ledger["reason"], "branch": ledger["branch"], "files": ledger["files"], "unowned": ledger_unowned},
        "truncated": truncated,
        "aliases_applied": sorted(aliases_applied.values(), key=lambda a: a["name"]),
        "unknown": unknown,
        "warnings": warnings,
    }


# --- 출력 ---------------------------------------------------------------------

_BLOCK_LABEL = {K_CHECK: "검사 실패", K_CONFLICT: "충돌", K_APPROVAL: "리뷰·승인 대기", K_AFTER: "앞 PR 대기", K_OTHER: "병합 조건", K_UNKNOWN: "확인 불능"}


def _link(repo: str, n: int, url: str = "") -> str:
    return pr_queue.pr_link(repo, n, url)


def _count(value: list | None) -> str:
    return "확인 불능" if value is None else str(len(value))


def _short_check(name: str) -> str:
    """공통 원인 칸이 길어지지 않게 'ai-review / review' 를 앞 이름 'ai-review' 로 줄인다."""
    return _check_group(name) or name


def _join_checks(names) -> str:
    seen: list[str] = []
    for n in names:
        short = _short_check(n)
        if short not in seen:
            seen.append(short)
    return "·".join(seen)


def _mark(n: int) -> str:
    return CIRCLED[n - 1] if n <= len(CIRCLED) else f"({n})"


def _reason_text(repo: str, r: dict) -> str:
    """막힘 하나를 한 구로. 검사 실패는 공통 원인이면 번호와 검사 이름 목록, 아니면 검사 이름: 사유 전문."""
    label = _BLOCK_LABEL[r["kind"]]
    if r["kind"] == K_CHECK:
        parts = []
        if r.get("checks_truncated"):
            parts.append(f"({TOO_MANY_CHECKS})")
        for cid in sorted({c["common_cause"] for c in r["checks"] if c["common_cause"]}):
            names = _join_checks(c["name"] for c in r["checks"] if c["common_cause"] == cid)
            parts.append(f"공통 원인 {_mark(cid)} ({names})")
        for c in r["checks"]:
            if c["common_cause"]:
                continue
            if c["reason_status"] == "unknown":
                parts.append(f"{c['name']}: 사유 확인 불능({c['unknown_reason']})")
            else:
                parts.append(f"{c['name']}: {c['reason'] or '사유 문구 없음'}")
        return f"{label}: " + "; ".join(parts)
    if r["kind"] == K_AFTER:
        return "앞 " + ", ".join(_link(repo, n) for n in r["after"]) + " 병합 대기"
    if r["kind"] == K_CONFLICT:
        return label
    return f"{label}: {pr_queue._clip(r['detail'] or r['state'], 100)}"


def render_team(res: dict) -> str:
    repo = res["repo"]
    now = parse_time(res["generated_at"])
    clip = pr_queue._clip
    lines = [
        f"{repo} 팀원별 현황 (기준 {kst(now)}, 병합은 최근 {res['days']}일, "
        f"정체 기준 PR {res['stale_days']}일·이슈 {res['issue_stale_days']}일 초과)",
    ]
    if res["unknown"]:
        lines += ["", "## 확인 불능(읽지 못해 아래 해당 칸은 없다·정상이라는 뜻이 아니다)"]
        lines += [f"- {u['item']}: {u['reason']}" for u in res["unknown"]]
    led = res["ledger"]
    if led["status"] == "none":
        lines += ["", f"진행 원장: 원장 없음(기본 브랜치 {led['branch']} 에 `audit/ledger/` 가 없어 맡은 개발 건은 건너뜀)"]
    tr = res["truncated"]
    lines += ["", "## 공통 원인"]
    if not res["common_causes"]:
        lines.append("없음(같은 사유로 실패한 PR 이 둘 이상인 검사가 없다)")
    for c in res["common_causes"]:
        prs = ", ".join(f"{_link(repo, p['number'], p['url'])}(@{p['author']})" for p in c["prs"])
        checks = _join_checks(c["checks"])
        lines.append(f"- {c['mark']} {c['reason']} — 검사 {checks} — {prs}")

    lines += ["", "## 팀원 요약", "", "| 팀원 | 최근 병합 | 열린 PR | 막힌 PR | 오래 머문 PR | 오래 머문 이슈 | 진행 중 개발 건 |", "|---|---|---|---|---|---|---|"]
    for p in res["people"]:
        devs = p["dev_items"]
        active = "확인 불능" if led["status"] == "unknown" else ("원장 없음" if devs is None else str(sum(1 for d in devs if d["status"] != "완료")))
        merged = "확인 불능" if p["progress"]["merged"] is None else str(p["progress"]["merged_count"]) + ("+ (부분)" if tr["merged"] else "")
        stale_prs = _count(p["stale"]["prs"])
        if p["stale"]["unknown_prs"]:
            stale_prs += f" + 판정 불능 {len(p['stale']['unknown_prs'])}"
        stale_issues = _count(p["stale"]["issues"])
        if p["stale"]["unknown_issues"]:
            stale_issues += f" + 판정 불능 {len(p['stale']['unknown_issues'])}"
        if tr["issues"] and p["stale"]["issues"] is not None:
            stale_issues = f"{stale_issues}+ (확인 불능, 부분)"
        lines.append(
            f"| @{p['login']} | {merged} | {len(p['progress']['open'])} | {len(p['blocked'])} | "
            f"{stale_prs} | {stale_issues} | {active} |"
        )

    for p in res["people"]:
        lines += ["", f"### @{p['login']}"]
        merged = p["progress"]["merged"]
        if merged is None:
            lines.append("- 진행(병합): 확인 불능")
        elif merged:
            lines.append(f"- 진행(최근 {res['days']}일 병합 {len(merged)}개{'이상, 일부만 읽음' if tr['merged'] else ''}): " + " · ".join(f"{_link(repo, m['number'], m['url'])} {clip(m['title'], 24)}" for m in merged[:8]) + (f" 외 {len(merged) - 8}개" if len(merged) > 8 else ""))
        else:
            lines.append(f"- 진행(최근 {res['days']}일 병합): 없음")
        for o in p["progress"]["open"]:
            commit = kst(parse_time(o["last_commit_at"])) if o["last_commit_at"] else "확인 불능"
            human = (
                f", 마지막 활동 {KIND_LABEL[o['last_activity_kind']]} {kst(parse_time(o['last_activity_at']))}"
                if o["last_activity_at"]
                else ", 마지막 활동 판정 불능"
            )
            lines.append(f"- 열린 PR {_link(repo, o['number'], o['url'])} {clip(o['title'])} — 마지막 커밋 {commit}{human}")
        for b in p["blocked"]:
            lines.append(f"- 막힘 {_link(repo, b['pr'], b['url'])} " + " · ".join(_reason_text(repo, r) for r in b["reasons"]))
        if p["stale"]["prs"] is None:
            lines.append("- 오래 머문 PR: 확인 불능")
        if p["stale"]["unknown_prs"]:
            lines.append("- 오래 머문 PR 판정 불능(활동 시각을 다 읽지 못함): " + ", ".join(_link(repo, n) for n in p["stale"]["unknown_prs"]))
        for s in p["stale"]["prs"] or []:
            lines.append(f"- 오래 머문 PR {_link(repo, s['number'], s['url'])} {clip(s['title'])} — {s['idle_days']}일 움직임 없음(마지막 {KIND_LABEL[s['last_activity_kind']]} {kst(parse_time(s['last_activity_at']))})")
        if p["stale"]["issues"] is None:
            lines.append("- 오래 머문 이슈: 확인 불능")
        elif tr["issues"]:
            lines.append("- 오래 머문 이슈: 확인 불능(부분) — 열린 이슈가 많아 오래된 것부터 잘렸다. 아래는 읽은 범위 안의 것뿐이다")
        for s in p["stale"]["issues"] or []:
            lines.append(f"- 오래 머문 이슈 [#{s['number']}]({s['url']}) {clip(s['title'])} — {s['idle_days']}일 움직임 없음(마지막 {KIND_LABEL[s['last_activity_kind']]} {kst(parse_time(s['last_activity_at']))})")
        if p["stale"]["unknown_issues"]:
            lines.append("- 오래 머문 이슈 판정 불능(코멘트를 다 읽지 못함): " + ", ".join(f"#{n}" for n in p["stale"]["unknown_issues"]))
        devs = p["dev_items"]
        if led["status"] == "unknown":
            lines.append("- 맡은 개발 건: 확인 불능")
        elif devs:
            for d in devs:
                lines.append(f"- 개발 건 {d['id']}({clip(d['title'], 30) or '제목 없음'}) — 담당 @{d['owner'] or p['login']}, {d['status'] or '상태 없음'}, 마지막 PR {d['last_pr'] or '없음'}")

    lines += ["", "## 담당자 없는 열린 이슈"]
    if res["unassigned_issues"] is None:
        lines.append("확인 불능")
    elif not res["unassigned_issues"]:
        lines.append("없음" + ("(읽은 범위 안에서만 — 열린 이슈가 많아 일부만 읽음)" if tr["issues"] else ""))
    else:
        if tr["issues"]:
            lines.append("(부분) 열린 이슈가 많아 최근에 갱신된 것만 읽었다")
        lines += [f"- [#{i['number']}]({i['url']}) {clip(i['title'], 50)}" for i in res["unassigned_issues"]]
    if led["unowned"]:
        lines += ["", "## 담당이 정해지지 않은 개발 건(원장)"]
        lines += [f"- {d['id']}({clip(d['title'], 30)}) — {d['status']}, 마지막 PR {d['last_pr'] or '없음'}" for d in led["unowned"]]
    for w in res["warnings"]:
        lines.append(f"주의: {w}")
    if res["aliases_applied"]:
        lines.append("별칭 적용: " + ", ".join(f"{a['name']} → {a['login']}({', '.join(a['items'])})" for a in res["aliases_applied"]))
    return "\n".join(lines)
