"""`md_table` 규칙 종류와 Spec `## 사용 객체` 표 검사(#287).

규칙 단위 테스트는 params 를 직접 넘기고, Spec 통합은 `/scaffold` 가 만든 구조의
`rules/spec.yaml` 로 돌린다. 양식 산출(`## 양식 항목` 만 읽음)이 새 절에 영향받지 않는지도 본다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from checker import export
from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION
from checker.model import ConfigError
from checker.rules.md_table import check
from checker.tests.test_scaffold import _run_auto, scaffold
from checker.tests.test_spec_rules import SPEC_VALID

PARAMS = {
    "절": "사용 객체",
    "열": ["종류", "이름", "작업", "비고"],
    "값": {
        "종류": ["CDS View", "Database Table", "Service Definition"],
        "작업": ["생성", "수정", "참조"],
    },
    "패턴": {"이름": "(?:/[A-Za-z0-9_]+/)?[A-Za-z][A-Za-z0-9_]*"},
}

HEAD = "| 종류 | 이름 | 작업 | 비고 |\n|---|---|---|---|\n"


def doc(table: str, title: str = "사용 객체") -> str:
    return f"# DEV-001 시험\n\n## 개요\n\n본문\n\n## {title}\n\n설명 줄.\n\n{table}\n## 완료 조건\n\n끝\n"


def run(tmp_path: Path, text: str, **override):
    p = tmp_path / "DEV-001-시험.md"
    p.write_text(text, encoding="utf-8")
    return check(p, {**PARAMS, **override})


def test_정상_표는_통과(tmp_path):
    rows = "| CDS View | ZSD_R_Customer | 생성 | |\n| Database Table | `ZSDA0010` | 수정 | 필드 추가 |\n"
    assert run(tmp_path, doc(HEAD + rows)) == []


def test_대소문자_섞인_이름도_통과(tmp_path):
    # naming.md 의 예시 이름(ZSD_S_Customer, ZCL_SalesOrderUpdate 류)이 걸리면 안 된다.
    assert run(tmp_path, doc(HEAD + "| CDS View | ZMM_R_Materials | 참조 | |\n")) == []


def test_절이_없으면_통과(tmp_path):
    assert run(tmp_path, "# 시험\n\n## 개요\n\n본문\n") == []


def test_필수로_바꾸면_절_없음이_위반(tmp_path):
    v = run(tmp_path, "# 시험\n\n## 개요\n\n본문\n", 필수=True)
    assert len(v) == 1 and v[0].rule == "md_table"


def test_머리만_있고_행이_없으면_통과(tmp_path):
    assert run(tmp_path, doc(HEAD)) == []


def test_템플릿_자리표시_빈_행은_통과(tmp_path):
    assert run(tmp_path, doc(HEAD + "|  |  |  |  |\n")) == []


def test_절은_있는데_표가_없으면_위반(tmp_path):
    v = run(tmp_path, doc(""))
    assert len(v) == 1 and "표가 없다" in v[0].message


def test_코드_펜스_안의_표는_표가_아니다(tmp_path):
    v = run(tmp_path, doc("```\n" + HEAD + "| CDS View | ZA | 생성 | |\n```\n"))
    assert len(v) == 1 and "표가 없다" in v[0].message


def test_머리_열이_다르면_위반(tmp_path):
    v = run(tmp_path, doc("| 종류 | 이름 | 작업 |\n|---|---|---|\n| CDS View | ZA | 생성 |\n"))
    assert len(v) == 1 and "머리 열" in v[0].message


def test_열_순서가_다르면_위반(tmp_path):
    v = run(tmp_path, doc("| 이름 | 종류 | 작업 | 비고 |\n|---|---|---|---|\n"))
    assert len(v) == 1 and "머리 열" in v[0].message


def test_종류가_허용_밖이면_위반(tmp_path):
    v = run(tmp_path, doc(HEAD + "| Table | ZA | 생성 | |\n"))
    assert len(v) == 1 and v[0].actual == "Table" and "'종류'" in v[0].message


def test_작업이_허용_밖이면_위반(tmp_path):
    v = run(tmp_path, doc(HEAD + "| CDS View | ZA | 삭제 | |\n"))
    assert len(v) == 1 and v[0].actual == "삭제"


def test_이름_패턴이_틀리면_위반(tmp_path):
    rows = (
        "| CDS View | ZA B | 생성 | |\n| CDS View | ZA-B | 생성 | |\n"
        "| CDS View | 고객 | 생성 | |\n| CDS View | 1ZA | 생성 | |\n"
    )
    v = run(tmp_path, doc(HEAD + rows))
    assert [x.actual for x in v] == ["ZA B", "ZA-B", "고객", "1ZA"]


def test_소문자_네임스페이스_표준_객체_이름은_통과(tmp_path):
    rows = (
        "| CDS View | zsd_ui_salesorder | 생성 | |\n| CDS View | /DMO/I_TRAVEL | 참조 | |\n"
        "| CDS View | I_SalesOrder | 참조 | |\n"
    )
    assert run(tmp_path, doc(HEAD + rows)) == []


def test_일부만_빈_행은_위반(tmp_path):
    v = run(tmp_path, doc(HEAD + "| CDS View |  | 생성 | |\n"))
    assert len(v) == 1 and v[0].actual == "빈 칸"


def test_칸_수가_머리와_다르면_위반(tmp_path):
    v = run(tmp_path, doc(HEAD + "| CDS View | ZA | 생성 |\n"))
    assert len(v) == 1 and "칸 수" in v[0].message


def test_위반_여러_개는_모두_낸다(tmp_path):
    v = run(tmp_path, doc(HEAD + "| Table | z a | 삭제 | |\n"))
    assert len(v) == 3


def test_다음_절의_표는_보지_않는다(tmp_path):
    text = f"# 시험\n\n## 사용 객체\n\n없음\n\n## 완료 조건\n\n{HEAD}| Table | ZA | 생성 | |\n"
    v = run(tmp_path, text)
    assert len(v) == 1 and "표가 없다" in v[0].message


def test_파일을_읽지_못하면_검사_불능(tmp_path):
    with pytest.raises(ConfigError):
        check(tmp_path / "없는파일.md", PARAMS)
    bad = tmp_path / "깨짐.md"
    bad.write_bytes(b"\xff\xfe\xfa## \xb0\xed")
    with pytest.raises(ConfigError):
        check(bad, PARAMS)


def test_규칙_데이터가_잘못되면_설정_오류(tmp_path):
    with pytest.raises(ConfigError):
        run(tmp_path, doc(HEAD), 열=None)
    with pytest.raises(ConfigError):
        run(tmp_path, doc(HEAD), 값={"없는열": ["x"]})
    with pytest.raises(ConfigError):
        run(tmp_path, doc(HEAD), 패턴={"이름": "["})


def test_영문_키도_받는다(tmp_path):
    p = {"section": "사용 객체", "columns": ["종류", "이름"], "values": {"종류": ["CDS View"]}}
    f = tmp_path / "a.md"
    f.write_text("## 사용 객체\n\n| 종류 | 이름 |\n|---|---|\n| X | ZA |\n", encoding="utf-8")
    assert len(check(f, p)) == 1


# ---- skeleton rules/spec.yaml 로 돌리는 통합 ----

def _spec_with(table: str | None) -> str:
    if table is None:
        return SPEC_VALID
    obj = (
        "## 사용 객체\n\n설명.\n\n" + table + "\n"
    )
    return SPEC_VALID.replace("## 완료 조건", obj + "## 완료 조건")


def _put(tmp_path: Path, text: str) -> Path:
    scaffold(tmp_path, "고객사", "프로젝트", False)
    spec = tmp_path / "docs" / "spec" / "DEV-001-결재단계추가.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(text, encoding="utf-8")
    return spec


def test_사용_객체_절이_없는_기존_spec은_통과한다(tmp_path, capsys):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with(None)))
    assert code == EXIT_PASS and out["summary"]["violations"] == 0


def test_올바른_사용_객체_표는_통과한다(tmp_path, capsys):
    rows = HEAD + "| Service Definition | ZSD_UI_CUSTOMER | 생성 | |\n| Database Table | ZSDA0010 | 참조 | |\n"
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with(rows)))
    assert code == EXIT_PASS, out


def test_틀에서_그대로_복사한_spec은_통과한다(tmp_path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    tpl = (tmp_path / "templates" / "harness" / "spec.md").read_text(encoding="utf-8")
    spec = tmp_path / "docs" / "spec" / "DEV-001-결재단계추가.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(tpl, encoding="utf-8")
    code, out = _run_auto(capsys, spec)
    assert code == EXIT_PASS, out


def test_사용_객체_표가_틀리면_spec이_위반이다(tmp_path, capsys):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with(HEAD + "| Table | ZA | 삭제 | |\n")))
    assert code == EXIT_VIOLATION
    assert {v["rule"] for v in out["files"][0]["violations"]} == {"md_table"}


LP_HEAD = (
    "| 타일 제목 | 부제 | 아이콘 | 시맨틱 오브젝트 | 액션 | 파라미터 | 카탈로그 | 배치 |\n"
    "|---|---|---|---|---|---|---|---|\n"
)
LP_ROW = (
    "| 기간별 재고 수불부 | 재고 수불 집계 | sap-icon://inventory | AnalyticQuery | preview | "
    "query=ZMM_C_STOCKLEDGERQUERY | ZMM_BC_AUTO1 | MM AUTO1 페이지 · 재고원장 보고서 영역 |\n"
)


def _spec_with_lp(table: str) -> str:
    return SPEC_VALID.replace("## 완료 조건", "## Launchpad 노출\n\n설명.\n\n" + table + "\n## 완료 조건")


def test_올바른_launchpad_노출_표는_통과한다(tmp_path, capsys):
    rows = LP_HEAD + LP_ROW + LP_ROW.replace("preview", "display").replace("기간별", "다른")
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with_lp(rows)))
    assert code == EXIT_PASS, out


def test_밑줄이_든_시맨틱_오브젝트는_통과한다(tmp_path, capsys):
    row = LP_ROW.replace("AnalyticQuery", "Z_Stock_Ledger1")
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with_lp(LP_HEAD + row)))
    assert code == EXIT_PASS, out


def test_launchpad_노출_절이_없는_spec은_통과한다(tmp_path, capsys):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with(None)))
    assert code == EXIT_PASS, out


@pytest.mark.parametrize("bad", [
    LP_ROW.replace("preview", "Preview"),            # 액션 대문자 시작
    LP_ROW.replace("preview", "pre view"),           # 액션 공백
    LP_ROW.replace("AnalyticQuery", "Analytic Query"),  # 시맨틱 오브젝트 공백
    LP_ROW.replace("AnalyticQuery", "1Query"),       # 숫자 시작
    LP_ROW.replace("AnalyticQuery", ""),             # 빈 칸
])
def test_launchpad_노출_표가_틀리면_위반이다(tmp_path, capsys, bad):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with_lp(LP_HEAD + bad)))
    assert code == EXIT_VIOLATION
    assert {v["rule"] for v in out["files"][0]["violations"]} == {"md_table"}


def test_launchpad_노출_표_머리가_다르면_위반이다(tmp_path, capsys):
    head = "| 타일 제목 | 액션 |\n|---|---|\n| X | preview |\n"
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with_lp(head)))
    assert code == EXIT_VIOLATION


# ---- 권한 표(#361) ----

AU_HEAD = (
    "| 동작 | 검사 방식 | 권한 객체 | 활동 | 검사 기준 필드 | 비고 |\n"
    "|---|---|---|---|---|---|\n"
)
AU_ROW = "| 생산실적 전기 | instance | ZPP_PLANT | 01, 02 | 플랜트 | |\n"


def _spec_with_au(table: str) -> str:
    return SPEC_VALID.replace("## 완료 조건", "## 권한\n\n설명.\n\n" + table + "\n## 완료 조건")


def _au(tmp_path, capsys, rows: str):
    return _run_auto(capsys, _put(tmp_path, _spec_with_au(AU_HEAD + rows)))


def test_올바른_권한_표는_통과한다(tmp_path, capsys):
    rows = (
        AU_ROW
        + "| 삭제 | global, instance | ZPP_PLANT | 06 | 플랜트 | |\n"
        + "| 승인 | update 위임 | ZPP_PLANT | - | 플랜트 | update 와 같음 |\n"
    )
    code, out = _au(tmp_path, capsys, rows)
    assert code == EXIT_PASS, out


def test_권한_절이_없는_기존_spec은_통과한다(tmp_path, capsys):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with(None)))
    assert code == EXIT_PASS, out


def test_검사_안_함은_비고가_비면_위반이다(tmp_path, capsys):
    code, out = _au(tmp_path, capsys, "| 전기 | 검사 안 함 | - | - | - | |\n")
    assert code == EXIT_VIOLATION
    (v,) = out["files"][0]["violations"]
    assert v["rule"] == "md_table" and "비고" in v["message"] and "검사 안 함" in v["message"]


def test_검사_안_함도_비고에_이유를_적으면_통과한다(tmp_path, capsys):
    row = "| 전기 | 검사 안 함 | - | - | - | 표준 BO 가 검사한다. 홍길동 2026-10-19 |\n"
    code, out = _au(tmp_path, capsys, row)
    assert code == EXIT_PASS, out


@pytest.mark.parametrize("field", ["-", ""])
def test_검사_기준_필드가_없으면_비고가_필요하다(tmp_path, capsys, field):
    row = f"| 전기 | global | ZPP_APP | 01 | {field} | |\n"
    code, out = _au(tmp_path, capsys, row)
    assert code == EXIT_VIOLATION
    assert "검사 기준 필드" in out["files"][0]["violations"][0]["message"]
    ok = f"| 전기 | global | ZPP_APP | 01 | {field} | 앱 사용 권한만 본다. 홍길동 2026-10-19 |\n"
    assert _au(tmp_path, capsys, ok)[0] == EXIT_PASS


@pytest.mark.parametrize("bad", [
    AU_ROW.replace("instance", "Instance"),      # 검사 방식 허용 밖
    AU_ROW.replace("instance", "전부 허용"),
    AU_ROW.replace("01, 02", "1"),               # 활동 형식
    AU_ROW.replace("01, 02", "일부"),
    AU_ROW.replace("01, 02", ""),                # 활동 빈 칸
])
def test_권한_표가_틀리면_위반이다(tmp_path, capsys, bad):
    code, out = _au(tmp_path, capsys, bad)
    assert code == EXIT_VIOLATION
    assert {v["rule"] for v in out["files"][0]["violations"]} == {"md_table"}


def test_권한_표_머리가_다르면_위반이다(tmp_path, capsys):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with_au("| 동작 | 비고 |\n|---|---|\n| x | y |\n")))
    assert code == EXIT_VIOLATION


def test_조건_필수_조건_열이_여럿이면_모두_맞을_때만_본다(tmp_path):
    params = {
        "절": "사용 객체", "열": ["종류", "이름", "작업", "비고"],
        "조건_필수": [{"열": "비고", "조건": {"종류": ["CDS View"], "작업": ["수정"]}}],
    }
    p = tmp_path / "a.md"
    p.write_text(doc(HEAD + "| CDS View | ZA | 수정 | |\n| CDS View | ZB | 생성 | |\n"), encoding="utf-8")
    out = check(p, params)
    assert len(out) == 1 and "1번째" in out[0].message


@pytest.mark.parametrize("bad", [
    "x",
    [{"열": "비고"}],
    [{"열": "없는열", "조건": {"종류": ["a"]}}],
    [{"열": "비고", "조건": {"없는열": ["a"]}}],
    [{"열": "비고", "조건": {"종류": "a"}}],
])
def test_조건_필수가_잘못되면_설정_오류(tmp_path, bad):
    with pytest.raises(ConfigError):
        run(tmp_path, doc(HEAD), 조건_필수=bad)


@pytest.mark.parametrize("kind", ["IAM App", "Business Catalog", "Launchpad App Descriptor Item"])
def test_새_종류_세_가지는_사용_객체에서_통과한다(tmp_path, capsys, kind):
    code, out = _run_auto(capsys, _put(tmp_path, _spec_with(HEAD + f"| {kind} | ZMM_BC_AUTO1 | 수정 | |\n")))
    assert code == EXIT_PASS, out


# ---- 양식 산출은 새 절에 영향받지 않는다 ----

FORM = """\
## 근거 요구사항

