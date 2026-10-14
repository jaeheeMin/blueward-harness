"""열린 PR 끼리 문서 판 번호가 겹치는지 본다(#315).

두 PR 이 main 의 같은 판(`버전: 0.2`)에서 출발해 각자 `0.3` 을 만들면 산출 파일명
(`BW_Backlog List_v0.3.xlsx`)과 SRS `버전:` 이 겹친다. 병합 뒤에야 알면 늦으므로 PR 에서
미리 **경고**한다. 막지 않는다(통과 유지) — 먼저 병합되는 쪽이 그 판을 갖고, 다른 쪽이
sync 뒤 다음 판으로 다시 산출하면 된다.

이 모듈은 네트워크를 쓰지 않는다. 열린 PR 정보는 `scripts/fetch_open_prs.py` 가 GitHub API 로
읽어 JSON 으로 저장하고, 여기서는 그 JSON 만 본다(테스트가 쉽도록).

입력(`open_prs`):

    {"status": "ok", "prs": [
        {"number": 200, "title": "...",
         "added": ["docs/srs/BW_Backlog List_v0.3.xlsx"],   # 이 PR 이 추가(이름 바꿈 포함)한 판 있는 산출 파일
         "srs_changed": true, "srs_version": "0.3", "srs_base_version": "0.2", "srs_error": null}, ...]}
    {"status": "cannot_check", "message": "..."}      # 목록을 못 읽음
    {"status": "not_needed"}                          # 이 PR 이 판 번호를 건드리지 않아 읽지 않음

- 산출 파일 겹침: 이 PR 이 **추가**한 `_v<판>` 파일이 다른 열린 PR 의 추가 파일과 같은 경로.
  이미 있던 파일을 고친 것은 추가가 아니라 대상이 아니다.
- SRS 판 겹침: 이 PR 이 `docs/ssot/SRS.md` 의 `버전:` 을 바꿨고(base 와 다른 값), 다른 PR 도 바꿔 같은 값.
- 읽지 못하면(목록, 이 PR 이 목록에 없음, 겹침 판정에 필요한 SRS 버전) **검사 불능**이다.
  통과도 위반도 아니다.
"""
from __future__ import annotations

import re

from checker.pairing import CANNOT_CHECK, PASS, SRS_PATH

NOT_NEEDED = "not_needed"
ADDED_STATUSES = {"added", "renamed"}

# 산출 파일 이름 끝의 판 표기: `..._v0.3.xlsx`. 템플릿 폴더의 파일은 산출물이 아니다.
_ARTIFACT = re.compile(r"_v(\d+(?:\.\d+)*)\.(?:xlsx|docx|pptx)$", re.IGNORECASE)
_SRS_VERSION = re.compile(r"^[ \t]*(?:[-*][ \t]+)?\**버전\**[ \t]*:[ \t]*\**[ \t]*[vV]?(\d+(?:\.\d+)*)", re.MULTILINE)


def artifact_version(path: str) -> str | None:
    """산출 파일 경로의 판 번호(`..._v0.3.xlsx` 의 `0.3`). 산출 파일이 아니면 None."""
    posix = path.replace("\\", "/")
    if posix.startswith("templates/") or "/templates/" in posix:
        return None
    m = _ARTIFACT.search(posix)
    return m.group(1) if m else None


def added_artifacts(files: list[dict]) -> list[str]:
    """API 의 파일 목록(`filename`, `status`)에서 추가된 판 있는 산출 파일 경로."""
    return [
        f["filename"] for f in files
        if f.get("status") in ADDED_STATUSES and artifact_version(f.get("filename", "")) is not None
    ]


def srs_version_of(text: str) -> str | None:
    """SRS 문서 머리의 `버전: 0.3`(앞의 `v`·목록 기호·굵게 표시는 무시). 없으면 None."""
    m = _SRS_VERSION.search(text)
    return m.group(1) if m else None


def bumped(pr: dict) -> str | None:
    """이 PR 이 SRS `버전:` 을 바꿨으면 새 값, 아니면 None."""
    if not pr.get("srs_changed"):
        return None
    version = pr.get("srs_version")
    if not version or version == pr.get("srs_base_version"):
        return None
    return version


def next_version(version: str) -> str:
    """`0.3` -> `0.4`. 마지막 마디를 1 올린다."""
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def touches_version(path: str) -> bool:
    """바뀐 파일 경로가 판 번호 검사를 돌릴 만한지(SRS 이거나 판 있는 산출 파일)."""
    posix = path.replace("\\", "/")
    return posix == SRS_PATH or artifact_version(posix) is not None


def _cannot(message: str) -> dict:
    return {"status": CANNOT_CHECK, "warnings": [], "message": message}


def _who(prs: list[dict]) -> str:
    return ", ".join(f"#{p['number']}({p.get('title') or '제목 없음'})" for p in prs)


def _tail(version: str) -> str:
    return (
        f"먼저 병합되는 쪽이 v{version} 을 갖고, 다른 쪽은 sync 뒤 {next_version(version)} 로 다시 산출해야 합니다."
    )


def check_version_overlap(open_prs: dict, self_number: int) -> dict:
    """결과: pass(경고 포함)/cannot_check. 위반은 없다."""
    status = open_prs.get("status")
    if status == CANNOT_CHECK:
        return _cannot(str(open_prs.get("message") or "열린 PR 목록을 읽지 못했습니다"))
    if status != "ok" or not isinstance(open_prs.get("prs"), list):
        return _cannot(f"열린 PR 정보의 모양을 읽을 수 없습니다(status: {status!r})")

    prs = open_prs["prs"]
    mine = next((p for p in prs if p.get("number") == self_number), None)
    if mine is None:
        return _cannot(f"이 PR(#{self_number})이 읽어 온 열린 PR 목록에 없습니다")
    others = [p for p in prs if p.get("number") != self_number]

    warnings: list[dict] = []

    # 산출 파일: 같은 경로를 둘 다 추가
    for path in sorted(set(mine.get("added") or [])):
        version = artifact_version(path)
        if version is None:
            continue
        clash = [p for p in others if path in (p.get("added") or [])]
        if clash:
            warnings.append({
                "kind": "file", "version": version, "file": path,
                "prs": [{"number": p["number"], "title": p.get("title") or ""} for p in clash],
                "message": f"이 판 번호(v{version})를 열린 PR {_who(clash)} 도 씁니다(산출 파일 `{path}`). {_tail(version)}",
            })

    # SRS 버전: 둘 다 바꿔서 같은 값
    if mine.get("srs_error"):
        return _cannot(f"이 PR 의 SRS 버전을 읽지 못했습니다: {mine['srs_error']}")
    mine_version = bumped(mine)
    if mine_version is not None:
        clash = []
        for p in others:
            if not p.get("srs_changed"):
                continue
            if p.get("srs_error"):
                return _cannot(f"PR #{p['number']} 의 SRS 버전을 읽지 못했습니다: {p['srs_error']}")
            if bumped(p) == mine_version:
                clash.append(p)
        if clash:
            warnings.append({
                "kind": "srs", "version": mine_version, "file": SRS_PATH,
                "prs": [{"number": p["number"], "title": p.get("title") or ""} for p in clash],
                "message": f"이 판 번호(v{mine_version})를 열린 PR {_who(clash)} 도 씁니다(SRS `버전:`). {_tail(mine_version)}",
            })

    return {"status": PASS, "warnings": warnings, "compared": len(others)}
