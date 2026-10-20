"""#389 — 뒤에서 만든 PR 표를 첫 프롬프트에 끼우는 훅(pr_table_notice.py) 테스트."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from checker.tests.test_plugin_layout import PLUGIN_ROOT

_spec = importlib.util.spec_from_file_location("pr_table_notice", PLUGIN_ROOT / "hooks" / "pr_table_notice.py")
pn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pn)

SID = "sess-1"


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "project"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def _file(repo, text, sid=SID, tmp=False):
    path = repo / ".git" / f"harness-pr-table.{sid}{'.tmp' if tmp else ''}"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _go(repo, sid=SID):
    return pn.run({"session_id": sid, "cwd": str(repo)})


def _context(out):
    data = json.loads(out)["hookSpecificOutput"]
    assert data["hookEventName"] == "UserPromptSubmit"
    return data["additionalContext"]


def test_no_file_gives_no_output(repo):
    assert _go(repo) is None


def test_tmp_only_gives_no_output_and_is_kept(repo):
    tmp = _file(repo, "rc=0\n표", tmp=True)
    assert _go(repo) is None
    assert tmp.exists()


def test_rc0_with_body_shows_table_once_and_deletes_file(repo):
    path = _file(repo, "rc=0\no/r 내 PR 1개 상태와 병합 순서\n| 1 | #5 제목 |\n")
    context = _context(_go(repo))
    assert "o/r 내 PR 1개 상태와 병합 순서" in context and "#5 제목" in context
    assert "자세한 상태와 다음 할 일은 /harness:prs 로 봅니다." in context
    assert not path.exists()
    assert _go(repo) is None  # 한 번만


def test_rc0_with_empty_body_is_silent_and_deletes_file(repo):
    path = _file(repo, "rc=0\n")
    assert _go(repo) is None
    assert not path.exists()


def test_rc2_shows_engine_first_line_with_retry(repo):
    path = _file(repo, "rc=2\nPR 상태 확인 불능 — 네트워크 실패\n")
    context = _context(_go(repo))
    assert "PR 상태 확인 불능 — 네트워크 실패 다음: /harness:prs 로 다시 확인하십시오." in context
    assert not path.exists()


def test_rc124_is_cannot_check_not_pass(repo):
    path = _file(repo, "rc=124\n")
    context = _context(_go(repo))
    assert "PR 상태 확인 불능(종료코드 124) - /harness:prs 로 다시 확인하십시오." in context
    assert "문제없" not in context
    assert not path.exists()


def test_other_rc_uses_first_line_of_output(repo):
    _file(repo, "rc=1\nTraceback boom\nmore\n")
    assert "PR 상태 확인 불능(Traceback boom)" in _context(_go(repo))


def test_unparsable_file_is_cannot_check(repo):
    path = _file(repo, "엉뚱한 내용\n")
    assert "PR 상태 확인 불능(결과 파일을 읽지 못함)" in _context(_go(repo))
    assert not path.exists()


def test_unreadable_file_is_cannot_check_and_deletion_is_attempted(repo, monkeypatch):
    path = _file(repo, "rc=0\n표\n")

    def boom(self, *args, **kwargs):
        raise OSError("읽을 수 없음")

    monkeypatch.setattr(type(path), "read_text", boom)
    context = _context(_go(repo))
    assert "PR 상태 확인 불능(결과 파일을 읽지 못함) - /harness:prs 로 다시 확인하십시오." in context
    assert not path.exists()


def test_output_is_emitted_before_the_file_is_deleted(repo):
    path = _file(repo, "rc=0\n표\n")
    seen = []
    pn.run({"session_id": SID, "cwd": str(repo)}, emit=lambda text: seen.append(path.exists()))
    assert seen == [True]
    assert not path.exists()


def test_other_session_file_is_never_read(repo):
    other = _file(repo, "rc=0\n남의 표\n", sid="sess-2")
    assert _go(repo, sid="sess-1") is None
    assert other.exists() and other.read_text(encoding="utf-8") == "rc=0\n남의 표\n"


def test_session_id_cannot_escape_the_git_dir(repo, tmp_path):
    outside = tmp_path / "harness-pr-table.x"
    outside.write_text("rc=0\n밖의 표\n", encoding="utf-8")
    assert pn.run({"session_id": "../../harness-pr-table.x", "cwd": str(repo)}) is None
    assert outside.exists()


def test_missing_session_id_or_cwd_or_not_git_is_silent(repo, tmp_path):
    _file(repo, "rc=0\n표\n")
    assert pn.run({"cwd": str(repo)}) is None
    assert pn.run({"session_id": SID}) is None
    plain = tmp_path / "plain"
    plain.mkdir()
    assert pn.run({"session_id": SID, "cwd": str(plain)}) is None


def test_main_exits_0_and_prints_json_even_with_bad_input(repo):
    script = str(PLUGIN_ROOT / "hooks" / "pr_table_notice.py")
    _file(repo, "rc=0\n표 한 줄\n")
    done = subprocess.run([sys.executable, script], input=json.dumps({"session_id": SID, "cwd": str(repo)}),
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0
    assert "표 한 줄" in _context(done.stdout)
    bad = subprocess.run([sys.executable, script], input="not json", capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode == 0 and bad.stdout == ""
