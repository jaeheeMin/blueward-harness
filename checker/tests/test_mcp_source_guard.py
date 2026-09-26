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
