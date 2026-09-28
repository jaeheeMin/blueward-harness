"""CR-001(한글 이름), CR-002(반복문 안 DB 조회), CR-003(SELECT *),
CR-007(빈 CATCH)의 기계 검사(#54, #81)."""
from __future__ import annotations

from pathlib import Path

import pytest

from checker import code_rules
from checker.code_rules import EXIT_CANNOT_CHECK, EXIT_PASS, EXIT_VIOLATION, check_source, main


def _rules(findings: list[dict], rule: str) -> list[dict]:
    return [f for f in findings if f["rule"] == rule]


# --- CR-001 (ABAP) ---------------------------------------------------------


def test_abap_한글_변수명은_위반():
    findings = check_source("t.abap", "DATA 주문번호 TYPE vbeln.\n")
    hits = _rules(findings, "CR-001")
    assert len(hits) == 1
    assert hits[0]["allowed"] is False
    assert hits[0]["line"] == 1
    assert "주문번호" in hits[0]["message"]


def test_abap_큰따옴표_주석_안의_한글은_괜찮다():
    findings = check_source("t.abap", 'DATA lv_ok TYPE string. " 한글 주석\n')
    assert _rules(findings, "CR-001") == []


def test_abap_별표_주석_안의_한글은_괜찮다():
    findings = check_source("t.abap", "* 한글 전체 주석\nDATA lv_ok TYPE string.\n")
    assert _rules(findings, "CR-001") == []


def test_abap_작은따옴표_문자열_안의_한글은_괜찮다():
    findings = check_source("t.abap", "DATA lv_x TYPE string VALUE '한글 문자열'.\n")
    assert _rules(findings, "CR-001") == []


def test_abap_문자열_템플릿_안의_한글은_괜찮다():
    text = "lv_tmpl = |템플릿 { lv_text } 안의 한글|.\n"
    findings = check_source("t.abap", text)
    assert _rules(findings, "CR-001") == []


# --- CR-002 (ABAP) -----------------------------------------------------------


def test_abap_반복문_안의_select는_위반():
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        "  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.\n"
        "ENDLOOP.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1
    assert hits[0]["line"] == 2
    assert hits[0]["allowed"] is False


