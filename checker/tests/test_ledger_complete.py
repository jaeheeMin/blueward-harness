"""`checker.ledger_complete` 와 재사용 워크플로 `ledger-complete.yml` 을 검증한다(#346, #445).

병합 PR 이 대표 `[DEV-xxx]` 이슈를 닫았는데 원장 행이 `완료` 가 아니면 위반(1), 판정 불능은 2, 그 밖은 0 이다.
GitHub 호출은 `GhClient` 를 fake 로 갈아 끼워 네트워크 없이 확인하고, 원장은 tmp_path 에 만든다.
검사기는 파일을 쓰지 않으므로 모든 시험이 원장이 그대로인지도 본다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from checker import ledger_complete as mod
from checker.ssot_approval import GhError

_REAL_SUBJECT = mod._commit_subject  # autouse 가 바꾸기 전의 원본
SHA = "a" * 40
REPO = "o/r"

HEADER = (
    "# 원장\n\n## 관련 요구사항\n\n| REQ | 내용 |\n|---|---|\n| REQ-001 | x |\n\n"
    "## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n"
)


def _ledger(*rows: str, tail: str = "\n## 메모\n\n| ID | 내용 |\n|---|---|\n| DEV-001 | 메모 표는 건드리지 않는다 |\n") -> str:
    return HEADER + "".join(r + "\n" for r in rows) + tail


def _write(root: Path, name: str, text: str, newline: str = "\n") -> Path:
    path = root / "audit" / "ledger" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", newline))
    return path


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class FakeGh:
    def __init__(self, prs, issues=None, fail: str | None = None):
        self.prs = prs  # 리스트면 모든 커밋에 같은 PR, dict 면 {sha: PR 목록}
        self.issues = issues or {}
        self.fail = fail
        self.pulls: dict[int, dict] = {}  # 직접 조회용 repos/{repo}/pulls/{n}

    def get_json(self, path: str):
        if self.fail and self.fail in path:
            raise GhError(f"{path} 실패")
        if path.startswith(f"repos/{REPO}/pulls/"):
            return self.pulls[int(path.rsplit("/", 1)[1])]
        if path.startswith(f"repos/{REPO}/commits/") and path.endswith("/pulls"):
            if isinstance(self.prs, dict):
                return self.prs.get(path.split("/")[-2], [])
            return self.prs
        prefix = f"repos/{REPO}/issues/"
        if path.startswith(prefix):
            return self.issues[int(path[len(prefix):])]
        raise AssertionError(f"예상 못한 호출: {path}")


@pytest.fixture(autouse=True)
def subjects(monkeypatch) -> dict:
    """커밋 제목을 git 대신 이 표에서 읽는다. 없는 SHA 는 `(#N)` 없는 평범한 제목이다."""
    table: dict[str, str] = {}
    monkeypatch.setattr(mod, "_commit_subject", lambda root, sha: table.get(sha, "feat: 무언가"))
    return table


def _pr(body: str, number: int = 50, merged: bool = True, base: str = "main", at: str = "2026-10-16T00:00:00Z") -> dict:
    return {"number": number, "body": body, "merged_at": at if merged else None, "base": {"ref": base}}


def _run(monkeypatch, root: Path, client: FakeGh, capsys, shas: list[str] | None = None) -> tuple[int, dict]:
    monkeypatch.setattr(mod, "GhClient", lambda: client)
    shas = shas or [SHA]
    code = mod.main(["check", "--repo", REPO, *[a for s in shas for a in ("--sha", s)], "--root", str(root)])
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


ROW1 = "| DEV-001 | 구매요청 승인 | [Spec](../../docs/spec/DEV-001.md) | alice | 리뷰 | #40 |"
ROW2 = "| DEV-002 | 타일 노출 | - | bob | 진행 |  |"
DONE1 = "| DEV-001 | 구매요청 승인 | [Spec](../../docs/spec/DEV-001.md) | alice | 완료 | #50 |"
DONE2 = "| DEV-002 | 타일 노출 | - | bob | 완료 | #50 |"


def _rep(n: int, dev: str = "DEV-001", body: str = "") -> dict:
    return {"title": f"[{dev}] 제목", "body": body}


def test_대표_이슈를_닫고_원장이_완료면_아무것도_안_한다(tmp_path, monkeypatch, capsys):
    text = _ledger(DONE1, ROW2)
    path = _write(tmp_path, "app.md", text)
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("본문\n\nCloses #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok" and res["pending"] == [] and res["done"] == ["DEV-001"]
    assert _read(path) == text


def test_대표_이슈를_닫았는데_원장이_리뷰면_위반이고_원장은_그대로(tmp_path, monkeypatch, capsys):
    text = _ledger(ROW1, ROW2)
    path = _write(tmp_path, "app.md", text)
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 1 and res["status"] == "violation" and res["prs"] == [50]
    assert res["pending"] == [{"dev": "DEV-001", "pr": 50, "file": "audit/ledger/app.md", "state": "리뷰"}]
    assert "DEV-001" in res["reason"] and "리뷰" in res["reason"]
    assert _read(path) == text


def test_상태_칸이_비어_있어도_위반이다(tmp_path, monkeypatch, capsys):
    row = "| DEV-001 | x | - | alice |  |  |"
    code, res = _run(monkeypatch, tmp_path_with(tmp_path, row), FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 1 and "빈 칸" in res["reason"]


def tmp_path_with(root: Path, row: str) -> Path:
    _write(root, "app.md", _ledger(row))
    return root


def test_하위_작업_이슈만_닫으면_확인하지_않는다(tmp_path, monkeypatch, capsys):
    text = _ledger(ROW1)
    path = _write(tmp_path, "app.md", text)
    client = FakeGh([_pr("Closes #8")], {8: {"title": "Launchpad 타일 노출 (DEV-001)", "body": ""}})
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 0 and res["status"] == "skipped" and "확인 대상 아님" in res["reason"]
    assert _read(path) == text


def test_DEV_번호_없는_이슈는_대상이_아니다(tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, "app.md", _ledger(ROW1))
    client = FakeGh([_pr("Closes #9")], {9: {"title": "문서 정리", "body": ""}})
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 0 and res["status"] == "skipped"
    assert "리뷰" in _read(path)


def test_Closes_가_없으면_확인하지_않는다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "app.md", _ledger(ROW1))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Refs #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "skipped"


def test_완료인데_마지막_PR_이_달라도_통과한다(tmp_path, monkeypatch, capsys):
    # deliver 가 예측한 PR 번호가 실제와 달라도 완료 여부만 본다.
    _write(tmp_path, "app.md", _ledger(DONE1.replace("#50", "#30")))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok"


def test_이슈_본문이_가리킨_원장_파일만_본다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(ROW1))  # 같은 ID 가 다른 파일에 리뷰로 있어도 지정한 파일만 본다
    _write(tmp_path, "b.md", _ledger(DONE1))
    body = "배경\n\n진행 원장: DEV-001 (audit/ledger/b.md)\n"
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7, body=body)}), capsys)
    assert code == 0 and res["status"] == "ok"
    body = "진행 원장: DEV-001 (audit/ledger/a.md)"
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7, body=body)}), capsys)
    assert code == 1 and res["pending"][0]["file"] == "audit/ledger/a.md"


def test_이슈_본문이_가리킨_파일이_없으면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(DONE1))
    body = "진행 원장: DEV-001 (audit/ledger/none.md)"
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7, body=body)}), capsys)
    assert code == 2 and res["status"] == "unknown" and "none.md" in res["reason"]


def test_원장_폴더_밖을_가리키면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(DONE1))
    (tmp_path / "README.md").write_text(_ledger(DONE1), encoding="utf-8")
    body = "진행 원장: DEV-001 (audit/ledger/../../README.md)"
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7, body=body)}), capsys)
    assert code == 2


def test_원장에_그_행이_없으면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "app.md", _ledger(ROW2))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2 and res["status"] == "unknown" and "DEV-001" in res["reason"]


def test_행이_둘_이상이면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(DONE1))
    _write(tmp_path, "b.md", _ledger(DONE1))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2 and "둘 이상" in res["reason"]


def test_한_파일_안에서_행이_중복이어도_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(DONE1, DONE1))
    code, _ = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2


def test_개발_건_절이_없는_파일은_건너뛴다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", "# 원장 아님\n\n## 메모\n\n없음\n")
    _write(tmp_path, "b.md", _ledger(DONE1))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok"


def test_어느_파일에서도_행을_못_찾으면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", "# 원장 아님\n\n## 메모\n\n없음\n")
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2 and "찾지 못했다" in res["reason"]


def test_지정한_파일에_개발_건_절이_없으면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", "## 메모\n\n없음\n")
    body = "진행 원장: DEV-001 (audit/ledger/a.md)"
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7, body=body)}), capsys)
    assert code == 2 and "표 형식" in res["reason"]


def test_절은_있는데_표_머리가_깨졌으면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", "## 개발 건\n\n| 번호 | 내용 |\n|---|---|\n| DEV-001 | x |\n")
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2 and "표 형식" in res["reason"]


def test_표에_상태_열이_없으면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", "## 개발 건\n\n| ID | 내용 | Spec | 담당 |\n|---|---|---|---|\n| DEV-001 | x | - | a |\n")
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2 and "상태" in res["reason"]


def test_행에_상태_칸이_모자라면_2(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger("| DEV-001 | x | - | alice"))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 2 and "상태" in res["reason"]


def test_main_으로_병합된_PR_만_본다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(ROW1))
    other = _pr("Closes #7", base="release")
    code, res = _run(monkeypatch, tmp_path, FakeGh([other], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "skipped" and "병합 PR 없음" in res["reason"]
    code, res = _run(monkeypatch, tmp_path, FakeGh([other, _pr("Closes #7", number=51)], {7: _rep(7)}), capsys)
    assert code == 1 and res["prs"] == [51]


def test_코드_펜스_인라인_코드_주석_인용_안의_Closes_는_무시한다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(ROW1))
    body = "예시:\n```\nCloses #7\n```\n`Closes #7` 와 <!-- Closes #7 -->\n> Closes #7\n~~~\nFixes #7\n~~~\n"
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr(body)], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "skipped"
    assert mod.closing_issues(body + "\nCloses #8") == [8]


def test_push_의_여러_커밋을_모두_보고_같은_DEV_는_마지막_PR_기준(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(ROW1, ROW2))
    prs = {
        "s1": [_pr("Closes #7", number=50, at="2026-10-16T01:00:00Z")],
        "s2": [_pr("Closes #7 Closes #8", number=51, at="2026-10-16T02:00:00Z")],
    }
    client = FakeGh(prs, {7: _rep(7), 8: _rep(8, "DEV-002")})
    code, res = _run(monkeypatch, tmp_path, client, capsys, shas=["s1", "s2"])
    assert code == 1 and res["prs"] == [51]
    assert [(p["dev"], p["pr"]) for p in res["pending"]] == [("DEV-001", 51), ("DEV-002", 51)]


def test_서로_다른_PR_이_각각_다른_DEV_를_닫으면_PR_번호를_모두_낸다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(ROW1, ROW2))
    prs = {"s1": [_pr("Closes #7", number=50)], "s2": [_pr("Closes #8", number=51, at="2026-10-16T02:00:00Z")]}
    client = FakeGh(prs, {7: _rep(7), 8: _rep(8, "DEV-002")})
    code, res = _run(monkeypatch, tmp_path, client, capsys, shas=["s1", "s2"])
    assert code == 1 and res["prs"] == [50, 51]


def test_BOM_붙은_원장도_읽는다(tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, "a.md", "﻿" + _ledger(DONE1))
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf# ")


def test_BOM_뒤가_바로_개발_건_절이어도_읽는다(tmp_path, monkeypatch, capsys):
    text = "﻿## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n" + DONE1 + "\n"
    _write(tmp_path, "a.md", text)
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok"


def test_CRLF_원장과_이스케이프된_파이프_칸도_읽는다(tmp_path, monkeypatch, capsys):
    row = "| DEV-001 | a \\| b | - | alice | 완료 | #50 |"
    _write(tmp_path, "a.md", _ledger(row), newline="\r\n")
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok"


def test_gh_호출이_실패하면_2(tmp_path, monkeypatch, capsys):
    text = _ledger(DONE1)
    path = _write(tmp_path, "a.md", text)
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}, fail="/pulls"), capsys)
    assert code == 2 and res["status"] == "unknown" and "판정 불능" in res["reason"]
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}, fail="/issues/7"), capsys)
    assert code == 2
    assert _read(path) == text


def test_원장_폴더가_없으면_0(tmp_path, monkeypatch, capsys):
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "skipped" and "audit/ledger" in res["reason"]


def test_병합_PR_이_없으면_0(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.md", _ledger(ROW1))
    for prs in ([], [_pr("Closes #7", merged=False)]):
        code, res = _run(monkeypatch, tmp_path, FakeGh(prs, {7: _rep(7)}), capsys)
        assert code == 0 and res["status"] == "skipped" and "병합 PR 없음" in res["reason"]


def test_여러_DEV_를_닫으면_완료_아닌_것만_위반으로_낸다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "app.md", _ledger(DONE1, ROW2))
    client = FakeGh([_pr("Closes #7\nResolves #8, closes #9")], {
        7: _rep(7), 8: _rep(8, "DEV-002"), 9: {"title": "하위 (DEV-002)", "body": ""}})
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 1 and res["done"] == ["DEV-001"]
    assert [p["dev"] for p in res["pending"]] == ["DEV-002"]
    _write(tmp_path, "app.md", _ledger(DONE1, DONE2))
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 0 and res["status"] == "ok" and res["done"] == ["DEV-001", "DEV-002"]


def test_하나라도_판정_불능이면_2다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "app.md", _ledger(ROW1))  # DEV-002 행이 없다. DEV-001 은 위반이지만 판정이 우선이다
    client = FakeGh([_pr("Closes #7 Closes #8")], {7: _rep(7), 8: _rep(8, "DEV-002")})
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 2 and res["status"] == "unknown"


def test_번호_자릿수가_달라도_같은_개발_건이다(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "app.md", _ledger(DONE1))
    client = FakeGh([_pr("Closes #7")], {7: {"title": "[DEV-1] 제목", "body": ""}})
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 0 and res["status"] == "ok"


def test_순수_함수들():
    assert mod.closing_issues("Closes #1, fixes #2\nRESOLVES #3 closes #1 Refs #4") == [1, 2, 3]
    assert mod.closing_issues(None) == []
    assert mod.representative_id("[DEV-012] 제목") == "DEV-012"
    assert mod.representative_id("제목 (DEV-012)") is None
    assert mod.ledger_file_hint("진행 원장: DEV-3 (audit/ledger/x.md)", "DEV-003") == "audit/ledger/x.md"
    assert mod.ledger_file_hint("진행 원장: DEV-4 (audit/ledger/x.md)", "DEV-003") is None


# --- 워크플로 구조 ------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ledger-complete.yml"
CALLER = (
    ROOT / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows"
    / "ledger-complete.yml"
)


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:  # YAML 1.1 에서 `on` 은 True 로 읽힌다.
        data["on"] = data.pop(True)
    return data


def test_재사용_워크플로는_workflow_call_이고_engine_ref_기본은_stable_이며_secret_이_없다():
    wf = _load(WORKFLOW)
    call = wf["on"]["workflow_call"]
    assert call["inputs"]["engine-ref"]["default"] == "stable"
    assert "secrets" not in call  # deploy key 같은 쓰기용 secret 은 우회로가 되므로 받지 않는다(#445)


def test_job_권한은_읽기와_이슈_쓰기뿐이다():
    job = _load(WORKFLOW)["jobs"]["complete"]
    assert job["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "write"}


def test_Project_Repository_를_main_으로_받고_엔진은_그_뒤에_받는다():
    steps = _load(WORKFLOW)["jobs"]["complete"]["steps"]
    uses = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert uses[0]["with"]["ref"] == "main" and uses[0]["with"]["fetch-depth"] == 0
    assert "repository" not in uses[0]["with"] and "ssh-key" not in uses[0]["with"]
    assert uses[1]["with"]["path"] == ".harness-engine"  # 앞 checkout 이 지우지 않게 뒤에 받는다


def test_워크플로는_쓰지_않고_확인한_뒤_이슈를_연다():
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("jobs:", 1)[1]
    assert "ledger_complete.py check" in body and "--before" in body
    assert "git push" not in body and "git commit" not in body and "ssh-key" not in body
    assert "LEDGER_DEPLOY_KEY" not in body
    assert "ledger-complete: 진행 원장이 완료로 표시돼 있지 않다" in body
    assert "gh issue comment" in body and "gh issue create" in body
    assert "--limit 500" in body
    assert "github.event.before" in body
    # 종료 0 이어도 status 가 ok·skipped 가 아니면 통과로 넘기지 않는다.
    assert '"$status" = "ok"' in body and '"$status" = "skipped"' in body
    assert not (ROOT / "scripts" / "ledger_complete_loop.sh").exists()  # push 재시도 루프는 없다


def test_스캐폴드_caller_모양():
    wf = _load(CALLER)
    assert wf["on"] == {"push": {"branches": ["main"]}}
    job = wf["jobs"]["ledger-complete"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/ledger-complete.yml@stable"
    assert job["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "write"}
    assert "secrets" not in job


def test_pulls_가_비면_squash_제목의_PR_번호로_직접_조회한다(tmp_path, monkeypatch, capsys, subjects):
    _write(tmp_path, "a.md", _ledger(ROW1))
    subjects[SHA] = "feat: 구매요청 승인 (#50)"
    client = FakeGh([], {7: _rep(7)})
    client.pulls[50] = _pr("Closes #7")
    code, res = _run(monkeypatch, tmp_path, client, capsys)
    assert code == 1 and res["prs"] == [50]


def test_직접_조회한_PR_이_병합_안_됐거나_main_이_아니면_건너뛴다(tmp_path, monkeypatch, capsys, subjects):
    _write(tmp_path, "a.md", _ledger(ROW1))
    subjects[SHA] = "feat: x (#50)"
    for pr in (_pr("Closes #7", merged=False), _pr("Closes #7", base="release")):
        client = FakeGh([], {7: _rep(7)})
        client.pulls[50] = pr
        code, res = _run(monkeypatch, tmp_path, client, capsys)
        assert code == 0 and res["status"] == "skipped"


def test_직접_조회가_실패하면_2(tmp_path, monkeypatch, capsys, subjects):
    _write(tmp_path, "a.md", _ledger(ROW1))
    subjects[SHA] = "feat: x (#50)"
    code, res = _run(monkeypatch, tmp_path, FakeGh([], {7: _rep(7)}, fail="/pulls/50"), capsys)
    assert code == 2 and res["status"] == "unknown"


def test_pulls_도_비고_제목에_번호도_없으면_건너뛴다(tmp_path, monkeypatch, capsys, subjects):
    _write(tmp_path, "a.md", _ledger(ROW1))
    subjects[SHA] = "chore: 직접 push"
    code, res = _run(monkeypatch, tmp_path, FakeGh([], {}), capsys)
    assert code == 0 and res["status"] == "skipped" and "병합 PR 없음" in res["reason"]


def test_pulls_가_있으면_제목의_번호로_조회하지_않는다(tmp_path, monkeypatch, capsys, subjects):
    _write(tmp_path, "a.md", _ledger(DONE1))
    subjects[SHA] = "feat: x (#99)"  # pulls/99 는 FakeGh 에 없어 조회하면 KeyError
    code, res = _run(monkeypatch, tmp_path, FakeGh([_pr("Closes #7")], {7: _rep(7)}), capsys)
    assert code == 0 and res["status"] == "ok"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=a@a", "-c", "user.name=a", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def test_커밋_제목을_git_에서_읽는다(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: 제목 (#12)")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    assert _REAL_SUBJECT(tmp_path, sha) == "feat: 제목 (#12)"
    with pytest.raises(mod.Unknown):
        _REAL_SUBJECT(tmp_path, "f" * 40)


def test_push_의_커밋_범위를_오래된_것부터_푼다(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    shas = []
    for i in range(3):
        _git(tmp_path, "commit", "-q", "--allow-empty", "-m", f"c{i}")
        shas.append(_git(tmp_path, "rev-parse", "HEAD"))
    assert mod.expand_shas(tmp_path, shas[2], shas[0]) == shas[1:]
    assert mod.expand_shas(tmp_path, shas[2], None) == [shas[2]]
    assert mod.expand_shas(tmp_path, shas[2], "") == [shas[2]]
    assert mod.expand_shas(tmp_path, shas[2], "0" * 40) == [shas[2]]  # 새 브랜치
    assert mod.expand_shas(tmp_path, shas[2], "f" * 40) == [shas[2]]  # 히스토리에 없는 before
    assert mod.expand_shas(tmp_path, shas[2], shas[2]) == [shas[2]]  # 빈 범위


def test_Closes_전처리는_주석을_먼저_지우고_들여쓴_코드_블록도_걷는다():
    # 주석 안의 펜스가 뒤의 진짜 Closes 를 삼키지 않는다.
    assert mod.closing_issues("<!--\n```\n-->\nCloses #7") == [7]
    # 4칸·탭 들여쓴 줄은 코드 블록이다.
    assert mod.closing_issues("예시\n\n    Closes #7\n\t Fixes #8\n\nResolves #9") == [9]


def test_진입점_스크립트는_main_을_부른다():
    text = (ROOT / "scripts" / "ledger_complete.py").read_text(encoding="utf-8")
    assert "from checker.ledger_complete import main" in text
