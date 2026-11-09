"""단위테스트 List 스킬(`/harness:unittest`, #831)의 규칙 사본과 시험 양식 산출을 검증한다.

고객 양식 xlsx 는 쓰지 않고 시험용 양식을 코드로 만든다. 지도는 public-cloud 의 `단위테스트 List` 지도와 같은 모양(Document Control 개정 이력 +
단위테스트 List 표 + 견본 시트 반복)이고 열·행 범위만 줄였다. 규칙은 스킬 폴더의 사본을 그대로 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest
import yaml
from openpyxl.worksheet.datavalidation import DataValidation

from checker import export
from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, main

SKILL = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "unittest"
FORM = "단위테스트 List"
LOB = "시험LoB"
OUT_NAME = f"BW_단위테스트 List_{LOB}_v0.1.xlsx"

MAP = """\
양식: 단위테스트 List
설명: 시험용
템플릿: ../ut_form.xlsx
산출:
  폴더: docs/unittest
  파일명: "BW_단위테스트 List_{LoB}_v{버전}.xlsx"
  자리:
    LoB: {메타: LoB}
    버전: {메타: 버전}
견본_검사: true
시트:
  - 이름: Document Control
    표:
      - 이름: 개정 이력
        머리글_행: 4
        시작_행: 5
        최대_행: 10
        필수: true
        열: {Version: A, 개정일자: B, 개정사유: C}
    비우기: [D5:E14]
    유지: [A2, A4:E4, A28:E29]
  - 이름: 단위테스트 List
    표:
      - 이름: 단위테스트 List
        머리글_행: 4
        시작_행: 5
        필수: true
        md_전용: [근거]
        열:
          Mega No: A
          Mega Name: B
          Task No: G
          Task Name: H
          Task Variant No: I
          Task Variant Name: J
          App(T-code): K
          Test Case ID: L
          Test Case 명: M
          Description: N
          연계 모듈/타 시스템: Q
    비우기: [S1, O5:P12, R5:V12]
    유지: [A1:R4, S2:V4]
  - 이름: TC.견본
    반복: true
    칸:
      - 항목: Test Case 명
        위치: A3
        필수: true
        형식: "{ID} : {값}"
    표:
      - 이름: 단계
        머리글_행: 8
        시작_행: 9
        필수: true
        md_전용: [근거]
        열: {모듈: A, 순서: B, 수행업무 (Step): C, App(T-Code): D, Input: E, Output: F, 주요 점검 Point: G, Test 대상 여부: J}
    비우기: [H9:I20, L9:N20]
    유지: [J1:L5, A7:N8, J9:K50]
