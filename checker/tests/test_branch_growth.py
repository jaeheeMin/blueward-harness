"""#536 — 브랜치의 src/ 변경 줄 세기와 커짐 알림 판정. 실제 임시 git 저장소로 확인한다."""
from __future__ import annotations

import json
import subprocess

import pytest

from checker import branch_growth
from checker.branch_growth import GrowthError, count_src_lines, judge, load_threshold, main


def test_설정이_없으면_기본_1000():
    assert load_threshold(None) == 1000
    assert load_threshold("# 주석만\n") == 1000


def test_설정값을_읽는다():
    assert load_threshold("notify_src_lines: 500\n") == 500


@pytest.mark.parametrize("text", ["notify_src_line: 5\n", "notify_src_lines: 0\n", "notify_src_lines: abc\n",
                                  "notify_src_lines: true\n", "- a\n", "a: [\n"])
def test_잘못된_설정은_검사_불능(text):
    with pytest.raises(GrowthError):
        load_threshold(text)


def test_src_아래_줄만_합친다():
    out = "10\t5\tsrc/a.abap\0" "300\t0\tdocs/spec/DEV-001-x.md\0" "1\t2\tsrc/sub/b.abap\0"
    assert count_src_lines(out) == (18, [])


def test_srcx_같은_비슷한_접두어는_세지_않는다():
    assert count_src_lines("5\t5\tsrcx/a.abap\0" "7\t0\tdocs/src/b.md\0") == (0, [])


def test_바이너리는_합에_넣지_않고_알린다():
    assert count_src_lines("-\t-\tsrc/x.png\0" "3\t1\tsrc/a.abap\0") == (4, ["src/x.png"])


@pytest.mark.parametrize("out", ["엉망\0", "1\t2\0", "a\tb\tsrc/x\0", "1\t2\t\0"])
def test_읽을_수_없는_출력은_조용히_버리지_않고_검사_불능(out):
    with pytest.raises(GrowthError):
        count_src_lines(out)


def test_기준_정확히_같으면_ok_넘으면_over():
    assert judge(1000, 1000) == "ok"
    assert judge(1001, 1000) == "over"


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """origin/main 이 있고 그 위에 브랜치가 있는 저장소."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "base.abap").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(tmp_path, "switch", "-qc", "feat")
    return tmp_path


def _commit_src(repo, lines):
    (repo / "src" / "new.abap").write_text("a\n" * lines, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "work")


def test_기준_이내면_ok(repo, capsys):
    _commit_src(repo, 10)
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_기준을_넘으면_over_종료코드_1(repo, capsys):
    _commit_src(repo, 1001)
    assert main(["--repo", str(repo), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "over" and out["src_lines"] == 1001 and out["threshold"] == 1000


def test_설정으로_기준을_바꾼다(repo, capsys):
    (repo / ".github").mkdir()
    (repo / ".github" / "branch-growth.yaml").write_text("notify_src_lines: 5\n", encoding="utf-8")
    _commit_src(repo, 6)
    assert main(["--repo", str(repo), "--json"]) == 1


def test_문서만_늘면_src_줄이_아니라_ok(repo, capsys):
    (repo / "docs").mkdir()
    (repo / "docs" / "big.md").write_text("a\n" * 5000, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "docs")
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["src_lines"] == 0


def test_src_가_기준에도_없는_저장소는_적용_안_함(tmp_path, capsys):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert main(["--repo", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_applicable"


def test_src_가_없고_기준도_못_읽으면_검사_불능(tmp_path, capsys):
    assert main(["--repo", str(tmp_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "cannot_check"


def test_src_를_통째로_지운_브랜치는_지운_줄로_센다(repo, capsys):
    (repo / "src" / "base.abap").write_text("a\n" * 1200, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "큰 파일")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "rm", "-rq", "src")
    _git(repo, "commit", "-qm", "src 삭제")
    assert not (repo / "src").exists()
    assert main(["--repo", str(repo), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "over" and out["src_lines"] == 1200


def test_기준_브랜치를_못_찾으면_검사_불능(repo, capsys):
    _commit_src(repo, 1)
    assert main(["--repo", str(repo), "--base", "nope", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "cannot_check"


def test_설정이_잘못되면_통과로_넘기지_않고_검사_불능(repo, capsys):
    (repo / ".github").mkdir()
    (repo / ".github" / "branch-growth.yaml").write_text("oops: 1\n", encoding="utf-8")
    assert main(["--repo", str(repo), "--json"]) == 2


def test_git_이_없으면_검사_불능(repo, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("없음")
    monkeypatch.setattr(branch_growth.subprocess, "run", boom)
    assert main(["--repo", str(repo), "--json"]) == 2


def test_한글_경로도_센다(repo, capsys):
    (repo / "src" / "판매오더_조회.abap").write_text("a\n" * 7, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "한글 파일")
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["src_lines"] == 7


def test_src_와_비슷한_폴더는_세지_않는다(repo, capsys):
    (repo / "srcx").mkdir()
    (repo / "srcx" / "a.abap").write_text("a\n" * 50, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "srcx")
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["src_lines"] == 0


def test_이름변경은_지움과_새로_쓴_줄로_삭제는_지운_줄로_센다(repo, capsys):
    (repo / "src" / "base.abap").write_text("a\n" * 10, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "10줄로")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "mv", "src/base.abap", "src/renamed.abap")
    _git(repo, "commit", "-qm", "이름변경")
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["src_lines"] == 20
    _git(repo, "rm", "-q", "src/renamed.abap")
    _git(repo, "commit", "-qm", "삭제")
    main(["--repo", str(repo), "--json"])
    assert json.loads(capsys.readouterr().out)["src_lines"] == 10


def test_기준_브랜치가_앞서가도_갈라진_지점부터_센다(repo, capsys):
    _commit_src(repo, 3)
    _git(repo, "switch", "-q", "main")
    (repo / "src" / "other.abap").write_text("a\n" * 500, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "main 이 앞서감")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "switch", "-q", "feat")
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["src_lines"] == 3


def test_커밋_안_된_변경은_세지_않는다(repo, capsys):
    _commit_src(repo, 2)
    (repo / "src" / "wip.abap").write_text("a\n" * 5000, encoding="utf-8")
    (repo / "src" / "new.abap").write_text("a\n" * 4000, encoding="utf-8")
    _git(repo, "add", "src/wip.abap")
    assert main(["--repo", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["src_lines"] == 2


def test_셀_수_없는_파일_수를_글로_보인다(repo, capsys):
    (repo / "src" / "img.bin").write_bytes(b"\x00\x01\x02" * 100)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "binary")
    assert main(["--repo", str(repo)]) == 0
    assert "줄 수를 셀 수 없는 파일 1개" in capsys.readouterr().out
