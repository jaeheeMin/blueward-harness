"""#136 — plugins/harness/ 변경 PR 의 plugin.json version 올림 검사."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from checker.plugin_version import PLUGIN_JSON, judge, main, parse_version

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = "plugins/harness/skills/start/SKILL.md"


@pytest.mark.parametrize(
    "text, expected",
    [("0.10.17", (0, 10, 17)), ("1.0", (1, 0)), (" 2.3.4 ", (2, 3, 4))],
)
def test_version_을_정수_튜플로_읽는다(text, expected):
    assert parse_version(text) == expected


def test_version_은_문자열이_아니라_정수로_비교한다():
    assert parse_version("0.10.9") < parse_version("0.10.17")


@pytest.mark.parametrize("bad", ["", "abc", "1.x.0", "1..2", "v1.0.0", "1.0.0-rc1", None, 3])
def test_version_형식이_틀리면_예외다(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


def test_plugin_이_안_바뀌었으면_통과한다():
    v = judge(["checker/engine.py", "README.md"], "0.10.17", "0.10.17")
    assert v.code == 0


def test_변경_파일이_없어도_통과한다():
    assert judge([], "0.10.17", "0.10.17").code == 0


def test_plugin_을_바꾸고_version_을_올렸으면_통과한다():
    assert judge([SKILL, PLUGIN_JSON], "0.10.17", "0.10.18").code == 0


def test_숫자_자리가_늘어도_올린_것으로_본다():
    assert judge([SKILL], "0.9.9", "0.10.0").code == 0


def test_plugin_을_바꾸고_version_이_같으면_실패한다():
    v = judge([SKILL], "0.10.17", "0.10.17")
    assert v.code == 1
    assert "다음:" in v.message and "version" in v.message


def test_plugin_을_바꾸고_version_을_내렸으면_실패한다():
    assert judge([SKILL], "0.10.17", "0.10.9").code == 1


def test_plugin_json_만_바뀌고_version_이_올랐으면_통과한다():
    assert judge([PLUGIN_JSON], "0.10.17", "0.11.0").code == 0


def test_plugin_json_만_바뀌고_version_이_같으면_실패한다():
    assert judge([PLUGIN_JSON], "0.10.17", "0.10.17").code == 1


@pytest.mark.parametrize("bad", ["", "latest", "1.a"])
def test_version_형식이_틀리면_통과가_아니라_판정_불가다(bad):
    v = judge([SKILL], "0.10.17", bad)
    assert v.code == 2
    assert "다음:" in v.message


def test_형식이_틀려도_plugin_이_안_바뀌었으면_따지지_않는다():
    assert judge(["README.md"], "0.10.17", "latest").code == 0


# --- git 을 실제로 쓰는 진입점 ------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def _plugin_json(version: str) -> str:
    return json.dumps({"name": "harness", "version": version})


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """main 에 version 0.1.0 인 plugin.json 이 있고, feat 브랜치로 옮겨 간 저장소."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _write(tmp_path, PLUGIN_JSON, _plugin_json("0.1.0"))
    _write(tmp_path, SKILL, "원본\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")


def test_진입점_plugin_을_바꾸고_version_을_안_올리면_1(repo, capsys):
    _write(repo, SKILL, "바뀜\n")
    _commit(repo)
    assert main(["--base", "main"]) == 1
    assert "다음:" in capsys.readouterr().err


def test_진입점_plugin_을_바꾸고_version_을_올리면_0(repo):
    _write(repo, SKILL, "바뀜\n")
    _write(repo, PLUGIN_JSON, _plugin_json("0.1.1"))
    _commit(repo)
    assert main(["--base", "main"]) == 0


def test_진입점_plugin_이_안_바뀌면_0(repo):
    _write(repo, "README.md", "x\n")
    _commit(repo)
    assert main(["--base", "main"]) == 0


def test_진입점_base_를_못_읽으면_통과가_아니라_2(repo, capsys):
    _write(repo, SKILL, "바뀜\n")
    _commit(repo)
    assert main(["--base", "없는-ref"]) == 2
    assert "검사 불능" in capsys.readouterr().err


def test_진입점_plugin_json_이_깨졌으면_2(repo):
    _write(repo, SKILL, "바뀜\n")
    _write(repo, PLUGIN_JSON, "{ 깨짐")
    _commit(repo)
    assert main(["--base", "main"]) == 2


def test_스크립트가_모듈_진입점을_부른다(repo):
    _write(repo, SKILL, "바뀜\n")
    _commit(repo)
    done = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_plugin_version.py"), "--base", "main"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert done.returncode == 1
