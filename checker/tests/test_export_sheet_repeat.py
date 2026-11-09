"""견본 시트 반복 복제(`반복: true`, #830)를 검증한다. 시험 템플릿은 openpyxl 로 코드에서 만든다.

Test Case 양식을 본뜬다: 고정 시트 Info, 견본 TC1(제목 칸 A3, 집계 수식, 데이터 유효성, 메모, 인쇄 제목),
함께 든 다른 견본 TC2(`빼기`).
"""
from __future__ import annotations

import json
import posixpath
import re
import zipfile
from pathlib import Path

import openpyxl
import pytest
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

from checker import export, sheet_repeat
from checker.blank_template import map_problems

MAP = """\
양식: 반복양식
설명: 시험용
템플릿: ../반복.xlsx
산출:
  폴더: docs/out
  파일명: "R_v{버전}.xlsx"
  자리:
    버전: {메타: 버전}
시트:
  - 이름: Info
    칸:
      - 항목: 프로젝트
        위치: B2
  - 이름: TC1
    반복: true
    빼기: [TC2]
    칸:
      - 항목: ID
        위치: A1
      - 항목: 제목
        위치: A3
        형식: "{ID} : {값}"
        필수: true
    표:
      - 이름: 단계
        머리글_행: 8
        시작_행: 9
        열: {순서: B, 수행업무: C, 결과: K}
        최대_행: 5
"""

SPEC = """\
# 시험

버전: 0.1

## 양식 항목

### 반복양식 · Info

| 항목 | 값 |
|---|---|
| 프로젝트 | 블루워드 |

### 반복양식 · TC1 · FI.01.03.02.02

| 항목 | 값 |
|---|---|
| 제목 | 로그인 |

#### 단계

| 순서 | 수행업무 | 결과 |
|---|---|---|
| 1 | 로그인 화면 진입 | P |
| 2 | ID 입력 | F |

### 반복양식 · TC1 · FI.02.03.02

| 항목 | 값 |
|---|---|
| 제목 | 조회 |

#### 단계

| 순서 | 수행업무 | 결과 |
|---|---|---|
| 1 | 조회 | P |
"""


