"""`/harness:spec` 이 넣는 Spec 규칙(`rules/spec.yaml`)을 검증한다.

이슈 #45 로 `docs/spec/` 에 개발 Spec 을 두고, 파일 이름(`DEV-xxx-<요약>.md`)과
`templates/harness/spec.md` 의 `##` 제목을 기준으로 필수 절을 검사하게 됐다.
`checker.tests.test_scaffold` 의 `scaffold`/`_run_auto` 를 그대로 써서, 여기서
만드는 문서가 `/scaffold` 가 실제로 만드는 구조 위에서 검사된다는 것을
보장한다. 진행 원장이 DEV 번호를 ID 로 쓰게 됐어도 `audit-ledger.yaml` 규칙이
여전히 통과하는지도 함께 본다.
"""
from __future__ import annotations

from pathlib import Path

from checker.cli import EXIT_PASS, EXIT_VIOLATION
from checker.tests.test_scaffold import _run_auto, scaffold

SPEC_VALID = """# DEV-001 결재단계 추가

## 근거 요구사항

REQ-031 ([SRS](../ssot/SRS.md))

## 개요

구매요청 결재에 단계를 하나 더한다.

## 상세 설계

기존 1단계 결재를 2단계로 늘린다. 화면 변경은 미정.

## 완료 조건

2단계 결재가 정상 동작하고 기존 데이터가 깨지지 않는다.

## 참조

`templates/`, `conventions/`

## 변경 이력

| 날짜 | 내용 | 변경 기록 링크 |
|---|---|---|
|  |  |  |
"""

# '근거 요구사항' 절이 빠졌다. 필수 절이므로 위반이어야 한다.
SPEC_MISSING_근거요구사항 = """# DEV-001 결재단계 추가

## 개요

구매요청 결재에 단계를 하나 더한다.

## 상세 설계

기존 1단계 결재를 2단계로 늘린다.

## 완료 조건

2단계 결재가 정상 동작한다.

## 참조

`templates/`, `conventions/`

## 변경 이력

| 날짜 | 내용 | 변경 기록 링크 |
|---|---|---|
|  |  |  |
"""

LEDGER_WITH_DEV_ID = """# 구매요청승인

## 관련 요구사항

REQ-031

## 개발 건

| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |
|---|---|---|---|---|---|
| DEV-001 | 결재단계 추가 | [spec](../../docs/spec/DEV-001-결재단계추가.md) | 김개발 | 진행 | #50 |

## 메모

없음.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_형식에_맞는_spec은_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    spec = tmp_path / "docs" / "spec" / "DEV-001-결재단계추가.md"
    _write(spec, SPEC_VALID)

    code, out = _run_auto(capsys, spec)

    assert code == EXIT_PASS
    assert out["summary"]["passed"] == 1
    assert out["summary"]["violations"] == 0


def test_spec_파일명이_DEV_형식이_아니면_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    # DEV 번호 접두사가 없다.
    spec = tmp_path / "docs" / "spec" / "결재단계.md"
    _write(spec, SPEC_VALID)

    code, out = _run_auto(capsys, spec)

    assert code == EXIT_VIOLATION
    assert out["summary"]["violations"] == 1
    assert out["files"][0]["violations"][0]["rule"] == "filename"


def test_spec에_근거_요구사항_절이_없으면_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    spec = tmp_path / "docs" / "spec" / "DEV-001-결재단계추가.md"
    _write(spec, SPEC_MISSING_근거요구사항)

    code, out = _run_auto(capsys, spec)

    assert code == EXIT_VIOLATION
    violations = out["files"][0]["violations"]
    assert any(
        v["rule"] == "required_sections" and v["expected"] == "근거 요구사항" for v in violations
    )


def test_spec_gitkeep은_건너뛰고_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    gitkeep = tmp_path / "docs" / "spec" / ".gitkeep"

    code, out = _run_auto(capsys, gitkeep)

    assert code == EXIT_PASS
    assert out["summary"]["skipped"] == 1
    assert out["summary"]["scoped"] == 0


def test_DEV_번호를_ID로_쓰는_진행_원장도_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    ledger = tmp_path / "audit" / "ledger" / "구매요청승인.md"
    _write(ledger, LEDGER_WITH_DEV_ID)

    code, out = _run_auto(capsys, ledger)

    assert code == EXIT_PASS
    assert out["summary"]["passed"] == 1
    assert out["summary"]["violations"] == 0
