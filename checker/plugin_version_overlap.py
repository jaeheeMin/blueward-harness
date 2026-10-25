"""열린 PR 끼리 plugin.json version 이 겹치는지 본다(#324, 실패로 바꿈 #470).

두 PR 이 main 의 같은 version 에서 출발해 둘 다 같은 값(0.10.81)으로 올리면 git 은 충돌 없이 병합한다.
먼저 병합된 쪽이 `v{version}` 태그를 가져가고 다른 쪽은 태그가 이미 있어 배포되지 못한다(#319/#317, #351/#353,
#462/#464 가 0.10.115 로 겹쳐 병합됨). 경고만 하면 체크가 초록이라 병합 판단에서 놓쳤다(#470) —
겹치면 **위반(실패)** 이다.

규칙: 검사가 도는 순간 같은 version 을 쓰는 다른 열린 PR 이 있으면 지금 PR 이 실패한다(먼저 차지한 쪽이 이긴다).
상대 PR 의 체크는 다시 돌지 않으므로 늦게 검사받는 쪽이 올려야 한다. 메시지에 올릴 다음 값을 적는다.

네트워크를 쓰지 않는 판정이다. 읽는 일은 `scripts/check_plugin_version_overlap.py` 가 한다.
입력(`info`):

    {"status": "ok", "main_version": "0.10.82", "my_version": "0.10.83",
     "prs": [{"number": 200, "title": "...", "version": "0.10.83"},        # 같은 base 의 다른 열린 PR
             {"number": 201, "title": "...", "version": null, "error": "..."}, ...]}   # 그 PR 만 읽지 못함
    {"status": "cannot_check", "message": "..."}                            # 읽지 못함
    {"status": "not_needed"}                                                # 이 PR 이 version 을 안 올려 읽지 않음

- 겹침: 이 PR 의 version 이 main 과 다르고(올렸고), 다른 열린 PR 의 head version 이 같은 값이다.
  version 을 바꾸지 않은 PR 은 main 의 값과 같으므로 이 PR 이 올린 값과 겹칠 수 없다 — 비교 대상이 아니다.
- 목록이나 이 PR 의 version 을 읽지 못하면 검사 불능이다. 통과도 위반도 아니다(원칙 7).
- 다른 PR 한 건의 version 만 못 읽으면(404, 깨진 JSON, 포크) 검사 불능으로 막지 않는다. 겹침과 무관한 이유로
  병합이 막히지 않게, 그 PR 만 `unchecked` 로 남기고 나머지를 비교한다. 이때 "겹침 없음" 이라 말하지 않는다.
- 비교는 `checker.plugin_version.parse_version` 의 정수 튜플로 한다(`0.10.9 < 0.10.17`).
"""
from __future__ import annotations

from checker.pairing import CANNOT_CHECK, PASS, VIOLATION
from checker.plugin_version import parse_version
from checker.version_overlap import NOT_NEEDED, RETRY_HINT, _title

__all__ = ["NOT_NEEDED", "check_plugin_version_overlap", "next_patch"]


def next_patch(version: str) -> str:
    """`0.10.83` -> `0.10.84`. 마지막 마디를 1 올린다. 정수 마디가 아니면 None."""
    try:
        parts = list(parse_version(version))
    except ValueError:
        return None
    parts[-1] += 1
    return ".".join(str(p) for p in parts)


def _cannot(detail: str) -> dict:
    return {
        "status": CANNOT_CHECK, "warnings": [], "read_failure": True,
        "message": f"다른 열린 PR 을 읽지 못해 plugin version 겹침을 확인하지 못했습니다(GitHub 일시 오류일 수 있습니다). {detail}\n{RETRY_HINT}",
    }


def check_plugin_version_overlap(info: dict, self_number: int) -> dict:
    """결과: pass/violation(겹침)/cannot_check/not_needed. 한 건을 못 읽은 PR 은 `unchecked` 에 남는다."""
    status = info.get("status")
    if status == NOT_NEEDED:
        return {"status": NOT_NEEDED, "warnings": []}
    if status == CANNOT_CHECK:
        return _cannot(str(info.get("message") or "열린 PR 목록을 읽지 못했습니다"))
    prs = info.get("prs")
    if status != "ok" or not isinstance(prs, list):
        return _cannot(f"열린 PR 정보의 모양을 읽을 수 없습니다(status: {status!r})")

    mine, main = info.get("my_version"), info.get("main_version")
    try:
        mine_t, main_t = parse_version(mine), parse_version(main)
    except ValueError as exc:
        return _cannot(f"이 PR 이나 main 의 plugin.json version 을 알 수 없습니다: {exc}")
    if mine_t == main_t:
        return {"status": NOT_NEEDED, "warnings": []}

    others = [p for p in prs if p.get("number") != self_number]
    unchecked, clash = [], []
    for p in others:
        try:
            same = parse_version(p.get("version")) == mine_t
        except ValueError:
            unchecked.append({"number": p.get("number"), "title": p.get("title") or "", "error": p.get("error") or "version 을 읽지 못함"})
            continue
        if same:
            clash.append(p)
    if clash:
        who = ", ".join(f"#{p['number']}({_title(p.get('title'))})" for p in clash)
        # main·이 PR·다른 열린 PR 의 version 을 모두 넘는 다음 값. 읽은 PR 만 안다.
        seen = [mine, main] + [p.get("version") for p in others]
        top = max((v for v in seen if _ok(v)), key=parse_version)
        nxt = next_patch(top)
        raise_to = f"{nxt} 로" if nxt else "한 칸 더"
        return {
            "status": VIOLATION, "warnings": [],
            "violations": [{
                "version": mine, "next": nxt,
                "prs": [{"number": p["number"], "title": p.get("title") or ""} for p in clash],
                "message": (
                    f"이 PR 의 version {mine} 을 열린 PR {who} 이 이미 씁니다. 이 PR 의 version 을 {raise_to} 올려 다시 푸시하세요"
                    f"(먼저 병합되는 쪽만 v{mine} 태그를 받아 배포됩니다)."
                ),
            }],
            "compared": len(others) - len(unchecked), "unchecked": unchecked,
        }
    return {"status": PASS, "warnings": [], "violations": [], "compared": len(others) - len(unchecked), "unchecked": unchecked}


def _ok(version) -> bool:
    try:
        parse_version(version)
    except ValueError:
        return False
    return True