def _template(path: Path) -> None:
    wb = openpyxl.Workbook()
    info = wb.active
    info.title = "Info"
    info["A2"], info["B2"] = "프로젝트", "견본"
    for name in ("TC1", "TC2"):
        ws = wb.create_sheet(name)
        ws["A1"] = name
        ws["A3"] = "견본 제목"
        ws["K1"] = '=COUNTIF(J$9:J$774,"=Yes")'
        ws["K2"] = '=COUNTIF(K$9:K$774,"=P")'
        ws["B8"], ws["C8"], ws["K8"] = "순서", "수행업무", "결과"
        dv = DataValidation(type="list", formula1='"P,PP,F,N/A"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add("K9:K19")
        ws["B9"] = "견본1"
        ws["C9"] = "견본 업무"
        ws["C9"].comment = Comment(f"{name} 메모", "t")
        ws.print_title_rows = "7:8"
        ws.page_setup.orientation = "landscape"
    wb.create_sheet("끝")
    wb.save(path)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    (tmp_path / "templates" / "forms").mkdir(parents=True)
    (tmp_path / "templates" / "forms" / "반복양식.yaml").write_text(MAP, encoding="utf-8")
    _template(tmp_path / "templates" / "반복.xlsx")
    return tmp_path


def _run(proj: Path, capsys, spec: str = SPEC, *extra: str):
    p = proj / "spec.md"
    p.write_text(spec, encoding="utf-8")
    code = export.main(["--spec", str(p), "--root", str(proj), *extra])
    return code, json.loads(capsys.readouterr().out)


def _out(proj: Path, report: dict) -> Path:
    assert len(report["files"]) == 1, report
    return proj / report["files"][0]


def test_견본을_소절마다_복제하고_견본과_빼기_시트는_빠진다(proj, capsys):
    code, rep = _run(proj, capsys)
    assert code == 0, rep
    wb = openpyxl.load_workbook(_out(proj, rep))
    assert wb.sheetnames == ["Info", "FI.01.03.02.02", "FI.02.03.02", "끝"]
    a, b = wb["FI.01.03.02.02"], wb["FI.02.03.02"]
    assert wb["Info"]["B2"].value == "블루워드"
    assert a["A1"].value == "FI.01.03.02.02" and b["A1"].value == "FI.02.03.02"  # 항목 ID 는 작업본에 안 적어도 채워진다
    assert a["A3"].value == "FI.01.03.02.02 : 로그인"
    assert b["A3"].value == "FI.02.03.02 : 조회"
    assert (a["C9"].value, a["K9"].value, a["C10"].value, a["K10"].value) == ("로그인 화면 진입", "P", "ID 입력", "F")
    assert (b["C9"].value, b["K9"].value) == ("조회", "P")
    assert b["C10"].value is None  # 쓰지 않은 행의 견본 값은 비워진다


def test_수식은_그대로이고_데이터_유효성과_인쇄_제목_메모가_복제본마다_있다(proj, capsys):
    code, rep = _run(proj, capsys)
    wb = openpyxl.load_workbook(_out(proj, rep))
    for n in ("FI.01.03.02.02", "FI.02.03.02"):
        ws = wb[n]
        assert ws["K1"].value == '=COUNTIF(J$9:J$774,"=Yes")'
        assert ws["K2"].value == '=COUNTIF(K$9:K$774,"=P")'
        assert [str(dv.sqref) for dv in ws.data_validations.dataValidation] == ["K9:K19"]
        assert ws.print_title_rows == "$7:$8"
    with zipfile.ZipFile(_out(proj, rep)) as zf:
        wbx = zf.read("xl/workbook.xml").decode()
        assert 'fullCalcOnLoad="1"' in wbx
        assert not any("calcChain" in n for n in zf.namelist())  # 빠진 시트의 계산 순서가 남지 않게 지웠다


def test_zip_연결이_맞는다(proj, capsys):
    code, rep = _run(proj, capsys)
    with zipfile.ZipFile(_out(proj, rep)) as zf:
        names = set(zf.namelist())
        ct = zf.read("[Content_Types].xml").decode()
        wbx = zf.read("xl/workbook.xml").decode()
        rels = zf.read("xl/_rels/workbook.xml.rels").decode()
        # [Content_Types] 의 Override 는 모두 실제 파트를 가리킨다
        for part in re.findall(r'<Override PartName="/([^"]+)"', ct):
            assert part in names, part
        # 시트마다 rId 가 있고 가리키는 파트가 있으며, 시트 파트는 Override 가 있다
        sheet_tags = re.findall(r"<sheet [^>]*/>", wbx)
        assert len(sheet_tags) == 4
        ids = [re.search(r'sheetId="(\d+)"', t).group(1) for t in sheet_tags]
        assert len(set(ids)) == 4
        for t in sheet_tags:
            rid = re.search(r'r:id="([^"]+)"', t).group(1)
            target = re.search(rf'<Relationship [^>]*Id="{rid}"[^>]*Target="([^"]+)"', rels) or re.search(
                rf'<Relationship [^>]*Target="([^"]+)"[^>]*Id="{rid}"', rels)
            part = "xl/" + target.group(1).lstrip("/").removeprefix("xl/")
            assert part in names and f'PartName="/{part}"' in ct
        # 모든 rels 의 내부 대상이 실제로 있다(메모·vml·프린터 설정이 복제본마다 따로 있다)
        for n in names:
            if n.endswith(".rels"):
                base = "x" if n == "_rels/.rels" else n.replace("/_rels/", "/")[:-5]
                for t, mode in re.findall(r'Target="([^"]+)"(?:\s+TargetMode="(\w+)")?', zf.read(n).decode()):
                    if mode == "External":
                        continue
                    import posixpath
                    tgt = t[1:] if t.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(base), t))
                    assert tgt in names, (n, t)
        # 복제본은 서로 다른 메모 파트를 쓴다
        comments = [n for n in names if re.fullmatch(r"xl/comments/comment\d+\.xml", n)]
        assert len(comments) == 2
        # 정의된 이름: 인쇄 제목은 복제본마다, localSheetId 는 새 순서
        dn = re.findall(r'<definedName [^>]*localSheetId="(\d+)"[^>]*>([^<]*)</definedName>', wbx)
        assert sorted((int(i), t) for i, t in dn if "Print_Titles" in wbx) == [
            (1, "'FI.01.03.02.02'!$7:$8"), (2, "'FI.02.03.02'!$7:$8")]
        uids = re.findall(r'xr:uid="([^"]+)"', "".join(zf.read(n).decode() for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)))
        assert len(uids) == len(set(uids))


def test_소절이_하나도_없으면_견본을_빼고_경고한다(proj, capsys):
    spec = SPEC.split("### 반복양식 · TC1")[0]
    code, rep = _run(proj, capsys, spec)
    assert code == export.EXIT_OK or code == export.EXIT_WARNING
    assert any("복제본 없음" in w["reason"] for w in rep["warnings"]), rep
    wb = openpyxl.load_workbook(_out(proj, rep))
    assert wb.sheetnames == ["Info", "끝"]


@pytest.mark.parametrize("sid,why", [
    ("A" * 32, "32자"),
    ("FI/01", "쓸 수 없는 문자"),
    ("a[1]", "쓸 수 없는 문자"),
    ("끝", "겹친다"),
    ("info", "겹친다"),
])
def test_시트_이름_규칙을_어기면_거부한다(proj, capsys, sid, why):
    code, rep = _run(proj, capsys, SPEC.replace("FI.02.03.02", sid))
    assert code == export.EXIT_REJECTED, rep
    assert any(why in p["reason"] for p in rep["problems"]), rep["problems"]
    assert rep["files"] == []


