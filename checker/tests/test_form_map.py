"""`/harness:spec` 의 양식 지도 형식 정본(`form-map.md`)을 검증한다(이슈 #191).

정본의 예시 yaml 블록이 실제로 파싱되고 필수 키를 갖는지만 본다. 예시가
깨지면 스킬이 읽을 형식 자체가 틀린 것이다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

FORM_MAP_MD = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "harness"
    / "skills"
    / "spec"
    / "form-map.md"
)


def _example_map() -> dict:
    text = FORM_MAP_MD.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert match, "form-map.md 에 yaml 예시 블록이 없다"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


def test_예시_지도가_필수_키를_갖는다():
    data = _example_map()
    assert data["양식"]
    assert data["템플릿"]
    sheets = data["시트"]
    assert isinstance(sheets, list) and sheets
    for sheet in sheets:
        assert sheet["이름"]


def test_예시_지도의_칸_표_서술_모양():
    sheet = _example_map()["시트"][0]
    assert all("항목" in f and "위치" in f for f in sheet["칸"])
    for table in sheet["표"]:
        assert table["이름"] and table["열"]
    assert all("이름" in n and "위치" in n for n in sheet["서술"])


def test_spec_스킬이_형식_정본을_가리킨다():
    skill = FORM_MAP_MD.parent / "SKILL.md"
    assert "form-map.md" in skill.read_text(encoding="utf-8")


def test_예시_지도의_열과_항목_키가_모두_문자열이다():
    # No·Yes·On·Off 를 따옴표 없이 쓰면 YAML 1.1 이 불리언으로 읽는다.
    data = _example_map()
    for sheet in data["시트"]:
        for field in sheet.get("칸", []):
            assert isinstance(field["항목"], str)
        for table in sheet.get("표", []):
            assert all(isinstance(k, str) for k in table["열"])
