"""열린 PR 끼리 plugin.json version 이 겹치면 실패한다(#324, 경고에서 실패로 #470). 이 저장소 자신의 PR 검사(`checker.yml`)가 부른다.

사용법: check_plugin_version_overlap.py <이 PR 번호> <base sha> <base ref>
환경변수: GITHUB_TOKEN, GITHUB_REPOSITORY(필수), GITHUB_API_URL(선택), GITHUB_STEP_SUMMARY(선택)

열린 PR 을 읽는 도구(`urllib` 클라이언트, 쪽수 읽기, 오류 종류)는 `scripts/fetch_open_prs.py`(#315)와 같은 것을 쓴다.
다만 JSON 파일로 넘기지 않고 이 스크립트가 읽어서 바로 판정한다 — #315 의 기록은 Project Repository 의 문서 판
번호(산출 파일, SRS)용이고 그 저장소들에는 `plugin.json` 이 없어, 한 JSON 에 묶으면 모든 고객사 PR 이 불필요한
API 호출을 하게 된다. 그래서 판정(`checker/plugin_version_overlap.py`)과 읽기 스크립트는 따로 두고 읽기 도구만 공유한다.

- main 의 version 은 체크아웃된 git(`git show <base sha>:plugin.json`)에서 읽고 base ref 는 이벤트 페이로드로 받는다.
  이 PR 이 version 을 올리지 않았으면(main 과 같으면) 네트워크를 전혀 쓰지 않는다 — 일시 장애로 빨개지지 않게.
- 다른 열린 PR 한 건의 head plugin.json 을 못 읽으면 그 PR 만 건너뛴다. "N건 중 M건 확인 못 함" 을 경고와 요약에
  남기고 막지 않는다(겹침과 무관한 이유로 병합이 막히지 않게. 읽은 PR 에서 겹침이 있으면 위반이다). "겹침 없음" 이라고 말하지 않는다.
- 겹침은 위반이다. 종료코드 1, GitHub 주석(`::error::`)과 실행 요약(step summary)에 올릴 다음 version 이 보인다.
  경고만 하면 체크가 초록이라 #462·#464 가 같은 0.10.115 로 병합됐다. 검사가 도는 순간 같은 version 의 다른 열린 PR 이
  있으면 지금 PR 이 실패한다(상대 PR 의 체크는 다시 돌지 않는다).
- 이 PR 자신의 version 이나 열린 PR 목록을 읽지 못하면 검사 불능이다. 종료코드 2(통과로 뭉개지 않는다).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_open_prs import BUDGET_SECONDS, FetchError, _http, paged  # noqa: E402

from checker.pairing import CANNOT_CHECK, VIOLATION  # noqa: E402
from checker.plugin_version import PLUGIN_JSON  # noqa: E402
from checker.plugin_version_overlap import NOT_NEEDED, check_plugin_version_overlap  # noqa: E402


def _version(text: str | None, where: str) -> str:
    if text is None:
        raise FetchError(f"{where} 에서 {PLUGIN_JSON} 를 읽지 못했습니다(404, 포크 PR 일 수 있음)")
    try:
        version = json.loads(text)["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError(f"{where} 의 {PLUGIN_JSON} 에서 version 을 읽지 못했습니다: {exc}") from exc
    if not isinstance(version, str):
        raise FetchError(f"{where} 의 {PLUGIN_JSON} version 이 문자열이 아닙니다: {version!r}")
    return version


def collect(
    get_json: Callable[[str], object],
    get_text: Callable[[str, str], str | None],
    repo: str,
    self_number: int,
    base_ref: str,
    main_version: str,
    my_version: str,
    budget: float = BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """판정에 넘길 dict. 이 PR 이 version 을 안 올렸으면 네트워크를 쓰지 않고 not_needed.

    목록을 못 읽으면 cannot_check. 다른 PR 한 건의 version 만 못 읽으면 그 PR 은 `error` 를 달고 version 이 None 이다.
    """
    if main_version == my_version:
        return {"status": NOT_NEEDED}
    deadline = clock() + budget
    try:
        records = []
        for pr in paged(get_json, f"/repos/{repo}/pulls?state=open"):
            if pr.get("number") == self_number or (pr.get("base") or {}).get("ref") != base_ref:
                continue
            if clock() > deadline:
                raise FetchError(f"{budget:.0f}초 안에 열린 PR 을 다 읽지 못했습니다(시간 예산 초과)")
            rec = {"number": pr["number"], "title": pr.get("title") or "", "version": None}
            sha = pr["head"]["sha"]
            try:
                rec["version"] = _version(get_text(PLUGIN_JSON, sha), f"PR #{pr['number']} head({sha[:7]})")
            except FetchError as exc:
                rec["error"] = str(exc)
            records.append(rec)
        return {"status": "ok", "main_version": main_version, "my_version": my_version, "prs": records}
    except FetchError as exc:
        return {"status": CANNOT_CHECK, "message": f"열린 PR 목록을 읽지 못했습니다: {exc}"}
    except (KeyError, TypeError, AttributeError) as exc:
        return {"status": CANNOT_CHECK, "message": f"열린 PR 정보의 모양이 예상과 다릅니다: {exc!r}"}


def git_version(rev: str) -> str:
    """체크아웃된 git 에서 `rev` 의 plugin.json version. 못 읽으면 FetchError."""
    try:
        done = subprocess.run(["git", "show", f"{rev}:{PLUGIN_JSON}"], capture_output=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FetchError(f"git 을 실행하지 못했습니다: {exc}") from exc
    if done.returncode != 0:
        raise FetchError(f"git show {rev}:{PLUGIN_JSON} 실패: {done.stderr.strip()}")
    return _version(done.stdout, f"base({rev[:7]})")


def escape_annotation(text: str) -> str:
    """`::warning::` 한 줄에 넣을 문자열. `%`, CR, LF 를 이스케이프해 PR 제목의 `%0A` 나 줄바꿈이 주석 명령을 깨지 않게 한다."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def unchecked_message(result: dict) -> str | None:
    unchecked = result.get("unchecked") or []
    if not unchecked:
        return None
    total = result["compared"] + len(unchecked)
    who = ", ".join(f"#{u['number']}" for u in unchecked)
    return (
        f"다른 열린 PR {total}건 중 {len(unchecked)}건({who})의 plugin.json version 을 읽지 못했습니다 — "
        "그 PR 과의 겹침은 확인하지 못했습니다. 이 PR 은 막지 않습니다. 다시 돌리면 확인될 수 있습니다."
    )


