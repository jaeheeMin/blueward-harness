"""화면 그림의 지난 판과 새 판을 비교해 추가·수정·삭제를 판정한다(#347).

입력은 `screen_draw` 가 읽은 목록(필터 바 [(이름, 필수)], 액션 [이름], 결과 테이블 [열 이름], Go 여부)이라 파일·git 을 모른다.
비교 단위는 소절(필터 바·액션·결과 테이블)이고 항목은 이름으로 짝짓는다.

- 새 판에만 있는 이름 = 추가, 옛 판에만 있는 이름 = 삭제. 이름이 바뀐 것은 삭제 + 추가로 본다.
- 필터 바의 `필수` 가 바뀐 것만 수정이다(빈칸은 N). 액션·결과 테이블에는 수정이 없다.
- 설정 표 `조회` 가 자동 ↔ Go 로 바뀌면 `Go` 액션의 추가/삭제다(대상 "액션 · Go").
- 순서만 바뀐 것은 표시하지 않는다.
- 삭제 항목도 그림에 남긴다. 옛 판에서 바로 앞에 있던 항목(새 판에도 남아 있는 것) 바로 뒤, 없으면 소절 맨 앞.
- 번호는 그리는 순서(필터 바 → Go → 액션 → 결과 테이블, 각 안에서 위치 순)다.
"""
from __future__ import annotations

from typing import NamedTuple

KINDS = ("추가", "수정", "삭제")
GO = "Go"
GO_KEY = ("Go", GO)  # 설정 표 `조회: Go` 가 그리는 Go 액션의 표시 키(같은 이름의 일반 액션과 구분한다)


class Change(NamedTuple):
    number: int
    kind: str  # 추가 | 수정 | 삭제
    target: str  # "필터 바 · 기간"
    content: str  # "필터 바에 '기간' 추가"


class Merged(NamedTuple):
    conds: list[tuple[str, bool]]
    actions: list[str]
    cols: list[str]
    go: bool
    marks: dict[tuple[str, str], tuple[str, int]]  # (소절, 이름) → (구분, 번호). Go 는 GO_KEY
    changes: list[Change]  # 번호 순


def circled(n: int) -> str:
    """①~⑳, 21 부터는 "(21)"."""
    return chr(0x2460 + n - 1) if 1 <= n <= 20 else f"({n})"


def _merge_names(old: list[str], new: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(합친 이름 순서, 추가된 이름, 삭제된 이름). 삭제된 것은 옛 판에서 바로 앞에 있던 남은 항목 바로 뒤에 둔다."""
    new_set, old_set = set(new), set(old)
    after: dict[str | None, list[str]] = {}
    anchor: str | None = None
    deleted: list[str] = []
    for n in old:
        if n in new_set:
            anchor = n
        else:
            after.setdefault(anchor, []).append(n)
            deleted.append(n)
    merged: list[str] = list(after.get(None, []))
    for n in new:
        merged.append(n)
        merged.extend(after.get(n, []))
    return merged, [n for n in new if n not in old_set], deleted


def merge(
    old: tuple[list[tuple[str, bool]], list[str], list[str], bool],
    new: tuple[list[tuple[str, bool]], list[str], list[str], bool],
) -> Merged:
    """(필터 바, 액션, 결과 테이블, Go) 두 판을 비교해 합친 목록과 표시를 낸다. 이름은 소절 안에서 겹치지 않는다고 본다."""
    oc, oa, ot, ogo = old
    nc, na, nt, ngo = new
    old_req, new_req = dict(oc), dict(nc)
    conds_names, c_add, c_del = _merge_names([n for n, _ in oc], [n for n, _ in nc])
    conds = [(n, new_req[n] if n in new_req else old_req[n]) for n in conds_names]
    c_mod = [n for n in new_req if n in old_req and new_req[n] != old_req[n]]
    actions, a_add, a_del = _merge_names(oa, na)
    cols, t_add, t_del = _merge_names(ot, nt)

    kinds: dict[tuple[str, str], tuple[str, str]] = {}  # 키 → (구분, 내용)
    for n in c_add:
        kinds[("필터 바", n)] = ("추가", f"필터 바에 '{n}' 추가")
    for n in c_del:
        kinds[("필터 바", n)] = ("삭제", f"필터 바에서 '{n}' 삭제")
    for n in c_mod:
        kinds[("필터 바", n)] = ("수정", f"필수 {'Y' if old_req[n] else 'N'} → {'Y' if new_req[n] else 'N'}")
    for n in a_add:
        kinds[("액션", n)] = ("추가", f"액션에 '{n}' 추가")
    for n in a_del:
        kinds[("액션", n)] = ("삭제", f"액션에서 '{n}' 삭제")
    for n in t_add:
        kinds[("결과 테이블", n)] = ("추가", f"결과 테이블에 '{n}' 추가")
    for n in t_del:
        kinds[("결과 테이블", n)] = ("삭제", f"결과 테이블에서 '{n}' 삭제")
    go = ngo
    if ngo and not ogo:
        kinds[GO_KEY] = ("추가", f"액션에 '{GO}' 추가")
    elif ogo and not ngo:
        kinds[GO_KEY] = ("삭제", f"액션에서 '{GO}' 삭제")
        go = True  # 삭제된 Go 도 그림에 남긴다

    order: list[tuple[str, str]] = (
        [("필터 바", n) for n, _ in conds]
        + ([GO_KEY] if go else [])
        + [("액션", n) for n in actions]
        + [("결과 테이블", n) for n in cols]
    )
    marks: dict[tuple[str, str], tuple[str, int]] = {}
    changes: list[Change] = []
    for key in order:
        if key in kinds:
            kind, content = kinds[key]
            num = len(changes) + 1
            marks[key] = (kind, num)
            section = "액션" if key == GO_KEY else key[0]
            changes.append(Change(num, kind, f"{section} · {key[1]}", content))
    return Merged(conds, actions, cols, go, marks, changes)
