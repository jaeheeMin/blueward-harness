"""SRS·Spec·원장 번호 짝 검사(#284)를 단언한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_changed import main_entry  # noqa: E402
from render_report import render  # noqa: E402

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION  # noqa: E402
from checker.pairing import CANNOT_CHECK, PASS, SKIPPED, VIOLATION, check_pairing  # noqa: E402

SRS_HEAD = "| ID | Title | Status | Priority (PO) | 출처 | 다음 단계 | Development RICEFW ID |\n|---|---|---|---|---|---|---|\n"
LEDGER_HEAD = "| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n"


def _srs(tmp: Path, rows: list[str], head: str = SRS_HEAD) -> None:
    path = tmp / "docs" / "ssot" / "SRS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# SRS\n\n## 요구사항\n\n" + head + "\n".join(rows) + "\n\n## 참조\n\n없음\n", encoding="utf-8")


def _req(n: int, step: str, ricefw: str = "", status: str = "New") -> str:
    return f"| REQ-{n:03d} | 제목{n} | {status} | High | 고객 | {step} | {ricefw} |"


def _ledger(tmp: Path, rows: list[str], name: str = "판매.md") -> None:
    path = tmp / "audit" / "ledger" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 판매\n\n## 개발 건\n\n" + LEDGER_HEAD + "\n".join(rows) + "\n\n## 메모\n\n없음\n", encoding="utf-8")


def _lrow(n: int, spec: str = "-", content: str = "내용") -> str:
    return f"| DEV-{n:03d} | {content} | {spec} | 홍길동 | 대기 |  |"


def _spec(tmp: Path, n: int, req: int | None = None, name: str = "요약") -> str:
    req = n if req is None else req
    path = tmp / "docs" / "spec" / f"DEV-{n:03d}-{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Spec\n\n## 근거 요구사항\n\nREQ-{req:03d} ([SRS](../ssot/SRS.md))\n\n## 참조\n\n없음\n", encoding="utf-8")
    return f"[{path.name}](../../docs/spec/{path.name})"


def _kinds(items: list[dict]) -> set[str]:
    return {i["kind"] for i in items}


def test_원장이_없으면_대상이_아니다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-009")])
    assert check_pairing(tmp_path)["status"] == SKIPPED


def test_모두_맞으면_통과이고_경고도_없다(tmp_path):
    link = _spec(tmp_path, 1)
    _srs(tmp_path, [_req(1, "개발", "DEV-001"), _req(2, "설정"), _req(3, "미정")])
    _ledger(tmp_path, [_lrow(1, link), _lrow(2, "설정")])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS
    assert r["violations"] == [] and _kinds(r["warnings"]) == set()


def test_숫자_정규화로_비교한다(tmp_path):
    _srs(tmp_path, [_req(3, "개발", "DEV-3")])
    _ledger(tmp_path, ["| DEV-3 | x | - | a | 대기 |  |"])
    r = check_pairing(tmp_path)
    assert r["violations"] == []


def test_개발인데_RICEFW_ID가_다른_번호면_위반이다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-002")])
    _ledger(tmp_path, [_lrow(1)])
    r = check_pairing(tmp_path)
    assert r["status"] == VIOLATION
    assert _kinds(r["violations"]) == {"ricefw_mismatch"}
    assert r["violations"][0]["file"] == "docs/ssot/SRS.md"


def test_개발인데_RICEFW_ID가_비어_있거나_열이_없으면_위반이_아니다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "")])
    _ledger(tmp_path, [_lrow(1)])
    assert check_pairing(tmp_path)["violations"] == []
    head = "| ID | Title | Status | 다음 단계 |\n|---|---|---|---|\n"
    _srs(tmp_path, ["| REQ-001 | t | New | 개발 |"], head=head)
    assert check_pairing(tmp_path)["violations"] == []


def test_설정_미정에_RICEFW_ID가_있으면_위반이다(tmp_path):
    _srs(tmp_path, [_req(1, "설정", "DEV-001"), _req(2, "미정", "DEV-002")])
    _ledger(tmp_path, [_lrow(1, "설정")])
    r = check_pairing(tmp_path)
    assert [x["kind"] for x in r["violations"]] == ["ricefw_not_empty", "ricefw_not_empty"]


def test_같은_DEV가_원장_여러_파일에_있으면_위반이다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1)], name="a.md")
    _ledger(tmp_path, [_lrow(1)], name="b.md")
    r = check_pairing(tmp_path)
    assert _kinds(r["violations"]) == {"ledger_duplicate"}


def test_같은_DEV가_한_원장에_두_줄이면_위반이다(tmp_path):
    _ledger(tmp_path, [_lrow(1), _lrow(1)])
    assert _kinds(check_pairing(tmp_path)["violations"]) == {"ledger_duplicate"}


def test_원장_Spec_링크_대상이_없으면_위반이다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1, "[x](../../docs/spec/DEV-001-없음.md)")])
    r = check_pairing(tmp_path)
    assert _kinds(r["violations"]) == {"spec_link_missing"}
    assert r["violations"][0]["file"] == "audit/ledger/판매.md"


def test_원장_Spec_링크가_다른_번호_파일이면_위반이다(tmp_path):
    link = _spec(tmp_path, 2)
    _srs(tmp_path, [_req(1, "개발", "DEV-001"), _req(2, "개발", "DEV-002")])
    _ledger(tmp_path, [_lrow(1, link), _lrow(2, "-")])
    assert _kinds(check_pairing(tmp_path)["violations"]) == {"spec_link_mismatch"}


def test_Spec_근거_REQ가_파일명_번호와_다르면_위반이다(tmp_path):
    link = _spec(tmp_path, 1, req=2, name="판매오더조회")
    _srs(tmp_path, [_req(1, "개발", "DEV-001"), _req(2, "개발", "DEV-002")])
    _ledger(tmp_path, [_lrow(1, link)])
    r = check_pairing(tmp_path)
    assert _kinds(r["violations"]) == {"spec_req_mismatch"}
    assert "판매오더조회" in r["violations"][0]["file"]


def test_한글_파일명_Spec_링크도_찾는다(tmp_path):
    _spec(tmp_path, 1, name="판매오더-조회앱")
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1, "[s](../../docs/spec/DEV-001-%ED%8C%90%EB%A7%A4%EC%98%A4%EB%8D%94-%EC%A1%B0%ED%9A%8C%EC%95%B1.md)")])
    assert check_pairing(tmp_path)["status"] == PASS
    _ledger(tmp_path, [_lrow(1, "[s](../../docs/spec/DEV-001-판매오더-조회앱.md)")])
    assert check_pairing(tmp_path)["status"] == PASS


def test_개발_REQ에_원장도_Spec도_없으면_경고다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS and _kinds(r["warnings"]) == {"no_ledger_no_spec"}


def test_Spec만_있고_원장_줄이_없으면_경고다(tmp_path):
    _spec(tmp_path, 1)
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [])
    assert _kinds(check_pairing(tmp_path)["warnings"]) == {"no_ledger"}


def test_원장_Spec_칸이_대시면_작성_전_경고_하나만_낸다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1, "-")])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS and [w["kind"] for w in r["warnings"]] == ["spec_not_yet"]


def test_개발인데_원장_Spec_칸이_설정이면_경고다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1, "설정")])
    assert [w["kind"] for w in check_pairing(tmp_path)["warnings"]] == ["spec_cell_config"]


def test_설정_REQ에_원장_줄이_없으면_경고다(tmp_path):
    _srs(tmp_path, [_req(1, "설정")])
    _ledger(tmp_path, [])
    assert _kinds(check_pairing(tmp_path)["warnings"]) == {"no_ledger_config"}


def test_SRS에_없는_원장_DEV와_Spec은_경고다(tmp_path):
    _spec(tmp_path, 7)
    _srs(tmp_path, [_req(1, "미정")])
    _ledger(tmp_path, [_lrow(7)])
    assert _kinds(check_pairing(tmp_path)["warnings"]) == {"ledger_without_req", "spec_without_req"}


def test_보류_취소_REQ는_경고하지_않는다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001", "On Hold"), _req(2, "개발", "DEV-002", "Dropped"),
                    _req(3, "개발", "DEV-003", "Duplicate"), _req(4, "설정", "", "Dropped")])
    _ledger(tmp_path, [_lrow(1, "-", "[보류] 내용")])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS and r["warnings"] == []


def test_SRS가_없으면_SRS_대조만_건너뛴다(tmp_path):
    _ledger(tmp_path, [_lrow(1), _lrow(1)])
    r = check_pairing(tmp_path)
    assert _kinds(r["violations"]) == {"ledger_duplicate"}
    assert _kinds(r["warnings"]) == {"srs_missing"}


def test_SRS_요구사항_표가_아직_없으면_SRS_대조를_건너뛴다(tmp_path):
    path = tmp_path / "docs" / "ssot" / "SRS.md"
    path.parent.mkdir(parents=True)
    path.write_text("# SRS\n\n## 요구사항\n\n아직 작성 전이다.\n", encoding="utf-8")
    _ledger(tmp_path, [_lrow(1)])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS and r["warnings"] == []


def test_다음_단계_열이_없으면_모두_개발로_보고_대조하고_참고를_남긴다(tmp_path):
    head = "| ID | Title | LoB | Type | Status | Priority (PO) | 출처 |\n|---|---|---|---|---|---|---|\n"
    _srs(tmp_path, ["| REQ-001 | t | SD | RAP | New | High | 고객 |",
                    "| REQ-002 | t | SD | RAP | On Hold | High | 고객 |"], head=head)
    _ledger(tmp_path, [_lrow(1)])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS
    assert _kinds(r["warnings"]) == {"srs_no_next_step", "spec_not_yet"}


def test_Backlog_양식에서도_개발로_본_REQ의_짝_위반은_잡는다(tmp_path):
    head = "| ID | Title | Status |\n|---|---|---|\n"
    _srs(tmp_path, ["| REQ-001 | t | New |"], head=head)
    _ledger(tmp_path, [_lrow(1, "[x](../../docs/spec/DEV-001-없음.md)")])
    assert _kinds(check_pairing(tmp_path)["violations"]) == {"spec_link_missing"}


def test_ID_열이_없는_요구사항_표는_검사_불능이다(tmp_path):
    _srs(tmp_path, ["| REQ-001 | t |"], head="| 번호 | Title |\n|---|---|\n")
    _ledger(tmp_path, [_lrow(1)])
    assert check_pairing(tmp_path)["status"] == CANNOT_CHECK


def test_근거_요구사항_설명에_옛_번호가_섞여도_위반이_아니다(tmp_path):
    path = tmp_path / "docs" / "spec" / "DEV-002-판매오더조회앱.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# DEV-002\n\n## 근거 요구사항\n\nREQ-002\n([SRS](../ssot/SRS.md))\n\n"
        "열세 줄(옛 REQ-001~013)을 합쳤다. 옛 번호는 `(옛 REQ-00x)` 로 남았다.\n\n## 참조\n\n없음\n",
        encoding="utf-8",
    )
    _srs(tmp_path, [_req(2, "개발", "DEV-002")])
    _ledger(tmp_path, [_lrow(2, "[s](../../docs/spec/DEV-002-판매오더조회앱.md)")])
    assert check_pairing(tmp_path)["status"] == PASS


def test_원장_Spec_칸의_외부_링크는_파일_검사를_하지_않고_참고만_낸다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1, "[s](https://example.com/DEV-009-x.md)")])
    r = check_pairing(tmp_path)
    assert r["status"] == PASS and "spec_link_external" in _kinds(r["warnings"])


def test_요구사항_절이_없으면_검사_불능이다(tmp_path):
    path = tmp_path / "docs" / "ssot" / "SRS.md"
    path.parent.mkdir(parents=True)
    path.write_text("# SRS\n\n내용\n", encoding="utf-8")
    _ledger(tmp_path, [])
    assert check_pairing(tmp_path)["status"] == CANNOT_CHECK


def test_원장_표_머리가_없으면_검사_불능이다(tmp_path):
    path = tmp_path / "audit" / "ledger" / "깨짐.md"
    path.parent.mkdir(parents=True)
    path.write_text("# 깨짐\n\n## 개발 건\n\n표가 없다\n", encoding="utf-8")
    r = check_pairing(tmp_path)
    assert r["status"] == CANNOT_CHECK and "깨짐.md" in r["message"]


def test_읽지_못하는_파일은_검사_불능이다(tmp_path):
    path = tmp_path / "audit" / "ledger" / "깨짐.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00bad")
    assert check_pairing(tmp_path)["status"] == CANNOT_CHECK


# --- check_changed 통합 ---------------------------------------------------

def _std_root(tmp: Path) -> None:
    (tmp / "templates").mkdir(exist_ok=True)
    (tmp / "rules").mkdir(exist_ok=True)
    # 관할이 SRS 에 겹치지 않는 규칙 하나. 규칙 폴더가 비면 엔진이 설정 오류를 낸다.
    (tmp / "rules" / "메모.yaml").write_text(
        '관할: "memo/**"\n규칙:\n  - 종류: filename\n    패턴: ".*"\n', encoding="utf-8"
    )


def test_원장이_바뀌면_짝_검사가_리포트에_합쳐지고_위반이면_1이다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _srs(tmp_path, [_req(1, "개발", "DEV-002")])
    _ledger(tmp_path, [_lrow(1)])
    (tmp_path / "changed.txt").write_text("audit/ledger/판매.md\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main_entry(["changed.txt"]) == EXIT_VIOLATION
    report = json.loads(capsys.readouterr().out)
    assert report["pairing"]["status"] == VIOLATION
    text = render(report, 1)
    assert "## 번호 짝" in text and "ricefw" not in text and "DEV-002" in text


def test_경고만_있으면_통과하고_코멘트에_참고가_나온다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1)])
    (tmp_path / "changed.txt").write_text("docs/ssot/SRS.md\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    report = json.loads(capsys.readouterr().out)
    assert report["pairing"]["status"] == PASS
    assert "참고" in render(report, 0)


def test_짝_검사_불능이면_2이고_코멘트에_검사_불능이_나온다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    path = tmp_path / "audit" / "ledger" / "깨짐.md"
    path.parent.mkdir(parents=True)
    path.write_text("# x\n", encoding="utf-8")
    (tmp_path / "changed.txt").write_text("audit/ledger/깨짐.md\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main_entry(["changed.txt"]) == EXIT_CONFIG_ERROR
    report = json.loads(capsys.readouterr().out)
    assert "검사 불능" in render(report, 2)


def test_원장이_없는_저장소는_리포트가_바뀌지_않는다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _srs(tmp_path, [_req(1, "개발", "DEV-009")])
    (tmp_path / "changed.txt").write_text("docs/ssot/SRS.md\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main_entry(["changed.txt"])
    assert "pairing" not in json.loads(capsys.readouterr().out)


def test_관계없는_파일만_바뀌면_짝_검사를_돌리지_않는다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _ledger(tmp_path, [_lrow(1), _lrow(1)])
    (tmp_path / "README.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "changed.txt").write_text("README.md\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    assert "pairing" not in json.loads(capsys.readouterr().out)


def test_메시지의_번호_뒤에_SRS_제목을_붙인다(tmp_path):
    link = _spec(tmp_path, 1)
    _srs(tmp_path, [_req(1, "개발", "DEV-001")])
    _ledger(tmp_path, [_lrow(1, link)], name="a.md")
    _ledger(tmp_path, [_lrow(1, link)], name="b.md")
    _spec(tmp_path, 2, req=3)
    msgs = {v["kind"]: v["message"] for v in check_pairing(tmp_path)["violations"]}
    assert msgs["ledger_duplicate"].startswith("DEV-001(제목1) 가 원장에 2번")
    # 파일명 번호 DEV-002 는 SRS·원장 어디에도 제목이 없고, 근거 REQ-003 도 없다. 추측하지 않는다
    assert "파일명은 DEV-002(제목 미확인) 인데" in msgs["spec_req_mismatch"]
    assert "REQ-003(제목 미확인)" in msgs["spec_req_mismatch"]


def test_SRS에_없는_번호는_원장_내용으로_대신하고_둘_다_없으면_제목_미확인이다(tmp_path):
    _spec(tmp_path, 7)
    _spec(tmp_path, 8)
    _srs(tmp_path, [_req(1, "미정")])
    _ledger(tmp_path, [_lrow(7, content="원장 내용 7")])
    warnings = check_pairing(tmp_path)["warnings"]
    ledger_msgs = [w["message"] for w in warnings if w["kind"] == "ledger_without_req"]
    assert ledger_msgs == ["원장의 DEV-007(원장 내용 7) 에 대응하는 SRS 요구사항 REQ-007(원장 내용 7) 가 없습니다."]
    spec_msgs = [w["message"] for w in warnings if w["kind"] == "spec_without_req"]
    assert "Spec DEV-008(제목 미확인) 에 대응하는 SRS 요구사항 REQ-008(제목 미확인) 가 없습니다." in spec_msgs


def test_SRS_제목_칸이_대시나_빈_값이면_원장_내용_그것도_없으면_제목_미확인이다(tmp_path):
    _srs(tmp_path, [
        "| REQ-001 | - | New | High | 고객 | 미정 |  |",
        "| REQ-002 | — | New | High | 고객 | 미정 |  |",
        "| REQ-003 |  | New | High | 고객 | 미정 |  |",
    ])
    _ledger(tmp_path, [_lrow(1, content="원장 내용 1"), _lrow(2, content="-"), _lrow(2, content="-")], name="a.md")
    _ledger(tmp_path, [_lrow(2, content="-")], name="b.md")
    msg = next(v["message"] for v in check_pairing(tmp_path)["violations"] if v["kind"] == "ledger_duplicate")
    assert msg.startswith("DEV-002(제목 미확인) 가 원장에")


def test_SRS가_없으면_원장_내용으로_제목을_대신한다(tmp_path):
    _ledger(tmp_path, [_lrow(1, content="원장 내용 1"), _lrow(1, content="원장 내용 1")])
    (v,) = check_pairing(tmp_path)["violations"]
    assert v["message"].startswith("DEV-001(원장 내용 1) 가 원장에 2번")


def test_원장_Spec_칸과_RICEFW_메시지에도_제목이_붙는다(tmp_path):
    _srs(tmp_path, [_req(1, "개발", "DEV-009"), _req(2, "개발", "DEV-002"), _req(3, "개발", "DEV-003")])
    _ledger(tmp_path, [_lrow(2, "[x](../../docs/spec/DEV-002-없음.md)"), _lrow(3, "[x](../../docs/spec/DEV-004-a.md)")])
    msgs = {v["kind"]: v["message"] for v in check_pairing(tmp_path)["violations"]}
    assert msgs["ricefw_mismatch"].startswith("REQ-001(제목1) 는 다음 단계가 `개발`")
    missing = [v["message"] for v in check_pairing(tmp_path)["violations"] if v["kind"] == "spec_link_missing"]
    assert any(m.startswith("DEV-002(제목2) 의 Spec 칸 링크") for m in missing)
    assert msgs["spec_link_mismatch"].startswith("DEV-003(제목3) 줄의 Spec 칸이")
