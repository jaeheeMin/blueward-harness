"""`/scaffold` 가 넣는 Audit 규칙(`audit-changes.yaml`, `audit-ledger.yaml`)을 검증한다.

변경 기록과 진행 원장 각각에 통과 1건, 파일명 위반 1건, 필수 절 위반 1건을
둔다. `audit/changes/.gitkeep` 처럼 자리표시 파일이 관할 안에서도 건너뛰어지는
것도 함께 본다(#15). `checker.tests.test_scaffold` 의 `scaffold`/`_run_auto` 를
그대로 써서, 여기서 만드는 문서가 `/scaffold` 가 실제로 만드는 구조 위에서
검사된다는 것을 보장한다.
"""
from __future__ import annotations

from pathlib import Path

from checker.cli import EXIT_PASS, EXIT_VIOLATION
from checker.tests.test_scaffold import _run_auto, scaffold

CHANGE_VALID = """# 결재단계 추가

- 날짜: 2026-09-26
- 작성자: 김개발

## 종류

설계 변경

## 바뀐 것

REQ-031, docs/spec/구매요청.md

## 근거

고객 요청으로 결재 단계를 하나 늘렸다.

## 영향

audit/ledger/구매요청승인.md

## 관련 PR

#50
"""

# '근거' 절이 빠졌다. 필수 절이므로 위반이어야 한다.
CHANGE_MISSING_근거 = """# 결재단계 추가

- 날짜: 2026-09-26
- 작성자: 김개발

## 종류

설계 변경

## 바뀐 것

REQ-031, docs/spec/구매요청.md

## 영향

audit/ledger/구매요청승인.md

## 관련 PR

#50
"""

LEDGER_VALID = """# 구매요청승인

## 관련 요구사항

REQ-031

## 개발 건

| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |
|---|---|---|---|---|---|
| DEV-1 | 결재단계 추가 | docs/spec/구매요청.md | 김개발 | 진행 | #50 |

## 메모

없음.
"""

# '개발 건' 절이 빠졌다. 필수 절이므로 위반이어야 한다.
LEDGER_MISSING_개발건 = """# 구매요청승인

## 관련 요구사항

REQ-031

## 메모

없음.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_형식에_맞는_변경_기록은_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    change = tmp_path / "audit" / "changes" / "20260926-결재단계추가.md"
    _write(change, CHANGE_VALID)

    code, out = _run_auto(capsys, change)

    assert code == EXIT_PASS
    assert out["summary"]["passed"] == 1
    assert out["summary"]["violations"] == 0


def test_변경_기록의_파일명이_형식과_다르면_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    # 날짜 접두사가 없다.
    change = tmp_path / "audit" / "changes" / "결재단계.md"
    _write(change, CHANGE_VALID)

    code, out = _run_auto(capsys, change)

    assert code == EXIT_VIOLATION
    assert out["summary"]["violations"] == 1
    assert out["files"][0]["violations"][0]["rule"] == "filename"


def test_변경_기록에_근거_절이_없으면_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    change = tmp_path / "audit" / "changes" / "20260926-결재단계추가.md"
    _write(change, CHANGE_MISSING_근거)

    code, out = _run_auto(capsys, change)

    assert code == EXIT_VIOLATION
    violations = out["files"][0]["violations"]
    assert any(v["rule"] == "required_sections" and v["expected"] == "근거" for v in violations)


def test_형식에_맞는_진행_원장은_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    ledger = tmp_path / "audit" / "ledger" / "구매요청승인.md"
    _write(ledger, LEDGER_VALID)

    code, out = _run_auto(capsys, ledger)

    assert code == EXIT_PASS
    assert out["summary"]["passed"] == 1
    assert out["summary"]["violations"] == 0


def test_스펙_칸이_대시인_start_등록_줄도_통과하고_스캐폴드_템플릿_자체도_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    ledger = tmp_path / "audit" / "ledger" / "구매요청승인.md"
    _write(ledger, LEDGER_VALID.replace("docs/spec/구매요청.md", "-").replace("| 진행 | #50 |", "| 진행 |  |"))

    code, out = _run_auto(capsys, ledger)

    assert code == EXIT_PASS
    assert out["summary"]["violations"] == 0

    template = tmp_path / "templates" / "harness" / "audit-ledger.md"
    copy = tmp_path / "audit" / "ledger" / "새프로그램.md"
    _write(copy, template.read_text(encoding="utf-8"))

    code, out = _run_auto(capsys, copy)

    assert code == EXIT_PASS
    assert out["summary"]["violations"] == 0


def test_진행_원장에_개발_건_절이_없으면_위반이다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    ledger = tmp_path / "audit" / "ledger" / "구매요청승인.md"
    _write(ledger, LEDGER_MISSING_개발건)

    code, out = _run_auto(capsys, ledger)

    assert code == EXIT_VIOLATION
    violations = out["files"][0]["violations"]
    assert any(v["rule"] == "required_sections" and v["expected"] == "개발 건" for v in violations)


def test_변경_기록_gitkeep은_건너뛰고_통과한다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    gitkeep = tmp_path / "audit" / "changes" / ".gitkeep"

    code, out = _run_auto(capsys, gitkeep)

    assert code == EXIT_PASS
    assert out["summary"]["skipped"] == 1
    assert out["summary"]["scoped"] == 0
