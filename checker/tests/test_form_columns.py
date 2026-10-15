"""`form_columns` 규칙을 검증한다(이슈 #316).

원본 md(SRS, Spec 의 `## 양식 항목`)의 열·소제목이 양식 지도 밖이면 거절한다. 스캐폴드가 넣는 실제
규칙 파일(`rules/ssot.yaml`, `rules/spec.yaml`)로 돌려서, Project Repository 가 받는 규칙 그대로의
동작을 본다. 훅(저장)은 문서를 임시 폴더로 옮기고 `--root` 만 그쪽으로 돌리므로 그 경로도 따로 본다.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, main
from checker.tests.test_scaffold import _run_auto, scaffold

BACKLOG_MAP = """\
양식: Backlog
설명: SRS 요구사항 표를 Backlog 시트로
템플릿: ../Backlog.xlsx
산출:
  폴더: docs/out
  파일명: "BW_Backlog List_v{버전}.xlsx"
  자리:
    버전: {메타: 버전}
시트:
  - 이름: Backlog
    표:
      - 이름: Backlog
        원본: SRS
        머리글_행: 3
        시작_행: 4
        번호_열: Backlog ID
        md_전용: [출처]
        열:
          Backlog ID: A
          LoB: B
          Title: C
          Short Description: D
          Status: E
          Priority (PO): F
          Development RICEFW ID: G
  - 이름: Values Drop Down
    설명: 드롭다운 목록 시트 — 건드리지 않는다
"""

SPEC_MAP = """\
양식: 시험양식
설명: 시험용
템플릿: ../시험.xlsx
산출:
  폴더: docs/out
  파일명: "T_{ID}_v{버전}.xlsx"
  자리:
    버전: {표: 이력, 열: Ver, 행: 마지막}
    ID: {칸: 코드}
시트:
  - 이름: Info
    칸:
      - 항목: 코드
        위치: B2
      - 항목: 제목
        위치: B3
    표:
      - 이름: 이력
        머리글_행: 8
        시작_행: 9
        열:
          Ver: A
          Date: B
    서술:
      - 이름: 설명
        위치: A14
