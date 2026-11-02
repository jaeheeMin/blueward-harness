"""User Role Mapping 산출(표 `펼침`)과 Spec 대조, 규칙 사본을 검증한다(이슈 #562, `/harness:role` 스킬).

고객 양식 xlsx 는 쓰지 않고 시험용 양식을 코드로 만든다. 지도는 public-cloud 의 사용자권한관리 지도와 같은 모양
(Role 개요 표 + Role 이 열로 늘어나는 메뉴 배정 + 머리글만 펼치는 ID-Role Mapping)이고 열 수만 줄였다
(Role 열 4개: 메뉴 배정 G~J, ID-Role Mapping P~S). 규칙은 스킬 폴더의 사본을 그대로 쓴다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import openpyxl
import pytest
import yaml
from openpyxl.styles import Border, Side

from checker import expand, export, role_check
from checker.cli import EXIT_PASS, EXIT_VIOLATION, main

SKILL = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "role"
FORM = "사용자권한관리"
OUT_NAME = "사용자권한관리_User_Role Mapping"
ROLE_COLS = ["Role ID", "Description", "주요 권한", "사용 대상자", "비고"]
MENU_COLS = ["Space", "Page", "Section", "Fiori App(한글)", "Fiori App(영문)", "Catalog"]
HEADER_TEXT = "ERP 시스템 사용자 권한 Master"

MAP = """\
양식: 사용자권한관리
설명: 시험용
템플릿: ../role_form.xlsx
산출:
  폴더: docs/권한관리
  파일명: "사용자권한관리_User_Role Mapping_v{버전}.xlsx"
  자리:
    버전: {메타: 버전}
견본_검사: true
시트:
  - 이름: Role 개요
    표:
      - 이름: Role 개요
        머리글_행: 2
        시작_행: 3
        최대_행: 10
        md_전용: [조직 레벨]
        열: {Role ID: C, Description: D, 주요 권한: E, 사용 대상자: F, 비고: G}
    유지: [A1:G2]
    머리글_유지: [ERP 시스템 사용자 권한 Master]
  - 이름: Role to Area Menu
    표:
      - 이름: 메뉴 배정
        머리글_행: 7
        시작_행: 8
        최대_행: 10
        열: {Space: A, Page: B, Section: C, Fiori App(한글): D, Fiori App(영문): E, Catalog: F}
        펼침:
          원본: {시트: Role 개요, 표: Role 개요, 열: Role ID}
          시작_열: G
          끝_열: J
          머리글: {3: Role ID, 4: Description, 5: 주요 권한, 6: 조직 레벨}
          표시: {열: Role, 값: O}
    서식_지우기: [G2:J2]
    유지: [A2:F7, G7:J7]
  - 이름: ID-Role Mapping
    표:
      - 이름: 사용자
        머리글_행: 5
        시작_행: 7
        최대_행: 10
        열: {사원 번호: A, 이름: B}
        펼침:
          원본: {시트: Role 개요, 표: Role 개요, 열: Role ID}
          시작_열: P
          끝_열: S
          머리글: {2: Role ID, 3: Description, 4: 주요 권한, 5: 조직 레벨}
    유지: [A1:O6, P6:S6]