def render(result: dict) -> str:
    status = result["status"]
    if status == NOT_NEEDED:
        return "plugin version 겹침: 이 PR 이 plugin.json version 을 올리지 않아 확인하지 않는다."
    if status == CANNOT_CHECK:
        return f"plugin version 겹침 검사 불능: {result['message']}"
    lines = [f"위반: {v['message']}" for v in result.get("violations", [])]
    note = unchecked_message(result)
    if not lines and not note:
        return f"plugin version 겹침 없음(다른 열린 PR {result['compared']}건 확인)."
    if note:
        lines.append(f"확인 못 함: {note}")
        if not lines[:-1]:
            lines.append(f"읽은 {result['compared']}건에서는 겹침이 없습니다.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or not args[0].isdigit():
        print("사용법: check_plugin_version_overlap.py <이 PR 번호> <base sha> <base ref>", file=sys.stderr)
        return 2
    number, base_sha, base_ref = int(args[0]), args[1], args[2]

    try:
        my_version = _version(Path(PLUGIN_JSON).read_text(encoding="utf-8"), "이 PR")
        main_version = git_version(base_sha)
    except (FetchError, OSError) as exc:
        info: dict = {"status": CANNOT_CHECK, "message": f"version 을 읽지 못했습니다: {exc}"}
    else:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if main_version == my_version:
            info = {"status": NOT_NEEDED}  # 네트워크도 토큰도 필요 없다.
        elif not token or not repo:
            info = {"status": CANNOT_CHECK, "message": "GITHUB_TOKEN 이나 GITHUB_REPOSITORY 가 없어 열린 PR 목록을 읽지 못했습니다"}
        else:
            get_json, get_text = _http(token, os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/"))
            info = collect(get_json, get_text, repo, number, base_ref, main_version, my_version)
    result = check_plugin_version_overlap(info, number)

    text = render(result)
    print(text, file=sys.stderr if result["status"] == CANNOT_CHECK else sys.stdout)
    for v in result.get("violations", []):
        print(f"::error title=plugin version 겹침::{escape_annotation(v['message'])}")
    note = unchecked_message(result) if result["status"] != CANNOT_CHECK else None
    if note:
        print(f"::warning title=plugin version 겹침 일부 확인 못 함::{escape_annotation(note)}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and result["status"] != NOT_NEEDED:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### plugin version 겹침\n\n{text}\n")
    if result["status"] == CANNOT_CHECK:
        return 2
    return 1 if result["status"] == VIOLATION else 0


if __name__ == "__main__":
    raise SystemExit(main())