"""


def _srs(header: str = "| ID | Title | Status | Priority (PO) | 출처 | 다음 단계 |",
         row: str = "| REQ-001 | 로그인 | New | 1. Must-Have | 회의 | 개발 |",
         details: str = "") -> str:
    cols = header.count("|") - 1
    sep = "|" + "---|" * cols
    return (
        "# 시험 SRS\n\n버전: 0.1\n\n## 배경과 목표\n\nx\n\n## 범위\n\n- 하는 것: x\n- 하지 않는 것: y\n\n"
        "## AS-IS / TO-BE\n\nx\n\n## 요구사항\n\n"
        f"{header}\n{sep}\n{row}\n\n{details}\n## 참조\n\n링크\n\n## 미결 사항\n\n없음\n"
    )


def _detail(*names: str) -> str:
    return "### REQ-001 로그인\n\n" + "".join(f"#### {n}\n\n내용\n\n" for n in names)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    scaffold(tmp_path, "고객사", "프로젝트", False)
    return tmp_path


def _with_map(repo: Path, text: str = BACKLOG_MAP, name: str = "Backlog.yaml") -> None:
    (repo / "templates" / "forms" / name).write_text(text, encoding="utf-8")


def _check(repo: Path, capsys, text: str, relative: str = "docs/ssot/SRS.md"):
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    code, out = _run_auto(capsys, path)
    return code, out


def _violations(out: dict, rule: str = "form_columns") -> list[dict]:
    return [v for f in out["files"] for v in f.get("violations", []) if v["rule"] == rule]


# ---------------------------------------------------------------- 지도가 있는 저장소의 SRS

def test_지도_열만_쓴_SRS는_통과한다(repo, capsys):
    _with_map(repo)
    text = _srs("| ID | Title | LoB | Status | Priority (PO) | Development RICEFW ID | 출처 | 다음 단계 |",
                "| REQ-001 | 로그인 | Finance | New | 1. Must-Have | DEV-001 | 회의 | 개발 |",
                _detail("Short Description"))
    code, out = _check(repo, capsys, text)
    assert code == EXIT_PASS, out


def test_모르는_열은_위반이고_허용_목록과_다음_행동을_알린다(repo, capsys):
    _with_map(repo)
    code, out = _check(repo, capsys, _srs("| ID | Title | Scope | Status |", "| REQ-001 | 로그인 | 가 | New |"))
    assert code == EXIT_VIOLATION
    [v] = _violations(out)
    assert v["message"].startswith("양식 밖 열: Scope. 허용")
    assert "Backlog ID" in v["expected"] and "출처" in v["expected"] and "다음 단계" in v["expected"]
    assert "다음: 양식 지도에 있는 열 이름으로 고치거나" in v["message"]
    assert v["actual"] == "Scope"


def test_오타_열도_위반이다(repo, capsys):
    _with_map(repo)
    code, out = _check(repo, capsys, _srs("| ID | Title | Satus |", "| REQ-001 | 로그인 | New |"))
    assert code == EXIT_VIOLATION
    assert _violations(out)[0]["actual"] == "Satus"


def test_모르는_소제목은_위반이고_어느_REQ인지_알린다(repo, capsys):
    _with_map(repo)
    code, out = _check(repo, capsys, _srs(details=_detail("Short Description", "Notes")))
    assert code == EXIT_VIOLATION
    [v] = _violations(out)
    assert v["actual"] == "Notes" and "REQ-001" in v["message"] and "`#### Notes`" in v["message"]


def test_번호_열은_상세_소제목으로_쓸_수_없다(repo, capsys):
    _with_map(repo)
    code, out = _check(repo, capsys, _srs(details=_detail("Backlog ID")))
    assert code == EXIT_VIOLATION
    assert _violations(out)[0]["actual"] == "Backlog ID"


def test_md_전용_열과_다음_단계_열은_지도에_안_적어도_통과한다(repo, capsys):
    _with_map(repo)
    # 출처는 지도 md_전용, 다음 단계는 엔진 기본 md 전용. 상세 절에도 쓸 수 있다.
    code, out = _check(repo, capsys, _srs(details=_detail("출처", "다음 단계")))
    assert code == EXIT_PASS, out


def test_지도_열이_표에_빠진_것은_허용한다_243(repo, capsys):
    _with_map(repo)
    code, out = _check(repo, capsys, _srs("| ID | Title |", "| REQ-001 | 로그인 |"))
    assert code == EXIT_PASS, out


def test_열_이름은_산출과_같은_정규화로_비교한다(repo, capsys):
    _with_map(repo)
    code, out = _check(repo, capsys, _srs("| ID |  Priority   (PO) |  Title |", "| REQ-001 | 1. Must-Have | 로그인 |"))
    assert code == EXIT_PASS, out


def test_코드_펜스_안_예시_열은_보지_않는다(repo, capsys):
    _with_map(repo)
    fence = "예시:\n\n```\n### REQ-009 예\n\n#### 아무거나\n\n| ID | 엉뚱 |\n```\n\n"
    code, out = _check(repo, capsys, _srs(details=_detail("Short Description") + fence))
    assert code == EXIT_PASS, out


def test_지도를_못_읽으면_검사_불능이다(repo, capsys):
    _with_map(repo)
    _with_map(repo, "양식: 깨짐\n시트: [\n", "깨짐.yaml")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR
    assert out["status"] == "config_error" and "깨짐.yaml" in out["message"]


def test_지도에_시트가_없어도_검사_불능이다(repo, capsys):
    _with_map(repo, "양식: 비었음\n", "비었음.yaml")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR and "비었음.yaml" in out["message"]


def test_SRS_원본_지도가_여럿이면_기준을_몰라_검사_불능이다(repo, capsys):
    _with_map(repo)
    _with_map(repo, BACKLOG_MAP.replace("양식: Backlog", "양식: 다른"), "다른.yaml")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR and "여럿" in out["message"]


def test_Spec_원본_지도만_있으면_SRS는_틀_기준이다(repo, capsys):
    _with_map(repo, SPEC_MAP, "시험양식.yaml")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_PASS, out
    code, out = _check(repo, capsys, _srs("| ID | Title | LoB |", "| REQ-001 | 로그인 | 가 |"))
    assert code == EXIT_VIOLATION and _violations(out)[0]["actual"] == "LoB"


def test_훅처럼_문서만_임시_폴더로_옮겨_돌려도_기준_폴더의_지도를_쓴다(repo, tmp_path_factory):
    _with_map(repo)
    staged_root = tmp_path_factory.mktemp("doc-guard-")
    staged = staged_root / "docs" / "ssot" / "SRS.md"
    staged.parent.mkdir(parents=True)
    staged.write_text(_srs("| ID | Title | Scope |", "| REQ-001 | 로그인 | 가 |"), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["--rules", str(repo / "rules"), "--root", str(staged_root), str(staged)])
    assert code == EXIT_VIOLATION
    out = json.loads(buf.getvalue())
    assert _violations(out)[0]["actual"] == "Scope"


# ---------------------------------------------------------------- 지도가 없는 저장소의 SRS

def test_지도가_없으면_SRS_틀의_열이_기준이다(repo, capsys):
    code, out = _check(repo, capsys, _srs(details=_detail("설명", "완료 조건")))
    assert code == EXIT_PASS, out


def test_지도가_없을_때_틀에_없는_열은_위반이다(repo, capsys):
    code, out = _check(repo, capsys, _srs("| ID | Title | 요구사항 | 상태 |", "| REQ-001 | 가 | 나 | 다 |"))
    assert code == EXIT_VIOLATION
    [v] = _violations(out)
    assert v["actual"] == "요구사항, 상태" and "templates/harness/SRS.md" in v["message"]


def test_지도가_없을_때_모르는_소제목은_위반이다(repo, capsys):
    code, out = _check(repo, capsys, _srs(details=_detail("설명", "Short Description")))
    assert code == EXIT_VIOLATION
    assert _violations(out)[0]["actual"] == "Short Description"


def test_템플릿에_요구사항_표가_없으면_검사_불능이다(repo, capsys):
    tpl = repo / "templates" / "harness" / "SRS.md"
    tpl.write_text(tpl.read_text(encoding="utf-8").replace("## 요구사항", "## 요구"), encoding="utf-8")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR and "요구사항" in out["message"]


def test_요구사항_절이_없는_SRS는_이_규칙이_말하지_않는다(repo, capsys):
    code, out = _check(repo, capsys, "# SRS\n\n## 배경과 목표\n\nx\n")
    assert code == EXIT_VIOLATION  # 필수 절 위반은 required_sections 가 낸다
    assert _violations(out) == [] and _violations(out, "required_sections")


def test_표_구조가_깨진_SRS는_위반으로_알린다(repo, capsys):
    text = _srs().replace("|---|---|---|---|---|---|", "내용이 구분선이 아니다")
    code, out = _check(repo, capsys, text)
    assert code == EXIT_VIOLATION
    assert "구조가 깨져" in _violations(out)[0]["message"]


# ---------------------------------------------------------------- Spec 의 `## 양식 항목`

def _spec(body: str) -> str:
    return (
        "# DEV-001 시험\n\n## 근거 요구사항\n\nREQ-001\n\n## 개요\n\nx\n\n## 상세 설계\n\nx\n\n"
        f"## 양식 항목\n\n{body}\n## 완료 조건\n\nx\n\n## 참조\n\n링크\n\n## 변경 이력\n\n없음\n"
    )


SPEC_OK = """\
### 시험양식 · Info

