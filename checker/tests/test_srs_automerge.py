"""SRS 같은 자리 줄 추가 충돌 자동 합치기(`checker/srs_automerge.py`, #977)를 임시 git 저장소에서 검증한다.

merge·rebase 각각, 자동으로 합치는 모양과 거절하는 모양, 다른 파일도 충돌한 경우, CLI 종료코드를 본다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from checker.pairing import SRS_PATH
from checker.srs_automerge import CANNOT_CHECK, MERGED, REFUSED, automerge, main

HEAD = "# P SRS\n\n이 문서는 SSOT 다.\n\n버전: 0.1\n\n## 범위\n\n- 하는 것: 조회\n\n## 요구사항\n\n"
TABLE_HEAD = "| ID | Title | Status |\n|---|---|---|\n"
ROW = "| REQ-{n:03d} | 제목{n} | New |\n"
DETAIL = "### REQ-{n:03d} 제목{n}\n\n#### Short Description\n\n설명{n}\n\n"
TAIL = "## 참조\n\n없음\n"


def doc(rows: list[int], details: list[int], head: str = HEAD, tail: str = TAIL) -> str:
    return head + TABLE_HEAD + "".join(ROW.format(n=n) for n in rows) + "\n" + "".join(DETAIL.format(n=n) for n in details) + tail


def git(repo: Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if ok:
        assert done.returncode == 0, done.stderr
    return done


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def commit(repo: Path, msg: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def conflict(tmp_path: Path, mode: str, base: str, main: str, mine: str, extra: tuple[str, str, str] | None = None) -> Path:
    """mode 방식으로 충돌 중인 저장소를 만든다. main 과 내 브랜치가 base 에서 갈라진다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "false")
    write(repo, SRS_PATH, base)
    if extra:
        write(repo, "other.txt", extra[0])
    commit(repo, "base")
    git(repo, "switch", "-q", "-c", "feat")
    write(repo, SRS_PATH, mine)
    if extra:
        write(repo, "other.txt", extra[2])
    commit(repo, "mine")
    git(repo, "switch", "-q", "main")
    write(repo, SRS_PATH, main)
    if extra:
        write(repo, "other.txt", extra[1])
    commit(repo, "main")
    if mode == "merge":
        git(repo, "switch", "-q", "feat")
        git(repo, "merge", "--no-edit", "main", ok=False)
    else:
        git(repo, "switch", "-q", "feat")
        git(repo, "rebase", "main", ok=False)
    return repo


@pytest.fixture(params=["merge", "rebase"])
def mode(request):
    return request.param


BASE = doc([1], [1])


