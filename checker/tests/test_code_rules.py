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


def test_abap_금액_같은_한글_변수명도_여전히_위반():
    findings = check_source("t.abap", "DATA 금액 TYPE i.\n")
    hits = _rules(findings, "CR-001")
    assert len(hits) == 1 and "금액" in hits[0]["message"]


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


# --- CR-002 (ABAP): 집계 함수·내부 테이블 대상은 반복문을 열지 않는다(#83) -----------


def test_abap_count_집계함수만_있는_select는_반복문을_열지_않는다():
    """이슈 #83 예시: COUNT( * ) 로 끝나는 SELECT 뒤의 무관한 SELECT 는 CR-002 가 아니다."""
    text = (
        "SELECT COUNT( * ) FROM vbak INTO @DATA(lv_n).\n"
        "SELECT vbeln FROM vbak INTO TABLE @DATA(lt).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_새_문법_fields_집계함수만_있으면_반복문을_열지_않는다():
    text = (
        "SELECT FROM vbak FIELDS COUNT( * ) INTO @DATA(lv_n).\n"
        "SELECT vbeln FROM vbak INTO TABLE @DATA(lt).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_집계함수_여러개_나열해도_반복문을_열지_않는다():
    text = (
        "SELECT SUM( netwr ), MAX( erdat ) FROM vbak INTO (@DATA(lv_sum), @DATA(lv_max)).\n"
        "SELECT vbeln FROM vbak INTO TABLE @DATA(lt).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_집계함수에_별칭이_붙어도_반복문을_열지_않는다():
    text = (
        "SELECT FROM vbak FIELDS COUNT( * ) AS cnt, MAX( erdat ) AS last\n"
        "  WHERE vkorg = @lv_vkorg INTO @DATA(ls_stat).\n"
        "SELECT vbeln FROM vbak INTO TABLE @DATA(lt).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_옛_문법_집계함수를_공백으로_나열해도_반복문을_열지_않는다():
    text = (
        "SELECT MAX( erdat ) MIN( erdat ) FROM vbak INTO (lv_max, lv_min).\n"
        "SELECT vbeln FROM vbak INTO TABLE lt.\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_집계만이라도_union_이_있으면_반복문으로_본다():
    text = (
        "SELECT FROM vbak FIELDS MAX( erdat ) AS d\n"
        "  UNION SELECT FROM vbap FIELDS MAX( erdat ) AS d INTO @DATA(ls_d).\n"
        "  SELECT vbeln FROM vbak INTO TABLE @DATA(lt).\n"
        "ENDSELECT.\n"
    )
    assert len(_rules(check_source("t.abap", text), "CR-002")) == 1


def test_abap_집계와_일반_필드가_섞이면_반복문으로_본다():
    text = (
        "SELECT vkorg COUNT( * ) FROM vbak INTO (lv_vkorg, lv_n).\n"
        "  SELECT vbeln FROM vbap INTO TABLE lt.\n"
        "ENDSELECT.\n"
    )
    assert len(_rules(check_source("t.abap", text), "CR-002")) == 1


def test_abap_into_corresponding_fields_of_table_뒤_select는_반복문을_열지_않는다():
    text = (
        "SELECT * FROM vbak INTO CORRESPONDING FIELDS OF TABLE @DATA(lt_vbak).\n"
        "SELECT vbeln FROM vbap INTO TABLE @DATA(lt_vbap).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_appending_table_뒤_select는_반복문을_열지_않는다():
    text = (
        "SELECT vbeln FROM vbak APPENDING TABLE @DATA(lt_vbak).\n"
        "SELECT vbeln FROM vbap INTO TABLE @DATA(lt_vbap).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-002") == []


def test_abap_진짜_endselect_반복문_안의_select는_여전히_위반():
    """집계 함수도 내부 테이블 대상도 아닌 SELECT 는 여전히 반복문을 연다(회귀 방지)."""
    text = (
        "SELECT vbeln FROM vbak INTO ls_vbak.\n"
        "  SELECT SINGLE * FROM vbap INTO ls_vbap WHERE vbeln = ls_vbak-vbeln.\n"
        "ENDSELECT.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_집계함수와_group_by가_함께_있으면_반복문을_연다():
    """GROUP BY 가 있으면 필드가 전부 집계 함수여도 여러 행이 나오므로 반복문이다."""
    text = (
        "SELECT COUNT( * ) FROM vbak INTO lv_n GROUP BY vkorg.\n"
        "  SELECT SINGLE * FROM vbap INTO ls_vbap WHERE vkorg = 'X'.\n"
        "ENDSELECT.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_into_table_package_size는_반복문을_연다():
    """PACKAGE SIZE 는 내부 테이블 대상이라도 n건씩 나눠 가져오는 반복 조회다."""
    text = (
        "SELECT vbeln FROM vbak INTO TABLE @DATA(lt_vbak) PACKAGE SIZE 100.\n"
        "  SELECT SINGLE * FROM vbap INTO ls_vbap WHERE vbeln = lt_vbak-vbeln.\n"
        "ENDSELECT.\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-002")
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_abap_여러_줄에_걸친_select도_올바르게_판정된다():
    text = (
        "SELECT COUNT( * )\n"
        "  FROM vbak\n"
        "  INTO @DATA(lv_n).\n"
        "SELECT vbeln FROM vbak INTO TABLE @DATA(lt).\n"
    )
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


# --- CR-003 (ABAP): 내부 테이블(호스트 표현식) 대상 SELECT 는 예외다(#91) ----------


def test_abap_내부테이블_대상_select_star는_괜찮다():
    """이슈 #91: `SELECT * FROM @itab ...` 은 이미 메모리에 있는 내부 테이블을
    다시 참조하는 것이라 DB 조회가 아니다 — CR-003 이 규칙으로 삼는 이유(DB 컬럼
    낭비)에 해당하지 않는다. precedent: #84 의 CR-002 도 같은 `FROM\\s+@` 판정으로
    내부 테이블 대상을 예외로 뒀다."""
    text = (
        "SELECT * FROM @gt_output_temp AS A1 WHERE (LV_WHERE_EXCLUDE) "
        "ORDER BY (lv_sort_string).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_내부테이블_대상_fields_star도_괜찮다():
    text = "SELECT FROM @lt_itab AS a FIELDS * INTO TABLE @lt_result.\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_db_테이블_select_star_안의_itab_서브쿼리가_바깥_검사를_면제하지_않는다():
    """이슈 #103: 예외는 `*` 를 품은 SELECT 의 FROM 대상만 본다."""
    text = (
        "SELECT * FROM ekko WHERE ebeln IN ( SELECT ebeln FROM @itab ) "
        "INTO TABLE @DATA(lt).\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_db_테이블_fields_star_안의_itab_서브쿼리도_바깥은_위반():
    text = (
        "SELECT FROM ekko FIELDS * WHERE ebeln IN ( SELECT ebeln FROM @itab ) "
        "INTO TABLE @DATA(lt).\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_내부테이블_select_star는_별칭_있어도_괜찮다():
    text = "SELECT * FROM @lt_items AS i INTO TABLE @DATA(lt2).\n"
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_itab_서브쿼리_안의_select_star는_괜찮다():
    text = (
        "SELECT ebeln FROM ekko WHERE ebeln IN ( SELECT * FROM @itab ) "
        "INTO TABLE @DATA(lt).\n"
    )
    assert _rules(check_source("t.abap", text), "CR-003") == []


def test_abap_필드_목록_바깥과_db_테이블_서브쿼리_select_star는_위반():
    text = (
        "SELECT ebeln FROM @itab AS i WHERE ebeln IN ( SELECT * FROM ekko ) "
        "INTO TABLE @DATA(lt).\n"
    )
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_내부테이블_join_별칭_전체_필드는_괜찮고_db_테이블_별칭은_위반():
    itab = "SELECT i~* FROM @lt_i AS i INTO TABLE @DATA(lt).\n"
    assert _rules(check_source("t.abap", itab), "CR-003") == []
    db = "SELECT i~* FROM ekko AS i WHERE ebeln IN ( SELECT ebeln FROM @lt ) INTO TABLE @DATA(lt2).\n"
    assert len(_rules(check_source("t.abap", db), "CR-003")) == 1


def test_abap_실제_db_테이블_select_star는_내부테이블_예외와_무관하게_여전히_위반():
    text = "SELECT * FROM ztable INTO TABLE lt_result.\n"
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


def test_abap_실제_db_테이블_fields_star도_여전히_위반():
    text = "SELECT FROM ztab FIELDS * INTO TABLE @lt_result.\n"
    hits = _rules(check_source("t.abap", text), "CR-003")
    assert len(hits) == 1


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


# --- CR-001 (JS): 템플릿 리터럴 안에 중첩된 백틱 템플릿(#91) -----------------------


def test_js_템플릿_리터럴_속_중첩된_삼항_백틱의_한글은_괜찮다():
    """이슈 #91: `${cond ? `한글` : `한글`}` 처럼 표현식 안에 백틱 템플릿이 중첩되면,
    바깥 템플릿을 감싸는 코드가 나이브하게 다음 백틱을 닫는 따옴표로 보아 중첩된
    템플릿의 내용을 문자열이 아닌 코드로 잘못 남겨 그 안의 한글을 이름으로 오인했다
    (public-cloud adt-login `scripts/adt-proxy/session.js`)."""
    text = (
        "console.log(`   프록시      ${up ? `기동 중 :${t.port}` "
        ": `내려감 :${t.port}`}`);\n"
    )
    assert _rules(check_source("t.js", text), "CR-001") == []


def test_js_템플릿_리터럴_속_중첩된_백틱의_한글_물음표도_괜찮다():
    """같은 이슈의 두 번째 사례(`scripts/adt-proxy/proxy.js`) — 중첩 조건이
    거짓 분기가 빈 문자열이고, 물음표가 문자열 안에 있는 모양."""
    text = (
        '  console.log(`[proxy] keepalive ${up.statusCode}'
        '${dead ? `  <<< 세션 만료? ${HINT}` : ""}`);\n'
    )
    assert _rules(check_source("t.js", text), "CR-001") == []


def test_js_한글_이름은_중첩_템플릿과_무관하게_여전히_위반():
    findings = check_source("t.js", "const 이름 = 1;\n")
    hits = _rules(findings, "CR-001")
    assert len(hits) == 1 and "이름" in hits[0]["message"]


# --- CR-001 (JS): 정규식 리터럴 안의 한글(#97) --------------------------------------


def test_js_정규식_리터럴_안의_한글은_괜찮다():
    """이슈 #97: `if (/로그인이 바뀌어/.test(line))` 처럼 정규식 리터럴 안의 한글이
    이름으로 오인되어 CR-001 로 잡혔다. 정규식 리터럴 안의 문자는 이름이 아니다."""
    text = "if (/로그인이 바뀌어/.test(line)) {}\n"
    assert _rules(check_source("t.js", text), "CR-001") == []


def test_js_정규식_리터럴_플래그와_이스케이프_안의_한글도_괜찮다():
    text = "const re = /세션\\s*만료/gi;\n"
    assert _rules(check_source("t.js", text), "CR-001") == []


def test_js_replace_인자_정규식_리터럴_안의_한글도_괜찮다():
    text = 'x = a.replace(/[가-힣]+/g, "");\n'
    assert _rules(check_source("t.js", text), "CR-001") == []


def test_js_한글_이름은_정규식_리터럴과_무관하게_여전히_위반():
    findings = check_source("t.js", "const 이름 = 1;\n")
    hits = _rules(findings, "CR-001")
    assert len(hits) == 1 and "이름" in hits[0]["message"]


def test_js_나누기_연산은_정규식_시작으로_보지_않는다():
    """`a / b / c` 처럼 나눗셈이 이어져도 정규식 리터럴의 시작으로 잘못 보고 그
    사이 코드를 마스킹하면 안 된다."""
    text = "const r = a / b / c; const 값 = 1;\n"
    hits = _rules(check_source("t.js", text), "CR-001")
    assert len(hits) == 1 and "값" in hits[0]["message"]


def test_js_괄호_뒤_나누기_연산도_정규식_시작으로_보지_않는다():
    """`)` 뒤의 `/` 는 괄호로 감싼 값을 나누는 연산이지 정규식 시작이 아니다.
    뒤에 나오는 식별자가 그대로 보이는지(마스킹으로 가려지지 않는지)로 확인한다."""
    text = "x = (a) / 2; y = b / 3; const 개수 = 1;\n"
    hits = _rules(check_source("t.js", text), "CR-001")
    assert len(hits) == 1 and "개수" in hits[0]["message"]


def test_js_정규식_문자_클래스_안의_슬래시와_이스케이프_슬래시를_올바르게_처리한다():
    text = "const re1 = /[/]/;\nconst re2 = /a\\/b/;\nconst 이름2 = 1;\n"
    hits = _rules(check_source("t.js", text), "CR-001")
    assert len(hits) == 1 and "이름2" in hits[0]["message"]


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


# --- CR-009: 권한 메서드가 전부 허용만 한다(#361, 경고) ------------------------------------

_POOL_DEF = (
    "CLASS lhc_upload DEFINITION INHERITING FROM cl_abap_behavior_handler.\n"
    "  PRIVATE SECTION.\n"
    "    METHODS get_global_authorizations FOR GLOBAL AUTHORIZATION\n"
    "      IMPORTING REQUEST requested_authorizations FOR Upload RESULT result.\n"
    "ENDCLASS.\n"
)


def _pool(body: str, extra: str = "") -> str:
    return (
        _POOL_DEF
        + "CLASS lhc_upload IMPLEMENTATION.\n"
        + "  METHOD get_global_authorizations.\n"
        + body
        + "  ENDMETHOD.\n"
        + extra
        + "ENDCLASS.\n"
    )


_ALLOW_ALL = (
    "    IF requested_authorizations-%create = if_abap_behv=>mk-on.\n"
    "      result-%create = if_abap_behv=>auth-allowed.\n"
    "    ENDIF.\n"
)


def _cr009(text: str, name: str = "zbp_x.clas.locals_imp.abap") -> list[dict]:
    return _rules(check_source(name, text), "CR-009")


def test_cr009_전부_허용만_하고_AUTHORITY_CHECK_가_없으면_경고():
    hits = _cr009(_pool(_ALLOW_ALL))
    assert len(hits) == 1
    assert hits[0]["level"] == "warn" and hits[0]["allowed"] is False
    assert "get_global_authorizations" in hits[0]["message"]
    assert hits[0]["line"] == 7  # METHOD 문 줄


def test_cr009_instance_권한_메서드도_본다():
    text = (
        "CLASS lhc DEFINITION INHERITING FROM cl_abap_behavior_handler.\n"
        "  PRIVATE SECTION.\n"
        "    METHODS get_instance_authorizations FOR INSTANCE AUTHORIZATION\n"
        "      IMPORTING keys REQUEST requested_authorizations FOR Doc RESULT result.\n"
        "ENDCLASS.\n"
        "CLASS lhc IMPLEMENTATION.\n"
        "  METHOD get_instance_authorizations.\n"
        "    result = VALUE #( FOR k IN keys ( %tky = k-%tky %update = if_abap_behv=>auth-allowed ) ).\n"
        "  ENDMETHOD.\n"
        "ENDCLASS.\n"
    )
    assert len(_cr009(text)) == 1


def test_cr009_같은_파일에_AUTHORITY_CHECK_가_있으면_다른_메서드여도_경고_아님():
    check = (
        "  METHOD check_plant.\n"
        "    AUTHORITY-CHECK OBJECT 'ZPLANT' ID 'WERKS' FIELD iv_plant ID 'ACTVT' FIELD '02'.\n"
        "  ENDMETHOD.\n"
    )
    assert _cr009(_pool(_ALLOW_ALL, extra=check)) == []


def test_cr009_주석_속_AUTHORITY_CHECK_는_무시한다():
    commented = _ALLOW_ALL + '    " AUTHORITY-CHECK OBJECT 는 나중에\n'
    assert len(_cr009(_pool(commented))) == 1
    star = _pool(_ALLOW_ALL, extra="* AUTHORITY-CHECK OBJECT 'ZX'.\n")
    assert len(_cr009(star)) == 1


def test_cr009_문자열_속_AUTHORITY_CHECK_도_무시한다():
    body = _ALLOW_ALL + "    DATA(lv_text) = 'AUTHORITY-CHECK'.\n"
    assert len(_cr009(_pool(body))) == 1


def test_cr009_unauthorized_를_쓰는_본문은_경고_아님():
    body = (
        "    IF lv_ok = abap_true.\n"
        "      result-%create = if_abap_behv=>auth-allowed.\n"
        "    ELSE.\n"
        "      result-%create = if_abap_behv=>auth-unauthorized.\n"
        "    ENDIF.\n"
    )
    assert _cr009(_pool(body)) == []


def test_cr009_본문이_비었거나_주석뿐이면_확인_필요_경고():
    for body in ("", '    " 권한은 표준 BO 가 검사한다.\n'):
        (hit,) = _cr009(_pool(body))
        assert hit["level"] == "warn" and "비어 있음" in hit["message"] and "확인 필요" in hit["message"]


def test_cr009_빈_본문도_harness_allow_로_예외를_남긴다():
    text = _pool('    " 표준 BO 가 검사한다.\n').replace(
        "  METHOD get_global_authorizations.\n",
        '  " harness:allow CR-009 표준 BO 위임(홍길동 2026-10-19)\n  METHOD get_global_authorizations.\n',
    )
    (hit,) = _cr009(text)
    assert hit["allowed"] is True


def test_cr009_콜론_체인_선언도_권한_메서드로_읽는다():
    text = (
        "CLASS lhc DEFINITION INHERITING FROM cl_abap_behavior_handler.\n"
        "  PRIVATE SECTION.\n"
        "    METHODS: get_instance_features FOR INSTANCE FEATURES\n"
        "               IMPORTING keys REQUEST requested_features FOR Doc RESULT result,\n"
        "             get_global_authorizations FOR GLOBAL AUTHORIZATION\n"
        "               IMPORTING REQUEST requested_authorizations FOR Doc RESULT result.\n"
        "ENDCLASS.\n"
        "CLASS lhc IMPLEMENTATION.\n"
        "  METHOD get_global_authorizations.\n"
        "    result-%create = if_abap_behv=>auth-allowed.\n"
        "  ENDMETHOD.\n"
        "  METHOD get_instance_features.\n"
        "    result-%create = if_abap_behv=>auth-allowed.\n"
        "  ENDMETHOD.\n"
        "ENDCLASS.\n"
    )
    (hit,) = _cr009(text)
    assert "get_global_authorizations" in hit["message"]


def test_cr009_다른_클래스의_AUTHORITY_CHECK_는_경고를_끄지_않는다():
    other = (
        "CLASS lcl_helper IMPLEMENTATION.\n"
        "  METHOD check.\n"
        "    AUTHORITY-CHECK OBJECT 'ZX' ID 'ACTVT' FIELD '02'.\n"
        "  ENDMETHOD.\n"
        "ENDCLASS.\n"
    )
    assert len(_cr009(_pool(_ALLOW_ALL) + other)) == 1
    assert _cr009(_pool(_ALLOW_ALL, extra=other.replace("CLASS lcl_helper IMPLEMENTATION.\n", "").replace("ENDCLASS.\n", ""))) == []


def test_cr009_권한_메서드_정의가_없으면_경고_아님():
    text = "CLASS lhc IMPLEMENTATION.\n  METHOD foo.\n    x = if_abap_behv=>auth-allowed.\n  ENDMETHOD.\nENDCLASS.\n"
    assert _cr009(text) == []


def test_cr009_harness_allow_로_예외를_남긴다():
    allow = _pool(_ALLOW_ALL).replace(
        "  METHOD get_global_authorizations.\n",
        '  " harness:allow CR-009 표준 구매오더 BO 가 검사한다(홍길동 2026-10-19)\n'
        "  METHOD get_global_authorizations.\n",
    )
    (hit,) = _cr009(allow)
    assert hit["allowed"] is True
    no_reason = allow.replace(" 표준 구매오더 BO 가 검사한다(홍길동 2026-10-19)", "")
    (hit,) = _cr009(no_reason)
    assert hit["allowed"] is False and "이유" in hit["note"]


def test_cr009_ABAP_가_아닌_언어에는_적용하지_않는다():
    assert _rules(check_source("a.js", "const x = 'FOR GLOBAL AUTHORIZATION auth-allowed';\n"), "CR-009") == []


def test_cr009_경고는_종료코드를_바꾸지_않고_요약에_센다(tmp_path: Path, capsys):
    target = tmp_path / "zbp_x.clas.locals_imp.abap"
    target.write_text(_pool(_ALLOW_ALL), encoding="utf-8")
    code = main([str(target)])
    assert code == EXIT_PASS
    report = _read_report(capsys)
    assert report["files"][0]["status"] == "pass"
    assert report["summary"]["violations"] == 0
    assert report["summary"]["warnings"] == 1
    assert report["files"][0]["findings"][0]["level"] == "warn"


def test_cr009_경고와_위반이_같이_있으면_위반만_종료코드를_올린다(tmp_path: Path, capsys):
    target = tmp_path / "zbp_x.clas.locals_imp.abap"
    target.write_text(_pool(_ALLOW_ALL + "    DATA lv_금액 TYPE i.\n"), encoding="utf-8")
    assert main([str(target)]) == EXIT_VIOLATION
    report = _read_report(capsys)
    assert report["files"][0]["status"] == "violation"
    assert report["summary"]["warnings"] == 1


def test_기존_규칙의_level_은_violation_이다():
    (hit,) = _rules(check_source("t.abap", "DATA lv_금액 TYPE i.\n"), "CR-001")
    assert hit["level"] == "violation"


def test_알_수_없는_level_은_설정_오류로_검사_불능(tmp_path: Path, capsys, monkeypatch):
    from checker.model import ConfigError

    cfg = {
        "languages": {"abap": {"suffixes": [".abap"]}},
        "rules": {"CR-001": {"languages": ["abap"], "level": "warning"}},
    }
    monkeypatch.setattr(code_rules, "_load_config", lambda: cfg)
    with pytest.raises(ConfigError):
        check_source("t.abap", "DATA a TYPE i.\n")
    target = tmp_path / "t.abap"
    target.write_text("DATA a TYPE i.\n", encoding="utf-8")
    assert main([str(target)]) == EXIT_CANNOT_CHECK
    report = _read_report(capsys)
    assert report["files"][0]["status"] == "error"
    assert "level" in report["files"][0]["reason"]


def test_code_checks_의_CR_009_는_경고다():
    rule = code_rules._load_config()["rules"]["CR-009"]
    assert rule["level"] == "warn" and rule["languages"] == ["abap"]


# --- CR-009: 권한을 맡긴다면서 EML 을 PRIVILEGED 로 부름(#524) -------------------------------

_EML_PRIV = (
    "    MODIFY ENTITIES OF i_supplierinvoicetp FORWARDING PRIVILEGED\n"
    "      ENTITY SupplierInvoice EXECUTE Create FROM lt_create\n"
    "      FAILED DATA(failed).\n"
)


def _priv_hits(text: str) -> list[dict]:
    return [h for h in _cr009(text) if "PRIVILEGED" in h["message"]]


def test_cr009_전부_허용이고_forwarding_privileged_면_별도_경고():
    text = _pool(_ALLOW_ALL, extra="  METHOD save.\n" + _EML_PRIV + "  ENDMETHOD.\n")
    assert len(_cr009(text)) == 2
    (hit,) = _priv_hits(text)
    assert hit["level"] == "warn" and hit["allowed"] is False
    assert hit["line"] == text.split("\n").index(_EML_PRIV.split("\n")[0]) + 1
    assert "harness:allow CR-009" in hit["message"]


def test_cr009_privileged_없으면_기존_경고만():
    assert len(_cr009(_pool(_ALLOW_ALL))) == 1
    assert _priv_hits(_pool(_ALLOW_ALL)) == []


def test_cr009_privileged_단독_키워드와_소문자도_본다():
    eml = "    read entities of i_x privileged entity A all fields with lt_k result DATA(r).\n"
    assert len(_priv_hits(_pool(_ALLOW_ALL, extra="  METHOD m.\n" + eml + "  ENDMETHOD.\n"))) == 1


def test_cr009_AUTHORITY_CHECK_가_있으면_privileged_만으로_경고하지_않는다():
    check = "  METHOD chk.\n    AUTHORITY-CHECK OBJECT 'ZX' ID 'ACTVT' FIELD '02'.\n" + _EML_PRIV + "  ENDMETHOD.\n"
    assert _cr009(_pool(_ALLOW_ALL, extra=check)) == []


def test_cr009_주석과_문자열_속_privileged_는_무시한다():
    extra = (
        "  METHOD m.\n"
        '    " MODIFY ENTITIES OF i_x FORWARDING PRIVILEGED\n'
        "* MODIFY ENTITIES OF i_x PRIVILEGED\n"
        "    DATA(t) = 'MODIFY ENTITIES PRIVILEGED'.\n"
        "  ENDMETHOD.\n"
    )
    assert _priv_hits(_pool(_ALLOW_ALL, extra=extra)) == []


def test_cr009_privileged_도_harness_allow_이유가_있으면_allowed():
    eml = _EML_PRIV.replace("    MODIFY", '    " harness:allow CR-009 시뮬레이션 호출에 필요(홍길동 2026-10-28)\n    MODIFY', 1)
    (hit,) = _priv_hits(_pool(_ALLOW_ALL, extra="  METHOD m.\n" + eml + "  ENDMETHOD.\n"))
    assert hit["allowed"] is True


def test_cr009_privileged_allow_이유가_없으면_인정하지_않는다():
    eml = _EML_PRIV.replace("    MODIFY", '    " harness:allow CR-009\n    MODIFY', 1)
    (hit,) = _priv_hits(_pool(_ALLOW_ALL, extra="  METHOD m.\n" + eml + "  ENDMETHOD.\n"))
    assert hit["allowed"] is False


# --- abapGit CDS 계열 확장자(#565) ----------------------------------------------

CDS_ABAPGIT_SUFFIXES = [".asddls", ".asddlxs", ".srvdsrv", ".asdcls", ".astabldt"]


@pytest.mark.parametrize("suffix", CDS_ABAPGIT_SUFFIXES)
def test_abapgit_cds_계열_확장자는_cds_로_분류된다(suffix):
    assert code_rules.language_for_suffix(Path(f"zi_order.x{suffix}")) == "cds"


@pytest.mark.parametrize("suffix", CDS_ABAPGIT_SUFFIXES)
def test_abapgit_cds_계열은_한글_이름만_위반이고_주석_문자열은_괜찮다(suffix):
    name = f"t{suffix}"
    hits = _rules(check_source(name, "define table 주문 {\n}\n"), "CR-001")
    assert len(hits) == 1
    ok = (
        "// 한글 주석\n/* 한글 블록 */\n@EndUserText.label : '한글 라벨'\n"
        "define table zt_order {\n}\n"
    )
    assert _rules(check_source(name, ok), "CR-001") == []


def test_훅_CODE_SUFFIXES_는_code_checks_yaml_의_모든_확장자를_덮는다():
    """훅은 엔진 설정을 못 읽어 사본을 둔다(pre_write_guard.py 주석). 어긋나면 저장 훅이 그 확장자를 건너뛴다."""
    import importlib.util

    hook = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "pre_write_guard.py"
    spec = importlib.util.spec_from_file_location("pre_write_guard_suffix_t", hook)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yaml_suffixes = set(code_rules._suffix_language_map(code_rules._load_config()))
    assert yaml_suffixes == set(mod.CODE_SUFFIXES)
