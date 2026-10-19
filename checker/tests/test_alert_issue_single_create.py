"""알림 이슈를 여는 재사용 워크플로가 이슈를 한 번만 만드는지 정적으로 검사한다(#359).

`gh issue create --assignee` 가 담당자 지정에서 실패하면 이슈는 이미 만들어진 채 명령이
실패로 끝난다. 그 뒤 `||` 나 `if !` 로 다시 create 하면 같은 알림이 두 번 열린다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
# 라벨·담당자를 붙이던 알림 워크플로들.
ALERTS = ["risk-gate.yml", "human-merge-alert.yml", "pr-tamper-alert.yml", "release-tag.yml"]
RISK_STEP = "승인 없이 위험한 변경이 들어왔으면 이슈를 연다"


def _logical_lines(text: str) -> list[str]:
    """`\\` 줄 이음을 합친 논리 줄. 주석 줄은 뺀다."""
    joined = re.sub(r"\\\r?\n\s*", " ", text)
    return [ln.strip() for ln in joined.splitlines() if not ln.lstrip().startswith("#")]


def _create_commands(text: str) -> list[str]:
    return [ln for ln in _logical_lines(text) if "gh issue create" in ln]


def _rest_calls(text: str) -> list[str]:
    return [ln for ln in _logical_lines(text) if re.search(r"gh api -X POST .*/issues/\S+/(labels|assignees)", ln)]


def _risk_run() -> str:
    wf = yaml.safe_load((WORKFLOWS / "risk-gate.yml").read_text(encoding="utf-8"))
    for job in wf["jobs"].values():
        for step in job["steps"]:
            if step.get("name") == RISK_STEP:
                return step["run"]
    raise AssertionError(f"step 을 찾지 못했다: {RISK_STEP}")


@pytest.mark.parametrize("name", ALERTS)
def test_create_는_한_번만_부르고_재시도하지_않는다(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    cmds = _create_commands(text)
    assert len(cmds) == 1, cmds
    assert "||" not in cmds[0]
    assert "then gh issue create" not in text


@pytest.mark.parametrize("name", ALERTS)
def test_create_에_담당자와_라벨을_묶지_않는다(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    cmd = _create_commands(text)[0]
    assert "--assignee" not in cmd and "--label" not in cmd


@pytest.mark.parametrize("name", ALERTS)
def test_라벨과_담당자는_REST_로_따로_붙이고_실패는_경고만_남긴다(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    calls = _rest_calls(text)
    kinds = {("labels" if "/labels" in c else "assignees") for c in calls}
    assert kinds == {"labels", "assignees"}, calls
    for c in calls:
        assert "gh issue edit" not in c
        # 같은 논리 줄(`\` 이음 포함)에서 `|| echo "::warning` 으로 이어진다.
        assert re.search(r'\|\| echo "::warning', c), c
    assert "gh issue edit" not in text


@pytest.mark.parametrize("name", ["risk-gate.yml", "human-merge-alert.yml", "release-tag.yml"])
def test_담당자는_소유자가_사용자일_때만_지정한다(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert ".owner.type" in text
    m = re.search(r'if \[ "\$owner_type" = "User" \]; then\n(.*?)\n\s*else\n', text, re.S)
    assert m, "owner_type 분기 블록이 없다"
    block = m.group(1)
    assert "/assignees" in block
    # 블록 밖에는 담당자 호출이 없다.
    assert text.count("/assignees") == 1


@pytest.mark.parametrize("name", ALERTS)
def test_create_가_실패하거나_번호가_비면_조용히_넘어가지_않는다(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert re.search(r'if ! url="\$\(gh issue create[^\n]*\)"; then\s*\n\s*echo "::error[^\n]*\n\s*exit 1', text)
    assert re.search(r'if \[ -z "\$num" \]; then\s*\n\s*echo "::error[^\n]*\n\s*exit 1', text)


def test_risk_gate_는_커밋_마커를_본문에_넣는다():
    run = _risk_run()
    assert 'marker="<!-- risk-gate:${GITHUB_SHA} -->"' in run
    body = run[run.index("{\n"):run.index("} > body.md")]
    assert 'printf \'%s\\n\' "$marker"' in body


def test_마커_중복_검사_jq_식이_열린_이슈_본문의_마커를_찾는다():
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq 가 없어 중복 검사 식을 실제로 돌리지 못했다(통과도 위반도 아니다)")
    m = re.search(r"jq -r --arg t \"\$title\" --arg m \"\$marker\" '([^']+)'", _risk_run())
    assert m, "중복 검사 jq 식을 찾지 못했다"
    expr = m.group(1)
    sha = "a" * 40
    marker = f"<!-- risk-gate:{sha} -->"
    title = "승인 없이 위험한 변경이 main 에 들어왔다: aaaaaaa"

    def run(issues):
        out = subprocess.run(
            [jq, "-r", "--arg", "t", title, "--arg", "m", marker, expr],
            input=json.dumps(issues), capture_output=True, text=True, encoding="utf-8", check=True,
        )
        return out.stdout.strip()

    # 제목이 달라도(라벨 없는 복제 등) 본문 마커가 있으면 찾는다.
    assert run([{"number": 7, "title": "다른 제목", "body": f"본문\n\n{marker}\n"}]) == "7"
    # 제목만 같아도 찾는다.
    assert run([{"number": 8, "title": title, "body": None}]) == "8"
    # 다른 커밋의 마커나 관련 없는 이슈는 찾지 않는다.
    other = f"<!-- risk-gate:{'b' * 40} -->"
    assert run([{"number": 9, "title": "x", "body": other}, {"number": 10, "title": "y", "body": ""}]) == ""