"""


def _template(path: Path, header: bool = True) -> None:
    """Role 개요 / Role to Area Menu(7행에 COUNTA) / ID-Role Mapping(6행에 COUNTA). 데이터 칸은 테두리 서식이 있다."""
    wb = openpyxl.Workbook()
    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws = wb.active
    ws.title = "Role 개요"
    ws["C1"] = "Role 목록"
    for i, n in enumerate(ROLE_COLS):
        ws.cell(2, 3 + i, n)
        for r in range(3, 8):
            ws.cell(r, 3 + i).border = box
    if header:
        ws.oddHeader.center.text = HEADER_TEXT
    menu = wb.create_sheet("Role to Area Menu")
    for i, n in enumerate(MENU_COLS):
        menu.cell(7, 1 + i, n)
    menu["A2"] = "Role Description"
    for c in "GHIJ":
        menu[f"{c}7"] = f"=COUNTA({c}8:{c}17)"
        for r in range(3, 7):
            menu[f"{c}{r}"].border = box
        for r in range(8, 18):
            menu[f"{c}{r}"].border = box
    idm = wb.create_sheet("ID-Role Mapping")
    idm["A5"], idm["B5"], idm["O2"] = "사원 번호", "이름 1", "SAP Role ID"
    for c in "PQRS":
        idm[f"{c}6"] = f"=COUNTA({c}7:{c}16)"
        for r in range(2, 6):
            idm[f"{c}{r}"].border = box
        for r in range(7, 17):
            idm[f"{c}{r}"].border = box
    wb.save(path)


def _table(cols: list[str], rows: list[dict]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n" for r in rows)


R_COLS = ROLE_COLS + ["조직 레벨"]
ROLES = [
    {"Role ID": "Z_PP_100", "Description": "생산 담당", "주요 권한": "계획 반영", "조직 레벨": "플랜트"},
    {"Role ID": "Z_PP_200", "Description": "생산 조회", "주요 권한": "조회", "조직 레벨": "플랜트"},
    {"Role ID": "Z_MM_100", "Description": "구매 담당", "주요 권한": "발주", "조직 레벨": "구매 조직"},
]
MENU_COLS_ALL = MENU_COLS + ["Role"]
MENUS = [
    {"Space": "생산", "Page": "계획", "Fiori App(한글)": "생산계획 보드", "Catalog": "ZPP_BC_PRODPLANBOARD", "Role": "Z_PP_100, Z_PP_200"},
    {"Space": "", "Page": "", "Fiori App(한글)": "혼류 라인 마스터", "Catalog": "ZPP_BC_LINEGROUP", "Role": "Z_PP_100"},
    {"Space": "구매", "Page": "발주", "Fiori App(한글)": "발주 현황", "Catalog": "SAP_MM_BC_PO", "Role": "Z_MM_100"},
]


def _worknote(roles=ROLES, menus=MENUS, version="0.1", head: bool = True, id_section: bool = True) -> str:
    ver = f"버전: {version}\n\n" if head else ""
    idm = (
        f"### {FORM} · ID-Role Mapping\n\n양식 지도: 사람 행은 비워 두고 Role 머리글만 채운다.\n" if id_section else ""
    )
    return (
        f"# 사용자권한관리 (User Role Mapping)\n\n{ver}## 양식 항목\n\n"
        f"### {FORM} · Role 개요\n\n#### Role 개요\n\n{_table(R_COLS, roles)}\n"
        f"### {FORM} · Role to Area Menu\n\n#### 메뉴 배정\n\n{_table(MENU_COLS_ALL, menus)}\n{idm}"
    )


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    (tmp_path / "templates" / "forms").mkdir(parents=True)
    (tmp_path / "templates" / "harness").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "docs" / "권한관리").mkdir(parents=True)
    (tmp_path / "docs" / "spec").mkdir()
    (tmp_path / "templates" / "forms" / f"{FORM}.yaml").write_text(MAP, encoding="utf-8")
    _template(tmp_path / "templates" / "role_form.xlsx")
    (tmp_path / "rules" / "role.yaml").write_text((SKILL / "role.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "rules" / "role-output.yaml").write_text((SKILL / "role-output.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "templates" / "harness" / "role.md").write_text((SKILL / "role-template.md").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _write(proj: Path, text: str) -> Path:
    p = proj / "docs" / "권한관리" / f"{OUT_NAME}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _export(proj: Path, capsys, *extra: str):
    code = export.main(["--spec", str(proj / "docs" / "권한관리" / f"{OUT_NAME}.md"), "--form", FORM, "--root", str(proj), *extra])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, "stdout 은 JSON 한 줄이어야 한다"
    return code, json.loads(out)


def _xlsx(proj: Path, version: str = "0.1") -> Path:
    return proj / "docs" / "권한관리" / f"{OUT_NAME}_v{version}.xlsx"


def _check_rules(capsys, path: Path):
    code = main(["--auto", str(path)])
    return code, json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- 산출: 펼침

def test_Role_열이_머리글과_O_표시로_펼쳐지고_수식_서식이_남는다(proj, capsys):
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 0, report
    assert report["files"] == [f"docs/권한관리/{OUT_NAME}_v0.1.xlsx"]

    wb = openpyxl.load_workbook(_xlsx(proj))
    # Role 개요: 표 열은 C~G, 조직 레벨은 엑셀 열이 아니다
    ov = wb["Role 개요"]
    assert [ov.cell(r, 3).value for r in (3, 4, 5, 6)] == ["Z_PP_100", "Z_PP_200", "Z_MM_100", None]
    assert ov["D3"].value == "생산 담당"
    assert "조직 레벨" not in [c.value for row in ov.iter_rows() for c in row]
    # 메뉴 배정: 메뉴 행은 A~F, Role 머리글은 G부터 3~6행, 표시는 8행부터
    ws = wb["Role to Area Menu"]
    assert [ws.cell(3, c).value for c in (7, 8, 9, 10)] == ["Z_PP_100", "Z_PP_200", "Z_MM_100", None]
    assert [ws.cell(4, c).value for c in (7, 8, 9)] == ["생산 담당", "생산 조회", "구매 담당"]
    assert [ws.cell(6, c).value for c in (7, 8, 9)] == ["플랜트", "플랜트", "구매 조직"]
    assert ws["F8"].value == "ZPP_BC_PRODPLANBOARD" and ws["D9"].value == "혼류 라인 마스터"
    marks = {(c.row, c.column) for row in ws.iter_rows(min_row=8, min_col=7, max_col=10) for c in row if c.value == "O"}
    assert marks == {(8, 7), (8, 8), (9, 7), (10, 9)}
    # 수식과 서식은 그대로
    assert [ws.cell(7, c).value for c in (7, 8, 9, 10)] == [f"=COUNTA({x}8:{x}17)" for x in "GHIJ"]
    assert ws["G8"].border.left.style == "thin" and ws["J17"].border.left.style == "thin"
    # ID-Role Mapping: 머리글만 펼치고 사람 행은 비어 있다
    idm = wb["ID-Role Mapping"]
    assert [idm.cell(2, c).value for c in (16, 17, 18, 19)] == ["Z_PP_100", "Z_PP_200", "Z_MM_100", None]
    assert [idm.cell(5, c).value for c in (16, 17, 18)] == ["플랜트", "플랜트", "구매 조직"]
    assert [idm.cell(6, c).value for c in (16, 19)] == ["=COUNTA(P7:P16)", "=COUNTA(S7:S16)"]
    assert all(c.value is None for row in idm.iter_rows(min_row=7, max_row=16) for c in row)
    assert idm["A5"].value == "사원 번호" and idm["O2"].value == "SAP Role ID"  # 양식 라벨


def test_표시가_없는_펼침은_머리글만_쓴다(proj, capsys):
    _write(proj, _worknote(menus=[]))
    code, report = _export(proj, capsys)
    assert code == 0, report
    ws = openpyxl.load_workbook(_xlsx(proj))["Role to Area Menu"]
    assert ws["G3"].value == "Z_PP_100"
    assert all(c.value is None for row in ws.iter_rows(min_row=8, min_col=7, max_col=10) for c in row)


def test_Role_개요가_비면_펼친_머리글이_모두_비고_표시가_있으면_거부된다(proj, capsys):
    _write(proj, _worknote(roles=[], menus=[]))
    code, report = _export(proj, capsys)
    assert code == 0, report
    ws = openpyxl.load_workbook(_xlsx(proj))["Role to Area Menu"]
    assert all(ws.cell(r, c).value is None for r in (3, 4, 5, 6) for c in (7, 8, 9, 10))
    _write(proj, _worknote(roles=[], menus=MENUS))
    code, report = _export(proj, capsys)
    assert code == 2 and "Z_PP_100" in json.dumps(report, ensure_ascii=False)


def test_양식_열보다_Role이_많으면_산출을_거부한다(proj, capsys):
    many = ROLES + [{"Role ID": f"Z_X_{n}", "Description": "추가"} for n in range(2)]  # 5개 > 4열
    _write(proj, _worknote(roles=many, menus=[]))
    code, report = _export(proj, capsys)
    assert code == 1, report
    assert any("G~J" in p["reason"] and "넘는다" in p["reason"] for p in report["problems"])
    assert not _xlsx(proj).exists()


def test_딱_맞는_Role_수는_산출된다(proj, capsys):
    four = ROLES + [{"Role ID": "Z_MM_200", "Description": "구매 조회"}]
    _write(proj, _worknote(roles=four, menus=[]))
    code, report = _export(proj, capsys)
    assert code == 0, report
    assert openpyxl.load_workbook(_xlsx(proj))["Role to Area Menu"]["J3"].value == "Z_MM_200"


def test_같은_Role_ID가_둘이면_거부한다(proj, capsys):
    _write(proj, _worknote(roles=ROLES + [dict(ROLES[0])], menus=[]))
    code, report = _export(proj, capsys)
    assert code == 1 and any("같은 값" in p["reason"] and "Z_PP_100" in p["reason"] for p in report["problems"])


def test_Role_개요에_없는_Role을_표시하면_산출이_멈춘다(proj, capsys):
    bad = [dict(MENUS[0], Role="Z_PP_100, Z_NOPE")]
    _write(proj, _worknote(menus=bad))
    code, report = _export(proj, capsys)
    assert code == 2
    text = json.dumps(report, ensure_ascii=False)
    assert "Z_NOPE" in text and "Z_PP_100" in text
    assert not _xlsx(proj).exists()


def test_펼침이_없는_표와_md_전용_밖의_열은_예전처럼_동작한다(proj, capsys):
    # 지도에서 펼침과 md_전용을 걷어 낸 표는 예전과 같다: 모르는 열은 읽지 못함
    (proj / "templates" / "forms" / f"{FORM}.yaml").write_text(
        MAP.replace("        md_전용: [조직 레벨]\n", ""), encoding="utf-8")
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 2 and "조직 레벨" in json.dumps(report, ensure_ascii=False)


def test_Role_열을_쓰면_이전_판처럼_행이_비워진다_행이_줄면_남는_표시는_지워진다(proj, capsys):
    _write(proj, _worknote())
    assert _export(proj, capsys)[0] == 0
    _write(proj, _worknote(menus=MENUS[:1], version="0.2"))
    code, report = _export(proj, capsys)
    assert code == 0, report
    ws = openpyxl.load_workbook(_xlsx(proj, "0.2"))["Role to Area Menu"]
    marks = {(c.row, c.column) for row in ws.iter_rows(min_row=8, min_col=7, max_col=10) for c in row if c.value == "O"}
    assert marks == {(8, 7), (8, 8)}


# ---------------------------------------------------------------- 지도 검사

@pytest.mark.parametrize(
    "old, new, needle",
    [
        ("          시작_열: G\n          끝_열: J", "          시작_열: J\n          끝_열: G", "오른쪽"),
        ("          시작_열: G\n          끝_열: J", "          시작_열: E\n          끝_열: J", "겹친다"),
        ("머리글: {3: Role ID, 4: Description, 5: 주요 권한, 6: 조직 레벨}", "머리글: {8: Role ID}", "시작_행"),
        ("표시: {열: Role, 값: O}", "표시: {열: Catalog, 값: O}", "작업본 전용"),
        ("    서식_지우기: [G2:J2]\n", "    서식_지우기: [G3:J3]\n", "겹친다"),
    ],
)
def test_펼침_지도_오류는_산출이_종료코드_2로_멈춘다(proj, capsys, old, new, needle):
    assert old in MAP
    (proj / "templates" / "forms" / f"{FORM}.yaml").write_text(MAP.replace(old, new, 1), encoding="utf-8")
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 2 and needle in json.dumps(report, ensure_ascii=False)


def test_기본_빈_양식_비우기는_펼친_영역을_포함한다():
    ws = yaml.safe_load(MAP)["시트"][1]
    ed = _ed_with_marks()
    ranges = export.fill_ranges(ed, ws)
    assert "G3:J3" in ranges and "G6:J6" in ranges and "G8:J17" in ranges


def _ed_with_marks():
    from checker.export import SheetXml

    return SheetXml('<worksheet><sheetData/></worksheet>', set(), False)


# ---------------------------------------------------------------- 머리글_유지(고정 문구)

def test_머리글_유지에_적은_고정_문구는_leftover_review를_내지_않는다(proj, capsys):
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 0 and not any(w.get("type") == "leftover-review" for w in report["warnings"])


def test_머리글_유지가_없으면_머리글_바닥글_경고가_난다(proj, capsys):
    (proj / "templates" / "forms" / f"{FORM}.yaml").write_text(
        MAP.replace("    머리글_유지: [ERP 시스템 사용자 권한 Master]\n", ""), encoding="utf-8")
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 3
    assert any(w.get("type") == "leftover-review" and HEADER_TEXT in w["reason"] for w in report["warnings"])


def test_머리글_유지와_다른_문구는_여전히_경고한다(proj, capsys):
    (proj / "templates" / "forms" / f"{FORM}.yaml").write_text(
        MAP.replace("[ERP 시스템 사용자 권한 Master]", "[다른 문구]"), encoding="utf-8")
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 3 and any(w.get("type") == "leftover-review" for w in report["warnings"])


# ---------------------------------------------------------------- 규칙 사본과 form_columns

def test_규칙_사본은_스킬_폴더에_있고_읽힌다():
    for name in ("role.yaml", "role-output.yaml", "role-template.md", "SKILL.md"):
        assert (SKILL / name).is_file(), name
    rules = yaml.safe_load((SKILL / "role.yaml").read_text(encoding="utf-8"))
    assert rules["관할"] == "docs/권한관리/*.md"
    assert [r["종류"] for r in rules["규칙"]] == ["filename", "required_sections", "form_columns"]
    assert yaml.safe_load((SKILL / "role-output.yaml").read_text(encoding="utf-8"))["관할"] == "docs/권한관리/*.xlsx"


def test_지도_안의_작업본은_규칙을_통과한다(proj, capsys):
    code, out = _check_rules(capsys, _write(proj, _worknote()))
    assert code == EXIT_PASS, out
    assert out["files"][0]["type"] == "role"


def test_Role_열은_허용_열이고_Role_개요에_없는_값은_위반이다(proj, capsys):
    bad = [dict(MENUS[0], Role="Z_PP_100, Z_NOPE")]
    code, out = _check_rules(capsys, _write(proj, _worknote(menus=bad)))
    assert code == EXIT_VIOLATION
    [v] = [v for v in out["files"][0]["violations"] if v["rule"] == "form_columns"]
    assert v["actual"] == "Z_NOPE" and "Role" in v["message"] and "Z_PP_100" in v["expected"]


def test_표시_열_이름이_틀리면_양식_밖_열이다(proj, capsys):
    text = _worknote().replace("| Catalog | Role |", "| Catalog | 롤 |", 1)
    code, out = _check_rules(capsys, _write(proj, text))
    assert code == EXIT_VIOLATION
    assert any(v["rule"] == "form_columns" and v["actual"] == "롤" for v in out["files"][0]["violations"])


def test_모르는_열과_다른_양식_이름은_위반이다(proj, capsys):
    text = _worknote().replace("| Role ID | Description |", "| Role ID | 설명 |", 1)
    code, out = _check_rules(capsys, _write(proj, text))
    assert code == EXIT_VIOLATION
    assert any(v["rule"] == "form_columns" and v["actual"] == "설명" for v in out["files"][0]["violations"])


def test_산출_xlsx_이름이_산출_규칙_패턴을_통과한다(proj, capsys):
    _write(proj, _worknote())
    code, report = _export(proj, capsys)
    assert code == 0, report
    code, out = _check_rules(capsys, proj / report["files"][0])
    assert code == EXIT_PASS, out


def test_작업본_파일명이_틀리면_위반이다(proj, capsys):
    path = proj / "docs" / "권한관리" / "사용자권한관리.md"
    path.write_text(_worknote(), encoding="utf-8")
    code, out = _check_rules(capsys, path)
    assert code == EXIT_VIOLATION and any(v["rule"] == "filename" for v in out["files"][0]["violations"])


# ---------------------------------------------------------------- Spec 대조

SPEC = """\
# DEV-012 생산계획 보드

