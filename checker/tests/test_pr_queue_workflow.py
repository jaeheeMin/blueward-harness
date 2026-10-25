"""이 저장소 자신의 `pr-queue-self.yml`(#383)의 구조 검사.

옛 재사용 워크플로 `pr-queue.yml` 은 #452 에서 지웠고, 그 job 을 `pr-queue-self.yml` 안으로 옮겼다.
Project Repository 의 pr-queue 단계는 test_pr_checks_workflow·test_pr_review_workflow·test_main_checks_workflow 가 본다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-queue-self.yml"


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:  # YAML 1.1 에서 `on` 은 True 로 읽힌다.
        data["on"] = data.pop(True)
    return data


def test_세_이벤트에서_돌고_재사용_호출_없이_직접_돈다():
    wf = _load(WORKFLOW)
    assert set(wf["on"]) == {"pull_request", "pull_request_review", "push"}
    assert wf["on"]["push"] == {"branches": ["main"]}
    job = wf["jobs"]["pr-queue"]
    assert "uses" not in job
    assert not (ROOT / ".github" / "workflows" / "pr-queue.yml").exists()


def test_check_이름은_옛_재사용_호출과_같은_pr_queue_슬래시_queue_이다():
    # 엔진(risk_gate·pr_queue)이 이 이름으로 순서 표시 check 를 알아보고 검사 실패에서 뺀다.
    assert _load(WORKFLOW)["jobs"]["pr-queue"]["name"] == "pr-queue / queue"


def test_concurrency_는_저장소_하나_취소형이고_권한을_job_에_명시한다():
    job = _load(WORKFLOW)["jobs"]["pr-queue"]
    assert job["concurrency"] == {"group": "pr-queue-${{ github.repository }}", "cancel-in-progress": True}
    assert job["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "issues": "write",
        "statuses": "write",
        "checks": "read",
        "actions": "read",
    }


def test_엔진은_stable_로_받아_scripts_진입점을_부른다():
    steps = _load(WORKFLOW)["jobs"]["pr-queue"]["steps"]
    checkout = steps[0]
    assert checkout["with"]["repository"] == "jaeheeMin/blueward-harness"
    assert checkout["with"]["ref"] == "stable"
    run = next(s for s in steps if "run" in s)
    assert ".harness-engine/scripts/pr_queue_actions.py" in run["run"]
    assert run["env"]["TEAMS_PLUGIN_ALERT_WEBHOOK"] == "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"
    # 읽기 불능(2)과 쓰기 실패(1)는 job 실패다.
    assert run["run"].count("exit 1") == 2
    assert (ROOT / "scripts" / "pr_queue_actions.py").is_file()
