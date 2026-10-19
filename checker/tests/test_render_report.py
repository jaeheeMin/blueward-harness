"""PR 코멘트 렌더링을 단언한다.

위반과 검사 불능은 받는 사람이 다르므로(#13) 제목부터 갈려야 한다. 위반은 문서를
올린 팀원이 고치고, 검사 불능은 규칙·설정을 관리하는 담당자가 고친다. 이 구분이
무너지면 엉뚱한 사람이 헤매게 된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from render_report import render  # noqa: E402


def _report(scoped: int, violations: int, files: list[dict] | None = None) -> dict:
    return {
        "summary": {
            "scoped": scoped,
            "passed": scoped - violations,
            "violations": violations,
            "out_of_scope": 0,
        },
        "files": files or [],
    }


def test_위반은_템플릿_위반_제목이다():
    report = _report(
        1,
        1,
        [
            {
                "file": "docs/제안서/제안서최종.md",
                "type": "제안서",
                "template": "templates/제안서.md",
                "status": "violation",
                "violations": [
                    {"rule": "filename", "expected": "20260101_x_제안서.md",
                     "actual": "제안서최종.md", "message": "파일 이름이 규칙과 다릅니다"}
                ],
            }
        ],
    )
    text = render(report, 1)
    assert "❌ 템플릿 위반" in text
    assert "문서를 고쳐야 합니다" in text
    assert "검사 불능" not in text
    assert "제안서최종.md" in text


def test_통과에는_위반_제목이_없다():
    text = render(_report(2, 0), 0)
    assert "❌" not in text
    assert "⚠️" not in text
    assert "모두 템플릿을 따릅니다" in text


def test_설정오류는_검사불능_제목이고_문서_문제가_아니라고_말한다():
    text = render({"message": "규칙.yaml 이 깨졌습니다"}, 2)
    assert "⚠️ 검사 불능" in text
    assert "문서의 문제가 아닙니다" in text
    assert "규칙.yaml 이 깨졌습니다" in text
    assert "❌ 템플릿 위반" not in text


def test_예상치_못한_코드도_검사불능이다():
    text = render({}, 7)
    assert "⚠️ 검사 불능" in text
    assert "문서의 문제가 아닙니다" in text


def test_리포트가_비어있어도_검사불능이지_통과가_아니다():
    """summary 가 없는 이상한 리포트를 통과로 읽으면 안 된다."""
    text = render({}, 2)
    assert "⚠️ 검사 불능" in text
    assert "모두 템플릿을 따릅니다" not in text


def test_리포트_json이_깨지면_main이_검사불능으로_렌더링한다(tmp_path, capsys):
    from render_report import main

    report_path = tmp_path / "report.json"
    report_path.write_text("이것은 JSON 이 아니다 {{{", encoding="utf-8")

    argv = ["render_report.py", str(report_path), "0"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        assert main() == 0
    finally:
        sys.argv = old_argv

    out = capsys.readouterr().out
    assert "⚠️ 검사 불능" in out
    assert "해석하지 못했습니다" in out


def _skip(file: str, reason: str = "자리표시·시스템 파일이라 문서로 보지 않는다") -> dict:
    return {
        "file": file, "type": "제안서", "template": None,
        "status": "skipped", "reason": reason, "violations": [],
    }


def test_통과_코멘트에_건너뛴_파일이_이유와_함께_보인다():
    report = _report(1, 0, [
        {"file": "docs/제안서/x.md", "type": "제안서", "template": "t", "status": "pass", "violations": []},
        _skip("docs/제안서/.gitkeep"),
    ])
    report["summary"]["skipped"] = 1

    text = render(report, 0)
    assert "모두 템플릿을 따릅니다" in text
    assert "건너뛴 파일 1건" in text
    assert "### 건너뛴 파일" in text
    assert ".gitkeep" in text
    assert "자리표시" in text


def test_위반_코멘트에도_건너뛴_파일이_보인다():
    report = _report(1, 1, [
        {
            "file": "docs/제안서/틀림.md", "type": "제안서", "template": "t", "status": "violation",
            "violations": [{"rule": "filename", "expected": "x", "actual": "틀림.md",
                            "message": "파일 이름이 다르다"}],
        },
        _skip("docs/제안서/.gitkeep"),
    ])
    report["summary"]["skipped"] = 1

    text = render(report, 1)
    assert "❌ 템플릿 위반" in text
    assert "### 건너뛴 파일" in text
    assert ".gitkeep" in text


def test_전부_건너뛴_파일뿐이면_검사한_문서는_없지만_통과다():
    report = _report(0, 0, [_skip("a/.gitkeep", "이유1"), _skip("b/.DS_Store", "이유2")])
    report["summary"]["skipped"] = 2

    text = render(report, 0)
    assert "검사할 문서는 없" in text
    assert "건너뛴 파일 2건" in text
    assert "관할 밖" not in text
    assert ".gitkeep" in text and ".DS_Store" in text


def test_리포트_파일이_없으면_main이_검사불능으로_렌더링한다(tmp_path, capsys):
    from render_report import main

    missing = tmp_path / "없다.json"
    argv = ["render_report.py", str(missing), "0"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        assert main() == 0
    finally:
        sys.argv = old_argv

    out = capsys.readouterr().out
    assert "⚠️ 검사 불능" in out
    assert str(missing) in out


# --- 공통 개발 규칙(CR-001, CR-002, #54) 절 --------------------------------
#
# `check_changed.py` 가 코드 파일을 검사하면 리포트에 `code_rules` 키를 더한다.
# doc-guard 절과 공통 개발 규칙 절은 서로 독립이어야 한다 — 한쪽이 위반이어도
# 다른 쪽이 통과라면 그 사실이 그대로 드러나야 한다.


def _code_section(exit_code: int, report: dict) -> dict:
    return {"exit": exit_code, "report": report}


def test_코드가_없으면_공통_개발_규칙_절이_없다():
    text = render(_report(1, 0), 0)
    assert "공통 개발 규칙" not in text


def test_문서는_통과하고_코드만_위반해도_각자_제목으로_보인다():
    report = _report(1, 0, [
        {"file": "docs/제안서/x.md", "type": "제안서", "template": "t", "status": "pass", "violations": []},
    ])
    report["code_rules"] = _code_section(1, {
        "summary": {"checked": 1, "violations": 1, "allowed": 0, "skipped": 0},
        "files": [
            {
                "file": "src/z_report.abap", "language": "abap", "status": "violation",
                "findings": [
                    {"rule": "CR-001", "line": 3, "col": 6, "message": "이름 '주문번호' 에 한글 등 비ASCII 문자가 있다.",
                     "fix": "영문 이름으로 바꾼다.", "allowed": False},
                ],
            }
        ],
    })

    # 바깥 종료코드는 check_changed.py 가 둘을 합친 값(코드가 위반이므로 1)이다. doc-guard
    # 자신은 통과였다는 사실이 여기서 사라지면 안 된다.
    text = render(report, 1)
    assert "모두 템플릿을 따릅니다" in text
    assert "❌ 템플릿 위반" not in text
    assert "### ❌ 공통 개발 규칙 위반" in text
    assert "z_report.abap" in text
    assert "CR-001" in text
    assert "주문번호" in text
    assert "영문 이름으로 바꾼다" in text


def test_코드도_통과하면_코드_절도_통과로_보인다():
    report = _report(1, 0)
    report["code_rules"] = _code_section(0, {
        "summary": {"checked": 2, "violations": 0, "allowed": 1, "skipped": 0},
        "files": [],
    })
    text = render(report, 0)
    assert "### ❌ 공통 개발 규칙 위반" not in text
    assert "모두 공통 개발 규칙" in text
    assert "예외로 인정된 발견 1건" in text


_WARN_FINDING = {
    "rule": "CR-009", "level": "warn", "line": 7, "col": 3,
    "message": "권한 메서드 get_global_authorizations 가 auth-allowed 만 대입한다.",
    "fix": "AUTHORITY-CHECK 로 검사한다.", "allowed": False,
}


def test_경고만_있으면_경고_절이_나오고_위반_절은_없다():
    report = _report(1, 0)
    report["code_rules"] = _code_section(0, {
        "summary": {"checked": 1, "violations": 0, "warnings": 1, "allowed": 0, "skipped": 0},
        "files": [{"file": "src/zbp_x.clas.locals_imp.abap", "language": "abap", "status": "pass",
                   "findings": [_WARN_FINDING]}],
    })
    text = render(report, 0)
    assert "### ❌ 공통 개발 규칙 위반" not in text
    assert "### ⚠️ 경고" in text and "병합을 막지는 않습니다" in text
    assert "[CR-009]" in text and "zbp_x.clas.locals_imp.abap" in text
    assert "고치기: AUTHORITY-CHECK" in text


def test_경고는_위반과_함께_있어도_위반_목록에_섞이지_않는다():
    report = _report(1, 0)
    report["code_rules"] = _code_section(1, {
        "summary": {"checked": 1, "violations": 1, "warnings": 1, "allowed": 0, "skipped": 0},
        "files": [{"file": "src/z.abap", "language": "abap", "status": "violation", "findings": [
            {"rule": "CR-001", "level": "violation", "line": 1, "col": 1, "message": "이름 문제",
             "fix": "영문으로.", "allowed": False},
            _WARN_FINDING,
        ]}],
    })
    text = render(report, 1)
    violation_part, warn_part = text.split("### ⚠️ 경고")
    assert "[CR-001]" in violation_part and "[CR-009]" not in violation_part
    assert "[CR-009]" in warn_part


def test_예외로_인정된_경고는_보이지_않는다():
    report = _report(1, 0)
    report["code_rules"] = _code_section(0, {
        "summary": {"checked": 1, "violations": 0, "warnings": 0, "allowed": 1, "skipped": 0},
        "files": [{"file": "src/z.abap", "language": "abap", "status": "pass",
                   "findings": [{**_WARN_FINDING, "allowed": True}]}],
    })
    assert "경고" not in render(report, 0)


def test_예외로_인정된_발견은_따로_보이지_않는다():
    report = _report(1, 0)
    report["code_rules"] = _code_section(1, {
        "summary": {"checked": 1, "violations": 1, "allowed": 1, "skipped": 0},
        "files": [
            {
                "file": "src/z.abap", "language": "abap", "status": "violation",
                "findings": [
                    {"rule": "CR-002", "line": 5, "col": 3, "message": "SELECT 문이 반복문 안에 있다.",
                     "fix": "모아 조회한다.", "allowed": False},
                    {"rule": "CR-002", "line": 9, "col": 3, "message": "SELECT 문이 반복문 안에 있다.",
                     "fix": "모아 조회한다.", "allowed": True},
                ],
            }
        ],
    })
    text = render(report, 1)
    assert text.count("5:3") == 1
    assert "9:3" not in text


def test_코드_검사_불능은_따로_알린다():
    report = _report(1, 0)
    report["code_rules"] = _code_section(2, {"message": "엔진을 받지 못했습니다"})
    text = render(report, 1)
    assert "모두 템플릿을 따릅니다" in text
    assert "### ⚠️ 검사 불능" in text
    assert "엔진을 받지 못했습니다" in text
    assert "코드의 문제가 아닙니다" in text
