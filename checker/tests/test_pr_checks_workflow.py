"""재사용 워크플로 `pr-checks.yml`(#418)의 구조 검사."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"
DOC_GUARD_CALLER = (
    ROOT / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows" / "doc-guard.yml"
)
CHECKS = ["gitleaks", "doc-guard", "ssot-approval", "risk-gate"]
PERMISSIONS = {
    "contents": "read",
    "pull-requests": "write",
    "issues": "write",
    "statuses": "write",
    "checks": "read",
    "actions": "read",
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
    if True in data:  # YAML 1.1 에서 `on` 은 True 로 읽힌다.
        data["on"] = data.pop(True)
    return data


def test_입력과_Teams_secret():
    call = _load(WORKFLOW)["on"]["workflow_call"]
    assert call["inputs"]["engine-ref"]["default"] == "stable"
    assert call["inputs"]["wait-checks"]["default"] == 600
    assert call["inputs"]["comment"]["default"] is True
    assert call["secrets"]["TEAMS_PLUGIN_ALERT_WEBHOOK"]["required"] is False


def test_job_은_하나이고_permissions_를_적지_않고_PR_단위_취소형이다():
    jobs = _load(WORKFLOW)["jobs"]
    assert list(jobs) == ["check"]
    job = jobs["check"]
    assert "permissions" not in job  # 부르는 쪽 권한을 그대로 받는다
    assert job["concurrency"] == {
        "group": "pr-checks-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


def test_단계_순서():
    ids = [s["id"] for s in _steps() if "id" in s]
    order = ["changed", "gitleaks", "doc-guard", "ssot-approval", "risk-gate", "pr-queue"]
    positions = [ids.index(i) for i in order]
    assert positions == sorted(positions)
    # 종합은 맨 마지막이다.
    assert _steps()[-1]["name"] == "종합"
    assert _index("pr-queue") < len(_steps()) - 1


def test_엔진은_engine_ref_로_받고_저장소_checkout_이_엔진보다_먼저다():
    steps = _steps()
    repo_checkout, engine_checkout = steps[0], steps[1]
    assert repo_checkout["with"] == {"fetch-depth": 0}
    assert repo_checkout["if"] == "github.event.action != 'closed'"
    assert engine_checkout["with"]["repository"] == "jaeheeMin/blueward-harness"
    assert engine_checkout["with"]["ref"] == "${{ inputs.engine-ref }}"
    assert engine_checkout["with"]["path"] == ".harness-engine"
    assert any("setup-uv" in s.get("uses", "") for s in steps)
    assert (ROOT / "scripts" / "step_status.py").is_file()


@pytest.mark.parametrize("name", CHECKS)
def test_검사_단계는_continue_on_error_이고_closed_에서_안_돈다(name):
    step = _step(name)
    assert step["continue-on-error"] is True
    assert "github.event.action != 'closed'" in step["if"]
    # 결과는 pass|fail|unknown 으로 낸다.
    assert "status=pass" in step["run"]
    assert "status=unknown" in step["run"]


def test_doc_guard_와_ssot_는_바뀐_파일_목록이_아니라고_할_때만_건너뛴다():
    assert _step("doc-guard")["if"].endswith("steps.changed.outputs.has_doc_guard != 'false'")
    assert _step("ssot-approval")["if"].endswith("steps.changed.outputs.has_ssot != 'false'")
    # 목록을 못 받으면 unknown 이고 위 조건(!= 'false')이 참이라 건너뛰지 않고 돈다.
    assert '"unknown"' in _step("changed")["run"]


def test_doc_guard_경로는_scaffold_caller_의_paths_와_같다():
    env = _step("changed")["env"]["DOC_GUARD_PATHS"].split()
    caller = _load(DOC_GUARD_CALLER)["on"]["pull_request"]["paths"]
    assert env == caller
    assert _step("changed")["env"]["SSOT_PATHS"].split() == ["docs/ssot/**"]


@pytest.mark.parametrize("name", CHECKS)
def test_각_검사_단계_바로_뒤에_옛_이름으로_status_를_단다(name):
    steps = _steps()
    i = _index(name)
    status = steps[i + 1]
    assert status["id"] == f"{name}-status"
    assert status["continue-on-error"] is True
    assert "github.event.action != 'closed'" in status["if"]
    assert status["env"]["SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert status["env"]["RESULT"] == f"${{{{ steps.{name}.outputs.status }}}}"
    run = status["run"]
    assert ".harness-engine/scripts/step_status.py" in run
    assert f"--context {name} " in run
    assert '--sha "$SHA"' in run and "--target-url" in run


def test_코멘트_단계는_옛_마커를_그대로_쓴다():
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in ("<!-- doc-guard -->", "<!-- ssot-approval -->", "<!-- risk-gate -->"):
        assert marker in text
    # doc-guard 코멘트만 comment 입력으로 끈다.
    assert "inputs.comment" in _step("doc-guard-comment")["if"]
    for step_id in ("doc-guard-comment", "ssot-approval-comment", "risk-gate-comment"):
        assert _step(step_id)["continue-on-error"] is True


def test_risk_gate_는_wait_checks_로_판정한다():
    step = _step("risk-gate")
    assert "check-pr" in step["run"] and '--wait-checks "$WAIT_CHECKS"' in step["run"]
    assert step["env"]["WAIT_CHECKS"] == "${{ inputs.wait-checks }}"


def test_pr_queue_는_closed_에서도_돌고_실패해도_계속한다():
    step = _step("pr-queue")
    assert step["continue-on-error"] is True
    assert "closed" not in step["if"]
    assert "!cancelled()" in step["if"]
    assert step["env"]["TEAMS_PLUGIN_ALERT_WEBHOOK"] == "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"
    assert ".harness-engine/scripts/pr_queue_actions.py" in step["run"]


def test_종합은_항상_돌고_네_검사만_판정하며_pr_queue_는_경고뿐이다():
    final = _steps()[-1]
    assert final["if"] == "always()"
    run = final["run"]
    for name in CHECKS:
        assert f'judge "{name}"' in run
    assert 'judge "pr-queue"' not in run
    # 종료코드는 fail 변수만 따르고, pr-queue 는 ::warning 줄에만 나온다.
    assert 'exit "$fail"' in run
    assert "::error title=$name 위반::" in run and "::error title=$name 검사 불능::" in run
    for line in run.splitlines():
        if "pr-queue" in line:
            assert "warn " in line or line.lstrip().startswith(("#", "printf"))  # 판정(judge)에는 안 나온다
    # 결과 표의 세 갈래 + 건너뜀.
    for label in ("통과", "위반", "검사 불능", "건너뜀(대상 아님)"):
        assert label in run


def test_caller_예시는_이벤트와_권한과_stable_을_정한다():
    example = _caller_example()
    assert example["on"]["pull_request"]["types"] == [
        "opened", "synchronize", "reopened", "ready_for_review", "closed",
    ]
    job = example["jobs"]["pr-checks"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/pr-checks.yml@stable"
    assert job["permissions"] == PERMISSIONS
    assert job["permissions"]["statuses"] == "write"
    assert job["secrets"] == {"TEAMS_PLUGIN_ALERT_WEBHOOK": "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"}
