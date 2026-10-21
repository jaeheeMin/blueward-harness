"""재사용 워크플로 `pr-review.yml`(#419)의 구조 검사."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review.yml"
CHECKS = ["ssot-approval", "risk-gate"]
PERMISSIONS = {
    "contents": "read",
    "pull-requests": "write",
    "issues": "write",
    "statuses": "write",
    "checks": "read",
    "actions": "write",
}


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:  # YAML 1.1 에서 `on` 은 True 로 읽힌다.
        data["on"] = data.pop(True)
    return data


def _steps() -> list[dict]:
    return _load(WORKFLOW)["jobs"]["check"]["steps"]


def _step(step_id: str) -> dict:
    return next(s for s in _steps() if s.get("id") == step_id)


def _index(step_id: str) -> int:
    return next(i for i, s in enumerate(_steps()) if s.get("id") == step_id)


def _caller_example() -> dict:
    """머리 주석의 '부르는 쪽 예' 블록을 YAML 로 읽는다."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# 부르는 쪽 예"))
    block = []
    for line in lines[start + 1 :]:
        if line.startswith("#   "):
            block.append(line[4:])
        elif line.strip() == "#" and not block:
            continue
        else:
            break
    data = yaml.safe_load("\n".join(block))
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_입력과_Teams_secret():
    call = _load(WORKFLOW)["on"]["workflow_call"]
    assert call["inputs"]["engine-ref"]["default"] == "stable"
    assert call["inputs"]["wait-checks"]["default"] == 600
    assert call["secrets"]["TEAMS_PLUGIN_ALERT_WEBHOOK"]["required"] is False


