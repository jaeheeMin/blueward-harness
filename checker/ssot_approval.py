"""PRD(`docs/ssot/`) 를 바꾼 PR 이 승인받았는지 판정한다(#49).

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

**판정은 순수 함수(`touches_ssot`, `load_approvers`, `is_approved`,
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
import subprocess
import sys

SSOT_PREFIX = "docs/ssot/"

EXIT_OK = 0
EXIT_NOT_APPROVED = 1
EXIT_HUMAN_REQUIRED = 1  # check-human-merge 의 "사람이 merge 해야 한다". 값은 위와 같다.
EXIT_UNKNOWN = 2

# 상태를 바꾸는 리뷰만 "최신 상태" 갱신에 참여한다. COMMENTED 는 리뷰가 남긴
# 코멘트일 뿐 승인도 반려도 아니므로, 그 리뷰어의 이전 상태(APPROVED 였을 수도
# 있다)를 그대로 둔다.
_STATE_CHANGING = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def touches_ssot(files: list[str]) -> bool:
    """바뀐 파일 중 `docs/ssot/` 아래가 하나라도 있는가."""
    return any(_normalize(f).startswith(SSOT_PREFIX) for f in files)


def load_approvers(text: str | None) -> set[str]:
    """`.github/ssot-approvers` 를 읽는다.

    한 줄에 GitHub 아이디 하나. `#` 뒤는 주석이고, 앞의 `@` 는 있어도 없어도
    된다. 대소문자는 구분하지 않는다(GitHub 아이디 자체가 대소문자를 구분하지
    않는다). 빈 파일이거나 내용이 없으면 빈 집합을 돌려주고, 그것은 "누구든
    승인할 수 있다" 는 뜻으로 `is_approved` 가 해석한다.
    """
    if not text:
        return set()
    approvers: set[str] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        login = line.lstrip("@").strip().lower()
        if login:
            approvers.add(login)
    return approvers


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


def is_approved(author: str, reviews: list[dict], approvers: set[str]) -> tuple[bool, str]:
    """작성자가 아닌 사람의 최신 리뷰 상태가 APPROVED 인지 본다.

    리뷰는 `submitted_at` 기준으로 정렬해 리뷰어별 최신 상태만 남긴다. 나중에
    한 CHANGES_REQUESTED 는 앞서 한 APPROVED 를 취소한다. `approvers` 가
    비어 있지 않으면 그 목록에 있는 사람의 승인만 인정한다.
    """
    author_l = (author or "").strip().lower()

    def _key(review: dict) -> str:
        return review.get("submitted_at") or ""

    latest: dict[str, str] = {}
    for review in sorted(reviews, key=_key):
        user = (review.get("user") or {}).get("login")
        if not user:
            continue
        state = (review.get("state") or "").upper()
        if state not in _STATE_CHANGING:
            # COMMENTED 등은 상태를 바꾸지 않는다.
            continue
        latest[user.strip().lower()] = state

    approving = [
        login
        for login, state in latest.items()
        if state == "APPROVED" and login != author_l and (not approvers or login in approvers)
    ]

    if approving:
        who = ", ".join(sorted(approving))
        return True, f"{who} 가 승인했다"

    if approvers:
        return False, f"승인자({', '.join(sorted(approvers))}) 중 아무도 승인하지 않았다"
    return False, "작성자가 아닌 사람의 승인이 없다"


# --- GitHub 에서 읽어오는 부분 ----------------------------------------------


class GhError(RuntimeError):
    """`gh` 호출이 실패했다. 판정 불가(EXIT_UNKNOWN)로 이어진다."""


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
                f"{done.stderr.strip()}"
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
            if "404" in str(exc) or "Not Found" in str(exc):
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


def fetch_approvers(client: GhClient, repo: str, ref: str) -> set[str]:
    data = client.get_json_or_none_404(f"repos/{repo}/contents/.github/ssot-approvers?ref={ref}")
    if not data:
        return set()
    content = data.get("content", "") or ""
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        text = ""
    return load_approvers(text)


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
    approvers = fetch_approvers(client, repo, base_ref)
    approved, reason = is_approved(author, reviews, approvers)
    return {"touches_ssot": True, "approved": approved, "reason": reason}


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
    """merge 뒤(push) 이 커밋이 승인 없이 PRD 를 바꿨는지 판정한다."""
    prs = fetch_commit_associated_prs(client, repo, sha)
    merged_prs = [p for p in prs if p.get("merged_at")]

    if not merged_prs:
        # 이 커밋과 연관된 merge PR 이 없다 — PR 없이 main 에 직접 push 됐을 수
        # 있다. 그 경우 PR 승인 절차 자체를 거치지 않았으므로, PRD 를 바꿨다면
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
