"""재사용 워크플로 `pr-queue.yml`(#370)과 scaffold caller 의 구조 검사."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-queue.yml"
CALLER = (
    ROOT / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows" / "pr-queue.yml"
)
PERMISSIONS = {"contents": "read", "pull-requests": "write", "issues": "write", "statuses": "write", "checks": "read", "actions": "read"}


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:  # YAML 1.1 에서 `on` 은 True 로 읽힌다.
        data["on"] = data.pop(True)
    return data


def test_재사용_워크플로의_입력과_Teams_secret():
    call = _load(WORKFLOW)["on"]["workflow_call"]
    assert call["inputs"]["engine-ref"]["default"] == "stable"
    assert call["secrets"]["TEAMS_PLUGIN_ALERT_WEBHOOK"]["required"] is False


def test_job_은_세_이벤트에서만_돌고_concurrency_는_저장소_하나_취소형이다():
    job = _load(WORKFLOW)["jobs"]["queue"]
    for event in ("pull_request", "pull_request_review", "push"):
        assert f"'{event}'" in job["if"]
    assert job["concurrency"] == {"group": "pr-queue-${{ github.repository }}", "cancel-in-progress": True}
    # risk-gate 처럼 job 에 permissions 를 적지 않아 부르는 쪽 권한을 그대로 받는다.
    assert "permissions" not in job


def test_엔진은_engine_ref_로_받아_scripts_진입점을_부른다():
    steps = _load(WORKFLOW)["jobs"]["queue"]["steps"]
    checkout = steps[0]
    assert checkout["with"]["repository"] == "jaeheeMin/blueward-harness"
    assert checkout["with"]["ref"] == "${{ inputs.engine-ref }}"
    run = next(s for s in steps if "run" in s)
    assert ".harness-engine/scripts/pr_queue_actions.py" in run["run"]
    assert run["env"]["TEAMS_PLUGIN_ALERT_WEBHOOK"] == "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"
    # 읽기 불능(2)과 쓰기 실패(1)는 job 실패다.
    assert run["run"].count("exit 1") == 2
    assert (ROOT / "scripts" / "pr_queue_actions.py").is_file()


def test_caller_는_이벤트와_권한과_stable_을_정한다():
    caller = _load(CALLER)
    on = caller["on"]
    # edited·converted_to_draft 는 Actions 분을 아끼려고 뺐다(#411). 본문 `먼저:` 를 고쳐도 다음 이벤트까지 낡는다.
    assert on["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review", "closed"]
    assert on["pull_request_review"]["types"] == ["submitted", "dismissed"]
    assert on["push"]["branches"] == ["main"]
    job = caller["jobs"]["pr-queue"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/pr-queue.yml@stable"
    assert job["permissions"] == PERMISSIONS
    assert job["secrets"] == {"TEAMS_PLUGIN_ALERT_WEBHOOK": "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"}
