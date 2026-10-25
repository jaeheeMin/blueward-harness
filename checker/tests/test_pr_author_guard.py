"""다른 계정이 만든 PR 을 바꾸지 못하게 하는 git 가드 훅 검사(#150) 테스트.

`pre-bash-git-guard.sh` 가 `gh pr merge|edit|close|reopen|comment|review|ready` 와
`DELIVER=1` 푸시에서 PR 작성자를 지금 gh 로그인 계정과 대소문자 무시로 비교하는지 본다.
진짜 gh 도 네트워크도 부르지 않는다. 가짜 gh(`_add_fake_gh`)가 환경 변수로 정한 답을 내고,
가짜 uvx 는 명령 분해만 진짜 `checker.merge_command` 로 보낸다.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import (
    _HAS_BASH,
    _HAS_JQ,
    REPO_ROOT,
    _add_fake_gh,
    _fake_uvx_prelude,
    _make_dispatch_uvx,
    _run_guard,
    _run_guard_with_fake_uvx,
)

pytestmark = [
    pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다"),
    pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git/gh 명령을 거부한다"),
    pytest.mark.skipif(shutil.which("base64") is None, reason="base64 가 없으면 가짜 uvx 를 만들 수 없다"),
]

_SSOT_OK = json.dumps({"touches_ssot": False, "approved": True, "reason": "SRS 변경 없음"})


@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fake-bin"
    d.mkdir()
    # merge 의 나머지 검사(SRS 승인 등)는 모두 통과하는 답을 낸다.
    b64 = base64.b64encode(_SSOT_OK.encode("utf-8")).decode("ascii")
    script = d / "uvx"
    script.write_text(
        _fake_uvx_prelude() + f"printf '%s' '{b64}' | base64 -d\nexit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    script.chmod(0o755)
    _add_fake_gh(d)
    return d


def _guard(command: str, bin_dir: Path, **env: str):
    full = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(REPO_ROOT),
        **env,
    }
    return _run_guard(command, env=full)


def _reason(out: dict | None) -> str:
    assert out is not None, "거부되어야 하는데 통과했다"
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    return out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("sub", ["comment", "edit", "close", "reopen", "review", "ready"])
def test_남의_PR_을_바꾸는_명령은_거부한다(bin_dir, sub):
    code, out = _guard(f"gh pr {sub} 12", bin_dir, FAKE_GH_AUTHORS="12=Other")
    assert code == 0
    reason = _reason(out)
    assert "Other" in reason and "me" in reason  # 작성자 X, 지금 계정 Y
    assert "다음:" in reason
    assert "읽기" in reason


def test_남의_PR_merge_는_거부한다(bin_dir):
    code, out = _guard("gh pr merge 12 --squash -R owner/repo", bin_dir, FAKE_GH_AUTHORS="12=Other")
    assert code == 0
    assert "Other" in _reason(out)


def test_내_PR_은_대소문자가_달라도_통과한다(bin_dir):
    # 로그인은 Me, 작성자는 ME — 같은 계정이다.
    code, out = _guard("gh pr comment 12 --body hi", bin_dir, FAKE_GH_LOGIN="Me", FAKE_GH_AUTHORS="12=ME")
    assert code == 0
    assert out is None


def test_내_PR_merge_는_기존_검사로_넘어가_통과한다(bin_dir):
    code, out = _guard("gh pr merge 12 -R owner/repo", bin_dir, FAKE_GH_AUTHORS="12=me")
    assert code == 0
    assert out is None


def test_인자_없는_gh_pr_comment_는_현재_브랜치_PR_로_판정한다(bin_dir, tmp_path):
    log = tmp_path / "gh.log"
    code, out = _guard(
        'gh pr comment --body "메모"', bin_dir, FAKE_GH_AUTHOR="Other", FAKE_GH_LOG=str(log)
    )
    assert code == 0
    assert "Other" in _reason(out)
    calls = log.read_text(encoding="utf-8").splitlines()
    # 번호 없이 현재 브랜치 PR 을 물었다(본문 "메모" 가 PR 지정으로 읽히지 않는다).
    assert any(c.startswith("pr view --json author") for c in calls)


def test_옵션_뒤의_PR_번호와_저장소를_함께_짝짓는다(bin_dir, tmp_path):
    log = tmp_path / "gh.log"
    code, out = _guard(
        'gh pr edit --title "새 제목" 7 -R acme/repo', bin_dir,
        FAKE_GH_AUTHORS="7=Other", FAKE_GH_LOG=str(log),
    )
    assert code == 0
    assert "Other" in _reason(out)
    assert "pr view 7 -R acme/repo --json author" in log.read_text(encoding="utf-8")


def test_묶인_명령은_조각마다_본다(bin_dir):
    code, out = _guard(
        "gh pr comment 1 --body a && gh pr close 2", bin_dir,
        FAKE_GH_LOGIN="Me", FAKE_GH_AUTHORS="1=me,2=Other",
    )
    assert code == 0
    assert "Other" in _reason(out)


def test_본문_안의_글자는_명령으로_보지_않는다(bin_dir):
    code, out = _guard('gh issue create --body "gh pr comment 12 를 하지 말 것"', bin_dir, FAKE_GH_AUTHORS="12=Other")
    assert code == 0
    assert out is None


@pytest.mark.parametrize("fail", ["login", "view"])
def test_gh_가_실패하면_검사_불능으로_거부한다(bin_dir, fail):
    code, out = _guard("gh pr comment 12 --body hi", bin_dir, FAKE_GH_FAIL=fail)
    assert code == 0
    reason = _reason(out)
    assert "검사 불능" in reason
    assert "다음:" in reason


@pytest.mark.parametrize("cmd", [
    "gh pr view 12", "gh pr diff 12", "gh pr checks 12", "gh pr list", "gh pr status",
    "gh pr checkout 12",
])
def test_읽기_명령은_작성자가_달라도_통과한다(bin_dir, cmd):
    code, out = _guard(cmd, bin_dir, FAKE_GH_AUTHORS="12=Other", FAKE_GH_FAIL="login")
    assert code == 0
    assert out is None


# --- DELIVER=1 푸시 -----------------------------------------------------------


def test_DELIVER_푸시가_남의_PR_브랜치면_거부한다(bin_dir):
    code, out = _guard(
        "DELIVER=1 git push -u origin feat/x", bin_dir, FAKE_GH_LIST="feat/x=Other"
    )
    assert code == 0
    reason = _reason(out)
    assert "Other" in reason and "feat/x" in reason and "다음:" in reason


@pytest.mark.parametrize(
    "command",
    [
        "DELIVER=1 git status && git push origin feat/x",
        "DELIVER=1 git status && (git push origin feat/x)",
        "DELIVER=1 git status; { git push origin feat/x; }",
    ],
)
def test_DELIVER_묶음의_푸시도_남의_PR_브랜치면_거부한다(bin_dir, command):
    code, out = _guard(command, bin_dir, FAKE_GH_LIST="feat/x=Other")
    assert code == 0
    reason = _reason(out)
    assert "Other" in reason and "feat/x" in reason


def test_DELIVER_푸시_refspec_도착_브랜치를_본다(bin_dir):
    code, out = _guard(
        "DELIVER=1 git push origin HEAD:refs/heads/feat/y", bin_dir, FAKE_GH_LIST="feat/y=Other"
    )
    assert code == 0
    assert "feat/y" in _reason(out)


def test_DELIVER_푸시_브랜치에_열린_PR_이_없으면_통과한다(bin_dir):
    code, out = _guard("DELIVER=1 git push -u origin feat/x", bin_dir, FAKE_GH_LIST="other/branch=Other")
    assert code == 0
    assert out is None


def test_DELIVER_푸시가_내_PR_브랜치면_통과한다(bin_dir):
    code, out = _guard("DELIVER=1 git push origin feat/x", bin_dir, FAKE_GH_LIST="feat/x=ME")
    assert code == 0
    assert out is None


def test_DELIVER_푸시_현재_브랜치_PR_도_본다(bin_dir, tmp_path):
    # cwd 를 임시 저장소로 두고 그 현재 브랜치(HEAD)를 푸시 대상으로 삼는다.
    import subprocess

    repo = tmp_path / "work"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feat/z"], cwd=repo, check=True)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(REPO_ROOT),
        "FAKE_GH_LIST": "feat/z=Other",
    }
    code, out = _run_guard("DELIVER=1 git push -u origin HEAD", env=env, cwd=str(repo))
    assert code == 0
    assert "feat/z" in _reason(out)


def test_DELIVER_푸시에서_gh_조회가_실패하면_검사_불능으로_거부한다(bin_dir):
    code, out = _guard("DELIVER=1 git push origin feat/x", bin_dir, FAKE_GH_FAIL="list")
    assert code == 0
    assert "검사 불능" in _reason(out)


def test_DELIVER_푸시에서_로그인_계정을_못_얻으면_검사_불능으로_거부한다(bin_dir):
    code, out = _guard("DELIVER=1 git push origin feat/x", bin_dir, FAKE_GH_FAIL="login")
    assert code == 0
    assert "검사 불능" in _reason(out)


def test_DELIVER_푸시_all_은_대상을_확정할_수_없어_거부한다(bin_dir):
    code, out = _guard("DELIVER=1 git push --all origin", bin_dir)
    assert code == 0
    assert "검사 불능" in _reason(out)


# --- admin 예외 -----------------------------------------------------------------


def test_admin_이면_남의_PR_comment_를_통과시킨다(bin_dir):
    code, out = _guard("gh pr comment 12 --body hi", bin_dir, FAKE_GH_AUTHORS="12=Other", FAKE_GH_PERM="ADMIN")
    assert code == 0
    assert out is None


def test_admin_이면_남의_PR_merge_를_기존_검사로_넘긴다(bin_dir):
    code, out = _guard("gh pr merge 12 -R owner/repo", bin_dir, FAKE_GH_AUTHORS="12=Other", FAKE_GH_PERM="ADMIN")
    assert code == 0
    assert out is None


def test_admin_이_아니면_거부_문구에_admin_안내가_들어간다(bin_dir):
    code, out = _guard("gh pr comment 12 --body hi", bin_dir, FAKE_GH_AUTHORS="12=Other", FAKE_GH_PERM="MAINTAIN")
    assert code == 0
    assert "admin 권한이 있는 계정만 남의 PR 을 고칠 수 있" in _reason(out)


def test_권한_조회가_실패하면_검사_불능으로_거부한다(bin_dir):
    code, out = _guard("gh pr comment 12 --body hi", bin_dir, FAKE_GH_AUTHORS="12=Other", FAKE_GH_FAIL="perm")
    assert code == 0
    assert "검사 불능" in _reason(out)


def test_내_PR_이면_권한을_조회하지_않는다(bin_dir, tmp_path):
    log = tmp_path / "gh.log"
    code, out = _guard("gh pr comment 12 --body hi", bin_dir, FAKE_GH_AUTHORS="12=me", FAKE_GH_LOG=str(log),
                       FAKE_GH_FAIL="perm")
    assert code == 0
    assert out is None
    assert "viewerPermission" not in log.read_text(encoding="utf-8")


def test_admin_이면_남의_PR_브랜치로_DELIVER_푸시를_통과시킨다(bin_dir):
    code, out = _guard("DELIVER=1 git push origin feat/x", bin_dir, FAKE_GH_LIST="feat/x=Other", FAKE_GH_PERM="ADMIN")
    assert code == 0
    assert out is None


# --- 검토 지적 재현(옵션 해석, 앞쪽 -R·GH_REPO, 문구 정리, 묶인 푸시) -------------


@pytest.mark.parametrize("cmd", [
    "gh pr merge -m 12",            # -m 은 값 없는 --merge. 뒤의 12 가 PR 번호다
    "gh pr merge -sd 12",           # 묶인 짧은 옵션
    "gh pr review -c 12 -b 메모",    # -c 는 값 없는 --comment
    "gh pr review 12 --approve",
])
def test_값_없는_짧은_옵션_뒤의_PR_번호도_짝짓는다(bin_dir, cmd, tmp_path):
    log = tmp_path / "gh.log"
    code, out = _guard(cmd, bin_dir, FAKE_GH_AUTHORS="12=Other", FAKE_GH_LOG=str(log))
    assert code == 0
    assert "Other" in _reason(out)
    assert "pr view 12 " in log.read_text(encoding="utf-8")  # 현재 브랜치 PR 로 새지 않는다


@pytest.mark.parametrize("cmd,expect_repo", [
    ("gh -R o/r pr comment 5 --body x", "-R o/r"),
    ("GH_REPO=o/r gh pr merge 5", "-R o/r"),
    ("gh pr -R o/r comment 5 --body x", "-R o/r"),
])
def test_앞쪽_R_와_GH_REPO_를_저장소로_읽는다(bin_dir, cmd, expect_repo, tmp_path):
    log = tmp_path / "gh.log"
    code, out = _guard(cmd, bin_dir, FAKE_GH_AUTHORS="5=Other", FAKE_GH_LOG=str(log))
    assert code == 0
    assert "Other" in _reason(out)
    assert f"pr view 5 {expect_repo} --json author" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("cmd", [
    "gh --weird pr comment 5",          # pr 앞의 해석 못 하는 옵션
    "gh pr comment --weird 5",          # 해석 못 하는 옵션 뒤의 위치 인자
    "gh pr merge --squash=1 5",
])
def test_해석_못_하는_옵션이_PR_지정을_모호하게_하면_검사_불능이다(bin_dir, cmd):
    code, out = _guard(cmd, bin_dir, FAKE_GH_AUTHORS="5=me")
    assert code == 0
    reason = _reason(out)
    assert "검사 불능" in reason and "다음:" in reason


def test_가짜_gh_는_등록_안_된_PR_번호에_실패해_검사_불능이_된다(bin_dir):
    code, out = _guard("gh pr comment 999 --body x", bin_dir, FAKE_GH_AUTHORS="12=me")
    assert code == 0
    assert "검사 불능" in _reason(out)


def test_푸시_거부_문구의_브랜치_이름에서_위험한_글자를_지운다(bin_dir):
    # $ 가 든 브랜치 이름. 문구에 그대로 들어가면 JSON 이나 셸 치환이 깨질 수 있다.
    code, out = _guard("DELIVER=1 git push origin feat/a$b", bin_dir, FAKE_GH_LIST="feat/a$b=Other")
    assert code == 0
    reason = _reason(out)
    assert "$" not in reason and "feat/ab" in reason


def test_푸시_검사불능_문구에서도_브랜치_이름을_정리한다(bin_dir):
    code, out = _guard("DELIVER=1 git push origin feat/a$b", bin_dir, FAKE_GH_FAIL="list")
    assert code == 0
    reason = _reason(out)
    assert "$" not in reason and "검사 불능" in reason


def test_DELIVER_뒤_다른_git_명령과_묶어도_push_조각을_검사한다(bin_dir):
    code, out = _guard(
        "DELIVER=1 git status && git push origin feat/x", bin_dir, FAKE_GH_LIST="feat/x=Other"
    )
    assert code == 0
    assert "feat/x" in _reason(out)


def test_DELIVER_선언이_있어도_push_조각이_없으면_gh_를_부르지_않는다(bin_dir, tmp_path):
    log = tmp_path / "gh.log"
    code, out = _guard("DELIVER=1 git status", bin_dir, FAKE_GH_LOG=str(log), FAKE_GH_FAIL="login")
    assert code == 0
    assert out is None
    assert not log.exists()


def test_푸시에서_권한_조회가_실패하면_검사_불능으로_거부한다(bin_dir):
    code, out = _guard("DELIVER=1 git push origin feat/x", bin_dir, FAKE_GH_LIST="feat/x=Other", FAKE_GH_FAIL="perm")
    assert code == 0
    assert "검사 불능" in _reason(out)


# --- 자동 병합 예약(--auto)과 --admin (#437) ------------------------------------


def _failing_checks_gh(bin_dir: Path) -> None:
    _add_fake_gh(bin_dir, checks={12: [{"name": "pr-checks / check", "state": "FAILURE", "bucket": "fail", "link": "https://example.com/r"}]})


def test_auto_병합은_검사가_실패_중이어도_예약을_허용한다(bin_dir):
    _failing_checks_gh(bin_dir)
    code, out = _guard("gh pr merge 12 --auto --squash", bin_dir, FAKE_GH_AUTHORS="12=me")
    assert code == 0
    assert out is None


def test_auto_없는_병합은_검사가_실패_중이면_여전히_거부한다(bin_dir):
    _failing_checks_gh(bin_dir)
    code, out = _guard("gh pr merge 12 --squash", bin_dir, FAKE_GH_AUTHORS="12=me")
    assert code == 0
    assert "검사가 실패" in _reason(out)


def test_auto_라도_남의_PR_은_거부한다(bin_dir):
    code, out = _guard("gh pr merge 12 --auto --squash", bin_dir, FAKE_GH_AUTHORS="12=Other")
    assert code == 0
    assert "Other" in _reason(out)


def test_auto_는_앞_PR_대기_판정을_건너뛴다(bin_dir):
    prq = base64.b64encode(json.dumps({"status": "ok", "pr": 12, "before": [{"number": 7, "title": "앞", "reasons": []}]}).encode()).decode()
    code, out = _guard("gh pr merge 12 --auto --squash", bin_dir, FAKE_GH_AUTHORS="12=me", FAKE_PRQ_B64=prq, FAKE_PRQ_RC="1")
    assert code == 0
    assert out is None
    code, out = _guard("gh pr merge 12 --squash", bin_dir, FAKE_GH_AUTHORS="12=me", FAKE_PRQ_B64=prq, FAKE_PRQ_RC="1")
    assert "먼저 병합해야 하는" in _reason(out)


@pytest.mark.parametrize("cmd", ["gh pr merge 12 --admin --squash", "gh pr merge 12 --auto --admin"])
def test_admin_병합은_내_PR_이어도_거부한다(bin_dir, cmd):
    code, out = _guard(cmd, bin_dir, FAKE_GH_AUTHORS="12=me")
    assert code == 0
    assert "--admin" in _reason(out)


def test_본문_안의_auto_글자는_예약으로_읽지_않는다(bin_dir):
    _failing_checks_gh(bin_dir)
    code, out = _guard('gh pr merge 12 --squash --body "--auto"', bin_dir, FAKE_GH_AUTHORS="12=me")
    assert "검사가 실패" in _reason(out)


def test_auto_라도_사람_병합_경로를_바꾼_PR_은_거부한다(tmp_path):
    human = json.dumps({"requires_human": True, "paths": ["plugins/harness/x.md"], "pr": 123, "repo": "own/repo"})
    d = _make_dispatch_uvx(tmp_path, human, 1)
    code, out = _run_guard_with_fake_uvx("gh pr merge 123 --auto --squash", d, {"FAKE_GH_AUTHORS": "123=me"})
    assert code == 0
    reason = _reason(out)
    assert "자동 병합을 걸 수 없어요" in reason and "plugins/harness/x.md" in reason


def test_auto_이고_사람_병합_경로가_아니면_허용한다(tmp_path):
    human = json.dumps({"requires_human": False, "paths": [], "pr": 123, "repo": "own/repo"})
    d = _make_dispatch_uvx(tmp_path, human, 0)
    code, out = _run_guard_with_fake_uvx("gh pr merge 123 --auto --squash", d, {"FAKE_GH_AUTHORS": "123=me"})
    assert code == 0
    assert out is None