"""

PEOPLE = "사람이름"


def _template(path: Path) -> None:
    wb = openpyxl.Workbook()
    dc = wb.active
    dc.title = "Document Control"
    dc["A2"] = "Document Control"
    for i, n in enumerate(["Version", "개정일자", "개정사유", "작성자", "결재(승인)"]):
        dc.cell(4, 1 + i, n)
    dc["A5"], dc["C5"], dc["D5"] = "v9.9", "견본 사유", PEOPLE
    dc["A28"], dc["A29"] = "배포대상", "프로젝트 팀원 전체"
    ls = wb.create_sheet("단위테스트 List")
    ls["G1"] = "=SUBTOTAL(3,G5:G9827)"
    ls["M1"] = "Test Case ID=To-Be Process Level 4 or Task Variant level"
    ls["S1"] = "8/6~9/5까지 기간내 계획 수립"
    for i, n in enumerate(["No.", "Name"] * 5 + ["App", "ID", "Test Case 명", "Description"]):
        ls.cell(4, 1 + i, n)
    ls["O3"], ls["Q3"] = "KU", "모듈/타 시스템"
    ls["A5"], ls["G5"], ls["P5"], ls["S5"], ls["U5"] = "FI", "FI.01.01.01", PEOPLE, "2025-08-11", "완료"
    tc = wb.create_sheet("TC.견본")
    tc["J1"], tc["K1"] = "총 테스트 대상", '=COUNTIF(J$9:J$774,"=Yes")'
    tc["J2"], tc["K2"], tc["L2"] = "P: Passed", '=COUNTIF(K$9:K$774,"=P")', "=K2/$K$1"
    tc["A3"] = "FI.01.03.02.02 : 견본 제목"
    for c, n in zip("ABCDEGHIJKL", ["모듈", "순서", "수행업무 (Step)", "App(T-Code)", "주요 Data", "주요 점검 Point", "Test 담당자", "컨설턴트", "Test 대상 여부", "Test 결과", "이슈"]):
        tc[f"{c}7"] = n
    tc["E8"], tc["F8"] = "Input", "Output"
    tc["A9"], tc["C9"], tc["H9"], tc["I9"] = "FI", "견본 단계", PEOPLE, PEOPLE  # K9(Test 결과)는 빈 칸으로 둔다
    dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True, showErrorMessage=True)
    dv.add("J9:J50")
    tc.add_data_validation(dv)
    dv2 = DataValidation(type="list", formula1='"P,PP,F,N/A"', allow_blank=True, showErrorMessage=True)
    dv2.add("K9:K50")
    tc.add_data_validation(dv2)
    wb.save(path)


LIST_COLS = ["Mega No", "Mega Name", "Task No", "Task Name", "Task Variant No", "Task Variant Name", "App(T-code)",
             "Test Case ID", "Test Case 명", "Description", "연계 모듈/타 시스템", "근거"]
STEP_COLS = ["모듈", "순서", "수행업무 (Step)", "App(T-Code)", "Input", "Output", "주요 점검 Point", "Test 대상 여부", "근거"]


def _table(cols: list[str], rows: list[dict]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n" for r in rows)


ROWS = [
    {"Mega No": "PP", "Mega Name": "생산", "Task No": "PP.01.01.01", "Task Name": "계획", "Task Variant No": "PP.01.01.01.01",
     "Task Variant Name": "A", "App(T-code)": "앱 A", "Test Case ID": "PP.01.01.01.01", "Test Case 명": "시험 A",
     "Description": "설명 A", "근거": "스코프 아이템 X · 시험 문서"},
    {"Task Variant No": "PP.01.01.01.02", "Task Variant Name": "B", "App(T-code)": "앱 B", "Test Case ID": "PP.01.01.01.02",
     "Test Case 명": "시험 B", "Description": "설명 B", "연계 모듈/타 시스템": "MM", "근거": "확인 필요: App"},
]
STEP = [{"모듈": "PP", "순서": "01", "수행업무 (Step)": "첫 단계", "App(T-Code)": "앱 A", "Input": "입력", "Output": "출력",
         "주요 점검 Point": "저장", "Test 대상 여부": "Yes", "근거": "시험 문서 1"}]


def _note(rows=ROWS, ids=("PP.01.01.01.01", "PP.01.01.01.02"), head: str = "버전: 0.1\nLoB: " + LOB + "\n", extra: str = "",
          list_cols=LIST_COLS, step_cols=STEP_COLS) -> str:
    parts = [
        f"# 단위테스트 List {LOB}\n\n{head}\n## 양식 항목\n\n",
        f"### {FORM} · Document Control\n\n#### 개정 이력\n\n{_table(['Version', '개정일자', '개정사유'], [{'Version': 'v0.1', '개정일자': '2026-11-09', '개정사유': '초안작성'}])}\n",
        f"### {FORM} · 단위테스트 List\n\n#### 단위테스트 List\n\n{_table(list_cols, rows)}\n",
    ]
    for i in ids:
        parts.append(f"### {FORM} · TC.견본 · {i}\n\n| 항목 | 값 |\n|---|---|\n| Test Case 명 | 시험 {i[-2:]} |\n\n#### 단계\n\n{_table(step_cols, STEP)}\n")
    return "".join(parts) + extra


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    for d in ("templates/forms", "templates/harness", "rules", "docs/unittest"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "templates" / "forms" / f"{FORM}.yaml").write_text(MAP, encoding="utf-8")
    _template(tmp_path / "templates" / "ut_form.xlsx")
    for src, dst in (("unittest.yaml", "rules/unittest.yaml"), ("unittest-output.yaml", "rules/unittest-output.yaml"),
                     ("unittest-template.md", "templates/harness/unittest.md")):
        (tmp_path / dst).write_text((SKILL / src).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _write(proj: Path, text: str, name: str = f"{LOB}.md") -> Path:
    p = proj / "docs" / "unittest" / name
    p.write_text(text, encoding="utf-8")
    return p


def _export(proj: Path, capsys, *extra: str, name: str = f"{LOB}.md"):
    code = export.main(["--spec", str(proj / "docs" / "unittest" / name), "--form", FORM, "--root", str(proj), *extra])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, "stdout 은 JSON 한 줄이어야 한다"
    return code, json.loads(out)


def _check_rules(capsys, path: Path):
    code = main(["--auto", str(path)])
    return code, json.loads(capsys.readouterr().out)


def _violations(out: dict, rule: str = "form_columns") -> list[dict]:
    return [v for f in out["files"] for v in f.get("violations", []) if v["rule"] == rule]


# ---------------------------------------------------------------- 규칙 사본

def test_규칙_사본은_스킬_폴더에_있고_읽힌다():
    for name in ("unittest.yaml", "unittest-output.yaml", "unittest-template.md", "SKILL.md"):
        assert (SKILL / name).is_file(), name
    rules = yaml.safe_load((SKILL / "unittest.yaml").read_text(encoding="utf-8"))
    assert rules["관할"] == "docs/unittest/*.md"
    assert [r["종류"] for r in rules["규칙"]] == ["filename", "required_sections", "form_columns"]
    assert rules["규칙"][2]["ID_패턴"]
    assert yaml.safe_load((SKILL / "unittest-output.yaml").read_text(encoding="utf-8"))["관할"] == "docs/unittest/*.xlsx"


def test_SKILL_은_사람_칸과_공식_문서_원칙을_적고_엔진_판을_engine_spec_으로_받는다():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "blueward-harness@" + "main" not in text and "hooks/engine_spec.py" in text
    assert "공식 문서" in text and "확인 필요" in text and "블로그와" in text
    assert "사람 정보는 이 저장소에 두지 않는다" in text and "다른 스킬이 부르는 브랜치 확인" in text


# ---------------------------------------------------------------- 작업본 규칙

def test_지도_안의_작업본은_규칙을_통과한다(proj, capsys):
    code, out = _check_rules(capsys, _write(proj, _note()))
    assert code == EXIT_PASS, out
    assert out["files"][0]["type"] == "unittest"


@pytest.mark.parametrize("task_id", ["FI.01.03.01", "FI.01.03.02.02", "ABC.01.02.03.04"])
def test_견본_체계의_Test_Case_ID는_통과한다(proj, capsys, task_id):
    code, out = _check_rules(capsys, _write(proj, _note(ids=(task_id,))))
    assert code == EXIT_PASS, out


@pytest.mark.parametrize("bad", ["fi.01.03.01", "FI.1.3.1", "FI.01.03", "FI.01.03.02.02.01", "FI-01-03-01", "F.01.03.01"])
def test_ID_형식이_다르면_위반이다(proj, capsys, bad):
    code, out = _check_rules(capsys, _write(proj, _note(ids=(bad,))))
    assert code == EXIT_VIOLATION, out
    [v] = _violations(out)
    assert v["actual"] == bad and "ID 형식" in v["message"]


def test_사람_칸_열은_작업본에_쓸_수_없다(proj, capsys):
    rows = [dict(r, 담당자="") for r in ROWS]
    code, out = _check_rules(capsys, _write(proj, _note(rows=rows, list_cols=LIST_COLS + ["담당자"])))
    assert code == EXIT_VIOLATION
    assert any(v["actual"] == "담당자" for v in _violations(out))


def test_단계_표의_사람_칸_열도_양식_밖이다(proj, capsys):
    code, out = _check_rules(capsys, _write(proj, _note(ids=("PP.01.01.01.01",), step_cols=STEP_COLS + ["Test 결과"])))
    assert code == EXIT_VIOLATION
    assert any(v["actual"] == "Test 결과" for v in _violations(out))


def test_근거_열은_작업본_전용으로_허용된다(proj, capsys):
    code, out = _check_rules(capsys, _write(proj, _note()))
    assert code == EXIT_PASS and not _violations(out)


def test_작업본_파일명에_쓸_수_없는_문자가_있으면_위반이다(proj, capsys):
    path = proj / "docs" / "unittest" / "A*B.md"
    try:
        path.write_text(_note(), encoding="utf-8")
    except OSError:  # Windows 는 파일 이름에 `*` 를 만들 수 없다 — 규칙 문자열을 바로 시험한다
        pytest.skip("이 OS 는 파일 이름에 * 를 쓸 수 없다")
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION and any(v["rule"] == "filename" for v in out["files"][0]["violations"])


def test_다른_양식_소절은_위반이다(proj, capsys):
    text = _note() + "### 개발사양서 · Cover\n\n| 항목 | 값 |\n|---|---|\n| 개발 ID | X |\n"
    code, out = _check_rules(capsys, _write(proj, text))
    assert code == EXIT_VIOLATION and any("양식 밖" in v["message"] for v in _violations(out))


def test_ID_패턴이_정규식이_아니면_검사_불능이다(proj, capsys):
    rule = proj / "rules" / "unittest.yaml"
    rule.write_text(rule.read_text(encoding="utf-8").replace("ID_패턴: '", "ID_패턴: '(", 1), encoding="utf-8")
    code, out = _check_rules(capsys, _write(proj, _note()))
    assert code == EXIT_CONFIG_ERROR, out


# ---------------------------------------------------------------- 산출

def test_산출하면_시트가_ID_이름으로_복제되고_사람_칸은_비어_있다(proj, capsys):
    _write(proj, _note())
    code, report = _export(proj, capsys)
    assert code == 0, report
    assert report["files"] == [f"docs/unittest/{OUT_NAME}"]
    wb = openpyxl.load_workbook(proj / "docs" / "unittest" / OUT_NAME)
    assert wb.sheetnames == ["Document Control", "단위테스트 List", "PP.01.01.01.01", "PP.01.01.01.02"]
    dc = wb["Document Control"]
    assert (dc["A5"].value, dc["C5"].value, dc["D5"].value, dc["E5"].value) == ("v0.1", "초안작성", None, None)
    ls = wb["단위테스트 List"]
    assert [ls[f"{c}5"].value for c in "ABGHIJKLMN"] == ["PP", "생산", "PP.01.01.01", "계획", "PP.01.01.01.01", "A", "앱 A", "PP.01.01.01.01", "시험 A", "설명 A"]
    assert ls["A6"].value is None and ls["G6"].value is None and ls["L6"].value == "PP.01.01.01.02" and ls["Q6"].value == "MM"
    assert ls["G1"].value.startswith("=SUBTOTAL(3,G5")
    assert ls["S1"].value is None  # 견본의 일정 안내 문구
    assert all(ls[f"{c}{r}"].value is None for r in range(5, 13) for c in "OPRSTUV")
    tc = wb["PP.01.01.01.01"]
    assert tc["A3"].value == "PP.01.01.01.01 : 시험 01"
    assert [tc[f"{c}9"].value for c in "ABCDEFGJ"] == ["PP", "01", "첫 단계", "앱 A", "입력", "출력", "저장", "Yes"]
    assert all(tc[f"{c}9"].value is None for c in "HIKLMN")
    assert tc["K1"].value.startswith("=COUNTIF(J$9:J$774")
    assert any(str(d.sqref) == "J9:J50" for d in tc.data_validations.dataValidation)


def test_산출물에_견본과_사람_흔적과_근거_열이_없다(proj, capsys):
    _write(proj, _note())
    code, _ = _export(proj, capsys)
    assert code == 0
    import zipfile

    z = zipfile.ZipFile(proj / "docs" / "unittest" / OUT_NAME)
    blob = b"".join(z.read(n) for n in z.namelist())
    for needle in (PEOPLE, "견본 사유", "견본 단계", "견본 제목", "v9.9", "2025-08-11", "스코프 아이템 X", "확인 필요", "시험 문서"):
        assert needle.encode() not in blob, needle


def test_산출_xlsx_이름이_산출_규칙_패턴을_통과한다(proj, capsys):
    _write(proj, _note())
    code, report = _export(proj, capsys)
    assert code == 0, report
    code, out = _check_rules(capsys, proj / report["files"][0])
    assert code == EXIT_PASS, out


def test_LoB_줄이_없으면_산출을_거부한다(proj, capsys):
    _write(proj, _note(head="버전: 0.1\n"))
    code, report = _export(proj, capsys)
    assert code != 0 and report["status"] != "ok" and not (proj / "docs" / "unittest" / OUT_NAME).exists()


def test_버전_줄이_없으면_산출을_거부한다(proj, capsys):
    _write(proj, _note(head=f"LoB: {LOB}\n"))
    code, report = _export(proj, capsys)
    assert code != 0 and report["status"] != "ok"


def test_ID가_시트_이름_규칙을_어기면_산출을_거부한다(proj, capsys):
    _write(proj, _note(ids=("PP.01.01.01.01.01.01.01.01.01.01.01.01.01.01",)))
    code, report = _export(proj, capsys)
    assert code == 1 and report["status"] == "rejected"


def test_Test_대상_여부가_Yes_No_밖이면_경고한다(proj, capsys):
    _write(proj, _note().replace("| Yes |", "| 예 |", 1))
    code, report = _export(proj, capsys)
    assert code == 3 and any(w.get("type") == "dropdown" and w.get("value") == "예" for w in report["warnings"])


def test_Test_Case_소절이_하나도_없으면_견본이_빠지고_경고한다(proj, capsys):
    _write(proj, _note(ids=()))
    code, report = _export(proj, capsys)
    assert any("복제본 없음" in w["reason"] for w in report["warnings"]), report  # 경고만 있고 종료코드는 엔진이 정한 대로
    wb = openpyxl.load_workbook(proj / "docs" / "unittest" / OUT_NAME)
    assert wb.sheetnames == ["Document Control", "단위테스트 List"]
