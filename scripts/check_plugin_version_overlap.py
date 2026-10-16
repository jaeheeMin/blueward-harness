"""열린 PR 끼리 plugin.json version 이 겹치면 경고한다(#324). 이 저장소 자신의 PR 검사(`checker.yml`)가 부른다.

사용법: check_plugin_version_overlap.py <이 PR 번호>
환경변수: GITHUB_TOKEN, GITHUB_REPOSITORY(필수), GITHUB_API_URL(선택), GITHUB_STEP_SUMMARY(선택)

열린 PR 을 읽는 도구(`urllib` 클라이언트, 쪽수 읽기, 오류 종류)는 `scripts/fetch_open_prs.py`(#315)와 같은 것을 쓴다.
다만 JSON 파일로 넘기지 않고 이 스크립트가 읽어서 바로 판정한다 — #315 의 기록은 Project Repository 의 문서 판
번호(산출 파일, SRS)용이고 그 저장소들에는 `plugin.json` 이 없어, 한 JSON 에 묶으면 모든 고객사 PR 이 불필요한
API 호출을 하게 된다. 그래서 판정(`checker/plugin_version_overlap.py`)과 읽기 스크립트는 따로 두고 읽기 도구만 공유한다.

- 이 PR 이 plugin.json version 을 올리지 않았으면(main 과 같으면) 다른 PR 을 읽지 않는다.
- 겹침은 경고다. 종료코드 0, GitHub 주석(`::warning::`)과 실행 요약(step summary)에 보인다.
- 열린 PR 을 읽지 못하면 검사 불능이다. 종료코드 2(통과로 뭉개지 않는다).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_open_prs import BUDGET_SECONDS, FetchError, _http, paged  # noqa: E402

from checker.pairing import CANNOT_CHECK  # noqa: E402
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
    my_version: str,
    budget: float = BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """판정에 넘길 dict. 읽지 못하면 cannot_check 로 답한다(예외를 밖으로 내지 않는다)."""
    deadline = clock() + budget
    try:
        me = get_json(f"/repos/{repo}/pulls/{self_number}")
        if not isinstance(me, dict) or "number" not in me:
            raise FetchError(f"PR #{self_number} 를 읽지 못했습니다")
        base_ref = me["base"]["ref"]
        main_version = _version(get_text(PLUGIN_JSON, base_ref), f"base({base_ref})")
        if main_version == my_version:
            return {"status": NOT_NEEDED}
        records = []
        for pr in paged(get_json, f"/repos/{repo}/pulls?state=open"):
            if pr.get("number") == self_number or (pr.get("base") or {}).get("ref") != base_ref:
                continue
            if clock() > deadline:
                raise FetchError(f"{budget:.0f}초 안에 열린 PR 을 다 읽지 못했습니다(시간 예산 초과)")
            sha = pr["head"]["sha"]
            records.append({
                "number": pr["number"],
                "title": pr.get("title") or "",
                "version": _version(get_text(PLUGIN_JSON, sha), f"PR #{pr['number']} head({sha[:7]})"),
            })
        return {"status": "ok", "main_version": main_version, "my_version": my_version, "prs": records}
    except FetchError as exc:
        return {"status": CANNOT_CHECK, "message": f"열린 PR 목록을 읽지 못했습니다: {exc}"}
    except (KeyError, TypeError, AttributeError) as exc:
        return {"status": CANNOT_CHECK, "message": f"열린 PR 정보의 모양이 예상과 다릅니다: {exc!r}"}


def render(result: dict) -> str:
    status = result["status"]
    if status == NOT_NEEDED:
        return "plugin version 겹침: 이 PR 이 plugin.json version 을 올리지 않아 확인하지 않는다."
    if status == CANNOT_CHECK:
        return f"plugin version 겹침 검사 불능: {result['message']}"
    if not result["warnings"]:
        return f"plugin version 겹침 없음(다른 열린 PR {result['compared']}건 확인)."
    return "\n".join(f"경고: {w['message']}" for w in result["warnings"])


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].isdigit():
        print("사용법: check_plugin_version_overlap.py <이 PR 번호>", file=sys.stderr)
        return 2
    number = int(args[0])

    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        info: dict = {"status": CANNOT_CHECK, "message": "GITHUB_TOKEN 이나 GITHUB_REPOSITORY 가 없어 열린 PR 목록을 읽지 못했습니다"}
    else:
        try:
            my_version = _version(Path(PLUGIN_JSON).read_text(encoding="utf-8"), "이 PR")
        except (FetchError, OSError) as exc:
            info = {"status": CANNOT_CHECK, "message": f"이 PR 의 version 을 읽지 못했습니다: {exc}"}
        else:
            get_json, get_text = _http(token, os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/"))
            info = collect(get_json, get_text, repo, number, my_version)
    result = check_plugin_version_overlap(info, number)

    text = render(result)
    print(text, file=sys.stderr if result["status"] == CANNOT_CHECK else sys.stdout)
    for w in result["warnings"]:
        print(f"::warning title=plugin version 겹침::{w['message']}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and result["status"] != NOT_NEEDED:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### plugin version 겹침\n\n{text}\n")
    return 2 if result["status"] == CANNOT_CHECK else 0


if __name__ == "__main__":
    raise SystemExit(main())
