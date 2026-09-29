"""main push 가 doc-guard 검사에 실패하면 이슈로 알리는 장치가 있는지 검증한다(#95).

무료 비공개 저장소라 branch protection 을 걸 수 없어, PR 검사가 실패한 채로
병합될 수 있다. main 에 push 된 커밋마저 doc-guard 에 실패하면 최소한 이슈로
남아야 아무도 놓치지 않는다. 이 테스트는 그 장치가:

- 재사용 워크플로(`.github/workflows/doc-guard.yml`)의 `check` job 에
  `failure() && push && refs/heads/main` 조건으로만 도는 스텝으로 있고
  `gh issue create` 를 쓰는지
- 그 스텝이 같은 원인의 이슈를 중복으로 만들지 않고 기존 이슈에 코멘트를
  남기는지
- 스캐폴딩 템플릿(`plugins/harness/skills/scaffold/skeleton/dot-github/workflows/doc-guard.yml`)이
  그 이슈를 열 수 있도록 `issues: write` 권한을 부르는 쪽에서 주는지

를 확인한다. 실제로 이슈가 열리는지(엔드투엔드)는 여기서 검증하지 않는다 —
GitHub Actions 러너와 실제 저장소가 필요해 이 테스트 스위트의 범위 밖이다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_GUARD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "doc-guard.yml"
SKELETON_DOC_GUARD_WORKFLOW = (
    REPO_ROOT
    / "plugins"
    / "harness"
    / "skills"
    / "scaffold"
    / "skeleton"
    / "dot-github"
    / "workflows"
    / "doc-guard.yml"
)


def _check_job_steps() -> list[dict]:
    workflow = yaml.safe_load(DOC_GUARD_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["check"]["steps"]


def _issue_alert_step() -> dict:
    steps = _check_job_steps()
    candidates = [s for s in steps if "gh issue create" in s.get("run", "")]
    assert candidates, "gh issue create 를 쓰는 스텝이 없다"
    return candidates[-1]


def test_main_push_실패시에만_이슈_알림_스텝이_돈다():
    condition = _issue_alert_step().get("if", "")
    assert "failure()" in condition
    assert "github.event_name == 'push'" in condition
    assert "refs/heads/main" in condition


def test_이슈_알림_스텝은_중복_생성_대신_코멘트를_남긴다():
    run = _issue_alert_step()["run"]
    assert "gh issue list" in run
    assert "gh issue comment" in run


def test_이슈_알림_스텝은_라벨이_없어도_실패하지_않는다():
    run = _issue_alert_step()["run"]
    # 라벨이 있는지 먼저 확인하고 없으면 라벨 없이 만든다 — caller 저장소에
    # type:fix 라벨이 없다고 이 스텝 자체가 실패하면 안 된다.
    assert "gh label list" in run
    assert 'gh issue create --title "$title" --body "$body"' in run


def test_스캐폴딩_템플릿이_issues_write_권한을_준다():
    workflow = yaml.safe_load(SKELETON_DOC_GUARD_WORKFLOW.read_text(encoding="utf-8"))
    permissions = workflow["jobs"]["doc-guard"]["permissions"]
    assert permissions.get("issues") == "write"
