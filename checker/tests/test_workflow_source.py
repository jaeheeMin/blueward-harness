"""작업 순서의 정본 plugins/harness/workflow.json 검사(#599).

- 모든 근거(basis) 문장이 실제 스킬·규칙 파일에 있다.
- plugins/harness/skills/ 의 모든 스킬이 workflow.json 의 단계나 도구에 있다(새 스킬을 빠뜨리면 실패한다).
- 콘솔이 workflow.json 을 읽는다(옛 console/flows.json 은 없다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "harness"
CONSOLE = PLUGIN / "console"
WORKFLOW = PLUGIN / "workflow.json"
sys.path.insert(0, str(CONSOLE))

import flows  # noqa: E402
import server as console_server  # noqa: E402

SKILLS = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))


def _data() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_json_basis_quotes_all_exist_in_the_plugin_files():
    data = _data()
    errors = flows.validate(data, set(SKILLS))
    assert errors == [], "workflow.json 의 근거(basis)가 맞지 않다. 스킬·규칙 문장을 바꿨다면 workflow.json 의 quote 도 맞춘다:\n" + "\n".join(errors)


def test_step_short_names_are_short_nonempty_strings():
    # short 는 선택. 있으면 화면용 짧은 이름이라 비지 않은 12자 이하 문자열이다.
    steps = [(f"{f['id']}/{s['id']}", s) for f in _data()["flows"] for s in f["steps"]]
    assert any("short" in s for _, s in steps)
    for key, s in steps:
        if "short" in s:
            assert isinstance(s["short"], str) and s["short"].strip() and len(s["short"]) <= 12, key


def test_every_step_has_plain_easy_words_without_skill_commands():
    # 새 작업 화면 순서 칸의 쉬운 말(plain 이름·easy 설명). 선택 필드지만 모든 단계에 채워 두고, 스킬 명령 문자는 쓰지 않는다.
    for f in _data()["flows"]:
        for s in f["steps"]:
            key = f"{f['id']}/{s['id']}"
            for field in ("plain", "easy"):
                assert isinstance(s.get(field), str) and s[field].strip(), (key, field)
                assert "/harness:" not in s[field], (key, field)
            assert len(s["plain"]) <= 12, key
            if "brief" in s:
                assert isinstance(s["brief"], str) and s["brief"].strip() and len(s["brief"]) <= 20, key


def test_console_passes_step_short_to_the_screen():
    data = _data()
    srs = next(f for f in data["flows"] if f["id"] == "srs")
    state = {"id": "srs", "name": srs["name"], "reason": "", "stepIndex": 0, "finished": False, "unknown": [],
             "steps": [{"id": s["id"], "name": s["name"], "kind": s["kind"]} for s in srs["steps"]]}
    out = flows.public_fields({"flowState": state}, data)
    assert [st["short"] for st in out["flowSteps"]] == ["쓰기", "올리기", "승인·합치기"]


def test_every_step_flow_next_tool_and_condition_has_a_basis():
    data = _data()
    owners = [("조건 " + k, v) for k, v in data["conditions"].items()]
    for f in data["flows"]:
        owners.append(("갈래 " + f["id"], f))
        owners += [(f"{f['id']}/{s['id']}", s) for s in f["steps"]]
        rule = f.get("next")
        if rule and "srsColumn" in rule:
            owners.append((f"{f['id']} next.srsColumn", rule["srsColumn"]))
            owners += [(f"{f['id']} next.{k}", b) for k, b in rule["srsColumn"]["branches"].items()]
        elif rule:
            owners.append((f"{f['id']} next", rule))
    owners += [("도구 " + t["id"], t) for t in data["tools"]]
    missing = [name for name, o in owners if not o.get("basis")]
    assert not missing, f"근거(basis)가 없다: {missing}"


def test_every_skill_is_in_a_workflow_step_or_listed_as_a_tool():
    missing = flows.missing_skills(_data(), SKILLS)
    assert not missing, (
        f"스킬 {missing} 이 plugins/harness/workflow.json 에 없다. 새 스킬은 workflow.json 에 순서(flows 의 단계)나 도구(tools)로 넣으라 "
        "(단계는 근거 스킬·규칙 문장 basis 와 함께, 단추를 안 내는 스킬은 \"hidden\": true 도구로)."
    )


def test_workflow_json_names_only_skills_that_exist():
    data = _data()
    ghosts = sorted((flows.flow_skills(data) | flows.tool_skills(data)) - set(SKILLS))
    assert not ghosts, f"workflow.json 이 없는 스킬을 가리킨다: {ghosts}"


def test_the_checker_catches_a_skill_missing_from_the_workflow():
    data = _data()
    assert flows.missing_skills(data, SKILLS) == []
    data["tools"] = [t for t in data["tools"] if t.get("skill") != "role"]
    assert flows.missing_skills(data, SKILLS) == ["role"]  # 위 시험이 부르는 것과 같은 함수가 빠진 스킬을 잡는다
    assert flows.missing_skills(data, SKILLS + ["brand-new"]) == ["brand-new", "role"]


def test_console_reads_workflow_json_from_the_plugin_not_a_console_copy():
    assert flows.DATA_FILE == WORKFLOW and WORKFLOW.is_file()
    assert not (CONSOLE / "flows.json").exists(), "옛 console/flows.json 은 없앴다. 작업 순서는 workflow.json 하나가 정본이다."
    fake_app = SimpleNamespace(plugin_root=PLUGIN)
    got, error = console_server.App.load_flows(fake_app, None)  # 경로를 안 주면 기본(플러그인의 workflow.json)을 읽는다
    assert error == "" and got is not None
    assert [f["id"] for f in got["flows"]] == ["srs", "spec", "dev", "config", "standard", "fix"]


def test_console_turns_flows_off_when_a_basis_quote_is_wrong(tmp_path, capsys):
    data = _data()
    data["flows"][0]["steps"][0]["basis"] = [{"file": "skills/srs/SKILL.md", "quote": "이 문장은 srs 스킬에 없다"}]
    bad = tmp_path / "workflow.json"
    bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    fake_app = SimpleNamespace(plugin_root=PLUGIN)
    got, error = console_server.App.load_flows(fake_app, bad)
    assert got is None and "basis" in error and "srs/srs" in error  # 갈래 기능만 끈다(콘솔은 계속 뜬다)
    assert "basis" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["CLAUDE.md", "plugins/harness/rules/governance.md"])
def test_docs_point_to_workflow_json_as_the_source_of_the_work_order(path):
    assert "workflow.json" in (ROOT / path).read_text(encoding="utf-8")