| 항목 | 값 |
|---|---|
| 코드 | CO-1 |
| 제목 | 가 |

#### 이력

| Ver | Date |
|---|---|
| 0.1 | 2026-10-14 |

#### 설명

본문
"""


def _spec_check(repo: Path, capsys, body: str):
    return _check(repo, capsys, _spec(body), "docs/spec/DEV-001-시험.md")


def test_Spec_양식_항목이_지도_안이면_통과한다(repo, capsys):
    _with_map(repo, SPEC_MAP, "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK)
    assert code == EXIT_PASS, out


def test_Spec_양식_항목_절이_없으면_통과한다(repo, capsys):
    code, out = _check(repo, capsys, _spec("").replace("## 양식 항목\n\n", ""), "docs/spec/DEV-001-시험.md")
    assert code == EXIT_PASS, out


@pytest.mark.parametrize("old,new,actual", [
    ("| 제목 | 가 |", "| 없는칸 | 가 |", "없는칸"),
    ("#### 설명", "#### 없는서술", "없는서술"),
    ("| Ver | Date |", "| Ver | Dat |", "Dat"),
    ("### 시험양식 · Info", "### 시험양식 · 없는시트", "없는시트"),
])
def test_Spec_양식_밖_항목은_위반이다(repo, capsys, old, new, actual):
    _with_map(repo, SPEC_MAP, "시험양식.yaml")
    body = SPEC_OK.replace(old, new)
    if old.startswith("| Ver"):
        body = body.replace("|---|---|\n| 0.1 | 2026-10-14 |", "|---|---|\n| 0.1 | 2026-10-14 |")
    code, out = _spec_check(repo, capsys, body)
    assert code == EXIT_VIOLATION
    assert [v["actual"] for v in _violations(out)] == [actual]
    assert "다음: 양식 지도에 있는" in _violations(out)[0]["message"]


def test_Spec_지도가_없는_양식은_위반이다(repo, capsys):
    code, out = _spec_check(repo, capsys, SPEC_OK)
    assert code == EXIT_VIOLATION
    assert _violations(out)[0]["actual"] == "시험양식"


def test_Spec_지도를_못_읽으면_검사_불능이다(repo, capsys):
    _with_map(repo, "양식: 깨짐\n시트: [\n", "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK)
    assert code == EXIT_CONFIG_ERROR and "시험양식.yaml" in out["message"]


def test_Spec_에_SRS_원본_양식을_쓰면_위반이다(repo, capsys):
    _with_map(repo)
    code, out = _spec_check(repo, capsys, SPEC_OK.replace("시험양식", "Backlog"))
    assert code == EXIT_VIOLATION and "원본이 SRS" in _violations(out)[0]["message"]


# ---------------------------------------------------------------- 스캐폴드 규칙 파일

def test_스캐폴드_규칙에_form_columns가_켜져_있다(repo):
    assert "종류: form_columns" in (repo / "rules" / "ssot.yaml").read_text(encoding="utf-8")
    assert "종류: form_columns" in (repo / "rules" / "spec.yaml").read_text(encoding="utf-8")


def test_규칙_파일의_원본_값이_틀리면_설정_오류다(repo, capsys):
    rule = repo / "rules" / "ssot.yaml"
    rule.write_text(rule.read_text(encoding="utf-8").replace("원본: SRS", "원본: 모름"), encoding="utf-8")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR and "원본" in out["message"]


# ---------------------------------------------------------------- 검토 반영(지도 모양·지도 폴더·NFC)

@pytest.mark.parametrize("broken", [
    SPEC_MAP.replace("      - 항목: 코드\n", "      - 위치: B2\n", 1),                    # 칸에 항목 없음
    SPEC_MAP.replace("    칸:\n", "    칸: 코드\n", 1).split("      - 항목: 코드")[0] + "    표: []\n",  # 칸이 목록 아님
    SPEC_MAP.replace("        열:\n          Ver: A\n          Date: B\n", "        열: [Ver, Date]\n"),  # 열이 dict 아님
    SPEC_MAP.replace("      - 이름: 설명\n", "      - 위치: A14\n", 1),                    # 서술에 이름 없음
])
def test_Spec_지도_모양이_틀리면_traceback_없이_검사_불능이다(repo, capsys, broken):
    _with_map(repo, broken, "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK)
    assert code == EXIT_CONFIG_ERROR and out["status"] == "config_error"
    assert "시험양식.yaml" in out["message"]


def test_SRS_지도의_열이_사전이_아니면_검사_불능이다(repo, capsys):
    _with_map(repo, BACKLOG_MAP.replace("        열:\n          Backlog ID: A", "        열: [Backlog ID]\n        x:\n          Backlog ID: A"))
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR and "Backlog.yaml" in out["message"]


def test_명시한_지도_폴더가_없으면_틀_기준으로_갈아타지_않고_검사_불능이다(repo, capsys):
    rule = repo / "rules" / "ssot.yaml"
    rule.write_text(rule.read_text(encoding="utf-8").replace("원본: SRS", "원본: SRS\n    지도_폴더: ../templates/formz"), encoding="utf-8")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_CONFIG_ERROR and "formz" in out["message"]


def test_Spec은_지도_폴더가_없으면_검사_불능이다(repo, capsys):
    shutil.rmtree(repo / "templates" / "forms")
    code, out = _spec_check(repo, capsys, SPEC_OK)
    assert code == EXIT_CONFIG_ERROR and "폴더" in out["message"]


def test_기본_지도_폴더가_없으면_SRS는_틀_기준으로_본다(repo, capsys):
    shutil.rmtree(repo / "templates" / "forms")
    code, out = _check(repo, capsys, _srs())
    assert code == EXIT_PASS, out


def test_NFD로_쓴_한글_이름도_같은_이름으로_본다(repo, capsys):
    import unicodedata

    _with_map(repo, SPEC_MAP, "시험양식.yaml")
    body = SPEC_OK.replace("| 제목 | 가 |", "| " + unicodedata.normalize("NFD", "제목") + " | 가 |")
    code, out = _spec_check(repo, capsys, body)
    assert code == EXIT_PASS, out


# ---------------------------------------------------------------- 화면 그림 (#335 C2)

SPEC_MAP_SCREEN = SPEC_MAP + "    화면:\n      - 이름: 화면 1\n        영역: D20:P30\n"
SCREEN_MD = (
    "\n#### 화면 1 그림\n\n##### 조회 조건\n\n| 이름 | 필수 |\n|---|---|\n| 기간 | Y |\n\n"
    "##### 버튼\n\n| 이름 |\n|---|\n| 취소 |\n\n##### 결과 표\n\n| 열 |\n|---|\n| 품목 |\n"
)


def test_지도에_화면이_있으면_화면_그림_소제목을_허용한다(repo, capsys):
    _with_map(repo, SPEC_MAP_SCREEN, "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD)
    assert code == EXIT_PASS, out


def test_지도에_화면이_없으면_화면_그림_소제목은_양식_밖이다(repo, capsys):
    _with_map(repo, SPEC_MAP, "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD)
    assert code == EXIT_VIOLATION
    assert [v["actual"] for v in _violations(out)] == ["화면 1 그림"]


@pytest.mark.parametrize("old,new,actual", [
    ("#### 화면 1 그림", "#### 화면 2 그림", "화면 2 그림"),
    ("##### 버튼", "##### 필터", "화면 1 그림 · 필터"),
    ("| 이름 | 필수 |", "| 이름 | 비고 |", "화면 1 그림 · 조회 조건: 이름 | 비고"),
])
def test_화면_그림의_이름_소절_표머리가_틀리면_위반이다(repo, capsys, old, new, actual):
    _with_map(repo, SPEC_MAP_SCREEN, "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD.replace(old, new))
    assert code == EXIT_VIOLATION
    assert [v["actual"] for v in _violations(out)] == [actual]


def test_화면_그림의_필수_값과_행_모양도_저장_PR_검사가_본다(repo, capsys):
    _with_map(repo, SPEC_MAP_SCREEN, "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD.replace("| 기간 | Y |", "| 기간 | 예 |"))
    assert code == EXIT_VIOLATION
    assert [v["actual"] for v in _violations(out)] == ["화면 1 그림 · 조회 조건 '기간': 예"]
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD.replace("| 기간 | Y |", "| 기간 | Y | 추가 |"))
    assert code == EXIT_VIOLATION
    assert [v["actual"] for v in _violations(out)] == ["화면 1 그림 · 조회 조건: 1번째 행의 셀 수 3"]


def test_지도의_화면_값이_틀리면_검사_불능이다(repo, capsys):
    _with_map(repo, SPEC_MAP_SCREEN + "        칸_수: {라벨: 0}\n", "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD)
    assert code == EXIT_CONFIG_ERROR and "칸_수" in out["message"]


def test_화면_영역이_지도의_칸과_겹치면_검사_불능이다(repo, capsys):
    _with_map(repo, SPEC_MAP + "    화면:\n      - 이름: 화면 1\n        영역: A10:C16\n", "시험양식.yaml")
    code, out = _spec_check(repo, capsys, SPEC_OK + SCREEN_MD)
    assert code == EXIT_CONFIG_ERROR and "겹친다" in out["message"]
