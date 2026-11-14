"""SRS 같은 자리 줄 추가 충돌을 자동으로 합친다(#977).

deliver(rebase)·sync(merge)·세션 시작 훅(merge·rebase)에서 충돌이 났을 때, 충돌 파일이 `docs/ssot/SRS.md` 하나뿐이고
모든 충돌 덩어리가 "양쪽이 같은 자리에 줄만 추가" 이면 main 줄 먼저 → 내 줄 순서로 이어 붙인다. 하나라도 아니면 아무것도 바꾸지 않고
돌려보내며, 호출하는 쪽이 지금처럼 abort 하고 사람에게 보고한다.

    python -m checker.srs_automerge --mode merge|rebase --root .

방식마다 stage 의 뜻이 반대다(임시 저장소 실험으로 확인). merge: ours(:2)=내 쪽, theirs(:3)=main. rebase: ours(:2)=main, theirs(:3)=내 쪽.
`git merge-file -p --zdiff3` 로 base(:1)·main·내 쪽을 다시 합쳐 충돌 덩어리를 얻는다(diff3 는 양쪽 공통 추가 줄이 두 번 남는다).

덩어리를 자동으로 합치는 조건(모두 만족):
- base 부분이 비어 있다(양쪽이 줄만 추가). 양쪽 모두 줄이 있다.
- 어느 쪽에도 `버전:` 줄이 없다. 표 머리글·구분줄(`| ID`, `|---|`)이 없다.
- 양쪽에서 새로(base 에 없던) 나온 REQ-n·DEV-n 번호가 겹치지 않는다.
- 표 행이면 바로 앞이 같은 표의 행이고 열 수가 그 표 머리글과 같다.
합친 결과는 `srs_shape` 검사와 같은 줄 중복 검사(빈 줄·표 구분줄·제목 줄 제외, base 에 없던 줄이 새로 겹친 것만)를 통과해야 한다.

결과(stdout JSON, 종료코드): `merged`(0, 작업 폴더에 쓰고 `git add` 까지 함) / `refused`(1, 조건이 아님 — 아무것도 안 바꿈) /
`cannot_check`(2, 읽거나 돌리지 못함 — 통과가 아니다. 아무것도 안 바꿈). 커밋·`rebase --continue` 는 호출하는 쪽이 한다.
합친 커밋은 SRS 승인을 낡게 만든다(`ssot_approval`) — 올리면 다시 승인을 받는다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from checker.model import ConfigError
from checker.pairing import SRS_PATH
from checker.version_overlap import _SRS_VERSION

MERGED = "merged"
REFUSED = "refused"
CANNOT_CHECK = "cannot_check"

_LABELS = ("main", "base", "mine")
_NUMBER = re.compile(r"\b(?:REQ|DEV)-\d+")
_VERSION_LOOSE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?\**버전\**[ \t]*[:：]")


class _Refuse(Exception):
    pass


class _Cannot(Exception):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except OSError as exc:
        raise _Cannot(f"git 을 실행하지 못했다: {exc}") from exc
    if check and done.returncode != 0:
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise _Cannot(f"git {' '.join(args)} 실패: {err[0] if err else done.returncode}")
    return done


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _Cannot(f"{what} 이 UTF-8 이 아니다: {exc}") from exc


def _cells(line: str) -> int:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return len(re.split(r"(?<!\\)\|", s))


def _is_separator(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and "-" in s and set(s) <= set("|-: \t")


def _is_id_header(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and re.split(r"(?<!\\)\|", s[1:])[0].strip().upper() == "ID"


def _check_added_lines(prefix: list[str], added: list[str]) -> None:
    """prefix 뒤에 added 를 이어 붙였을 때 표 규칙을 어기면 _Refuse."""
    seq = [l.rstrip("\r\n") for l in prefix]
    for raw in added:
        line = raw.rstrip("\r\n")
        if _VERSION_LOOSE.match(line) or _SRS_VERSION.match(line):
            raise _Refuse("`버전:` 줄이 든 덩어리다")
        if _is_separator(line) or _is_id_header(line):
            raise _Refuse("표 머리글이나 구분줄이 든 덩어리다")
        if line.lstrip().startswith("|"):
            if not seq or not seq[-1].lstrip().startswith("|"):
                raise _Refuse("표 행이 기존 표 바로 뒤가 아니라 새 표를 시작한다")
            i = len(seq) - 1
            while i >= 0 and seq[i].lstrip().startswith("|"):
                i -= 1
            header = seq[i + 1]
            if _cells(line) != _cells(header):
                raise _Refuse(f"표 행의 열 수({_cells(line)})가 표 머리글({_cells(header)})과 다르다")
        seq.append(line)


def _new_numbers(lines: list[str], base_text: str) -> set[str]:
    known = set(_NUMBER.findall(base_text))
    return set(_NUMBER.findall("".join(lines))) - known


def _resolve(merged: str, base_text: str) -> tuple[str, int]:
    """`merge-file --zdiff3` 결과의 충돌 덩어리를 모두 main 먼저 → 내 줄로 풀어 (결과, 덩어리 수). 조건 밖이면 _Refuse."""
    out: list[str] = []
    state = "text"
    main: list[str] = []
    base: list[str] = []
    mine: list[str] = []
    count = 0
    main_new: set[str] = set()
    mine_new: set[str] = set()
    for line in merged.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if state == "text":
            if body == "<<<<<<< main":
                state, main, base, mine = "main", [], [], []
            elif body.startswith(("<<<<<<<", "|||||||", ">>>>>>>")) or body == "=======":
                raise _Refuse("충돌 표시가 예상한 모양이 아니다")
            else:
                out.append(line)
        elif state == "main":
            if body == "||||||| base":
                state = "base"
            else:
                main.append(line)
        elif state == "base":
            if body == "=======":
                state = "mine"
            else:
                base.append(line)
        else:
            if body == ">>>>>>> mine":
                count += 1
                if base:
                    raise _Refuse("충돌 덩어리에 base 줄이 있다(양쪽이 줄만 추가한 것이 아니다)")
                if not main or not mine:
                    raise _Refuse("한쪽에 줄이 없는 충돌 덩어리다")
                if not main[-1].endswith("\n"):
                    main[-1] += "\n"
                _check_added_lines(out, main + mine)
                main_new |= _new_numbers(main, base_text)
                mine_new |= _new_numbers(mine, base_text)
                out.extend(main + mine)
                state = "text"
            else:
                mine.append(line)
    if state != "text":
        raise _Refuse("충돌 표시가 닫히지 않았다")
    both = sorted(main_new & mine_new)
    if both:
        raise _Refuse(f"양쪽이 새로 만든 번호가 겹친다: {', '.join(both)}")
    return "".join(out), count


def _line_counter(text: str) -> Counter:
    """빈 줄·표 구분줄·제목 줄을 뺀 줄별 개수. 제목(`#### Short Description`)은 상세 절마다 되풀이되는 것이 정상이다."""
    return Counter(
        l.rstrip("\r") for l in text.split("\n") if l.strip() and not _is_separator(l) and not l.lstrip().startswith("#")
    )


def _check_result(result: str, base_text: str, main_text: str, mine_text: str) -> None:
    from checker.rules.srs_shape import check

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "SRS.md"
        p.write_bytes(result.encode("utf-8"))
        try:
            violations = check(p, {})
        except ConfigError as exc:
            raise _Cannot(f"합친 결과의 SRS 모양을 검사하지 못했다: {exc}") from exc
    if violations:
        raise _Refuse("합친 결과가 SRS 모양 검사에 걸린다: " + "; ".join(f"{v.actual}" for v in violations))
    now, a, b, base = (_line_counter(t) for t in (result, main_text, mine_text, base_text))
    # base 에 이미 있던 줄(상세 절마다 되풀이되는 문구 등)은 늘어나도 중복으로 보지 않는다.
    dups = sorted(l for l, n in now.items() if n > 1 and n > max(a[l], b[l]) and not base[l])
    if dups:
        raise _Refuse("합친 결과에 같은 줄이 새로 중복된다: " + " / ".join(d.strip()[:60] for d in dups[:3]))


def automerge(root: Path, mode: str) -> dict:
    """충돌 중인 저장소 `root` 에서 SRS 를 자동으로 합친다. 돌려주는 값은 `status` 와 `reason`/`conflicts`."""
    try:
        if mode not in ("merge", "rebase"):
            raise _Cannot(f"모드가 merge 도 rebase 도 아니다: {mode}")
        unmerged = _git(root, "diff", "--name-only", "--diff-filter=U", "-z").stdout.decode("utf-8", "replace")
        files = [f for f in unmerged.split("\0") if f]
        if files != [SRS_PATH]:
            raise _Refuse(f"충돌 파일이 {SRS_PATH} 하나가 아니다: {', '.join(files) or '없음'}")
        stages = {
            int(line.split()[2])
            for line in _git(root, "ls-files", "-u", "--", SRS_PATH).stdout.decode("utf-8", "replace").splitlines()
        }
        if stages != {1, 2, 3}:
            raise _Refuse("base·양쪽 판이 다 있는 수정 충돌이 아니다(추가·삭제 충돌)")
        base_b, ours_b, theirs_b = (_git(root, "show", f":{n}:{SRS_PATH}").stdout for n in (1, 2, 3))
        main_b, mine_b = (theirs_b, ours_b) if mode == "merge" else (ours_b, theirs_b)
        base_text, main_text, mine_text = (_decode(b, n) for b, n in ((base_b, "base"), (main_b, "main 판"), (mine_b, "내 판")))
        if "\r" in base_text + main_text + mine_text and not (
            "\r\n" in main_text and "\r\n" in mine_text and "\r\n" in base_text
        ):
            raise _Cannot("줄바꿈이 CRLF 와 LF 로 섞여 있어 확인하지 못했다")
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, data in zip(("main", "base", "mine"), (main_b, base_b, mine_b)):
                p = Path(tmp) / name
                p.write_bytes(data)
                paths.append(str(p))
            done = subprocess.run(
                ["git", "merge-file", "-p", "--zdiff3", "-L", _LABELS[0], "-L", _LABELS[1], "-L", _LABELS[2], *paths],
                capture_output=True,
            )
        if done.returncode > 127 or done.returncode < 0:
            raise _Cannot(f"git merge-file 실패(종료코드 {done.returncode})")
        merged_text = _decode(done.stdout, "합친 결과")
        result, count = _resolve(merged_text, base_text)
        _check_result(result, base_text, main_text, mine_text)
        (root / SRS_PATH).write_bytes(result.encode("utf-8"))
        _git(root, "add", "--", SRS_PATH)
        return {"status": MERGED, "conflicts": count}
    except _Refuse as exc:
        return {"status": REFUSED, "reason": str(exc)}
    except _Cannot as exc:
        return {"status": CANNOT_CHECK, "reason": str(exc)}
    except OSError as exc:
        return {"status": CANNOT_CHECK, "reason": f"파일을 읽거나 쓰지 못했다: {exc}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="checker.srs_automerge")
    ap.add_argument("--mode", required=True, choices=["merge", "rebase"])
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    result = automerge(Path(args.root), args.mode)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return {MERGED: 0, REFUSED: 1}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
