"""재사용 워크플로 `pr-tamper-alert.yml`(#150)과 scaffold caller 의 구조 검사."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-tamper-alert.yml"
CALLER = (
    ROOT / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows"
    / "pr-tamper-alert.yml"
)


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 에서 `on` 은 True 로 읽힌다.
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_재사용_워크플로는_workflow_call_이고_Teams_secret_은_선택이다():
    wf = _load(WORKFLOW)
    call = wf["on"]["workflow_call"]
    assert call["secrets"]["TEAMS_PLUGIN_ALERT_WEBHOOK"]["required"] is False


def test_권한은_최소이고_PR_코드를_내려받지_않는다():
    wf = _load(WORKFLOW)
    assert wf["permissions"] == {"contents": "read", "issues": "write", "pull-requests": "read"}
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout" not in text


def test_알리는_이벤트는_push_와_리뷰_해제_둘뿐이다():
    wf = _load(WORKFLOW)
    cond = wf["jobs"]["alert"]["if"]
    assert "synchronize" in cond and "dismissed" in cond
    assert "closed" not in cond and "merged" not in cond


def test_caller_는_기존_caller_처럼_main_을_부른다():
    caller = _load(CALLER)
    assert caller["on"]["pull_request_target"]["types"] == ["synchronize"]
    assert caller["on"]["pull_request_review"]["types"] == ["dismissed"]
    job = caller["jobs"]["pr-tamper-alert"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/pr-tamper-alert.yml@stable"
    assert job["permissions"] == {"contents": "read", "issues": "write", "pull-requests": "read"}


def test_이슈_단계는_GH_REPO_를_명시한다():
    # checkout 이 없어 gh issue 가 저장소를 스스로 찾지 못한다.
    wf = _load(WORKFLOW)
    steps = {s["name"]: s for s in wf["jobs"]["alert"]["steps"]}
    assert steps["GitHub 이슈로 알리기"]["env"]["GH_REPO"] == "${{ github.repository }}"
    assert "uses" not in steps["GitHub 이슈로 알리기"]


# --- 판정 단계의 run 스크립트를 가짜 gh 로 실제로 돌린다 ------------------------

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH  # noqa: E402

_needs_bash = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 run 스크립트를 돌릴 수 없다")

_FAKE_GH = """#!/usr/bin/env bash
# gh api repos/<repo>/collaborators/<sender>/permission --jq .permission
[ "${FAKE_GH_FAIL:-}" = perm ] && exit 1
echo "${FAKE_GH_PERM-write}"
"""


def _decide(tmp_path: Path, **env: str) -> tuple[int, str]:
    wf = _load(WORKFLOW)
    step = next(s for s in wf["jobs"]["alert"]["steps"] if s["id"] == "decide")
    script = tmp_path / "decide.sh"
    script.write_text(step["run"], encoding="utf-8", newline="\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(_FAKE_GH, encoding="utf-8", newline="\n")
    gh.chmod(0o755)
    out = tmp_path / "output.txt"
    out.write_text("", encoding="utf-8")
    full = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_OUTPUT": out.as_posix(),
        "GITHUB_REPOSITORY": "o/r",
        "EVENT_NAME": "pull_request_target",
        "SENDER": "Other",
        "SENDER_TYPE": "User",
        "PR_AUTHOR": "me",
        **env,
    }
    done = subprocess.run([_BASH, str(script)], cwd=tmp_path, env=full, capture_output=True, timeout=120)
    return done.returncode, out.read_text(encoding="utf-8")


@_needs_bash
def test_판정_작성자_본인의_행동은_대소문자가_달라도_알리지_않는다(tmp_path):
    rc, out = _decide(tmp_path, SENDER="ME", PR_AUTHOR="me")
    assert rc == 0 and "notify=false" in out


@_needs_bash
def test_판정_봇의_행동은_알리지_않는다(tmp_path):
    rc, out = _decide(tmp_path, SENDER="github-actions[bot]", SENDER_TYPE="Bot", FAKE_GH_FAIL="perm")
    assert rc == 0 and "notify=false" in out


@_needs_bash
def test_판정_admin_의_행동은_알리지_않는다(tmp_path):
    rc, out = _decide(tmp_path, FAKE_GH_PERM="admin")
    assert rc == 0 and "notify=false" in out


@_needs_bash
def test_판정_admin_이_아닌_다른_계정의_행동은_알린다(tmp_path):
    for perm in ("write", "read", "none"):
        rc, out = _decide(tmp_path, FAKE_GH_PERM=perm)
        assert rc == 0 and "notify=true" in out, perm


@_needs_bash
def test_판정_권한_조회가_실패하면_job_이_실패한다(tmp_path):
    rc, out = _decide(tmp_path, FAKE_GH_FAIL="perm")
    assert rc != 0 and "notify" not in out


@_needs_bash
@pytest.mark.parametrize("missing", ["SENDER", "PR_AUTHOR"])
def test_판정_계정을_읽지_못하면_job_이_실패한다(tmp_path, missing):
    rc, out = _decide(tmp_path, **{missing: ""})
    assert rc != 0 and "notify" not in out