def test_표_끝_양쪽_추가는_자동으로_합친다_main_먼저(tmp_path, mode):
    main = doc([1, 2], [1, 2])
    mine = doc([1, 3], [1, 3])
    repo = conflict(tmp_path, mode, BASE, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == MERGED, res
    text = (repo / SRS_PATH).read_text(encoding="utf-8")
    assert text.index("| REQ-002 |") < text.index("| REQ-003 |")
    assert text.index("### REQ-002") < text.index("### REQ-003")
    assert text.count("버전: 0.1") == 1
    assert "<<<<" not in text and "====" not in text
    assert git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""  # git add 까지 됨


def test_합친_결과로_merge_는_커밋_rebase_는_continue_가_된다(tmp_path, mode):
    repo = conflict(tmp_path, mode, BASE, doc([1, 2], [1, 2]), doc([1, 3], [1, 3]))
    assert automerge(repo, mode)["status"] == MERGED
    if mode == "merge":
        git(repo, "commit", "-q", "-m", "chore: main 의 새 변경 합쳐 받기")
    else:
        done = subprocess.run(["git", "-C", str(repo), "rebase", "--continue"], capture_output=True, env={**__import__("os").environ, "GIT_EDITOR": "true"})
        assert done.returncode == 0, done.stderr
    assert git(repo, "status", "--porcelain").stdout.strip() == ""


def test_상세_절_양쪽_추가도_main_먼저(tmp_path, mode):
    base = doc([1], [1])
    main = base.replace("## 참조", DETAIL.format(n=2) + "## 참조").replace(TABLE_HEAD + ROW.format(n=1), TABLE_HEAD + ROW.format(n=1) + ROW.format(n=2))
    mine = base.replace("## 참조", DETAIL.format(n=3) + "## 참조").replace(TABLE_HEAD + ROW.format(n=1), TABLE_HEAD + ROW.format(n=1) + ROW.format(n=3))
    repo = conflict(tmp_path, mode, base, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == MERGED and res["conflicts"] == 2, res
    text = (repo / SRS_PATH).read_text(encoding="utf-8")
    assert text.index("### REQ-002") < text.index("### REQ-003")


def test_공통_줄이_섞인_추가는_중복_없이_합친다(tmp_path, mode):
    base = BASE
    main = base.replace("- 하는 것: 조회\n", "- 하는 것: 조회\n- 공통\n- main 추가\n")
    mine = base.replace("- 하는 것: 조회\n", "- 하는 것: 조회\n- 공통\n- 내 추가\n")
    repo = conflict(tmp_path, mode, base, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == MERGED, res
    text = (repo / SRS_PATH).read_text(encoding="utf-8")
    assert text.count("- 공통\n") == 1
    assert text.index("- main 추가") < text.index("- 내 추가")


def test_버전_줄_충돌은_거절한다(tmp_path, mode):
    main = doc([1], [1], head=HEAD.replace("버전: 0.1", "버전: 0.2"))
    mine = doc([1], [1], head=HEAD.replace("버전: 0.1", "버전: 0.3"))
    repo = conflict(tmp_path, mode, BASE, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == REFUSED, res
    assert "버전: 0.1" in (repo / SRS_PATH).read_text(encoding="utf-8") or "<<<<<<<" in (repo / SRS_PATH).read_text(encoding="utf-8")


def test_버전_줄_양쪽_추가는_거절한다(tmp_path, mode):
    base = doc([1], [1], head=HEAD.replace("버전: 0.1\n", ""))
    main = doc([1], [1], head=HEAD.replace("버전: 0.1\n", "버전: 0.2\n"))
    mine = doc([1], [1], head=HEAD.replace("버전: 0.1\n", "버전: 0.3\n"))
    repo = conflict(tmp_path, mode, base, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == REFUSED, res


def test_표_머리글_변경은_거절한다(tmp_path, mode):
    main = BASE.replace("| ID | Title | Status |\n|---|---|---|\n", "| ID | Title | Status | 담당 |\n|---|---|---|---|\n")
    mine = BASE.replace("| ID | Title | Status |\n|---|---|---|\n", "| ID | Title | Status | 비고 |\n|---|---|---|---|\n")
    repo = conflict(tmp_path, mode, BASE, main, mine)
    assert automerge(repo, mode)["status"] == REFUSED


def test_열_수가_다른_표_행은_거절한다(tmp_path, mode):
    main = doc([1, 2], [1, 2])
    mine = doc([1], [1, 3]).replace(ROW.format(n=1), ROW.format(n=1) + "| REQ-003 | 제목3 | New | 여분 |\n")
    repo = conflict(tmp_path, mode, BASE, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == REFUSED and "열 수" in res["reason"], res


def test_같은_REQ_번호_양쪽_추가는_거절한다(tmp_path, mode):
    main = doc([1, 2], [1, 2]).replace("제목2", "main 쪽")
    mine = doc([1, 2], [1, 2]).replace("제목2", "내 쪽")
    repo = conflict(tmp_path, mode, BASE, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == REFUSED, res
    assert "REQ-002" in res["reason"]


def test_같은_줄_양쪽_수정은_거절한다(tmp_path, mode):
    main = BASE.replace("- 하는 것: 조회", "- 하는 것: 조회와 등록")
    mine = BASE.replace("- 하는 것: 조회", "- 하는 것: 조회와 삭제")
    repo = conflict(tmp_path, mode, BASE, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == REFUSED and "base" in res["reason"], res


def test_SRS_말고_다른_파일도_충돌하면_거절한다(tmp_path, mode):
    repo = conflict(
        tmp_path, mode, BASE, doc([1, 2], [1, 2]), doc([1, 3], [1, 3]), extra=("a\n", "main\n", "mine\n")
    )
    res = automerge(repo, mode)
    assert res["status"] == REFUSED and "하나가 아니다" in res["reason"], res


def test_합친_결과가_모양_검사에_걸리면_거절한다(tmp_path, mode):
    # 표 행만 더하고 상세 절은 한쪽이 안 쓰면 합친 뒤 표에만 있는 번호가 생긴다.
    main = doc([1, 2], [1])
    mine = doc([1, 3], [1])
    repo = conflict(tmp_path, mode, BASE, main, mine)
    res = automerge(repo, mode)
    assert res["status"] == REFUSED and "모양 검사" in res["reason"], res


def test_충돌이_없으면_거절한다(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    res = automerge(repo, "merge")
    assert res["status"] == REFUSED


def test_모드가_이상하면_검사_불능(tmp_path):
    assert automerge(tmp_path, "squash")["status"] == CANNOT_CHECK


def test_cli_종료코드와_json(tmp_path, capsys, mode):
    repo = conflict(tmp_path, mode, BASE, doc([1, 2], [1, 2]), doc([1, 3], [1, 3]))
    assert main(["--mode", mode, "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == MERGED
    assert main(["--mode", mode, "--root", str(repo)]) == 1  # 이미 풀려 충돌 파일이 없다
    assert json.loads(capsys.readouterr().out)["status"] == REFUSED
