"""CTS 관리대장 작업본 산출과 규칙 사본을 검증한다(이슈 #577, `/harness:cts` 스킬).

고객 양식 xlsx 는 쓰지 않고 시험용 양식을 코드로 만든다. 지도는 public-cloud 의 CTS 관리대장 지도와 같은 모양
(표만 있는 xlsx, 머리글 3~4행, 데이터 5행부터, `자리: 버전: {메타: 버전}`)이고, 규칙은 스킬 폴더의 사본을 그대로 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest
import yaml
from openpyxl.comments import Comment
from openpyxl.styles import Border, Side

from checker import export
from checker.cli import EXIT_PASS, EXIT_VIOLATION, main

SKILL = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "cts"

# 종류 → (요청 시트, 요청 표 열, Error 표 열). 양식 머리글의 오타 '모둘' 도 지도 그대로 둔다.
ERROR_COLS = ["오픈단계", "NO", "요청일", "모둘", "CTS 유형", "Client 종속여부", "Target System", "Target Client",
              "Request NO", "Description", "Error 내용", "요청자", "조치사항"]
KINDS = {
    "Configuration": (
        "Config. CTS",
        ["오픈단계", "NO", "요청일", "모둘", "CTS 유형", "Target System", "Request NO", "Description", "주요변경 및 특이사항",
         "요청자", "처리일자", "처리시간", "처리자", "처리결과", "승인"],
    ),
    "CBO": (
        "CBO CTS",
        ["오픈단계", "NO", "요청일", "모둘", "CTS 유형", "Client 종속여부", "Target System", "Target Client", "Request NO",
         "Description", "주요변경 및 특이사항", "요청자", "처리일자", "처리시간", "처리자", "처리결과", "승인"],
    ),
}
DATE_COLS = {"요청일", "처리일자"}


def _letter(i: int) -> str:
    return openpyxl.utils.get_column_letter(i + 2)  # 열은 B 부터


def _map(kind: str) -> str:
    sheet, cols = KINDS[kind]

    def cols_yaml(names):
        return "".join(f'          "{n}": {_letter(i)}\n' for i, n in enumerate(names))

    last = _letter(len(cols) - 1)
    err_last = _letter(len(ERROR_COLS) - 1)
    return (
        f"양식: CTS_관리대장_{kind}\n설명: 시험용\n템플릿: ../cts_{kind}.xlsx\n"
        "산출:\n  폴더: docs/CTS관리대장\n"
        f'  파일명: "CTS관리대장_{kind}_v{{버전}}.xlsx"\n  자리:\n    버전: {{메타: 버전}}\n'
        "견본_검사: true\n시트:\n"
        f"  - 이름: {sheet}\n    표:\n      - 이름: {sheet}\n        머리글_행: 3\n        시작_행: 5\n        열:\n"
        f"{cols_yaml(cols)}    유지: [B1:{last}4]\n"
        "  - 이름: Error 내역\n    표:\n      - 이름: Error 내역\n        머리글_행: 3\n        시작_행: 5\n        열:\n"
        f"{cols_yaml(ERROR_COLS)}    유지: [B1:{err_last}4]\n"
    )


def _template(path: Path, kind: str) -> None:
    """머리글 3~4행(두 줄, 병합)·제목·서식 있는 빈 행 4줄. 날짜 칸은 날짜 서식이다."""
    sheet, cols = KINDS[kind]
    wb = openpyxl.Workbook()
    thin = Side(style="thin")
    for ws, names in ((wb.active, cols), (wb.create_sheet("Error 내역"), ERROR_COLS)):
        ws.title = sheet if ws is wb.worksheets[0] else "Error 내역"
        ws["C1"] = "시험 대장 리스트"
        for i, n in enumerate(names):
            ws.cell(3, i + 2, n)
            ws.merge_cells(start_row=3, start_column=i + 2, end_row=4, end_column=i + 2)
            for r in range(5, 9):
                c = ws.cell(r, i + 2)
                c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
                if n in DATE_COLS:
                    c.number_format = "yyyy\\-mm\\-dd"
        ws["B3"].comment = Comment("머리글 메모는 남아야 한다", "시험")
    wb.save(path)


def _row(cols: list[str], **v) -> str:
    return "| " + " | ".join(str(v.get(c, "")) for c in cols) + " |"


def _table(cols: list[str], rows: list[dict]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join(_row(cols, **r) + "\n" for r in rows)


def _worknote(kind: str, requests: list[dict], errors: list[dict], version: str = "0.1", head: bool = True) -> str:
    sheet, cols = KINDS[kind]
    ver = f"버전: {version}\n\n" if head else ""
    return (
        f"# CTS 관리대장 {kind}\n\n{ver}## 양식 항목\n\n"
        f"### CTS_관리대장_{kind} · {sheet}\n\n#### {sheet}\n\n{_table(cols, requests)}\n"
        f"### CTS_관리대장_{kind} · Error 내역\n\n#### Error 내역\n\n{_table(ERROR_COLS, errors)}"
    )


def _req(n: int, **extra) -> dict:
    return {"오픈단계": "시험", "NO": n, "요청일": "2026-11-02", "모둘": "FI", "CTS 유형": "IMG", "Target System": "QAS",
            "Request NO": f"시험요청{n}", "Description": f"시험용 {n}번째 요청", "요청자": "시험요청자", **extra}


ERR = {"오픈단계": "시험", "NO": 1, "요청일": "2026-11-03", "모둘": "MM", "CTS 유형": "IMG", "Client 종속여부": "Y",
       "Target System": "QAS", "Target Client": 100, "Request NO": "시험요청2", "Error 내용": "시험 오류", "조치사항": "시험 조치"}


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    (tmp_path / "templates" / "forms").mkdir(parents=True)
    (tmp_path / "templates" / "harness").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "docs" / "CTS관리대장").mkdir(parents=True)
    for kind in KINDS:
        (tmp_path / "templates" / "forms" / f"CTS_관리대장_{kind}.yaml").write_text(_map(kind), encoding="utf-8")
        _template(tmp_path / "templates" / f"cts_{kind}.xlsx", kind)
    # 스킬 폴더의 규칙 사본을 Project Repository 에 설치한 모양
    (tmp_path / "rules" / "cts.yaml").write_text((SKILL / "cts.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "rules" / "cts-output.yaml").write_text((SKILL / "cts-output.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "templates" / "harness" / "cts.md").write_text((SKILL / "cts-template.md").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _write(proj: Path, kind: str, text: str) -> Path:
    p = proj / "docs" / "CTS관리대장" / f"CTS관리대장_{kind}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _export(proj: Path, capsys, kind: str, *extra: str):
    code = export.main(["--spec", str(proj / "docs" / "CTS관리대장" / f"CTS관리대장_{kind}.md"),
                        "--form", f"CTS_관리대장_{kind}", "--root", str(proj), *extra])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, "stdout 은 JSON 한 줄이어야 한다"
    return code, json.loads(out)


def _check_rules(capsys, path: Path):
    code = main(["--auto", str(path)])
    return code, json.loads(capsys.readouterr().out)


def _xlsx(proj: Path, kind: str, version: str) -> Path:
    return proj / "docs" / "CTS관리대장" / f"CTS관리대장_{kind}_v{version}.xlsx"


# ---------------------------------------------------------------- 산출

@pytest.mark.parametrize("kind", list(KINDS))
def test_두_양식_모두_작업본으로_v0_1_산출된다(proj, capsys, kind):
    _write(proj, kind, _worknote(kind, [_req(1), _req(2)], [ERR]))
    code, report = _export(proj, capsys, kind)
    assert code == 0, report
    assert report["files"] == [f"docs/CTS관리대장/CTS관리대장_{kind}_v0.1.xlsx"]

    wb = openpyxl.load_workbook(_xlsx(proj, kind, "0.1"))
    sheet, cols = KINDS[kind]
    ws = wb[sheet]
    # 머리글·제목·메모는 그대로, 값은 5행부터 열 위치대로
    assert ws["C1"].value == "시험 대장 리스트" and ws["B3"].comment is not None
    assert [ws.cell(3, i + 2).value for i in range(len(cols))] == cols
    assert ws["C5"].value == 1 and ws["C6"].value == 2  # NO 는 숫자
    assert ws["D5"].value.date().isoformat() == "2026-11-02" and ws["D5"].number_format == "yyyy\\-mm\\-dd"
    req_col = _letter(cols.index("Request NO"))
    assert ws[f"{req_col}5"].value == "시험요청1" and ws[f"{req_col}6"].value == "시험요청2"
    assert ws["B7"].value is None  # 요청이 둘뿐이라 7행은 비어 있다
    err = wb["Error 내역"]
    assert err["C5"].value == 1 and err["I5"].value == 100 and err["N5"].value == "시험 조치"
    assert err["B1"].value is None and err["C1"].value == "시험 대장 리스트"


def test_행을_더하고_버전을_올리면_v0_2가_생기고_이전_판은_그대로_남는다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [_req(1), _req(2)], [ERR]))
    assert _export(proj, capsys, "Configuration")[0] == 0
    v01 = _xlsx(proj, "Configuration", "0.1")
    before = v01.read_bytes()

    _write(proj, "Configuration", _worknote("Configuration", [_req(1), _req(2), _req(3)], [ERR], version="0.2"))
    code, report = _export(proj, capsys, "Configuration")
    assert code == 0, report
    assert report["files"] == ["docs/CTS관리대장/CTS관리대장_Configuration_v0.2.xlsx"]
    assert v01.read_bytes() == before, "이전 판은 지우거나 고치지 않는다"
    ws = openpyxl.load_workbook(_xlsx(proj, "Configuration", "0.2"))["Config. CTS"]
    assert [ws.cell(r, 3).value for r in (5, 6, 7, 8)] == [1, 2, 3, None]


def test_서식_줄_수를_넘는_행도_서식이_이어진다(proj, capsys):
    rows = [_req(n) for n in range(1, 8)]  # 시험 양식은 서식 있는 줄이 4줄
    _write(proj, "CBO", _worknote("CBO", rows, []))
    code, report = _export(proj, capsys, "CBO")
    assert code == 0, report
    ws = openpyxl.load_workbook(_xlsx(proj, "CBO", "0.1"))["CBO CTS"]
    assert ws["C11"].value == 7
    assert ws["D11"].number_format == "yyyy\\-mm\\-dd" and ws["D11"].border.left.style == "thin"


def test_같은_판을_다시_산출하면_덮지_않는다_main_판_여부를_모르면_거부(proj, capsys):
    _write(proj, "CBO", _worknote("CBO", [_req(1)], []))
    assert _export(proj, capsys, "CBO")[0] == 0
    before = _xlsx(proj, "CBO", "0.1").read_bytes()
    _write(proj, "CBO", _worknote("CBO", [_req(1), _req(2)], []))
    code, report = _export(proj, capsys, "CBO")
    assert code == 1 and "통과 아님" in report["problems"][0]["reason"]
    assert _xlsx(proj, "CBO", "0.1").read_bytes() == before


def test_머리_버전_줄이_없으면_산출을_거부한다(proj, capsys):
    _write(proj, "CBO", _worknote("CBO", [_req(1)], [], head=False))
    code, report = _export(proj, capsys, "CBO")
    assert code == 1
    assert any("버전" in p["reason"] for p in report["problems"])
    assert not _xlsx(proj, "CBO", "0.1").exists()


def test_양식_밖_열은_산출이_종료코드_2로_멈춘다(proj, capsys):
    text = _worknote("Configuration", [_req(1)], [ERR]).replace("| 모둘 |", "| 모듈 |", 1)
    _write(proj, "Configuration", text)
    code, report = _export(proj, capsys, "Configuration")
    assert code == 2 and any("모듈" in json.dumps(p, ensure_ascii=False) for p in report["problems"])
    assert not _xlsx(proj, "Configuration", "0.1").exists()


# ---------------------------------------------------------------- 규칙 사본

def test_규칙_사본은_스킬_폴더에_세_파일이_있고_읽힌다():
    for name in ("cts.yaml", "cts-output.yaml", "cts-template.md", "SKILL.md"):
        assert (SKILL / name).is_file(), name
    rules = yaml.safe_load((SKILL / "cts.yaml").read_text(encoding="utf-8"))
    assert rules["관할"] == "docs/CTS관리대장/*.md"
    assert [r["종류"] for r in rules["규칙"]] == ["filename", "required_sections", "form_columns"]
    out = yaml.safe_load((SKILL / "cts-output.yaml").read_text(encoding="utf-8"))
    assert out["관할"] == "docs/CTS관리대장/*.xlsx"


@pytest.mark.parametrize("kind", list(KINDS))
def test_지도_안의_작업본은_규칙을_통과한다(proj, capsys, kind):
    path = _write(proj, kind, _worknote(kind, [_req(1)], [ERR]))
    code, out = _check_rules(capsys, path)
    assert code == EXIT_PASS, out
    assert out["files"][0]["type"] == "cts"


def test_양식_밖_열은_작업본_규칙이_거절하고_허용_목록을_알린다(proj, capsys):
    text = _worknote("Configuration", [_req(1)], [ERR]).replace("| 모둘 |", "| 모듈 |", 1)
    path = _write(proj, "Configuration", text)
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION
    [v] = [v for v in out["files"][0]["violations"] if v["rule"] == "form_columns"]
    assert v["actual"] == "모듈" and "모둘" in v["expected"]


def test_다른_종류의_시트는_양식_밖이다(proj, capsys):
    text = _worknote("Configuration", [_req(1)], [ERR]).replace("· Config. CTS", "· CBO CTS", 1)
    path = _write(proj, "Configuration", text)
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION
    assert any(v["rule"] == "form_columns" and v["actual"] == "CBO CTS" for v in out["files"][0]["violations"])


def test_다른_종류의_양식_소절은_파일명_양식_규칙이_거절한다(proj, capsys):
    # Configuration 작업본 안에 CBO 양식 소절 — 그대로 `--form Configuration` 으로 산출하면 행이 조용히 빠진다(#577)
    _, cbo_cols = KINDS["CBO"]
    text = _worknote("Configuration", [_req(1)], [ERR]).replace(
        "### CTS_관리대장_Configuration · Config. CTS\n\n#### Config. CTS\n\n" + _table(KINDS["Configuration"][1], [_req(1)]),
        "### CTS_관리대장_CBO · CBO CTS\n\n#### CBO CTS\n\n" + _table(cbo_cols, [_req(1)]),
    )
    assert "### CTS_관리대장_CBO · CBO CTS" in text
    path = _write(proj, "Configuration", text)
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION
    bad = [v for v in out["files"][0]["violations"] if v["rule"] == "form_columns"]
    assert any(v["actual"] == "CTS_관리대장_CBO" and v["expected"] == "CTS_관리대장_Configuration" for v in bad)


def test_파일명_양식_틀이_패턴에_없는_그룹을_쓰면_검사_불능이다(tmp_path):
    from checker.rules import form_columns

    with pytest.raises(form_columns.ConfigError):
        form_columns._form_from_name({"파일명_양식": {"패턴": r"^(?P<a>.+)\.md$", "양식": "X_{b}"}}, "Y.md")


@pytest.mark.parametrize("bad", ["11/2", "2026-13-01", "내일"])
def test_날짜_칸에_날짜가_아닌_값은_date_text_경고로_종료코드_3(proj, capsys, bad):
    _write(proj, "Configuration", _worknote("Configuration", [_req(1, 요청일=bad)], []))
    code, out = _export(proj, capsys, "Configuration")
    assert code == 3 and out["status"] == "warning"
    assert any(w.get("type") == "date-text" and w.get("value") == bad for w in out["warnings"])


def test_날짜_칸의_올바른_날짜는_경고가_없다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [_req(1)], [ERR]))
    code, out = _export(proj, capsys, "Configuration")
    assert code == 0 and not any(w.get("type") == "date-text" for w in out["warnings"])


def test_작업본_파일명이_틀리면_위반이다(proj, capsys):
    path = proj / "docs" / "CTS관리대장" / "CTS관리대장_Config.md"
    path.write_text(_worknote("Configuration", [_req(1)], [ERR]), encoding="utf-8")
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION
    assert any(v["rule"] == "filename" for v in out["files"][0]["violations"])


def test_필수_절이_없으면_위반이다(proj, capsys):
    path = _write(proj, "CBO", "# CTS 관리대장 CBO\n\n버전: 0.1\n")
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION
    assert any(v["rule"] == "required_sections" for v in out["files"][0]["violations"])


@pytest.mark.parametrize("kind", list(KINDS))
def test_산출_xlsx_이름이_산출_규칙_패턴을_통과한다(proj, capsys, kind):
    _write(proj, kind, _worknote(kind, [_req(1)], []))
    code, report = _export(proj, capsys, kind)
    assert code == 0, report
    code, out = _check_rules(capsys, proj / report["files"][0])
    assert code == EXIT_PASS, out
    assert out["files"][0]["status"] == "pass"


def test_산출_xlsx_이름이_틀리면_산출_규칙이_위반으로_본다(proj, capsys):
    _write(proj, "CBO", _worknote("CBO", [_req(1)], []))
    _export(proj, capsys, "CBO")
    wrong = proj / "docs" / "CTS관리대장" / "CTS관리대장_CBO_최종.xlsx"
    _xlsx(proj, "CBO", "0.1").rename(wrong)
    code, out = _check_rules(capsys, wrong)
    assert code == EXIT_VIOLATION
    assert any(v["rule"] == "filename" for v in out["files"][0]["violations"])
