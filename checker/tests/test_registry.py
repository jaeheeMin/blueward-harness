"""이 설계의 핵심 주장을 지킨다.

CLAUDE.md: "규칙이 늘어날 때 엔진 코드를 고치게 되면 설계가 어긋난 것이다."

규칙 종류를 하나만 만들면 그 주장은 검증되지 않는다. 두 번째, 세 번째를 붙여 봐야 엔진이
정말 멍청한지 알 수 있다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from checker import engine
from checker import rules as rule_registry
from checker.model import Violation
from checker.readers import supported


def test_규칙_종류_열이_등록된다():
    assert set(rule_registry.known()) == {
        "external_traces",
        "filename",
        "form_columns",
        "location",
        "md_table",
        "req_cross_reference",
        "required_sections",
        "required_sheets",
        "slide_layouts",
        "table_headers",
    }


def test_리더_넷이_등록된다():
    assert {".md", ".docx", ".xlsx", ".pptx"} <= set(supported())


def test_엔진은_규칙_종류를_하나도_모른다():
    """엔진 소스에 규칙 종류 이름이 박혀 있으면 안 된다.

    박혀 있다면 규칙을 늘릴 때 엔진을 고쳐야 한다는 뜻이다.
    """
    source = inspect.getsource(engine)
    for kind in rule_registry.known():
        assert kind not in source, f"engine.py 에 '{kind}' 가 박혀 있다"


def test_엔진은_형식도_모른다():
    source = inspect.getsource(engine)
    for ext in (".md", ".docx", ".xlsx", ".pptx"):
        assert ext not in source, f"engine.py 에 '{ext}' 가 박혀 있다"


def test_새_규칙_종류를_엔진을_고치지_않고_붙일_수_있다():
    """등록만 하면 엔진이 그대로 불러 쓴다."""
    before = inspect.getsource(engine)

    @rule_registry.rule("시험용")
    def _fake(path: Path, params: dict) -> list[Violation]:
        return [Violation(rule="시험용", expected="a", actual="b")]

    try:
        assert "시험용" in rule_registry.known()
        assert rule_registry.get("시험용") is _fake
        assert rule_registry.get("시험용")(Path("x"), {})[0].rule == "시험용"
        assert inspect.getsource(engine) == before
    finally:
        rule_registry._RULES.pop("시험용", None)