REQ-001

## 양식 항목

### 시험양식 · Info

| 항목 | 값 |
|---|---|
| 코드 | X-01 |

#### 설명

1. 첫째
"""

OBJ = "## 사용 객체\n\n" + HEAD + "| CDS View | ZA | 생성 | |\n\n"


def test_양식_항목_파싱은_사용_객체_절에_영향받지_않는다():
    base = export.parse_spec("# DEV-001\n\n" + FORM)
    before = export.parse_spec("# DEV-001\n\n" + OBJ + FORM)
    # 양식 항목 뒤에 사용 객체가 와도 그 절은 양식 항목의 끝으로 잘려야 한다.
    after = export.parse_spec("# DEV-001\n\n" + FORM + "\n" + OBJ)
    assert base == before == after


# ---- 규칙 데이터 검증 ----

def test_모르는_키는_설정_오류(tmp_path):
    with pytest.raises(ConfigError, match="모르는 키"):
        run(tmp_path, doc(HEAD), 패턴s={"이름": "x"})
    with pytest.raises(ConfigError, match="모르는 키"):
        run(tmp_path, doc(HEAD), 필수임=True)


def test_값이_목록이_아니면_설정_오류(tmp_path):
    with pytest.raises(ConfigError):
        run(tmp_path, doc(HEAD), 값={"작업": "생성/수정/참조"})
    with pytest.raises(ConfigError):
        run(tmp_path, doc(HEAD), 패턴={"이름": ["x"]})


# ---- 표 파싱 ----

def test_이스케이프한_파이프는_칸_구분이_아니다(tmp_path):
    assert run(tmp_path, doc(HEAD + "| CDS View | ZA | 생성 | a \\| b |\n")) == []


def test_이스케이프_없는_파이프는_칸이_늘어_위반이고_안내한다(tmp_path):
    v = run(tmp_path, doc(HEAD + "| CDS View | ZA | 생성 | a | b |\n"))
    assert len(v) == 1 and "\\|" in v[0].message


def test_백틱_안_파이프는_칸_구분으로_본다_한계(tmp_path):
    v = run(tmp_path, doc(HEAD + "| CDS View | ZA | 생성 | `a | b` |\n"))
    assert len(v) == 1 and "칸 수" in v[0].message


def test_머리_다음_줄이_정렬_줄이_아니면_표가_아니다(tmp_path):
    v = run(tmp_path, doc("| 종류 | 이름 | 작업 | 비고 |\n| CDS View | ZA | 생성 | |\n"))
    assert len(v) == 1 and "표가 없다" in v[0].message


def test_정렬_줄_모양_행은_머리_바로_다음에서만_정렬_줄이다(tmp_path):
    v = run(tmp_path, doc(HEAD + "|---|---|---|---|\n"))
    # 머리 바로 다음이 아닌 정렬 줄 모양 행은 데이터 행이라 값 검사를 받는다.
    assert [x.actual for x in v] == ["---", "---", "---"]
