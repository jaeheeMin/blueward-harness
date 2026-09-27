"""바뀐 파일 목록을 거르는 부분.

실제 저장소에서 한 번 당한 자리다. git 이 한글 경로를 따옴표와 8진수로 감싸 내놓는
바람에 모든 경로가 깨졌는데, 그때 말없이 "검사 대상 없음" 으로 넘겨 위반 문서가 있는
PR 이 초록불로 통과했다. 지역 테스트가 이것을 놓친 이유는 `git diff` 를 거치지 않고
경로를 직접 만들었기 때문이다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_changed import (  # noqa: E402
    EXIT_CONFIG_ERROR,
    EXIT_PASS,
    has_standards_root,
    main_entry,
    split_listing,
)


def test_전부_깨진_목록은_통과로_답하지_않는다(tmp_path, capsys):
    """검사할 수 없는 상태를 통과라고 답하면 보호가 필요한 순간에 보호가 사라진다."""
    listing = tmp_path / "changed.txt"
    listing.write_text(
        '"sample/docs/\353\260\234\355\221\234/\353\247\250.pptx"\n',
        encoding="utf-8",
    )
    assert main_entry([str(listing)]) == EXIT_CONFIG_ERROR
    assert "실제 파일이 아닙니다" in capsys.readouterr().out


def test_목록이_비어_있으면_통과다(tmp_path, capsys):
    """검사할 것이 없는 것과 검사하지 못한 것은 다르다."""
    listing = tmp_path / "changed.txt"
    listing.write_text("\n  \n", encoding="utf-8")
    assert main_entry([str(listing)]) == EXIT_PASS
    assert '"scoped": 0' in capsys.readouterr().out


def test_목록_파일이_아예_없으면_검사불능이다(tmp_path, capsys):
    """비어 있는 것과 없는 것은 다르다. 없으면 무엇이 바뀌었는지조차 모른다."""
    missing_listing = tmp_path / "존재하지_않음.txt"
    assert main_entry([str(missing_listing)]) == EXIT_CONFIG_ERROR
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "config_error"
    assert str(missing_listing) in out["message"]


def test_있는_것과_없는_것을_가른다(tmp_path):
    real = tmp_path / "있다.md"
    real.write_text("# 제목\n", encoding="utf-8")
    found, missing = split_listing(f"{real}\n{tmp_path / '없다.md'}\n\n")
    assert found == [str(real)]
    assert missing == [str(tmp_path / "없다.md")]


@pytest.mark.skipif(not Path(".git").exists() and not Path("../.git").exists(),
                    reason="git 저장소가 아니다")
def test_git_이_한글_경로를_이스케이프하지_않게_한다(tmp_path):
    """워크플로가 쓰는 그 옵션이 실제로 효과가 있는지 git 에 직접 확인한다.

    이 테스트는 `git diff` 를 실제로 거친다. 경로를 손으로 만들면 이 버그를 놓친다.
    """
    repo = tmp_path / "저장소"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True,
                                    encoding="utf-8", check=True)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "기준.md").write_text("처음\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "first")
    (repo / "한글 이름.md").write_text("내용\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "second")

    기본 = run("diff", "--name-only", "HEAD~1", "HEAD").stdout
    끈것 = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--name-only", "HEAD~1", "HEAD"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout

    assert "\\" in 기본, "git 이 한글 경로를 이스케이프하지 않는다면 이 검사는 무의미하다"
    assert 끈것.strip() == "한글 이름.md"
    # 그리고 이스케이프된 쪽은 실제 파일로 인식되지 않는다 — 이것이 버그의 본체였다
    found, missing = split_listing(기본)
    assert found == [] and missing


# ── 규칙 폴더를 빠뜨린 경우 ──────────────────────────────────────────────────
#
# `templates/` 와 `rules/` 를 함께 둔 폴더가 저장소 안에 하나도 없으면, 지금까지는
# 모든 문서가 out_of_scope 로 빠져 조용히 통과했다(#24). 이 워크플로를 부르는 저장소는
# 검사받을 뜻으로 부른 것이므로, 그것은 관할 밖이 아니라 설정을 빠뜨린 것이다.


def test_규칙_폴더를_찾는다(tmp_path):
    assert not has_standards_root(tmp_path)

    (tmp_path / "대한물산" / "templates").mkdir(parents=True)
    assert not has_standards_root(tmp_path), "templates 만으로는 규칙 폴더가 아니다"

    (tmp_path / "대한물산" / "rules").mkdir()
    assert has_standards_root(tmp_path)


def test_규칙_폴더가_한_단계_아래_있어도_찾는다(tmp_path):
    """`acme/templates` 와 `acme/rules` 처럼 한 단계 들어간 곳도 찾아야 한다."""
    (tmp_path / "acme" / "templates").mkdir(parents=True)
    (tmp_path / "acme" / "rules").mkdir()
    assert has_standards_root(tmp_path)


def test_규칙_폴더가_없으면_통과로_답하지_않는다(tmp_path, monkeypatch, capsys):
    """Project Repository 가 `/scaffold` 를 잊으면 여기로 온다.

    규칙 폴더가 없으면 바뀐 문서가 있어도 검사할 방법이 없다. 그것은 관할 밖이 아니라
    설정이 어긋난 것이다.
    """
    문서 = tmp_path / "docs" / "회의록" / "20260922_주간정기.md"
    문서.parent.mkdir(parents=True)
    문서.write_text("# 회의록\n", encoding="utf-8")
    (tmp_path / "changed.txt").write_text("docs/회의록/20260922_주간정기.md\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main_entry(["changed.txt"]) == EXIT_CONFIG_ERROR
    out = capsys.readouterr().out
    assert "templates" in out and "rules" in out


def test_규칙_폴더가_있으면_정상적으로_검사한다(tmp_path, monkeypatch, capsys):
    """규칙 폴더가 있으면 이 가드에 걸리지 않고 평소대로 검사한다."""
    (tmp_path / "대한물산" / "templates").mkdir(parents=True)
    (tmp_path / "대한물산" / "rules").mkdir()
    (tmp_path / "README.md").write_text("# 안내\n", encoding="utf-8")
    (tmp_path / "changed.txt").write_text("README.md\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    code = main_entry(["changed.txt"])
    report = json.loads(capsys.readouterr().out)
    assert code == EXIT_PASS
    assert report["summary"]["out_of_scope"] == 1


def test_바뀐_것이_없으면_규칙_폴더가_없어도_통과다(tmp_path, monkeypatch, capsys):
    """바뀐 것이 없다는 것은 정당한 통과이지 설정 오류가 아니다."""
    (tmp_path / "changed.txt").write_text("\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    assert '"scoped": 0' in capsys.readouterr().out
