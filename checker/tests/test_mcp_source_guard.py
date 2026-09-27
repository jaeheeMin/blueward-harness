"""MCP `setObjectSource` 훅(`mcp_source_guard.py`)이 설치된 플러그인 레이아웃에서도
동작하는지 확인한다(#60).

`test_hook.py` 와 같은 이유로 `plugins/harness/` 를 저장소 밖 임시 폴더로 복사해
설치본을 흉내 낸다 — 마켓플레이스 설치본에는 `checker/` 가 따라오지 않는다(#12).
엔진은 `DOC_GUARD_ENGINE` 으로 이 워크트리를 가리켜 네트워크 없이 로컬 소스로
받게 한다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SRC = ENGINE_ROOT / "plugins" / "harness"

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv 가 없으면 엔진을 받아 실행할 수 없다"
)


@pytest.fixture(scope="module")
def installed_hook(tmp_path_factory) -> Path:
    """`plugins/harness/` 를 저장소 밖으로 복사해 설치본을 흉내 낸다."""
    dest_parent = tmp_path_factory.mktemp("harness-installed-mcp")
    dest = dest_parent / "harness"
    shutil.copytree(PLUGIN_SRC, dest)

    assert not (dest / "checker").exists()
    assert not (dest_parent / "pyproject.toml").exists()
    assert not (dest_parent.parent / "pyproject.toml").exists()
    # 이 훅이 stdlib 만으로 URL 을 판별하는 전제(#60) — 매핑 데이터가 설치본에도
    # 그대로 따라와야 한다.
    assert (dest / "hooks" / "mcp_object_source_map.json").is_file()

    return dest / "hooks" / "mcp_source_guard.py"


def run_hook(hook: Path, payload: dict, engine: str) -> tuple[int, dict | None]:
    env = {**os.environ, "DOC_GUARD_ENGINE": engine}
    done = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=180,
    )
    if not done.stdout.strip():
        return done.returncode, None
    return done.returncode, json.loads(done.stdout)


def decision(out: dict | None) -> str | None:
    if out is None:
        return None
    return out["hookSpecificOutput"]["permissionDecision"]


def _payload(url, source, tool_name="mcp__abap_adt__setObjectSource") -> dict:
    tool_input = {"lockHandle": "abcd1234"}
    if url is not None:
        tool_input["objectSourceUrl"] = url
    if source is not None:
        tool_input["source"] = source
    return {"tool_name": tool_name, "tool_input": tool_input}


ABAP_URL = "/sap/bc/adt/oo/classes/zcl_x/source/main"
CDS_URL = "/sap/bc/adt/ddic/ddl/sources/z_i_order/source/main"


def test_한글_이름이_있는_abap_소스는_막는다(installed_hook):
    code, out = run_hook(
        installed_hook,
        _payload(ABAP_URL, "DATA 주문번호 TYPE vbeln.\n"),
        str(ENGINE_ROOT),
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert "주문번호" in reason
    assert ABAP_URL in reason


def test_반복문_안의_select가_있는_abap_소스는_막는다(installed_hook):
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        "  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.\n"
        "ENDLOOP.\n"
    )
    code, out = run_hook(installed_hook, _payload(ABAP_URL, text), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    assert "CR-002" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_규칙을_지킨_abap_소스는_통과시킨다(installed_hook):
    code, out = run_hook(
        installed_hook, _payload(ABAP_URL, "DATA lv_order TYPE vbeln.\n"), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


def test_cds_url은_cds_규칙으로_한글_이름을_막는다(installed_hook):
    text = "define view entity Z_I_Order as select from vbak {\n  vbeln as 주문번호\n};\n"
    code, out = run_hook(installed_hook, _payload(CDS_URL, text), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert "주문번호" in reason


def test_알_수_없는_url은_검사_불능으로_거절한다(installed_hook):
    code, out = run_hook(
        installed_hook,
        _payload("/sap/bc/adt/unknown/thing/source/main", "아무거나"),
        str(ENGINE_ROOT),
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "판별할 수 없" in reason
    assert "/sap/bc/adt/unknown/thing/source/main" in reason


def test_source가_없으면_검사_불능으로_거절한다(installed_hook):
    code, out = run_hook(installed_hook, _payload(ABAP_URL, None), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


def test_harness_allow_주석이_있으면_통과시킨다(installed_hook):
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln. "#harness:allow CR-002 이유\n'
        "ENDLOOP.\n"
    )
    code, out = run_hook(installed_hook, _payload(ABAP_URL, text), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_다른_mcp_도구는_관여하지_않는다(installed_hook):
    """매처가 걸러 주는 것과 별개로, 이 스크립트 자신도 도구 이름을 확인한다."""
    code, out = run_hook(
        installed_hook,
        _payload(ABAP_URL, "DATA 주문번호 TYPE vbeln.\n", tool_name="mcp__abap_adt__getObjectSource"),
        str(ENGINE_ROOT),
    )
    assert code == 0 and out is None


def test_엔진을_받을_수_없으면_통과가_아니라_거절한다(installed_hook, tmp_path):
    """CLAUDE.md 원칙 7: '검사를 못 했다' 를 '통과' 로 뭉개지 않는다."""
    missing_engine = str(tmp_path / "존재하지-않는-경로")
    code, out = run_hook(
        installed_hook, _payload(ABAP_URL, "DATA lv_x TYPE vbeln.\n"), missing_engine
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


# --- 리팩토링/생성 도구는 새 이름만 CR-001 로 본다(#61) -----------------------
#
# renamePreview/renameExecute/extractMethodPreview 는 새 이름을 담은 필드가 객체로도,
# JSON 문자열로도 올 수 있다(방어적으로 둘 다 받는다). createObject 는 `name` 이 바로
# 문자열이다. extractMethodExecute 는 이름 필드가 따로 없어 `contentNew` 코드 조각을
# 이어 붙여 검사한다 — 아래에 따로 둔다.

ASCII_NAME = "ZCL_NEW_METHOD"
KOREAN_NAME = "새메서드"


def _name_field_payload(tool_name: str, field: str, key: str, name, as_string: bool) -> dict:
    tool_input: dict = {}
    if name is not None:
        obj = {key: name}
        tool_input[field] = json.dumps(obj, ensure_ascii=False) if as_string else obj
    return {"tool_name": tool_name, "tool_input": tool_input}


_NAME_TOOLS = [
    ("renamePreview", "renameRefactoring", "newName"),
    ("renameExecute", "refactoring", "newName"),
    ("extractMethodPreview", "proposal", "name"),
]


@pytest.mark.parametrize("tool_suffix,field,key", _NAME_TOOLS)
@pytest.mark.parametrize("as_string", [False, True], ids=["object", "json문자열"])
def test_이름만_보는_도구는_영문_이름을_통과시킨다(installed_hook, tool_suffix, field, key, as_string):
    payload = _name_field_payload(f"mcp__abap_adt__{tool_suffix}", field, key, ASCII_NAME, as_string)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert code == 0 and out is None


@pytest.mark.parametrize("tool_suffix,field,key", _NAME_TOOLS)
@pytest.mark.parametrize("as_string", [False, True], ids=["object", "json문자열"])
def test_이름만_보는_도구는_한글_이름을_cr001로_막는다(installed_hook, tool_suffix, field, key, as_string):
    tool_name = f"mcp__abap_adt_z5u__{tool_suffix}"
    payload = _name_field_payload(tool_name, field, key, KOREAN_NAME, as_string)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert KOREAN_NAME in reason
    assert tool_name in reason


@pytest.mark.parametrize("tool_suffix,field,key", _NAME_TOOLS)
def test_이름만_보는_도구는_필드가_없으면_검사_불능으로_거절한다(installed_hook, tool_suffix, field, key):
    payload = {"tool_name": f"mcp__abap_adt__{tool_suffix}", "tool_input": {}}
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


@pytest.mark.parametrize("tool_suffix,field,key", _NAME_TOOLS)
def test_이름만_보는_도구는_json이_아니면_검사_불능으로_거절한다(installed_hook, tool_suffix, field, key):
    payload = {
        "tool_name": f"mcp__abap_adt__{tool_suffix}",
        "tool_input": {field: "이것은 JSON 도 객체도 아니다"},
    }
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


@pytest.mark.parametrize("tool_suffix,field,key", _NAME_TOOLS)
def test_이름만_보는_도구는_이름_필드가_빈_문자열이면_검사_불능으로_거절한다(installed_hook, tool_suffix, field, key):
    payload = _name_field_payload(f"mcp__abap_adt__{tool_suffix}", field, key, "", False)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


def _create_object_payload(tool_name: str, name) -> dict:
    tool_input: dict = {}
    if name is not None:
        tool_input["name"] = name
    return {"tool_name": tool_name, "tool_input": tool_input}


def test_createobject는_영문_이름을_통과시킨다(installed_hook):
    payload = _create_object_payload("mcp__abap_adt__createObject", ASCII_NAME)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_createobject는_한글_이름을_cr001로_막는다(installed_hook):
    payload = _create_object_payload("mcp__abap_adt_z5u_dev__createObject", KOREAN_NAME)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert KOREAN_NAME in reason
    assert "createObject" in reason


def test_createobject는_이름이_없으면_검사_불능으로_거절한다(installed_hook):
    payload = _create_object_payload("mcp__abap_adt__createObject", None)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


# --- extractMethodExecute: 이름 필드가 없어 contentNew 조각을 이어 붙여 본다(#61) --


def _extract_refactoring(content_news: list[str], as_string: bool = True):
    obj = {"affectedObjects": [{"textReplaceDeltas": [{"contentNew": c} for c in content_news]}]}
    return json.dumps(obj, ensure_ascii=False) if as_string else obj


def _extract_execute_payload(refactoring, tool_name="mcp__abap_adt__extractMethodExecute") -> dict:
    return {"tool_name": tool_name, "tool_input": {"refactoring": refactoring}}


def test_extractmethodexecute는_코드조각_안의_한글_이름을_cr001로_막는다(installed_hook):
    fragment = "METHOD 새메서드.\nENDMETHOD.\n"
    payload = _extract_execute_payload(_extract_refactoring([fragment]))
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert "새메서드" in reason
    assert "extractMethodExecute" in reason


def test_extractmethodexecute는_주석과_문자열_안의_한글은_통과시킨다(installed_hook):
    fragment = (
        "METHOD zif_x~do_it.\n"
        '  " 새메서드 설명\n'
        "  lv_msg = '한글 문자열'.\n"
        "ENDMETHOD.\n"
    )
    payload = _extract_execute_payload(_extract_refactoring([fragment]))
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_extractmethodexecute는_반복문_안_select_모양이어도_cr002는_안_보고_통과시킨다(installed_hook):
    """옮기기만 하는 코드 조각이라 CR-002(반복문 안 DB 조회)는 이 경로의 관할이 아니다."""
    fragment = (
        "LOOP AT lt_order INTO ls_order.\n"
        "  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.\n"
        "ENDLOOP.\n"
    )
    payload = _extract_execute_payload(_extract_refactoring([fragment]))
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_extractmethodexecute는_객체_형태의_refactoring도_받는다(installed_hook):
    fragment = "METHOD 새메서드.\nENDMETHOD.\n"
    payload = _extract_execute_payload(_extract_refactoring([fragment], as_string=False))
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    assert "CR-001" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize(
    "tool_input",
    [
        {},
        {"refactoring": "이것은 JSON 도 객체도 아니다"},
        {"refactoring": json.dumps({"affectedObjects": "배열이 아니다"})},
        {"refactoring": json.dumps({"affectedObjects": [{"textReplaceDeltas": [{}]}]})},
        {"refactoring": json.dumps({"affectedObjects": [{"textReplaceDeltas": "배열이 아니다"}]})},
        {"refactoring": json.dumps({"affectedObjects": [{}]})},
    ],
    ids=[
        "필드없음", "json도_객체도_아님", "affectedObjects배열아님",
        "contentNew없음", "textReplaceDeltas배열아님", "textReplaceDeltas없음",
    ],
)
def test_extractmethodexecute는_모양이_어긋나면_검사_불능으로_거절한다(installed_hook, tool_input):
    payload = {"tool_name": "mcp__abap_adt__extractMethodExecute", "tool_input": tool_input}
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


def test_이_다섯_도구_말고_다른_mcp_도구는_관여하지_않는다(installed_hook):
    """예: renameEvaluate 는 이 훅이 다루는 여섯 도구에 없다."""
    payload = _create_object_payload("mcp__abap_adt__renameEvaluate", KOREAN_NAME)
    code, out = run_hook(installed_hook, payload, str(ENGINE_ROOT))
    assert code == 0 and out is None