## Launchpad 노출

| 타일 제목 | 부제 | 카탈로그 | 배치 |
|---|---|---|---|
| 생산계획 보드 | - | `ZPP_BC_PRODPLANBOARD` | 배정 완료 |
| 혼류 라인 마스터 | - | ZPP_BC_LINEGROUP | 배정 완료 |
| 새 타일 | - | ZPP_BC_NEW | 아직 |
| 카탈로그 없음 | - | 없음 | - |

두 번째 표.

## 사용 객체
"""


def _role_check(capsys, proj: Path, *extra: str):
    code = role_check.main([
        "--workbook", str(proj / "docs" / "권한관리" / f"{OUT_NAME}.md"), "--form", FORM,
        "--sheet", "Role to Area Menu", "--table", "메뉴 배정", "--column", "Catalog", *extra,
    ])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def test_Spec의_카탈로그가_작업본에_없으면_목록으로_알린다(proj, capsys):
    _write(proj, _worknote())
    (proj / "docs" / "spec" / "DEV-012-생산계획보드.md").write_text(SPEC, encoding="utf-8")
    code, rep = _role_check(capsys, proj, "--spec-dir", str(proj / "docs" / "spec"))
    assert code == 1 and rep["status"] == "missing"
    assert rep["missing"] == [{"spec": "DEV-012-생산계획보드.md", "catalog": "ZPP_BC_NEW", "tile": "새 타일"}]
    assert rep["specs_checked"] == 1


def test_모두_있으면_ok_이고_Launchpad_절이_없는_Spec은_건너뛴다(proj, capsys):
    _write(proj, _worknote())
    (proj / "docs" / "spec" / "DEV-012-a.md").write_text(SPEC.replace("ZPP_BC_NEW", "SAP_MM_BC_PO"), encoding="utf-8")
    (proj / "docs" / "spec" / "DEV-013-b.md").write_text("# DEV-013\n\n## 개요\n\n내용\n", encoding="utf-8")
    code, rep = _role_check(capsys, proj, "--spec-dir", str(proj / "docs" / "spec"))
    assert code == 0 and rep["status"] == "ok" and rep["skipped"] == ["DEV-013-b.md"] and rep["missing"] == []


def test_작업본이_비어도_카탈로그는_모두_빠진_것이다(proj, capsys):
    _write(proj, _worknote(menus=[]))
    (proj / "docs" / "spec" / "DEV-012-a.md").write_text(SPEC, encoding="utf-8")
    code, rep = _role_check(capsys, proj, "--spec", str(proj / "docs" / "spec" / "DEV-012-a.md"))
    assert code == 1 and {m["catalog"] for m in rep["missing"]} == {"ZPP_BC_PRODPLANBOARD", "ZPP_BC_LINEGROUP", "ZPP_BC_NEW"}


def test_읽지_못한_Spec이나_작업본은_검사_불능이다(proj, capsys):
    _write(proj, _worknote())
    (proj / "docs" / "spec" / "DEV-012-a.md").write_text(SPEC.replace("카탈로그", "카탈"), encoding="utf-8")
    code, rep = _role_check(capsys, proj, "--spec-dir", str(proj / "docs" / "spec"))
    assert code == 2 and rep["status"] == "error" and rep["unchecked"][0]["spec"] == "DEV-012-a.md"
    # 작업본 파일이 없다
    (proj / "docs" / "권한관리" / f"{OUT_NAME}.md").unlink()
    code, rep = _role_check(capsys, proj, "--spec-dir", str(proj / "docs" / "spec"))
    assert code == 2 and rep["status"] == "error"


def test_catalogs_in은_밑줄이_든_이름만_취한다():
    assert role_check.catalogs_in("`ZPP_BC_A`, ZPP_BC_B (게시 안 됨)") == ["ZPP_BC_A", "ZPP_BC_B"]
    assert role_check.catalogs_in("-") == [] and role_check.catalogs_in("없음") == []


def test_expand_split_values():
    assert expand.split_values("A, B<br>C\nD") == ["A", "B", "C", "D"]