def test_abap_내부테이블에서_가져오는_select는_괜찮다():
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        "  SELECT * FROM @lt_order AS t INTO TABLE @lt_result.\n"
        "ENDLOOP.\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_반복문_밖의_select는_괜찮다():
    text = "SELECT * FROM vbak INTO TABLE lt_vbak WHERE vbeln IN lt_vbeln.\n"
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_do_안의_select도_위반():
    text = "DO 3 TIMES.\n  SELECT SINGLE * FROM vbak INTO ls_vbak.\nENDDO.\n"
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_while_안의_select도_위반():
    text = "WHILE lv_x < 10.\n  SELECT SINGLE * FROM vbak INTO ls_vbak.\nENDWHILE.\n"
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_endselect_반복문_안의_select도_위반():
    text = (
        "SELECT * FROM vbak INTO ls_vbak.\n"
        "  SELECT SINGLE * FROM vbap INTO ls_vbap WHERE vbeln = ls_vbak-vbeln.\n"
        "ENDSELECT.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_select_single은_endselect_반복문을_열지_않는다():
    """SELECT SINGLE 은 한 줄만 가져오므로 반복문을 열지 않는다.

    이것이 틀리면 SELECT SINGLE 뒤의 아무 관계 없는 SELECT 까지 반복문 안으로
    잘못 세어진다 — 실제로 처음 구현에서 이 결함이 있었다.
    """
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        "  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.\n"
        "ENDLOOP.\n"
        "SELECT * FROM vbak INTO TABLE lt_vbak FOR ALL ENTRIES IN lt_order WHERE vbeln = lt_order-vbeln.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_open_cursor가_반복문_안에_있으면_위반():
    text = "LOOP AT lt_order INTO ls_order.\n  OPEN CURSOR lv_cur FOR SELECT * FROM vbak.\nENDLOOP.\n"
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2
    assert "OPEN CURSOR" in hits[0]["message"]


def test_abap_open_cursor가_반복문_밖에_있으면_괜찮다():
    text = "OPEN CURSOR lv_cur FOR SELECT * FROM vbak.\n"
    assert _rules(check_source("t.abap", text), "CR-002") == []


# --- CR-003 (ABAP) ------------------------------------------------------------


def test_abap_select_star는_위반():
    text = "SELECT * FROM vbak INTO TABLE lt_vbak WHERE vbeln IN lt_vbeln.\n"
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["allowed"] is False


def test_abap_select_single_star도_위반():
    text = "SELECT SINGLE * FROM vbak INTO ls_vbak.\n"
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_select_distinct_star도_위반():
    text = "SELECT DISTINCT * FROM vbak INTO TABLE lt_vbak.\n"
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_새_문법_fields_star도_위반():
    text = "SELECT FROM vbak FIELDS * WHERE vbeln = lv_vbeln INTO TABLE @lt_vbak.\n"
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_조인의_별칭_전체_필드도_위반():
    text = (
        "SELECT a~*, b~carrid FROM spfli AS a JOIN sflight AS b "
        "ON a~carrid = b~carrid INTO TABLE @lt_result.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1
    assert "a~*" in hits[0]["message"]


def test_abap_필드_목록_select는_괜찮다():
    text = "SELECT vbeln, erdat, kunnr FROM vbak INTO TABLE lt_vbak WHERE vbeln IN lt_vbeln.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_새_문법_필드_목록도_괜찮다():
    text = "SELECT FROM vbak FIELDS vbeln, erdat WHERE vbeln = lv_vbeln INTO TABLE @lt_vbak.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_count_star는_괜찮다():
    text = "SELECT COUNT( * ) FROM vbak INTO lv_count.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_select_single_count_star도_괜찮다():
    text = "SELECT SINGLE COUNT( * ) FROM vbak INTO lv_count.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_문자열_안의_select_star는_괜찮다():
    text = "lv_x = ' SELECT * FROM vbak '.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_주석_안의_select_star는_괜찮다():
    text = "* SELECT * FROM vbak\nDATA lv_x TYPE i.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_cds는_cr003_설정에_없다():
    """CDS 의 `select from x { * }` 문법이 불확실해 이번에는 넣지 않았다(#81 보고 참고)."""
    cfg = code_rules._load_config()
    assert "cds" not in (cfg["rules"]["CR-003"].get("languages") or [])


# --- CR-007 (ABAP): 빈 CATCH ----------------------------------------------------


def test_abap_빈_catch는_위반():
    text = "TRY.\n    lo_service->call( ).\n  CATCH cx_root.\nENDTRY.\n"
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1
    assert hits[0]["line"] == 3
    assert hits[0]["allowed"] is False


def test_abap_주석만_있는_catch도_위반():
    text = (
        "TRY.\n"
        "    lo_service->call( ).\n"
        "  CATCH cx_root.\n"
        "    \" 나중에 처리한다\n"
        "ENDTRY.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1
    assert hits[0]["line"] == 3


def test_abap_처리_문장이_있는_catch는_괜찮다():
    text = (
        "TRY.\n"
        "    lo_service->call( ).\n"
        "  CATCH cx_root INTO lx_error.\n"
        "    MESSAGE lx_error->get_text( ) TYPE 'E'.\n"
        "ENDTRY.\n"
    )
    assert _rules(check_source("t.abap", text), "CR-007") == []


def test_abap_여러_catch가_모두_비어있으면_각각_위반():
    text = "TRY.\n    foo( ).\n  CATCH cx_a.\n  CATCH cx_b.\nENDTRY.\n"
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert sorted(h["line"] for h in hits) == [3, 4]


def test_abap_system_exceptions_빈_블록은_위반():
    text = "CATCH SYSTEM-EXCEPTIONS arithmetic_errors = 1.\nENDCATCH.\n"
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1
    assert "SYSTEM-EXCEPTIONS" in hits[0]["message"]


def test_abap_system_exceptions_처리_있으면_괜찮다():
    text = "CATCH SYSTEM-EXCEPTIONS arithmetic_errors = 1.\n  result = a / b.\nENDCATCH.\n"
    assert _rules(check_source("t.abap", text), "CR-007") == []


def test_abap_중첩_try_안쪽만_비어있으면_안쪽만_위반():
    text = (
        "TRY.\n"
        "    TRY.\n"
        "      foo( ).\n"
        "    CATCH cx_b.\n"
        "    ENDTRY.\n"
        "  CATCH cx_a.\n"
        "    handle( ).\n"
        "ENDTRY.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1
    assert hits[0]["line"] == 4


def test_abap_중첩_try_바깥쪽만_비어있으면_바깥쪽만_위반():
    text = (
        "TRY.\n"
        "    TRY.\n"
        "      foo( ).\n"
        "    CATCH cx_b.\n"
        "      handle_inner( ).\n"
        "    ENDTRY.\n"
        "  CATCH cx_a.\n"
        "ENDTRY.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1
    assert hits[0]["line"] == 7


# --- 예외: harness:allow ----------------------------------------------------


def test_이유가_있는_allow_주석은_예외로_인정한다():
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln. "#harness:allow CR-002 임시\n'
        "ENDLOOP.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1
    assert hits[0]["allowed"] is True
    assert "note" not in hits[0]


def test_바로_위_줄의_allow_주석도_인정한다():
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  "#harness:allow CR-002 다음 릴리스에서 FOR ALL ENTRIES 로 바꾼다\n'
        "  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.\n"
        "ENDLOOP.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1
    assert hits[0]["allowed"] is True


def test_이유_없는_allow_주석은_예외로_인정하지_않는다():
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln. "#harness:allow CR-002\n'
        "ENDLOOP.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1
    assert hits[0]["allowed"] is False
    assert "이유" in hits[0]["note"]


def test_다른_규칙번호의_allow는_적용되지_않는다():
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln. "#harness:allow CR-001 관계없음\n'
        "ENDLOOP.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["allowed"] is False


def test_cr003에_이유_있는_allow는_예외로_인정한다():
    text = 'SELECT * FROM vbak INTO TABLE lt_vbak. "#harness:allow CR-003 임시로 전체 조회\n'
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1 and hits[0]["allowed"] is True


def test_cr003에_이유_없는_allow는_예외로_인정하지_않는다():
    text = 'SELECT * FROM vbak INTO TABLE lt_vbak. "#harness:allow CR-003\n'
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1
    assert hits[0]["allowed"] is False
    assert "이유" in hits[0]["note"]


def test_cr007에_이유_있는_allow는_예외로_인정한다():
    text = (
        "TRY.\n"
        "    lo_service->call( ).\n"
        '  CATCH cx_root. "#harness:allow CR-007 로그는 상위에서 남긴다\n'
        "ENDTRY.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1 and hits[0]["allowed"] is True


def test_cr007에_이유_없는_allow는_예외로_인정하지_않는다():
    text = (
        "TRY.\n"
        "    lo_service->call( ).\n"
        '  CATCH cx_root. "#harness:allow CR-007\n'
        "ENDTRY.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-007")
    assert len(hits) == 1
    assert hits[0]["allowed"] is False
    assert "이유" in hits[0]["note"]


# --- JS/TS (CAP) -------------------------------------------------------------


def test_js_한글_이름은_위반():
    findings = check_source("t.js", "const 주문번호 = 1;\n")
    hits = _rules(findings, "CR-001")
    assert len(hits) == 1 and "주문번호" in hits[0]["message"]


def test_js_for_안의_select_from은_위반():
    text = (
        "async function h(req) {\n"
        "  for (const o of orders) {\n"
        "    await SELECT.from(Orders).where({ ID: o.ID });\n"
        "  }\n"
        "}\n"
    )
    hits = _rules(check_source("t.js", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 3
    assert "휴리스틱" in hits[0]["message"]


def test_js_반복문_밖의_select_from은_괜찮다():
    text = "async function h(req) {\n  const r = await SELECT.from(Orders);\n}\n"
    assert _rules(check_source("t.js", text), "CR-002") == []


def test_js_forEach_콜백_안의_insert도_위반():
    text = (
        "orders.forEach(async (o) => {\n"
        "  await INSERT.into(Log).entries({ id: o.ID });\n"
        "});\n"
    )
    hits = _rules(check_source("t.js", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_js_문자열과_주석_안의_한글은_괜찮다():
    text = "// 한글 주석\nconst ok = '한글 문자열';\nconst tpl = `템플릿 ${ok} 안`;\n"
    assert _rules(check_source("t.js", text), "CR-001") == []


# --- CR-007 (JS/TS) -------------------------------------------------------------


def test_js_빈_catch는_위반():
    text = "try {\n  doIt();\n} catch (e) {}\n"
    hits = _rules(check_source("t.js", text), "CR-007")
    assert len(hits) == 1 and hits[0]["line"] == 3


def test_js_바인딩_없는_빈_catch도_위반():
    text = "try {\n  doIt();\n} catch {}\n"
    hits = _rules(check_source("t.js", text), "CR-007")
    assert len(hits) == 1 and hits[0]["line"] == 3


def test_js_주석만_있는_catch도_위반():
    text = "try {\n  doIt();\n} catch (e) {\n  // 나중에 처리\n}\n"
    hits = _rules(check_source("t.js", text), "CR-007")
    assert len(hits) == 1


def test_js_처리_있는_catch는_괜찮다():
    text = "try {\n  doIt();\n} catch (e) {\n  log(e);\n}\n"
    assert _rules(check_source("t.js", text), "CR-007") == []


def test_js_promise_catch_화살표_빈_몸통은_위반():
    text = "promise.then(x => x).catch(() => {});\n"
    hits = _rules(check_source("t.js", text), "CR-007")
    assert len(hits) == 1


def test_js_promise_catch_function_빈_몸통도_위반():
    text = "promise.catch(function () {\n  // ignore\n});\n"
    hits = _rules(check_source("t.js", text), "CR-007")
    assert len(hits) == 1


def test_js_promise_catch_처리_있으면_괜찮다():
    text = "promise.catch(err => { log(err); });\n"
    assert _rules(check_source("t.js", text), "CR-007") == []


def test_js_promise_catch_이름_있는_콜백은_판정하지_않는다():
    """이름만 넘긴 콜백은 몸통을 볼 수 없어 놓친다(과검출보다 낫다, 모듈 docstring)."""
    text = "promise.catch(handleError);\n"
    assert _rules(check_source("t.js", text), "CR-007") == []


def test_js_주석_문자열_속_catch_모양은_괜찮다():
    text = "// catch {} in comment\nconst s = 'catch {}';\n"
    assert _rules(check_source("t.js", text), "CR-007") == []


# --- CDS ----------------------------------------------------------------------


def test_cds_한글_요소명은_위반():
    text = "define view entity Z_I_Order as select from vbak {\n  vbeln as 주문번호\n};\n"
    hits = _rules(check_source("t.cds", text), "CR-001")
    assert len(hits) == 1


def test_cds_주석_안의_한글은_괜찮다():
    text = "// 한글 주석\ndefine view entity Z_I_Order as select from vbak;\n"
    assert _rules(check_source("t.cds", text), "CR-001") == []


# --- BDEF(RAP 동작 정의, #72) --------------------------------------------------

BDEF_SAMPLE = """managed implementation in class zbp_bnh2_i_course unique;
strict ( 2 );

define behavior for ZBNH2_I_COURSE //alias <alias_name>
persistent table zbnh2_course
lock master
authorization master ( instance )
//etag master <field_name>
{
  create ( authorization : global );
  update;
  delete;
  field ( readonly, numbering : managed ) CourseUuid;
  field ( mandatory : create ) CourseId, CourseName, CourseLength, Price;
  field ( readonly : update ) CourseId;

  mapping for zbnh2_course corresponding
    {
      CourseUuid   = course_uuid;
      CourseId     = course_id;
      //Price = price;
      CurrencyCode = currency_code;
    }

}
"""


def test_bdef_한글_이름은_위반():
    findings = check_source("t.asbdef", "action 승인하기;\n")
    hits = _rules(findings, "CR-001")
    assert len(hits) == 1
    assert "승인하기" in hits[0]["message"]


def test_bdef_줄_주석_안의_한글은_괜찮다():
    text = "define behavior for Z_I_ORDER //한글 주석\n{\n}\n"
    assert _rules(check_source("t.asbdef", text), "CR-001") == []


def test_bdef_블록_주석_안의_한글은_괜찮다():
    text = "/* 한글 블록 주석 */\ndefine behavior for Z_I_ORDER\n{\n}\n"
    assert _rules(check_source("t.asbdef", text), "CR-001") == []


def test_bdef_문자열_안의_한글은_괜찮다():
    text = "define behavior for Z_I_ORDER\n{\n  //'한글 문자열' = 1;\n}\n"
    assert _rules(check_source("t.asbdef", text), "CR-001") == []


def test_bdef_실제_샘플은_통과():
    assert check_source("t.asbdef", BDEF_SAMPLE) == []


def test_bdef는_반복문_모양이_있어도_cr002를_적용하지_않는다():
    """BDEF 에는 반복문 개념이 없어 CR-002 설정 대상이 아니다."""
    text = "LOOP AT lt_x INTO ls_x.\n  SELECT SINGLE * FROM t001 INTO ls_y.\nENDLOOP.\n"
    assert _rules(check_source("t.asbdef", text), "CR-002") == []


def test_bdef는_cr002_설정에_없다():
    cfg = code_rules._load_config()
    assert "bdef" not in (cfg["rules"]["CR-002"].get("languages") or [])


# --- 확장자·읽기 실패 ----------------------------------------------------------


def test_모르는_확장자는_검사하지_않는다():
    assert check_source("t.txt", "주문번호") == []


def test_cli_모르는_확장자는_skipped로_센다(tmp_path: Path, capsys):
    target = tmp_path / "무관.txt"
    target.write_text("아무거나", encoding="utf-8")
    code = main([str(target)])
    assert code == EXIT_PASS
    report = _read_report(capsys)
    assert report["summary"]["skipped"] == 1
    assert report["files"][0]["status"] == "skipped"


def test_cli_읽을_수_없는_파일은_통과가_아니라_검사_불능이다(tmp_path: Path, capsys):
    target = tmp_path / "깨짐.abap"
    target.write_bytes(b"\xff\xfe\x00DATA")  # UTF-8 로 디코딩할 수 없다
    code = main([str(target)])
    assert code == EXIT_CANNOT_CHECK
    report = _read_report(capsys)
    assert report["files"][0]["status"] == "error"


def test_cli_존재하지_않는_파일도_검사_불능이다(tmp_path: Path, capsys):
    target = tmp_path / "없음.abap"
    code = main([str(target)])
    assert code == EXIT_CANNOT_CHECK


# --- CLI 통합 -------------------------------------------------------------------


def test_cli_위반이_있으면_종료코드_1(tmp_path: Path, capsys):
    target = tmp_path / "위반.abap"
    target.write_text("DATA 주문번호 TYPE vbeln.\n", encoding="utf-8")
    code = main([str(target)])
    assert code == EXIT_VIOLATION
    report = _read_report(capsys)
    assert report["summary"]["violations"] == 1
    assert report["files"][0]["status"] == "violation"


def test_cli_위반이_없으면_종료코드_0(tmp_path: Path, capsys):
    target = tmp_path / "통과.abap"
    target.write_text("DATA lv_order TYPE vbeln.\n", encoding="utf-8")
    code = main([str(target)])
    assert code == EXIT_PASS
    report = _read_report(capsys)
    assert report["summary"]["violations"] == 0
    assert report["files"][0]["status"] == "pass"


def test_cli_예외로_인정된_위반만_있으면_종료코드_0(tmp_path: Path, capsys):
    target = tmp_path / "예외.abap"
    target.write_text(
        "LOOP AT lt_order INTO ls_order.\n"
        # 필드 목록을 써서 CR-002(반복문 안 SELECT) 만 걸리게 한다 — `*` 를 쓰면
        # CR-003(SELECT *) 도 함께 걸려 이 테스트가 확인하려는 것(CR-002 하나만
        # 예외 처리됐을 때 통과하는지)이 흐려진다.
        '  SELECT SINGLE vbeln FROM vbak INTO ls_vbak-vbeln WHERE vbeln = ls_order-vbeln. "#harness:allow CR-002 이유\n'
        "ENDLOOP.\n",
        encoding="utf-8",
    )
    code = main([str(target)])
    assert code == EXIT_PASS
    report = _read_report(capsys)
    assert report["summary"]["allowed"] == 1
    assert report["files"][0]["status"] == "pass"


def _read_report(capsys) -> dict:
    import json

    return json.loads(capsys.readouterr().out)


def test_규칙_설정에_없는_언어는_그_규칙을_적용하지_않는다():
    """CDS 는 CR-002(반복문) 설정에 없다 — 반복문 개념이 없는 언어라서다."""
    cfg = code_rules._load_config()
    assert "cds" not in (cfg["rules"]["CR-002"].get("languages") or [])
