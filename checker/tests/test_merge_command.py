"""merge 가드용 명령 분해기(checker.merge_command) 테스트(#101)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from checker.merge_command import MergeCommandError, find_merges, find_pr_mutations


def _m(repo=None, prref=None):
    return {"repo": repo, "prref": prref}


def test_세미콜론으로_묶인_두_merge_는_각자의_저장소를_가진다():
    cmd = "gh pr merge 100 --squash; gh pr merge 51 --squash -R jaeheeMin/public-cloud"
    assert find_merges(cmd) == [_m(None, "100"), _m("jaeheeMin/public-cloud", "51")]


def test_인자_안의_글자는_merge_가_아니다():
    assert find_merges('gh issue create --title t --body "본문 gh pr merge 5 끝"') == []


@pytest.mark.parametrize("opener", ["<<EOF", "<<'EOF'", '<<"EOF"', "<<-EOF"])
def test_heredoc_본문_안의_글자는_merge_가_아니다(opener):
    cmd = f"gh issue create --body-file - {opener}\n본문\ngh pr merge 5\nEOF\n"
    assert find_merges(cmd) == []


def test_heredoc_닫는_구분자_뒤의_명령은_본다():
    cmd = "cat <<EOF\ngh pr merge 5\nEOF\ngh pr merge 7 -R o/r"
    assert find_merges(cmd) == [_m("o/r", "7")]


def test_대시_heredoc_은_탭_들여쓴_구분자를_인정한다():
    cmd = "cat <<-EOF\n\tgh pr merge 5\n\tEOF\ngh pr merge 7"
    assert find_merges(cmd) == [_m(None, "7")]


def test_닫히지_않은_heredoc_은_끝까지_본문이다():
    assert find_merges("cat <<EOF\ngh pr merge 5\n") == []


def test_따옴표_안의_heredoc_표시는_본문을_시작하지_않는다():
    assert find_merges('echo "<<EOF"\ngh pr merge 5') == [_m(None, "5")]


def test_파워셸_here_string_본문은_무시한다():
    cmd = "gh issue create --body @'\ngh pr merge 5\n'@\ngh pr merge 9"
    assert find_merges(cmd) == [_m(None, "9")]
    cmd2 = 'gh issue create --body @"\ngh pr merge 5\n"@'
    assert find_merges(cmd2) == []


@pytest.mark.parametrize("sep", ["&&", "||", "|", "&", "\n", ";", " ; "])
def test_구분자마다_명령을_나눈다(sep):
    cmd = f"gh pr merge 1 -R a/b{sep}gh pr merge 2"
    assert find_merges(cmd) == [_m("a/b", "1"), _m(None, "2")]


def test_환경변수_대입이_앞에_있어도_본다():
    assert find_merges("FOO=1 BAR=x gh pr merge 5") == [_m(None, "5")]


def test_윈도우_경로의_gh_exe_도_본다():
    assert find_merges("C:\\tools\\gh.exe pr merge 5") == [_m(None, "5")]
    assert find_merges("C:/tools/GH.EXE pr merge 5") == [_m(None, "5")]


def test_URL_은_prref_로_그대로_남긴다():
    url = "https://github.com/o/r/pull/7"
    assert find_merges(f"gh pr merge {url}") == [_m(None, url)]


@pytest.mark.parametrize(
    "flags",
    ["-R o/r", "-R=o/r", "--repo o/r", "--repo=o/r"],
)
def test_저장소_지정_형태들(flags):
    assert find_merges(f"gh pr merge {flags} 5 --squash") == [_m("o/r", "5")]
    assert find_merges(f"gh pr merge 5 {flags}") == [_m("o/r", "5")]


def test_옵션의_값은_prref_로_읽지_않는다_번호_없이_현재_브랜치():
    assert find_merges("gh pr merge --squash --delete-branch") == [_m(None, None)]


def test_gh_바로_뒤의_옵션은_건너뛰고_pr_merge_를_찾는다():
    assert find_merges("gh --no-color pr merge 5") == [_m(None, "5")]


@pytest.mark.parametrize("cmd", ["gh pr view 5", "git merge x", "gh issue merge 5", "echo pr merge", "gh pr"])
def test_merge_가_아닌_명령은_비어_있다(cmd):
    assert find_merges(cmd) == []


def test_명령_치환_안의_merge_도_잡는다():
    assert find_merges("echo $(gh pr merge 5)") == [_m(None, "5")]
    assert find_merges("echo `gh pr merge 5`") == [_m(None, "5")]
    assert find_merges("(gh pr merge 5)") == [_m(None, "5")]


def test_리다이렉션이_붙어도_본다():
    assert find_merges("gh pr merge 5 > out.txt 2>&1") == [_m(None, "5")]


def test_따옴표가_짝이_안_맞으면_오류다():
    with pytest.raises(MergeCommandError):
        find_merges('gh pr merge 5 "abc')


def test_CLI_는_JSON_을_낸다():
    done = subprocess.run(
        [sys.executable, "-m", "checker.merge_command"],
        input="gh pr merge 5 -R o/r".encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout) == {"merges": [_m("o/r", "5")]}


# --- PR 을 바꾸는 하위 명령(#150) ---------------------------------------------


def _mut(sub, repo=None, prref=None):
    return {"sub": sub, "repo": repo, "prref": prref}


@pytest.mark.parametrize("cmd,expected", [
    ("gh pr merge -m 12", [_mut("merge", None, "12")]),              # -m 은 값 없는 --merge
    ("gh pr merge -sd 12", [_mut("merge", None, "12")]),
    ("gh pr merge --squash --subject 제목 12", [_mut("merge", None, "12")]),
    ("gh pr review -c 5 -b hi", [_mut("review", None, "5")]),        # -c 는 값 없는 --comment
    ("gh pr close -c 안녕 7", [_mut("close", None, "7")]),           # close -c 는 값을 받는다
    ("gh pr edit -m 마일스톤 7 -R a/b", [_mut("edit", "a/b", "7")]),  # edit -m 은 값을 받는다
    ("gh pr comment --body hi", [_mut("comment", None, None)]),
    ("gh -R o/r pr comment 5", [_mut("comment", "o/r", "5")]),
    ("gh pr -R o/r comment 5", [_mut("comment", "o/r", "5")]),
    ("GH_REPO=o/r gh pr merge 5", [_mut("merge", "o/r", "5")]),
    ("GH_REPO=o/r gh pr merge 5 -R x/y", [_mut("merge", "x/y", "5")]),
    ("gh pr ready 3 --undo", [_mut("ready", None, "3")]),
    ("gh pr view 3; gh pr reopen 4", [_mut("reopen", None, "4")]),
    ("gh pr merge -bbody 9", [_mut("merge", None, "9")]),             # 값이 붙은 짧은 옵션
])
def test_pr_변경_명령의_대상을_하위_명령별_옵션_표로_짝짓는다(cmd, expected):
    assert find_pr_mutations(cmd) == expected


@pytest.mark.parametrize("cmd", [
    "gh --weird pr comment 5",
    "gh pr comment --weird 5",
    "gh pr merge --squash=1 5",
])
def test_해석_못_하는_옵션이_PR_지정을_모호하게_하면_오류다(cmd):
    with pytest.raises(MergeCommandError):
        find_pr_mutations(cmd)


def test_대상이_아닌_gh_명령은_해석_못_하는_옵션이_있어도_오류가_아니다():
    assert find_pr_mutations("gh --weird pr view 5") == []
    assert find_pr_mutations("gh issue comment --weird 5") == []


def test_CLI_mutations_는_mutations_키로_답한다():
    done = subprocess.run(
        [sys.executable, "-m", "checker.merge_command", "--mutations"],
        input="gh pr comment 5 -R o/r".encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout) == {"mutations": [_mut("comment", "o/r", "5")]}


def test_CLI_는_나누지_못하면_종료코드_2와_error_를_낸다():
    done = subprocess.run(
        [sys.executable, "-m", "checker.merge_command"],
        input='gh pr merge 5 "abc'.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    assert done.returncode == 2
    assert "error" in json.loads(done.stdout)


def test_auto_와_admin_옵션은_있을_때만_표시한다():
    assert find_merges("gh pr merge 5 --auto --squash") == [{**_m(None, "5"), "auto": True}]
    assert find_merges("gh pr merge 5 --admin") == [{**_m(None, "5"), "admin": True}]
    assert find_merges('gh pr merge 5 --body "--auto"') == [_m(None, "5")]