def test_job_은_하나이고_permissions_를_적지_않고_PR_단위_취소형이다():
    jobs = _load(WORKFLOW)["jobs"]
    assert list(jobs) == ["check"]
    job = jobs["check"]
    assert "permissions" not in job
    # 그룹 이름이 pr-checks 의 그룹(`pr-checks-<번호>`)과 달라야 rerun-stale 이 현재 실행을 취소하지 않는다.
    assert job["concurrency"] == {
        "group": "pr-review-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }
    assert not job["concurrency"]["group"].startswith("pr-checks")


def test_단계_순서():
    ids = [s["id"] for s in _steps() if "id" in s]
    order = ["changed", "ssot-approval", "risk-gate", "rerun-stale", "pr-queue"]
    positions = [ids.index(i) for i in order]
    assert positions == sorted(positions)
    assert _steps()[-1]["name"] == "종합"


def test_엔진은_engine_ref_로_받고_저장소는_받지_않는다():
    steps = _steps()
    engine_checkout = steps[0]
    assert engine_checkout["with"]["repository"] == "jaeheeMin/blueward-harness"
    assert engine_checkout["with"]["ref"] == "${{ inputs.engine-ref }}"
    assert engine_checkout["with"]["path"] == ".harness-engine"
    assert any("setup-uv" in s.get("uses", "") for s in steps)
    # 판정은 API 만 쓴다. 저장소 checkout 은 엔진 하나뿐이다.
    assert sum("actions/checkout" in s.get("uses", "") for s in steps) == 1


@pytest.mark.parametrize("name", CHECKS)
def test_검사_단계는_continue_on_error_이고_pass_unknown_을_낸다(name):
    step = _step(name)
    assert step["continue-on-error"] is True
    assert "status=pass" in step["run"] and "status=unknown" in step["run"] and "status=fail" in step["run"]


def test_ssot_approval_은_docs_ssot_를_안_바꾼_PR_에서만_건너뛴다():
    assert _step("ssot-approval")["if"] == "steps.changed.outputs.has_ssot != 'false'"
    changed = _step("changed")
    assert changed["env"]["SSOT_PATHS"].split() == ["docs/ssot/**"]
    assert '"unknown"' in changed["run"]  # 목록을 못 받으면 unknown 이라 건너뛰지 않는다


@pytest.mark.parametrize("name", CHECKS)
def test_각_검사_단계_바로_뒤에_옛_이름으로_status_를_단다(name):
    status = _steps()[_index(name) + 1]
    assert status["id"] == f"{name}-status"
    assert status["continue-on-error"] is True
    assert status["env"]["SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert status["env"]["RESULT"] == f"${{{{ steps.{name}.outputs.status }}}}"
    assert ".harness-engine/scripts/step_status.py" in status["run"]
    assert f"--context {name} " in status["run"]


def test_코멘트_단계는_옛_마커를_그대로_쓴다():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "<!-- ssot-approval -->" in text and "<!-- risk-gate -->" in text
    for step_id in ("ssot-approval-comment", "risk-gate-comment"):
        assert _step(step_id)["continue-on-error"] is True


def test_risk_gate_는_wait_checks_로_판정한다():
    step = _step("risk-gate")
    assert "check-pr" in step["run"] and '--wait-checks "$WAIT_CHECKS"' in step["run"]
    assert step["env"]["WAIT_CHECKS"] == "${{ inputs.wait-checks }}"


def test_rerun_stale_은_두_판정이_성공일_때만_돌고_pr_checks_실행을_대상으로_한다():
    step = _step("rerun-stale")
    cond = step["if"]
    assert "steps.risk-gate.outputs.status == 'pass'" in cond
    assert "steps.ssot-approval.outputs.status == 'pass'" in cond
    # ssot-approval 이 대상 아니라 건너뛴 PR 은 성공으로 센다.
    assert "steps.changed.outputs.has_ssot == 'false'" in cond
    assert "always()" not in cond and "failure()" not in cond
    assert step["continue-on-error"] is True
    assert step["env"]["TARGET_WORKFLOW_NAME"] == "pr-checks"
    assert step["env"]["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    run = step["run"]
    # 같은 PR head 의 pull_request 실행 중 이름이 pr-checks 인 실패·취소만 고른다.
    assert "head_sha=$PR_HEAD_SHA&event=pull_request" in run
    assert '.name == \\"$TARGET_WORKFLOW_NAME\\"' in run
    assert 'conclusion == \\"failure\\"' in run and 'conclusion == \\"cancelled\\"' in run
    assert 'ep="rerun-failed-jobs"' in run and 'ep="rerun"' in run
    # 어떤 경우에도 성공으로 끝나고 권한이 없으면 경고만 낸다.
    assert "actions: write" in run and "::warning" in run
    assert run.rstrip().endswith("exit 0")


def test_rerun_stale_은_risk_gate_코멘트_뒤_pr_queue_앞에_있다():
    assert _index("risk-gate-comment") < _index("rerun-stale") < _index("pr-queue")


def test_pr_queue_는_항상_돌고_실패해도_계속한다():
    step = _step("pr-queue")
    assert step["continue-on-error"] is True
    assert "!cancelled()" in step["if"]
    assert step["env"]["TEAMS_PLUGIN_ALERT_WEBHOOK"] == "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"
    assert ".harness-engine/scripts/pr_queue_actions.py" in step["run"]


def test_종합은_항상_돌고_두_검사만_판정하며_pr_queue_와_rerun_은_경고뿐이다():
    final = _steps()[-1]
    assert final["if"] == "always()"
    run = final["run"]
    for name in CHECKS:
        assert f'judge "{name}"' in run
    assert 'judge "pr-queue"' not in run and 'judge "rerun-stale"' not in run
    assert 'exit "$fail"' in run
    assert "::error title=$name 위반::" in run and "::error title=$name 검사 불능::" in run
    for label in ("통과", "위반", "검사 불능", "건너뜀(대상 아님)"):
        assert label in run
    for line in run.splitlines():
        if "pr-queue" in line or "rerun-stale" in line:
            assert "warn " in line or line.lstrip().startswith(("#", "printf"))


def test_caller_예시는_리뷰_이벤트와_권한과_stable_을_정한다():
    example = _caller_example()
    assert example["on"] == {"pull_request_review": {"types": ["submitted", "dismissed"]}}
    job = example["jobs"]["pr-review"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/pr-review.yml@stable"
    assert job["permissions"] == PERMISSIONS
    assert job["permissions"]["actions"] == "write"  # rerun 용
    assert job["secrets"] == {"TEAMS_PLUGIN_ALERT_WEBHOOK": "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"}
