"""`/scaffold` 가 넣는 SRS 규칙(`rules/ssot.yaml`)을 검증한다.

이슈 #44 로 `rules/ssot.yaml` 이 파일명뿐 아니라 `templates/harness/SRS.md` 의
`##` 제목을 기준으로 필수 절도 검사하게 됐다. `checker.tests.test_scaffold` 의
`scaffold`/`_run_auto` 를 그대로 써서, 여기서 만드는 문서가 `/scaffold` 가
실제로 만드는 구조 위에서 검사된다는 것을 보장한다.
"""
from __future__ import annotations

from pathlib import Path

from checker.cli import EXIT_PASS, EXIT_VIOLATION
from checker.tests.test_scaffold import _run_auto, scaffold

SRS_VALID = """# 테스트프로젝트 SRS

## 배경과 목표

구매요청 승인 절차를 전자화한다.

## 범위

- 하는 것: 구매요청 기안과 결재
- 하지 않는 것: 예산 편성

## AS-IS / TO-BE

AS-IS: 종이 결재. TO-BE: 전자 결재.

## 요구사항

| ID | 요구사항 | 우선순위 | 출처 | 상태 |
|---|---|---|---|---|
| REQ-001 | 기안자는 구매요청을 등록한다 | 상 | 요구사항정리.md | 유효 |

## 참조

`templates/`, `conventions/`

## 미결 사항

없음.
"""

# '요구사항' 절이 빠졌다. 필수 절이므로 위반이어야 한다.
SRS_MISSING_요구사항 = """# 테스트프로젝트 SRS

## 배경과 목표

구매요청 승인 절차를 전자화한다.

## 범위

- 하는 것: 구매요청 기안과 결재
- 하지 않는 것: 예산 편성

## AS-IS / TO-BE

AS-IS: 종이 결재. TO-BE: 전자 결재.

## 참조

`templates/`, `conventions/`

## 미결 사항

없음.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_형식에_맞는_SRS는_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "테스트프로젝트", False)
    srs = tmp_path / "docs" / "ssot" / "SRS.md"
    _write(srs, SRS_VALID)

    code, out = _run_auto(capsys, srs)

    assert code == EXIT_PASS
    assert out["summary"]["passed"] == 1
    assert out["summary"]["violations"] == 0


def test_SRS에_요구사항_절이_없으면_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "테스트프로젝트", False)
    srs = tmp_path / "docs" / "ssot" / "SRS.md"
    _write(srs, SRS_MISSING_요구사항)

    code, out = _run_auto(capsys, srs)

    assert code == EXIT_VIOLATION
    violations = out["files"][0]["violations"]
    assert any(v["rule"] == "required_sections" and v["expected"] == "요구사항" for v in violations)


def test_SRS_v2_처럼_파일명이_다르면_여전히_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "테스트프로젝트", False)
    srs = tmp_path / "docs" / "ssot" / "SRS.md"
    _write(srs, SRS_VALID)
    srs_v2 = srs.parent / "SRS_v2.md"
    _write(srs_v2, SRS_VALID)

    code, out = _run_auto(capsys, srs_v2)

    assert code == EXIT_VIOLATION
    assert out["summary"]["violations"] == 1
    assert out["files"][0]["violations"][0]["rule"] == "filename"
