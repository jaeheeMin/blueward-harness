"""열린 PR 끼리 plugin.json version 이 겹치는지 본다(#324).

두 PR 이 main 의 같은 version 에서 출발해 둘 다 같은 값(0.10.81)으로 올리면 git 은 충돌 없이 병합한다.
먼저 병합된 쪽이 `v{version}` 태그를 가져가고 다른 쪽은 태그가 이미 있어 배포되지 못한다(#319/#317, #351/#353).
PR 에서 미리 **경고**한다. 막지 않는다(#315 와 같은 방침).

네트워크를 쓰지 않는 판정이다. 읽는 일은 `scripts/check_plugin_version_overlap.py` 가 한다.
입력(`info`):

    {"status": "ok", "main_version": "0.10.82", "my_version": "0.10.83",
     "prs": [{"number": 200, "title": "...", "version": "0.10.83"}, ...]}   # 같은 base 의 다른 열린 PR
    {"status": "cannot_check", "message": "..."}                            # 읽지 못함
    {"status": "not_needed"}                                                # 이 PR 이 version 을 안 올려 읽지 않음

- 겹침: 이 PR 의 version 이 main 과 다르고(올렸고), 다른 열린 PR 의 head version 이 같은 값이다.
  version 을 바꾸지 않은 PR 은 main 의 값과 같으므로 이 PR 이 올린 값과 겹칠 수 없다 — 비교 대상이 아니다.
- 읽지 못하면 검사 불능이다. 통과도 위반도 아니다(원칙 7).
"""
from __future__ import annotations

from checker.pairing import CANNOT_CHECK, PASS
from checker.version_overlap import NOT_NEEDED, RETRY_HINT, _title

__all__ = ["NOT_NEEDED", "check_plugin_version_overlap", "next_patch"]


def next_patch(version: str) -> str:
    """`0.10.83` -> `0.10.84`. 마지막 마디를 1 올린다."""
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def _cannot(detail: str) -> dict:
    return {
        "status": CANNOT_CHECK, "warnings": [], "read_failure": True,
        "message": f"다른 열린 PR 을 읽지 못해 plugin version 겹침을 확인하지 못했습니다(GitHub 일시 오류일 수 있습니다). {detail}\n{RETRY_HINT}",
    }


def check_plugin_version_overlap(info: dict, self_number: int) -> dict:
    """결과: pass(경고 포함)/cannot_check/not_needed. 위반은 없다."""
    status = info.get("status")
    if status == NOT_NEEDED:
        return {"status": NOT_NEEDED, "warnings": []}
    if status == CANNOT_CHECK:
        return _cannot(str(info.get("message") or "열린 PR 목록을 읽지 못했습니다"))
    prs = info.get("prs")
    if status != "ok" or not isinstance(prs, list):
        return _cannot(f"열린 PR 정보의 모양을 읽을 수 없습니다(status: {status!r})")

    mine, main = info.get("my_version"), info.get("main_version")
    if not mine or not main:
        return _cannot("이 PR 이나 main 의 plugin.json version 을 알 수 없습니다")
    if mine == main:
        return {"status": NOT_NEEDED, "warnings": []}

    others = [p for p in prs if p.get("number") != self_number]
    clash = [p for p in others if p.get("version") == mine]
    warnings = []
    if clash:
        who = ", ".join(f"#{p['number']}({_title(p.get('title'))})" for p in clash)
        warnings.append({
            "version": mine,
            "prs": [{"number": p["number"], "title": p.get("title") or ""} for p in clash],
            "message": (
                f"plugin.json version {mine} 을 열린 PR {who} 도 씁니다. 먼저 병합되는 쪽이 v{mine} 태그를 갖고, "
                f"다른 쪽은 그 뒤 sync 해서 version 을 {next_patch(mine)} 처럼 한 칸 더 올려야 배포됩니다."
            ),
        })
    return {"status": PASS, "warnings": warnings, "compared": len(others)}
