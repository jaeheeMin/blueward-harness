"""재사용 워크플로 `main-checks.yml`(#419)의 구조 검사."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "main-checks.yml"
LEDGER = ROOT / ".github" / "workflows" / "ledger-complete.yml"
PR_CHECKS = ROOT / ".github" / "workflows" / "pr-checks.yml"
CHECKS = ["gitleaks", "doc-guard", "risk-gate", "ssot-approval"]
PERMISSIONS = {
    "contents": "read",
    "pull-requests": "read",
    "issues": "write",
    "statuses": "write",
    "checks": "read",
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
    # pr-queue 단계를 뺀 뒤로 쓰이지 않지만, 옛 caller 가 넘겨도 오류가 나지 않게 선언은 남긴다(#508).
    assert call["secrets"]["TEAMS_PLUGIN_ALERT_WEBHOOK"]["required"] is False
    assert call["inputs"]["ledger-complete"]["type"] == "boolean"
    assert call["inputs"]["ledger-complete"]["default"] is False  # 따로 부르는 ledger-complete.yml 과 이슈가 겹치지 않게


def test_job_은_하나이고_concurrency_도_permissions_도_없다():
    jobs = _load(WORKFLOW)["jobs"]
    assert list(jobs) == ["check"]
    job = jobs["check"]
    assert "permissions" not in job  # 부르는 쪽 권한을 그대로 받는다
    # 병합 뒤 감시는 취소되면 안 된다.
    assert "concurrency" not in job


def test_단계_순서():
    ids = [s["id"] for s in _steps() if "id" in s]
    order = ["changed", "gitleaks", "doc-guard", "doc-guard-issue", "risk-gate", "risk-gate-issue",
             "ssot-approval", "ssot-approval-issue", "ledger-complete", "ledger-complete-issue"]
    positions = [ids.index(i) for i in order]
    assert positions == sorted(positions)
    assert _steps()[-1]["name"] == "종합"


def test_저장소가_엔진보다_먼저이고_전체_이력을_받는다():
    steps = _steps()
    repo_checkout, engine_checkout = steps[0], steps[1]
    assert repo_checkout["with"] == {"fetch-depth": 0}
    assert engine_checkout["with"]["repository"] == "jaeheeMin/blueward-harness"
    assert engine_checkout["with"]["ref"] == "${{ inputs.engine-ref }}"
    assert engine_checkout["with"]["path"] == ".harness-engine"
    assert any("setup-uv" in s.get("uses", "") for s in steps)


@pytest.mark.parametrize("name", CHECKS)
def test_검사_단계는_continue_on_error_이고_pass_unknown_을_낸다(name):
    step = _step(name)
    assert step["continue-on-error"] is True
    assert "status=pass" in step["run"] and "status=unknown" in step["run"]


def test_gitleaks_는_push_범위를_본다():
    env = _step("gitleaks")["env"]
    assert env["EVENT_NAME"] == "${{ github.event_name }}"
    assert env["BASE_SHA"] == "${{ github.event.before }}"
    assert env["HEAD_SHA"] == "${{ github.sha }}"


def test_doc_guard_paths_는_단계_if_이고_pr_checks_와_같다():
    assert _step("doc-guard")["if"] == "steps.changed.outputs.has_doc_guard != 'false'"
    changed = _step("changed")
    assert '"unknown"' in changed["run"]  # 목록을 못 받으면 unknown 이라 건너뛰지 않는다
    assert "compare/$BEFORE_SHA...$AFTER_SHA" in changed["run"]
    paths = changed["env"]["DOC_GUARD_PATHS"].split()
    pr_checks = next(s for s in _load(PR_CHECKS)["jobs"]["check"]["steps"] if s.get("id") == "changed")
    assert paths == pr_checks["env"]["DOC_GUARD_PATHS"].split()


def test_doc_guard_는_이전_커밋과_비교하고_실패를_이슈로_알린다():
    run = _step("doc-guard")["run"]
    assert 'diff --name-only --diff-filter=d "$BEFORE_SHA" HEAD' in run
    issue = _step("doc-guard-issue")
    assert issue["continue-on-error"] is True
    assert "steps.doc-guard.outputs.status != 'pass'" in issue["if"]
    assert "refs/heads/main" in issue["if"]
    assert "main 의 doc-guard 검사 실패:" in issue["run"]


@pytest.mark.parametrize("name", CHECKS)
def test_각_검사_단계_바로_뒤에_옛_이름으로_main_커밋에_status_를_단다(name):
    status = next(s for s in _steps() if s.get("id") == f"{name}-status")
    assert status["continue-on-error"] is True
    assert status["env"]["SHA"] == "${{ github.sha }}"  # PR head 가 아니라 main 커밋
    assert status["env"]["RESULT"] == f"${{{{ steps.{name}.outputs.status }}}}"
    assert ".harness-engine/scripts/step_status.py" in status["run"]
    assert f"--context {name} " in status["run"]
    assert _index(f"{name}-status") == _index(name) + 1


def test_risk_gate_와_ssot_approval_은_merge_뒤_판정이고_이슈를_연다():
    assert "risk_gate.py" in _step("risk-gate")["run"] and "check-commit" in _step("risk-gate")["run"]
    assert "ssot_approval.py" in _step("ssot-approval")["run"] and "check-commit" in _step("ssot-approval")["run"]
    assert _step("risk-gate-issue")["if"] == "steps.risk-gate.outputs.exit-code == '1'"
    assert "steps.ssot-approval.outputs.exit-code != '0'" in _step("ssot-approval-issue")["if"]
    for step_id in ("risk-gate-issue", "ssot-approval-issue"):
        assert _step(step_id)["continue-on-error"] is True
    # 판정 불능(1 도 0 도 아닌 코드)은 unknown 이고 종합이 실패시킨다.
    assert "status=unknown" in _step("risk-gate")["run"] and "status=unknown" in _step("ssot-approval")["run"]


def test_pr_queue_단계는_없다_closed_pr_checks_가_맡는다():
    # #508: 같은 계산을 PR 이 닫힐 때 pr-checks 가 하고, 여기서는 권한 부족으로 매번 실패했다.
    assert not any(s.get("id") == "pr-queue" for s in _steps())
    assert "pr_queue_actions.py" not in WORKFLOW.read_text(encoding="utf-8").split("jobs:", 1)[1]
    assert any(s.get("id") == "pr-queue" for s in _load(PR_CHECKS)["jobs"]["check"]["steps"])


def test_ledger_complete_는_입력이_true_일_때만_돌고_종합이_판정한다():
    step = _step("ledger-complete")
    assert step["if"] == "inputs.ledger-complete"
    assert step["continue-on-error"] is True
    assert "status=pass" in step["run"] and "status=fail" in step["run"] and "status=unknown" in step["run"]
    assert _index("ledger-complete-issue") == _index("ledger-complete") + 1
    run = _steps()[-1]["run"]
    assert 'LEDGER_ENABLED" != "true"' in run  # 입력이 꺼져 있으면 건너뜀
    assert 'judge "ledger-complete"' in run


def test_종합은_항상_돌고_다섯_검사를_판정한다():
    final = _steps()[-1]
    assert final["if"] == "always()"
    run = final["run"]
    for name in CHECKS:
        assert f'judge "{name}"' in run
    assert "pr-queue" not in run and "OUTCOME_PRQ" not in run
    assert 'exit "$fail"' in run
    assert "::error title=$name 위반::" in run and "::error title=$name 검사 불능::" in run
    # 이슈를 열지 못한 것은 실패로 센다.
    assert "issue_failed" in run
    for label in ("통과", "위반", "검사 불능", "건너뜀(대상 아님)"):
        assert label in run


def test_caller_예시는_push_main_과_읽기_권한만_정한다():
    example = _caller_example()
    assert example["on"] == {"push": {"branches": ["main"]}}
    job = example["jobs"]["main-checks"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/main-checks.yml@stable"
    assert job["permissions"] == PERMISSIONS
    assert job["permissions"]["contents"] == "read"
    assert "write" not in {job["permissions"].get("contents"), job["permissions"].get("pull-requests")}
    assert job["secrets"] == {"TEAMS_PLUGIN_ALERT_WEBHOOK": "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"}
    assert job["with"] == {"ledger-complete": True}


def test_ledger_complete_도_쓰기_토큰이_없다():
    # 원장을 쓰지 않는 검사기라 읽기만 한다(#445). main-checks 와 별도 파일로 남아 있다.
    ledger = _load(LEDGER)
    assert ledger["jobs"]["complete"]["permissions"]["contents"] == "read"
    assert "gitleaks" not in LEDGER.read_text(encoding="utf-8").split("jobs:", 1)[1]


def test_doc_guard_직전_커밋을_못_구하거나_비교가_실패하면_전체_파일로_넘어가지_않고_검사_불능이다():
    # #518: BEFORE_SHA 가 비었거나 0 으로만 된 첫 푸시도, git diff 실패도 `ls-files` 대체 없이 검사 불능이다.
    run = _step("doc-guard")["run"]
    assert "ls-files" not in run
    assert '[ -z "${BEFORE_SHA//0/}" ]' in run
    assert 'diff --name-only --diff-filter=d "$BEFORE_SHA" HEAD > changed.txt 2> changed-err.txt' in run
    branch = run.split('if [ "$diff_ok" != true ]; then', 1)[1].split("elif", 1)[0]
    assert "status=unknown" in branch
    assert "git diff ${BEFORE_SHA" in branch
    assert "${err}" in branch
    assert "check_changed.py" not in branch
