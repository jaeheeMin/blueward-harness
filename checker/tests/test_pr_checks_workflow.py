"""재사용 워크플로 `pr-checks.yml`(#418)의 구조 검사."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"
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
    assert call["secrets"]["TEAMS_MERGE_WEBHOOK_URL"]["required"] is False  # #508: 없으면 병합 알림만 건너뛴다


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
    order = ["changed", "gitleaks", "doc-guard", "ssot-approval", "ledger-ready", "risk-gate", "pr-queue"]
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


def test_doc_guard_경로는_pr_checks_안의_단일_정의이고_main_checks_와_같다():
    # #420: scaffold doc-guard caller 가 없어져 이 env 가 유일한 정의다. main-checks 가 같은 목록을 써야 한다.
    env = _step("changed")["env"]["DOC_GUARD_PATHS"].split()
    assert env and len(env) == len(set(env))
    main_steps = _load(ROOT / ".github" / "workflows" / "main-checks.yml")["jobs"]["check"]["steps"]
    main_env = next(s for s in main_steps if s.get("id") == "changed")["env"]["DOC_GUARD_PATHS"].split()
    assert env == main_env
    assert _step("changed")["env"]["SSOT_PATHS"].split() == ["docs/ssot/**"]


EARLY = ["gitleaks", "doc-guard", "ssot-approval"]


def test_앞_검사_셋의_status_는_한_단계에서_옛_이름으로_달고_risk_gate_보다_앞이다():
    step = _step("early-status")
    assert step["continue-on-error"] is True
    assert step["if"] == "github.event.action != 'closed'"
    assert step["env"]["SHA"] == "${{ github.event.pull_request.head.sha }}"
    run = step["run"]
    for name, key in (("gitleaks", "GITLEAKS"), ("doc-guard", "DOC_GUARD"), ("ssot-approval", "SSOT")):
        assert f"post_status {name} " in run
        assert step["env"][f"OUTCOME_{key}"] == f"${{{{ steps.{name}.outcome }}}}"
        assert step["env"][f"RESULT_{key}"] == f"${{{{ steps.{name}.outputs.status }}}}"
    # uv 를 띄우지 않고 표준 라이브러리만 쓰는 같은 스크립트를 부른다(#515).
    assert "uv run" not in run
    assert "python3 .harness-engine/scripts/step_status.py" in run and step["env"]["PYTHONPATH"] == ".harness-engine"
    assert '--sha "$SHA"' in run and "--target-url" in run
    # 건너뛴 검사의 status 는 달지 않고, 못 단 이름은 failed 출력에 남기며 마지막에 실패 코드로 끝낸다.
    assert '[ "$outcome" = "skipped" ] && return 0' in run
    assert 'echo "failed=$failed" >> "$GITHUB_OUTPUT"' in run and run.rstrip().endswith('[ -z "$failed" ]')
    for dropped in ("gitleaks-status", "doc-guard-status", "ssot-approval-status"):
        assert not any(s.get("id") == dropped for s in _steps())
    # risk-gate 가 앞 검사 status 를 API 로 읽으므로 그 앞에 와야 한다. 판정 단계들은 모두 이 단계보다 앞이다.
    assert _index("ssot-approval") < _index("ledger-ready") < _index("early-status") < _index("risk-gate")


def test_risk_gate_status_는_risk_gate_바로_뒤에서_옛_이름으로_단다():
    steps = _steps()
    i = _index("risk-gate")
    status = steps[i + 1]
    assert status["id"] == "risk-gate-status"
    assert status["continue-on-error"] is True
    assert "github.event.action != 'closed'" in status["if"]
    assert status["env"]["SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert status["env"]["RESULT"] == "${{ steps.risk-gate.outputs.status }}"
    run = status["run"]
    assert "python3 .harness-engine/scripts/step_status.py" in run and "uv run" not in run
    assert "--context risk-gate " in run and '--sha "$SHA"' in run and "--target-url" in run


def test_코멘트_단계는_옛_마커를_그대로_쓴다():
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in ("<!-- doc-guard -->", "<!-- ssot-approval -->", "<!-- risk-gate -->", "<!-- ledger-ready -->"):
        assert marker in text
    # 앞 검사 셋과 ledger-ready 의 코멘트는 한 단계다. doc-guard 코멘트만 comment 입력으로 끈다.
    step = _step("early-comments")
    assert step["continue-on-error"] is True
    assert "inputs.comment" in step["if"] and "inputs.comment" in step["env"]["RUN_DOC_GUARD"]
    assert "github.event.action != 'closed'" in step["if"]
    for dropped in ("doc-guard-comment", "ssot-approval-comment", "ledger-ready-comment"):
        assert not any(s.get("id") == dropped for s in _steps())
    script = step["with"]["script"]
    # 하나가 실패해도 나머지를 계속하고 이름을 출력으로 남기며, 지울 코멘트(body null)와 요약 쓰기는 예전과 같다.
    assert "core.setOutput('failed'" in script and "core.setFailed(" in script
    assert "deleteComment" in script and "core.summary.addRaw" in script
    assert _step("risk-gate-comment")["continue-on-error"] is True


def test_종합은_앞_검사_status_코멘트_실패를_이름별로_경고한다():
    final = _steps()[-1]
    run = final["run"]
    env = final["env"]
    assert env["OUTCOME_ST_EARLY"] == "${{ steps.early-status.outcome }}"
    assert env["FAILED_ST_EARLY"] == "${{ steps.early-status.outputs.failed }}"
    assert env["OUTCOME_COMMENTS_EARLY"] == "${{ steps.early-comments.outcome }}"
    assert env["FAILED_COMMENTS_EARLY"] == "${{ steps.early-comments.outputs.failed }}"
    for title in ("gitleaks status 못 담", "doc-guard status 못 담", "ssot-approval status 못 담",
                  "doc-guard 코멘트 실패", "ssot-approval 코멘트 실패", "ledger-ready 코멘트 실패"):
        line = next(ln for ln in run.splitlines() if f'warn "{title}"' in ln)
        assert "early_failed" in line
    # 이름을 못 남기고 단계만 실패했으면 셋 다 경고한다(원인을 모르므로 조용히 넘기지 않는다).
    assert '[ -z "$names" ] && return 0' in run


def test_risk_gate_는_wait_checks_로_판정한다():
    step = _step("risk-gate")
    assert "check-pr" in step["run"] and '--wait-checks "$WAIT_CHECKS"' in step["run"]
    assert step["env"]["WAIT_CHECKS"] == "${{ inputs.wait-checks }}"


def test_ledger_ready_는_원장_완료를_판정하고_종합에_들어간다():
    step = _step("ledger-ready")
    assert step["continue-on-error"] is True
    assert "github.event.action != 'closed'" in step["if"]
    assert ".harness-engine/scripts/ledger_ready.py" in step["run"] and "check-pr" in step["run"]
    for token in ("status=pass", "status=fail", "status=unknown"):
        assert token in step["run"]
    assert (ROOT / "scripts" / "ledger_ready.py").is_file()
    # 코멘트는 마커로 갱신하고, 새 commit status 는 달지 않는다(종합이 곧 필수 검사 pr-checks / check 다).
    assert _step("early-comments")["continue-on-error"] is True  # ledger-ready 코멘트도 이 단계에서 갱신한다(#515)
    assert "<!-- ledger-ready -->" in WORKFLOW.read_text(encoding="utf-8")
    assert not any(s.get("id") == "ledger-ready-status" for s in _steps())
    run = _steps()[-1]["run"]
    assert 'judge "ledger-ready" "$S_LEDGER" "$R_LEDGER" "$closed"' in run
    env = _steps()[-1]["env"]
    assert env["S_LEDGER"] == "${{ steps.ledger-ready.outputs.status }}"
    # 읽기 권한만 쓴다. caller 권한(PERMISSIONS)은 늘리지 않는다.
    assert _caller_example()["jobs"]["pr-checks"]["permissions"] == PERMISSIONS


def test_pr_queue_는_closed_에서도_돌고_실패해도_계속한다():
    step = _step("pr-queue")
    assert step["continue-on-error"] is True
    assert "closed" not in step["if"]
    assert "!cancelled()" in step["if"]
    assert step["env"]["TEAMS_PLUGIN_ALERT_WEBHOOK"] == "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"
    assert ".harness-engine/scripts/pr_queue_actions.py" in step["run"]


def test_병합_Teams_알림은_기본_브랜치로_병합된_closed_에서만_secret_이_있을_때_보낸다():
    step = _step("merge-notify")
    cond = step["if"]
    for part in ("github.event.action == 'closed'", "github.event.pull_request.merged == true",
                 "github.event.pull_request.base.ref == github.event.repository.default_branch"):
        assert part in cond
    assert step["continue-on-error"] is True  # 이미 병합된 PR 의 필수 검사를 붉게 만들지 않는다
    assert step["env"]["TEAMS_MERGE_WEBHOOK_URL"] == "${{ secrets.TEAMS_MERGE_WEBHOOK_URL }}"
    assert "secrets." not in cond  # secret 은 step if 에서 못 쓴다 — 안에서 가린다
    run = step["run"]
    assert '[ -z "${TEAMS_MERGE_WEBHOOK_URL:-}" ]' in run and "::notice" in run and "result=skipped" in run
    assert "application/vnd.microsoft.card.adaptive" in run and "PR이 main에 병합되었습니다" in run
    assert "curl -sS -f" in run
    assert _index("pr-queue") < _index("merge-notify") < len(_steps()) - 1


def test_병합_알림_실패는_종합이_판정에는_넣지_않고_경고로_남긴다():
    run = _steps()[-1]["run"]
    assert "OUTCOME_MERGE_NOTIFY" in run
    assert 'judge "merge-notify"' not in run
    line = next(ln for ln in run.splitlines() if "OUTCOME_MERGE_NOTIFY" in ln and "warn" in ln)
    assert "병합 Teams 알림 실패" in line


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
    assert job["secrets"]["TEAMS_PLUGIN_ALERT_WEBHOOK"] == "${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}"
    assert job["secrets"]["TEAMS_MERGE_WEBHOOK_URL"] == "${{ secrets.TEAMS_WEBHOOK_URL }}"


def test_doc_guard_바뀐_파일은_갈라진_지점부터_세_점으로_구하고_얕게_받지_않는다():
    # #504: 병합 ref(HEAD) 와 최신 기준 브랜치의 두 점 차이에는 기준 브랜치의 새 변경이 섞인다.
    # `--depth=1` 로 받으면 전체 이력 위에 얕은 경계가 생겨 세 점 비교가 갈라진 지점을 못 찾는다.
    run = _step("doc-guard")["run"]
    assert 'diff --name-only --diff-filter=d "$base"...HEAD' in run
    assert '"$base" HEAD' not in run
    fetch_lines = [line for line in run.splitlines() if line.strip().startswith("git fetch")]
    assert fetch_lines and all("--depth" not in line for line in fetch_lines)
