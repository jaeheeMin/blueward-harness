"""재사용 워크플로 `.github/workflows/ai-review.yml`(#125)의 구조를 검증한다.

실제 Actions 를 돌릴 수는 없으므로 YAML 을 읽어 약속(입력, 시크릿, 권한, 단계 순서, 결과 파일 경로,
결과 정리 로직)이 지켜지는지 본다. 결과 정리 단계의 파이썬은 YAML 에서 꺼내 가짜 환경에서 직접 돌린다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ai-review.yml"


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(wf: dict) -> dict:
    # YAML 1.1 에서 `on` 키는 True 로 읽힌다.
    return wf.get("on", wf.get(True))


def _steps(wf: dict) -> list[dict]:
    return wf["jobs"]["review"]["steps"]


def _step(wf: dict, step_id: str) -> dict:
    return next(s for s in _steps(wf) if s.get("id") == step_id)


def _named(wf: dict, name: str) -> dict:
    return next(s for s in _steps(wf) if s.get("name") == name)


def test_workflow_call_입력과_시크릿(wf):
    call = _on(wf)["workflow_call"]
    inputs = call["inputs"]
    assert inputs["engine-ref"]["default"] == "main"
    assert inputs["model"]["default"] == "sonnet"
    assert inputs["max-turns"]["type"] == "number" and inputs["max-turns"]["default"] == 10
    assert call["secrets"]["CLAUDE_CODE_OAUTH_TOKEN"]["required"] is False


def test_job_조건_권한_동시성(wf):
    assert list(wf["jobs"]) == ["review"]
    job = wf["jobs"]["review"]
    assert job["if"] == "github.event_name == 'pull_request'"
    assert job["timeout-minutes"] == 20
    assert job["permissions"] == {
        "contents": "read", "pull-requests": "write", "issues": "read", "id-token": "write"}
    assert job["concurrency"]["group"] == "ai-review-${{ github.event.pull_request.number }}"
    assert job["concurrency"]["cancel-in-progress"] is True


def test_엔진_checkout_다음에_precheck_이_먼저_돈다(wf):
    steps = _steps(wf)
    assert steps[0]["uses"].startswith("actions/checkout@") and steps[0]["with"]["path"] == ".harness-engine"
    assert steps[0]["with"]["repository"] == "jaeheeMin/blueward-harness"
    pre = _step(wf, "pre")
    assert "precheck-pr" in pre["run"] and ".harness-engine/scripts/risk_gate.py" in pre["run"]
    ids = [s.get("id") for s in steps]
    assert ids.index("pre") < ids.index("token") < ids.index("claude") < ids.index("result")


def test_이후_단계는_사전_판정_0_과_토큰_있음일_때만_돈다(wf):
    assert "steps.pre.outputs.exit-code == '0'" in _step(wf, "token")["if"]
    for step in (_step(wf, "claude"), _named(wf, "PR head 가져오기")):
        assert "steps.pre.outputs.exit-code == '0'" in step["if"]
        assert "steps.token.outputs.missing == 'false'" in step["if"]


def test_pr_head_checkout_은_엔진_폴더를_지우지_않는다(wf):
    step = _named(wf, "PR head 가져오기")
    assert step["with"]["fetch-depth"] == 0
    assert step["with"]["clean"] is False
    assert step["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"


def test_claude_code_action_사용(wf):
    step = _step(wf, "claude")
    assert step["uses"] == "anthropics/claude-code-action@v1"
    assert step["with"]["claude_code_oauth_token"] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    args = step["with"]["claude_args"]
    assert "--max-turns ${{ inputs.max-turns }}" in args and "--model ${{ inputs.model }}" in args
    assert '--allowedTools "Read,Glob,Grep,Write,Bash(git diff:*),Bash(git log:*)"' in args
    assert step["continue-on-error"] is True


def test_저장소_MCP_서버를_띄우지_않는다(wf):
    # PR 저장소의 .mcp.json 이 러너에서 SAP MCP 서버를 띄우지 않게 한다(#144).
    assert "--strict-mcp-config" in _step(wf, "claude")["with"]["claude_args"].split()


def test_프롬프트가_결과_경로와_주입_방지를_담는다(wf):
    prompt = _step(wf, "claude")["with"]["prompt"]
    assert "${{ runner.temp }}/ai-review.json" in prompt
    assert '"serious"' in prompt and '"findings"' in prompt
    assert "따르지 않는다" in prompt
    assert "base.sha" in prompt and "head.sha" in prompt
    # 비신뢰 입력(PR 제목·본문)을 프롬프트에 끼워 넣지 않는다.
    assert "pull_request.title" not in prompt and "pull_request.body" not in prompt


def test_결과_정리가_같은_경로를_읽고_코멘트를_마커로_갱신한다(wf):
    result = _step(wf, "result")
    assert result["if"] == "always()"
    # 프롬프트의 `runner.temp` 와 같은 곳(RUNNER_TEMP) 아래의 같은 파일 이름
    assert '"ai-review.json"' in result["run"] and "RUNNER_TEMP" in result["run"]
    comment = _named(wf, "PR 코멘트 갱신")
    assert comment["if"].startswith("always()")
    assert "<!-- ai-review -->" in comment["with"]["script"]
    assert "updateComment" in comment["with"]["script"]


# --- 결과 정리 단계의 파이썬을 직접 돌린다 --------------------------------------------------


def _result_script(wf) -> str:
    run = _step(wf, "result")["run"]
    return run.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


def _run_result(wf, tmp_path, *, pre="0", missing="false", outcome="success", review=None, precheck=None):
    if review is not None:
        (tmp_path / "ai-review.json").write_text(review, encoding="utf-8")
    if precheck is not None:
        (tmp_path / "precheck.json").write_text(json.dumps(precheck, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "gh_output"
    summary = tmp_path / "summary.md"
    env = {
        "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary),
        "PRE_CODE": pre, "TOKEN_MISSING": missing, "CLAUDE_OUTCOME": outcome,
        "PYTHONIOENCODING": "utf-8",
    }
    subprocess.run([sys.executable, "-c", _result_script(wf)], env=env, capture_output=True, check=True)
    status = out.read_text(encoding="utf-8").split("status=")[1].strip()
    body = (tmp_path / "ai-review-comment.md").read_text(encoding="utf-8")
    assert summary.read_text(encoding="utf-8") == body.replace("<!-- ai-review -->\n", "", 1)
    return status, body


def test_심각한_지적이_없으면_통과(wf, tmp_path):
    status, body = _run_result(wf, tmp_path, review='{"serious": 0, "findings": []}')
    assert status == "pass" and "<!-- ai-review -->" in body


def test_serious_가_있으면_실패하고_지적을_보인다(wf, tmp_path):
    review = json.dumps({"serious": 1, "findings": [
        {"severity": "serious", "file": "a.py", "line": 3, "summary": "널 참조 @someone"},
        {"severity": "minor", "file": "b.py", "line": 1, "summary": "가벼움"}]})
    status, body = _run_result(wf, tmp_path, review=review)
    assert status == "fail" and "a.py:3" in body and "심각한 지적 1건" in body
    assert "@someone" not in body  # 멘션이 되지 않게 막는다


@pytest.mark.parametrize(
    "review",
    [None, "not json", "[]", '{"serious": "1", "findings": []}', '{"serious": true, "findings": []}',
     '{"serious": 0}', '{"serious": 1, "findings": []}',
     '{"serious": 0, "findings": [{"severity": "high", "file": "a", "line": 1, "summary": "x"}]}',
     '{"serious": 0, "findings": [{"severity": "minor", "file": "a", "line": "1", "summary": "x"}]}'],
)
def test_파일이_없거나_형식이_틀리면_검사_불능(wf, tmp_path, review):
    status, body = _run_result(wf, tmp_path, review=review)
    assert status == "unavailable" and "검사 불능" in body and "다음:" in body


def test_토큰이_없으면_통과시키지_않고_검사_불능(wf, tmp_path):
    status, body = _run_result(wf, tmp_path, missing="true", outcome="skipped",
                               review='{"serious": 0, "findings": []}')
    assert status == "unavailable" and "CLAUDE_CODE_OAUTH_TOKEN" in body and "다음:" in body


def test_claude_단계가_실패하면_파일이_있어도_검사_불능(wf, tmp_path):
    status, _ = _run_result(wf, tmp_path, outcome="failure", review='{"serious": 0, "findings": []}')
    assert status == "unavailable"


def test_사전_판정_3_은_건너뜀_사유를_남긴다(wf, tmp_path):
    status, body = _run_result(wf, tmp_path, pre="3", missing="", outcome="skipped",
                               precheck={"reasons": ["ai_review 가 꺼져 있음"]})
    assert status == "skip" and "AI 리뷰 건너뜀: ai_review 가 꺼져 있음" in body


@pytest.mark.parametrize("pre", ["2", "1", ""])
def test_사전_판정_불능은_검사_불능(wf, tmp_path, pre):
    status, body = _run_result(wf, tmp_path, pre=pre, missing="", outcome="skipped",
                               precheck={"reasons": ["판정 불가: x"]})
    assert status == "unavailable" and "검사 불능" in body


def test_최종_판정은_통과와_건너뜀만_성공이다(wf):
    run = _named(wf, "판정")["run"]
    assert "pass)" in run and "skip)" in run
    assert run.count("exit 1") == 2
