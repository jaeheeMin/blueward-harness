"""SRS(`docs/ssot/`) 를 바꾼 PR 이 승인받았는지 판정한다(#49).

Project Repository 는 개인 무료 계정의 비공개 저장소라 브랜치 보호·ruleset·
CODEOWNERS 를 쓸 수 없다. 무료 요금제에서는 쓰기 권한자가 화면에서 그냥
merge 하는 것을 막을 방법이 없으므로, 이 모듈은 "막는다" 대신 "승인 없이
넘어가면 반드시 드러나고 기록에 남는다" 를 만든다. 세 곳이 이 모듈의 같은
판정 함수를 부른다.

- `.github/workflows/ssot-approval.yml` 의 `check` job — PR 을 검사해 실패시킨다.
- 같은 워크플로의 `after-merge` job — main 에 승인 없이 들어온 것을 잡아 이슈를 연다.
- `plugins/harness/hooks/pre-bash-git-guard.sh` — `gh pr merge` 를 거부한다.

같은 방식으로 "사람이 직접 merge 해야 하는 경로(`.github/human-merge-paths`)를
바꾼 PR 인가" 도 판정한다(#104). Claude 세션은 소유자 계정으로 동작해 GitHub 가
사람과 구분하지 못하므로, 훅(`check-human-merge` 로 `gh pr merge` 거부)과
`.github/workflows/human-merge-alert.yml`(소유자에게 알림) 두 곳이 부른다.
목록은 PR 이 아니라 **base 브랜치**에서 읽는다 — PR 이 자기 보호를 스스로
지울 수 없게 하기 위해서다.

**승인은 PR 의 현재 head 커밋에 대한 것일 때만 인정한다(#119).** 승인한 뒤 새 커밋이
올라오면 그 승인은 낡은 것이라 미승인이다. 새 커밋에 다시 Approve 하면 통과한다.

**판정은 순수 함수(`touches_ssot`, `parse_approvers`, `approvers_for`, `is_approved`,
`load_human_merge_paths`, `human_merge_hits`)에 있고,
GitHub 에서 무엇을 읽어와야 하는지는 `GhClient` 와 `decide_*` 함수에 있다.**
셋을 가르는 이유는 순수 함수는 `gh` 없이도 테스트할 수 있어야 하고, `gh` 를
부르는 부분은 네트워크 없이 단위 테스트할 수 없기 때문이다.

**이 파일이 `checker` 패키지 안에 사는 이유.** 마켓플레이스로 설치된 플러그인
캐시에는 `plugins/harness/` 만 들어가고 이 저장소의 `scripts/` 는 따라오지
않는다(#12 와 같은 사정). 훅은 `uvx --from <이 저장소>` 로 엔진을 받아 쓰므로,
훅이 부를 판정 로직은 `uvx` 가 설치하는 `checker` 패키지 안에 있어야
`python -m checker.ssot_approval` 로 닿는다. `scripts/ssot_approval.py` 는
GitHub Actions 가 `check_changed.py` 를 부르는 것과 같은 자리에서 이 모듈을
그대로 감싸는 얇은 진입점일 뿐이다.

**"판정 불가" 를 "승인" 으로 뭉개지 않는다(CLAUDE.md 원칙 7).** `gh api` 호출이
실패하면(네트워크, 권한, 예상 못한 응답) 종료코드 2(EXIT_UNKNOWN)로 답한다.
0(통과)도 1(승인 필요)도 아니다 — 이 판정은 merge 를 막는 근거로 쓰이므로,
모른다는 것을 통과로 답하면 그 순간 보호가 사라진다.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from typing import NamedTuple

SSOT_PREFIX = "docs/ssot/"

EXIT_OK = 0
EXIT_NOT_APPROVED = 1
EXIT_HUMAN_REQUIRED = 1  # check-human-merge 의 "사람이 merge 해야 한다". 값은 위와 같다.
EXIT_UNKNOWN = 2

# 상태를 바꾸는 리뷰만 "최신 상태" 갱신에 참여한다. COMMENTED 는 리뷰가 남긴
# 코멘트일 뿐 승인도 반려도 아니므로, 그 리뷰어의 이전 상태(APPROVED 였을 수도
# 있다)를 그대로 둔다.
_STATE_CHANGING = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}

NO_APPROVER_FOR_AUTHOR = (
    "이 작성자의 PR 을 승인할 사람이 .github/ssot-approvers 에 없다(작성자 본인은 제외). "
    "다음: 사람이 할 일 - 이 작성자 줄이나 `*:` 줄에 작성자가 아닌 승인자의 GitHub 아이디를 "
    "추가하십시오(이 파일은 기준 브랜치에서 읽으므로 따로 먼저 반영해야 합니다)."
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def touches_ssot(files: list[str]) -> bool:
    """바뀐 파일 중 `docs/ssot/` 아래가 하나라도 있는가."""
    return any(_normalize(f).startswith(SSOT_PREFIX) for f in files)


class ParsedApprovers(NamedTuple):
    """`.github/ssot-approvers` 를 읽은 결과.

    `by_author` 는 PR 작성자(소문자)별 전용 승인자, `default` 는 `*:` 줄과 옛 형식
    줄(콜론 없는 줄)의 합이다. `has_entries` 는 주석·빈 줄 말고 내용이 있었는가다.
    """

    by_author: dict[str, set[str]]
    default: set[str]
    has_entries: bool

    def for_author(self, author: str | None) -> set[str]:
        return approvers_for(self, author)

    def everyone(self) -> set[str]:
        result = set(self.default)
        for logins in self.by_author.values():
            result |= logins
        return result


def _logins(text: str) -> set[str]:
    return {t.lstrip("@").lower() for t in re.split(r"[\s,]+", text) if t.lstrip("@")}


def parse_approvers(text: str | None) -> ParsedApprovers:
    """`.github/ssot-approvers` 를 읽는다. 순수 함수다.

    형식은 한 줄에 하나다. `#` 뒤는 주석이고 대소문자는 구분하지 않는다(GitHub
    아이디 자체가 구분하지 않는다). 아이디 앞의 `@` 는 있어도 없어도 된다.

    - `<PR 작성자>: <승인자> <승인자> ...` — 그 작성자의 PR 을 승인할 사람들(공백이나
      쉼표로 나눈다). 작성자 자리의 `*` 는 전용 줄이 없는 모든 작성자에게 해당한다.
    - 콜론 없는 줄(옛 형식, 한 줄 한 아이디) — `*:` 줄에 적은 것과 같다.
    - 같은 작성자 줄이 여러 번이면 합친다.
    """
    by_author: dict[str, set[str]] = {}
    default: set[str] = set()
    has_entries = False
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            login = line.lstrip("@").strip().lower()
            if login:
                default.add(login)
                has_entries = True
            continue
        left, right = line.split(":", 1)
        key = left.strip().lstrip("@").strip().lower()
        has_entries = True
        if not key:
            continue
        if key == "*":
            default |= _logins(right)
        else:
            by_author.setdefault(key, set()).update(_logins(right))
    return ParsedApprovers(by_author, default, has_entries)


def approvers_for(parsed: ParsedApprovers, author: str | None) -> set[str]:
    """이 PR 작성자의 PR 을 승인할 수 있는 사람들(작성자 본인은 늘 뺀다).

    그 작성자 전용 줄이 있으면 그 줄의 사람만, 없으면 `*:` 줄과 옛 형식 줄의 합이다.
    """
    author_l = (author or "").strip().lower()
    chosen = parsed.by_author[author_l] if author_l in parsed.by_author else parsed.default
    return {a for a in chosen if a != author_l}


def load_approvers(text: str | None) -> set[str]:
    """`.github/ssot-approvers` 에 적힌 모든 승인자의 합집합(작성자 구분 없음).

    작성자별 판정은 `parse_approvers` + `approvers_for` 를 쓴다. 옛 형식 파일(한 줄
    한 아이디)이면 예전과 같은 결과다. 내용이 없으면 빈 집합이다.
    """
    return parse_approvers(text).everyone()


def load_human_merge_paths(text: str | None) -> list[str]:
    """`.github/human-merge-paths` 를 읽는다.

    한 줄에 경로 접두어 하나, `#` 뒤는 주석. 비어 있으면 빈 목록이고, 그것은
    "제한 없음" 이다.
    """
    if not text:
        return []
    prefixes: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        prefix = _normalize(line)
        if prefix:
            prefixes.append(prefix)
    return prefixes


def human_merge_hits(files: list[str], prefixes: list[str]) -> list[str]:
    """바뀐 파일 중 보호 접두어 아래에 있는 것을 순서대로 돌려준다."""
    return [f for f in files if any(_normalize(f).startswith(p) for p in prefixes)]


def _short(sha: str | None) -> str:
    return (sha or "")[:7] or "알 수 없는 커밋"


def evaluate_approval(
    author: str, reviews: list[dict], approvers: set[str], head_sha: str | None = None
) -> tuple[bool, str, list[dict]]:
    """승인 여부, 사유, 그리고 "승인은 했지만 옛 커밋 기준" 인 승인자 목록을 돌려준다.

    리뷰는 `submitted_at` 기준으로 정렬해 리뷰어별 최신 상태만 남긴다. 나중에
    한 CHANGES_REQUESTED 는 앞서 한 APPROVED 를 취소한다. `approvers` 가
    비어 있지 않으면 그 목록에 있는 사람의 승인만 인정한다.

    `head_sha` 를 주면(#119) 그 리뷰어의 최신 상태가 APPROVED 이면서 그 리뷰가
    `head_sha` 에 대해 제출된 것일 때만 인정한다. 승인한 뒤 새 커밋이 올라오면
    승인자가 보지 않은 내용이 들어가므로(무료 요금제에는 "새 커밋이 올라오면
    승인 취소" 기능이 없다), 옛 커밋에 대한 승인은 "낡았다(stale)" 고 보고
    미승인으로 친다. 새 커밋에 다시 Approve 하면 그 리뷰가 최신이라 인정된다.
    """
    author_l = (author or "").strip().lower()

    def _key(review: dict) -> str:
        return review.get("submitted_at") or ""

    latest: dict[str, tuple[str, str | None]] = {}
    for review in sorted(reviews, key=_key):
        user = (review.get("user") or {}).get("login")
        if not user:
            continue
        state = (review.get("state") or "").upper()
        if state not in _STATE_CHANGING:
            # COMMENTED 등은 상태를 바꾸지 않는다.
            continue
        latest[user.strip().lower()] = (state, review.get("commit_id"))

    approving: list[str] = []
    stale: list[dict] = []
    for login, (state, commit_id) in latest.items():
        if state != "APPROVED" or login == author_l or (approvers and login not in approvers):
            continue
        if head_sha is None or commit_id == head_sha:
            approving.append(login)
        else:
            stale.append({"login": login, "commit": commit_id})

    if approving:
        who = ", ".join(sorted(approving))
        return True, f"{who} 가 승인했다", []

    if stale:
        stale.sort(key=lambda e: e["login"])
        who = ", ".join(e["login"] for e in stale)
        commits = ", ".join(sorted({_short(e["commit"]) for e in stale}))
        reason = (
            f"승인자 {who} 의 승인은 이전 커밋({commits})에 대한 것이고, 그 뒤 새 커밋이 "
            "올라와 다시 승인이 필요합니다. 다음: 사람이 할 일 - 승인자에게 최신 커밋을 보고 "
            "이 PR 을 다시 Approve 해 달라고 요청하십시오."
        )
        return False, reason, stale

    if approvers:
        return False, f"승인자({', '.join(sorted(approvers))}) 중 아무도 승인하지 않았다", []
    return False, "작성자가 아닌 사람의 승인이 없다", []


def is_approved(
    author: str, reviews: list[dict], approvers: set[str], head_sha: str | None = None
) -> tuple[bool, str]:
    """`evaluate_approval` 의 (승인 여부, 사유) 만 돌려준다."""
    approved, reason, _ = evaluate_approval(author, reviews, approvers, head_sha)
    return approved, reason


# --- GitHub 에서 읽어오는 부분 ----------------------------------------------


class GhError(RuntimeError):
    """`gh` 호출이 실패했다. 판정 불가(EXIT_UNKNOWN)로 이어진다.

    `status` 는 `gh` 가 stderr 마지막 줄에 `(HTTP 404)` 로 알려 준 HTTP 상태 코드다.
    시간 초과·실행 실패처럼 HTTP 응답을 못 받은 경우와 상태 표기가 없는 경우는 None 이다.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# `gh api` 는 HTTP 오류를 `gh: <서버 메시지> (HTTP 404)` 한 줄로 stderr 에 낸다.
_HTTP_STATUS_TAIL = re.compile(r"\(HTTP (\d{3})\)\s*$")


def _http_status(stderr: str) -> int | None:
    """stderr 의 마지막 비어 있지 않은 줄 끝의 `(HTTP nnn)` 만 상태 코드로 읽는다."""
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    m = _HTTP_STATUS_TAIL.search(lines[-1])
    return int(m.group(1)) if m else None


class GhClient:
    """`gh api` 호출을 감싼다.

    테스트는 이 클래스를 fake 로 갈아 끼우거나, 아래 `fetch_*` 함수들을 직접
    monkeypatch 한다. 여기서 쓰는 `gh` 는 `GH_TOKEN` 환경변수(또는 이미 로그인된
    세션)로 인증한다 — 이 모듈은 그 값을 직접 다루지 않고 `gh` 에게 맡긴다.
    """

    def run(self, args: list[str]) -> str:
        try:
            done = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GhError(f"gh {' '.join(args)} 실행에 실패했다: {exc}") from exc
        if done.returncode != 0:
            raise GhError(
                f"gh {' '.join(args)} 가 종료코드 {done.returncode} 로 실패했다: "
                f"{done.stderr.strip()}",
                status=_http_status(done.stderr),
            )
        return done.stdout

    def get_json(self, path: str):
        raw = self.run(["api", path]) or "null"
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GhError(f"gh api {path} 의 출력을 해석하지 못했다: {exc}") from exc

    def get_json_or_none_404(self, path: str):
        try:
            return self.get_json(path)
        except GhError as exc:
            # 오류 메시지 문자열이 아니라 HTTP 상태로만 "파일 없음" 을 판정한다. 메시지에는
            # 요청 경로(40자리 SHA)가 들어가 "404" 가 우연히 섞일 수 있다.
            if exc.status == 404:
                return None
            raise

    def get_all(self, path: str, per_page: int = 100) -> list:
        """페이지를 직접 넘기며 배열 응답을 모은다."""
        sep = "&" if "?" in path else "?"
        items: list = []
        page = 1
        while True:
            batch = self.get_json(f"{path}{sep}per_page={per_page}&page={page}")
            if not batch:
                break
            items.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return items


def fetch_pr_info(client: GhClient, repo: str, pr: int) -> dict:
    return client.get_json(f"repos/{repo}/pulls/{pr}")


def fetch_pr_files(client: GhClient, repo: str, pr: int) -> list[str]:
    entries = client.get_all(f"repos/{repo}/pulls/{pr}/files")
    return [e["filename"] for e in entries if "filename" in e]


def fetch_pr_reviews(client: GhClient, repo: str, pr: int) -> list[dict]:
    return client.get_all(f"repos/{repo}/pulls/{pr}/reviews")


def fetch_approver_rules(client: GhClient, repo: str, ref: str) -> ParsedApprovers:
    data = client.get_json_or_none_404(f"repos/{repo}/contents/.github/ssot-approvers?ref={ref}")
    if not data:
        return parse_approvers(None)
    content = data.get("content", "") or ""
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        text = ""
    return parse_approvers(text)


def fetch_approvers(client: GhClient, repo: str, ref: str) -> set[str]:
    """모든 승인자의 합집합. 작성자별 판정은 `fetch_approver_rules` 를 쓴다."""
    return fetch_approver_rules(client, repo, ref).everyone()


def judge_by_rules(
    author: str, reviews: list[dict], rules: ParsedApprovers, head_sha: str | None
) -> tuple[bool, str, list[dict]]:
    """작성자에게 정해진 승인자로 `evaluate_approval` 을 부른다.

    파일에 내용이 없으면 "누구든" 이다. 내용은 있는데 이 작성자의 PR 을 승인할 사람이
    (작성자 본인을 빼면) 없으면, "누구든" 으로 풀지 않고 미승인으로 답한다.
    """
    if not rules.has_entries:
        return evaluate_approval(author, reviews, set(), head_sha)
    eligible = approvers_for(rules, author)
    if not eligible:
        return False, NO_APPROVER_FOR_AUTHOR, []
    return evaluate_approval(author, reviews, eligible, head_sha)


def fetch_human_merge_paths(client: GhClient, repo: str, ref: str) -> list[str]:
    data = client.get_json_or_none_404(f"repos/{repo}/contents/.github/human-merge-paths?ref={ref}")
    if not data:
        return []
    content = data.get("content", "") or ""
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        text = ""
    return load_human_merge_paths(text)


def fetch_commit_associated_prs(client: GhClient, repo: str, sha: str) -> list[dict]:
    return client.get_json(f"repos/{repo}/commits/{sha}/pulls") or []


def fetch_commit_files(client: GhClient, repo: str, sha: str) -> list[str]:
    commit = client.get_json(f"repos/{repo}/commits/{sha}")
    return [f["filename"] for f in (commit.get("files") or []) if "filename" in f]


def decide_pr(client: GhClient, repo: str, pr: int) -> dict:
    """PR 하나의 승인 여부를 판정한다."""
    info = fetch_pr_info(client, repo, pr)
    files = fetch_pr_files(client, repo, pr)

    if not touches_ssot(files):
        return {"touches_ssot": False, "approved": True, "reason": "docs/ssot 를 바꾸지 않았다"}

    author = (info.get("user") or {}).get("login", "")
    base_ref = (info.get("base") or {}).get("ref") or "main"
    reviews = fetch_pr_reviews(client, repo, pr)
    rules = fetch_approver_rules(client, repo, base_ref)
    # 승인은 PR 의 현재 head 커밋에 대한 것이어야 한다(#119). head 를 모르면 옛
    # 승인을 걸러낼 수 없으므로 통과시키지 않고 판정 불가로 답한다(원칙 7).
    # merge 된 PR 의 head.sha 는 merge 시점의 마지막 커밋이라 after-merge 도 같다.
    head_sha = (info.get("head") or {}).get("sha")
    if not head_sha:
        raise GhError(f"PR #{pr} 의 head 커밋을 응답에서 찾지 못했다")
    approved, reason, stale = judge_by_rules(author, reviews, rules, head_sha)
    result = {"touches_ssot": True, "approved": approved, "reason": reason}
    if stale:
        result["stale_approvers"] = [e["login"] for e in stale]
    return result


def decide_human_merge(client: GhClient, repo: str, pr: int) -> dict:
    """PR 이 사람이 직접 merge 해야 하는 경로를 바꿨는지 판정한다(#104)."""
    info = fetch_pr_info(client, repo, pr)
    base_ref = (info.get("base") or {}).get("ref") or "main"
    prefixes = fetch_human_merge_paths(client, repo, base_ref)
    if not prefixes:
        return {"requires_human": False, "paths": [], "pr": pr, "repo": repo}
    hits = human_merge_hits(fetch_pr_files(client, repo, pr), prefixes)
    return {"requires_human": bool(hits), "paths": hits, "pr": pr, "repo": repo}


def decide_commit(client: GhClient, repo: str, sha: str) -> dict:
    """merge 뒤(push) 이 커밋이 승인 없이 SRS 를 바꿨는지 판정한다."""
    prs = fetch_commit_associated_prs(client, repo, sha)
    merged_prs = [p for p in prs if p.get("merged_at")]

    if not merged_prs:
        # 이 커밋과 연관된 merge PR 이 없다 — PR 없이 main 에 직접 push 됐을 수
        # 있다. 그 경우 PR 승인 절차 자체를 거치지 않았으므로, SRS 를 바꿨다면
        # 곧바로 승인 없음으로 본다.
        files = fetch_commit_files(client, repo, sha)
        if touches_ssot(files):
            return {"approved": False, "reason": "PR 없이 main 에 직접 들어왔다", "prs": []}
        return {"approved": True, "reason": "docs/ssot 를 바꾸지 않았다", "prs": []}

    problems = []
    checked = []
    for pr in merged_prs:
        number = pr.get("number")
        result = decide_pr(client, repo, number)
        checked.append(number)
        if result["touches_ssot"] and not result["approved"]:
            problems.append({"pr": number, "url": pr.get("html_url", ""), "reason": result["reason"]})

    if problems:
        return {"approved": False, "reason": "승인 없이 merge 된 PR 이 있다", "prs": problems}
    return {"approved": True, "reason": "모두 승인됐거나 docs/ssot 를 바꾸지 않았다", "prs": checked}


# --- CLI ---------------------------------------------------------------------


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def cmd_check_pr(args: argparse.Namespace) -> int:
    client = GhClient()
    try:
        result = decide_pr(client, args.repo, args.pr)
    except GhError as exc:
        _print({"touches_ssot": None, "approved": None, "reason": f"판정 불가: {exc}"})
        return EXIT_UNKNOWN

    _print(result)
    if not result["touches_ssot"] or result["approved"]:
        return EXIT_OK
    return EXIT_NOT_APPROVED


def cmd_check_human_merge(args: argparse.Namespace) -> int:
    client = GhClient()
    try:
        result = decide_human_merge(client, args.repo, args.pr)
    except GhError as exc:
        # 모르는 것을 "사람 확인 불필요" 로 답하지 않는다(원칙 7).
        _print({"requires_human": None, "paths": [], "reason": f"판정 불가: {exc}"})
        return EXIT_UNKNOWN

    _print(result)
    return EXIT_HUMAN_REQUIRED if result["requires_human"] else EXIT_OK


def cmd_check_commit(args: argparse.Namespace) -> int:
    client = GhClient()
    try:
        result = decide_commit(client, args.repo, args.sha)
    except GhError as exc:
        _print({"approved": None, "reason": f"판정 불가: {exc}", "prs": []})
        return EXIT_UNKNOWN

    _print(result)
    return EXIT_OK if result["approved"] else EXIT_NOT_APPROVED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssot_approval",
        description="docs/ssot 를 바꾼 PR 의 승인 여부를 판정한다.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    check_pr = sub.add_parser("check-pr", help="PR 하나의 승인 여부를 판정한다")
    check_pr.add_argument("--repo", required=True, help="owner/repo")
    check_pr.add_argument("--pr", required=True, type=int, help="PR 번호")
    check_pr.set_defaults(func=cmd_check_pr)

    check_commit = sub.add_parser(
        "check-commit", help="merge 된(또는 직접 push 된) 커밋의 승인 여부를 판정한다"
    )
    check_commit.add_argument("--repo", required=True, help="owner/repo")
    check_commit.add_argument("--sha", required=True, help="커밋 SHA")
    check_commit.set_defaults(func=cmd_check_commit)

    check_human = sub.add_parser(
        "check-human-merge", help="PR 이 사람이 직접 merge 해야 하는 경로를 바꿨는지 판정한다"
    )
    check_human.add_argument("--repo", required=True, help="owner/repo")
    check_human.add_argument("--pr", required=True, type=int, help="PR 번호")
    check_human.set_defaults(func=cmd_check_human_merge)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