def test_ID가_서로_겹치면_거부한다(proj, capsys):
    code, rep = _run(proj, capsys, SPEC.replace("FI.02.03.02", "fi.01.03.02.02"))
    assert code == export.EXIT_REJECTED
    assert any("겹친다" in p["reason"] for p in rep["problems"])


def test_견본_이름만_쓴_소절은_읽지_못함(proj, capsys):
    code, rep = _run(proj, capsys, SPEC + "\n### 반복양식 · TC1\n\n해당 없음\n")
    assert code == export.EXIT_ERROR
    assert "반복 견본" in json.dumps(rep, ensure_ascii=False)


def test_빼기_시트에는_소절을_쓸_수_없다(proj, capsys):
    code, rep = _run(proj, capsys, SPEC + "\n### 반복양식 · TC2\n\n해당 없음\n")
    assert code == export.EXIT_ERROR


def test_복제_소절_안_양식_밖_표_열은_읽지_못함(proj, capsys):
    code, rep = _run(proj, capsys, SPEC.replace("| 순서 | 수행업무 | 결과 |", "| 순서 | 수행업무 | 오타 |", 1))
    assert code == export.EXIT_ERROR


def test_필수_칸이_비면_그_복제본만_짚어_거부한다(proj, capsys):
    code, rep = _run(proj, capsys, SPEC.replace("| 제목 | 조회 |", "| 제목 | 미정 |"))
    assert code == export.EXIT_REJECTED
    assert [p["sheet"] for p in rep["problems"]] == ["FI.02.03.02"]


def test_drawing이_딸린_견본은_복제하지_않고_검사_불능(proj, capsys):
    tpl = proj / "templates" / "반복.xlsx"
    with zipfile.ZipFile(tpl) as zi:
        parts = {n: zi.read(n) for n in zi.namelist()}
    rp = "xl/worksheets/_rels/sheet2.xml.rels"
    rels = parts.get(rp, b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>').decode()
    rels = rels.replace("</Relationships>", '<Relationship Id="rId99" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>')
    parts[rp] = rels.encode()
    parts["xl/drawings/drawing1.xml"] = b"<x/>"
    with zipfile.ZipFile(tpl, "w") as zo:
        for n, d in parts.items():
            zo.writestr(n, d)
    code, rep = _run(proj, capsys)
    assert code == export.EXIT_ERROR
    assert "복제할 수 없는" in json.dumps(rep, ensure_ascii=False)


def test_지도_키_모양_검사():
    base = {"시트": [{"이름": "A", "반복": "예"}, {"이름": "B", "빼기": ["C"]}, {"이름": "C"},
                    {"이름": "D", "반복": True, "빼기": ["C"]}]}
    msgs = " | ".join(m for _, m in map_problems(base))
    assert "`반복` 은 true/false" in msgs
    assert "`빼기` 는 `반복: true`" in msgs
    assert "지도에 시트 항목으로 있는 시트" in msgs


def test_시트_이름_검사_함수():
    assert sheet_repeat.name_problem("FI.01.03.02.02") is None
    assert sheet_repeat.name_problem("") and sheet_repeat.name_problem("x" * 32)
    assert sheet_repeat.name_problem("a:b") and sheet_repeat.name_problem("'a")


def test_빈_양식_만들기는_반복_지도에서도_예외_없이_돈다(proj):
    from checker import blank_template

    built = blank_template.build_blank(proj, "반복양식", proj / "templates" / "반복.xlsx")
    assert built is not None


APP = (
    '<Properties xmlns="x" xmlns:vt="y"><HeadingPairs><vt:vector size="4" baseType="variant"><vt:variant><vt:lpstr>워크시트</vt:lpstr></vt:variant>'
    '<vt:variant><vt:i4>4</vt:i4></vt:variant><vt:variant><vt:lpstr>이름 지정된 범위</vt:lpstr></vt:variant><vt:variant><vt:i4>3</vt:i4></vt:variant>'
    '</vt:vector></HeadingPairs><TitlesOfParts><vt:vector size="7" baseType="lpstr"><vt:lpstr>A</vt:lpstr><vt:lpstr>B</vt:lpstr><vt:lpstr>C</vt:lpstr>'
    '<vt:lpstr>D</vt:lpstr><vt:lpstr>C!Print_Titles</vt:lpstr><vt:lpstr>D!Print_Titles</vt:lpstr><vt:lpstr>B!Print_Titles</vt:lpstr></vt:vector></TitlesOfParts></Properties>'
)


def test_app_xml_시트_목록과_개수가_새_시트에_맞는다():
    out = sheet_repeat._app_xml(APP, ["A", "B", "X & Y", "Z", "W"], lambda r: None)
    assert "<vt:i4>5</vt:i4>" in out and 'size="5" baseType="lpstr"' in out
    assert "X &amp; Y" in out and "Print_Titles" not in out and "이름 지정된 범위" not in out
