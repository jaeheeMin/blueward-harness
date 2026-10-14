"""열린 PR 들의 판 번호 정보를 GitHub API 로 읽어 JSON 으로 저장한다(#315). doc-guard 워크플로가 부른다.

사용법: fetch_open_prs.py <이 PR 번호> <저장할 JSON 경로>
환경변수: GITHUB_TOKEN(필수), GITHUB_REPOSITORY(`owner/repo`, Actions 가 채운다), GITHUB_API_URL(선택)

검사 엔진(`checker/version_overlap.py`)은 네트워크를 쓰지 않는다. 여기서만 네트워크를 쓰고, 결과
모양은 그 모듈 문서에 있다. 이 스크립트는 **항상 0 으로 끝난다** — 못 읽은 사실은 종료코드가 아니라
JSON 의 `{"status": "cannot_check", "message": ...}` 로 남기고, 그것을 검사 불능으로 알리는 일은
`scripts/check_changed.py` 가 한다. 못 읽었는데 파일마저 없으면 그쪽이 같은 검사 불능으로 처리한다.

- 이 PR 이 판 번호를 건드리지 않으면(추가한 판 있는 산출 파일도, 바꾼 SRS `버전:` 도 없음) 다른 PR 을
  읽지 않고 `{"status": "not_needed"}` 만 쓴다 — PR 마다 API 를 수십 번 부르지 않으려는 것이다.
- 스위치 `판_겹침` 이 꺼져 있어도 읽지 않는다(스위치 파일이 깨졌으면 읽는다. 그 오류는 check_changed 가 알린다).
- 다른 PR 은 파일 목록으로 추가된 산출 파일을, SRS 를 바꾼 PR 만 SRS 내용(head 와 base)에서 `버전:` 을 읽는다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from checker.cross_switches import SwitchError, load_switches
from checker.pairing import SRS_PATH
from checker.version_overlap import NOT_NEEDED, added_artifacts, bumped, srs_version_of

PER_PAGE = 100
MAX_PAGES = 30  # 파일 목록 API 의 상한(3000)과 같은 크기. 넘으면 일부만 본 것이므로 검사 불능.


class FetchError(Exception):
    """GitHub 에서 읽지 못했다. 통과로도 위반으로도 답하지 않는다."""


def paged(get_json: Callable[[str], object], path: str) -> list:
    """`?page=` 로 끝까지 읽는다. 상한까지 읽고도 끝이 아니면 FetchError."""
    sep = "&" if "?" in path else "?"
    out: list = []
    for page in range(1, MAX_PAGES + 1):
        chunk = get_json(f"{path}{sep}per_page={PER_PAGE}&page={page}")
        if not isinstance(chunk, list):
            raise FetchError(f"{path} 의 응답이 목록이 아닙니다")
        out += chunk
        if len(chunk) < PER_PAGE:
            return out
    raise FetchError(f"{path} 가 {MAX_PAGES * PER_PAGE}건을 넘어 끝까지 읽지 못했습니다")


def _record(
    get_json: Callable[[str], object],
    get_text: Callable[[str, str], str | None],
    repo: str,
    pr: dict,
) -> dict:
    """PR 하나의 기록. `get_text(경로, ref)` 는 파일이 없으면 None."""
    number = pr["number"]
    files = paged(get_json, f"/repos/{repo}/pulls/{number}/files")
    srs_changed = any(f.get("filename") == SRS_PATH and f.get("status") != "removed" for f in files)
    rec = {
        "number": number,
        "title": pr.get("title") or "",
        "added": added_artifacts(files),
        "srs_changed": srs_changed,
        "srs_version": None,
        "srs_base_version": None,
        "srs_error": None,
    }
    if srs_changed:
        try:
            head = get_text(SRS_PATH, pr["head"]["sha"])
            base = get_text(SRS_PATH, pr["base"]["sha"])
        except FetchError as exc:
            rec["srs_error"] = str(exc)
        else:
            rec["srs_version"] = srs_version_of(head) if head is not None else None
            rec["srs_base_version"] = srs_version_of(base) if base is not None else None
    return rec


def collect(
    get_json: Callable[[str], object],
    get_text: Callable[[str, str], str | None],
    repo: str,
    self_number: int,
) -> dict:
    """저장할 JSON(dict). 읽지 못하면 cannot_check 로 답한다(예외를 밖으로 내지 않는다)."""
    try:
        me = get_json(f"/repos/{repo}/pulls/{self_number}")
        if not isinstance(me, dict) or "number" not in me:
            raise FetchError(f"PR #{self_number} 를 읽지 못했습니다")
        mine = _record(get_json, get_text, repo, me)
        if not mine["added"] and bumped(mine) is None and not mine["srs_error"]:
            return {"status": NOT_NEEDED}
        records = [mine]
        for pr in paged(get_json, f"/repos/{repo}/pulls?state=open"):
            if pr.get("number") != self_number:
                records.append(_record(get_json, get_text, repo, pr))
        return {"status": "ok", "prs": records}
    except FetchError as exc:
        return {"status": "cannot_check", "message": f"열린 PR 목록을 읽지 못했습니다: {exc}"}
    except (KeyError, TypeError, AttributeError) as exc:
        return {"status": "cannot_check", "message": f"열린 PR 정보의 모양이 예상과 다릅니다: {exc!r}"}


def _http(token: str, api_url: str) -> tuple[Callable[[str], object], Callable[[str, str], str | None]]:
    def request(url: str, accept: str) -> bytes | None:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "doc-guard-fetch-open-prs",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            hint = (
                " (토큰에 pull-requests 읽기 권한이 없을 수 있습니다 — 부르는 쪽 workflow 의 permissions 를 확인하십시오)"
                if exc.code in (401, 403) else ""
            )
            raise FetchError(f"GitHub API {exc.code} {exc.reason}{hint}: {url}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise FetchError(f"GitHub API 에 닿지 못했습니다: {exc}") from exc

    def get_json(path: str) -> object:
        raw = request(api_url + path, "application/vnd.github+json")
        if raw is None:
            raise FetchError(f"GitHub API 404: {path}")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError(f"GitHub API 응답을 해석하지 못했습니다: {path}") from exc

    def get_text(path: str, ref: str) -> str | None:
        quoted = urllib.parse.quote(path)
        raw = request(f"{api_url}/repos/{os.environ['GITHUB_REPOSITORY']}/contents/{quoted}?ref={ref}",
                      "application/vnd.github.raw+json")
        return None if raw is None else raw.decode("utf-8-sig", errors="replace")

    return get_json, get_text


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or not args[0].isdigit():
        print("사용법: fetch_open_prs.py <이 PR 번호> <저장할 JSON 경로>", file=sys.stderr)
        return 2
    number, out_path = int(args[0]), Path(args[1])

    try:
        skip = load_switches(Path.cwd()).get("판_겹침") is False
    except SwitchError:
        skip = False  # 스위치 파일 오류는 check_changed 가 알린다. 여기서는 읽어 둔다.
    if skip:
        result: dict = {"status": NOT_NEEDED}
    else:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            result = {"status": "cannot_check", "message": "GITHUB_TOKEN 이나 GITHUB_REPOSITORY 가 없어 열린 PR 목록을 읽지 못했습니다"}
        else:
            get_json, get_text = _http(token, os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/"))
            result = collect(get_json, get_text, repo, number)
    out_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"열린 PR 정보: {result['status']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
