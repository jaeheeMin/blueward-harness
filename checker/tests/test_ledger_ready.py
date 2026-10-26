"""병합 전 관문 `ledger_ready.py check-pr`(#479). GitHub 호출은 test_ledger_stale 의 가짜를 쓴다."""
from __future__ import annotations

import json

import pytest

from checker import ledger_stale
from checker.ssot_approval import GhError
from checker.tests.test_ledger_stale import F, REP, REPO, SHA, SUB, Gh, ledger, row


class PrGh(Gh):
    def __init__(self, body, *args, pr_error=None, **kw):
        super().__init__(*args, **kw)
        self.body = body
        self.pr_error = pr_error

    def get_json(self, path):
        if path == f"repos/{REPO}/pulls/5":
            if self.pr_error:
                raise GhError(self.pr_error)
            return {"body": self.body, "head": {"sha": SHA}}
        return super().get_json(path)


def run(gh, tmp_path, capsys, _mp=pytest.MonkeyPatch()):
    md = tmp_path / "out.md"
    _mp.setattr(ledger_stale, "GhClient", lambda: gh)
    try:
        code = ledger_stale.main(["check-pr", "--repo", REPO, "--pr", "5", "--markdown-file", str(md)])
    finally:
        _mp.undo()
    return code, json.loads(capsys.readouterr().out), md.read_text(encoding="utf-8")


def test_pending_은_위반이고_쉬운_말로_할_일을_적는다(tmp_path, capsys):
    gh = PrGh("Closes #7", {7: REP}, {F: ledger(row("DEV-010", "리뷰"))})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and result["status"] == "violation"
    assert "<!-- ledger-ready -->" in md
    assert "DEV-010(고객매출주가분석)" in md and f"`{F}`" in md and "'리뷰'" in md
    assert "원장 고쳐서 다시 올려줘" in md


def test_완료면_통과이고_코멘트는_빈다(tmp_path, capsys):
    code, result, md = run(PrGh("Closes #7", {7: REP}, {F: ledger(row("DEV-010", "완료"))}), tmp_path, capsys)
    assert code == 0 and result["status"] == "ok" and md == ""


def test_Closes_가_없거나_하위_작업만이면_통과(tmp_path, capsys):
    assert run(PrGh("없음", {}, {F: ledger(row("DEV-010", "리뷰"))}), tmp_path, capsys)[0] == 0
    assert run(PrGh("Closes #7", {7: SUB}, {F: ledger(row("DEV-010", "리뷰"))}), tmp_path, capsys)[0] == 0


def test_원장_없는_저장소는_통과(tmp_path, capsys):
    assert run(PrGh("Closes #7", {7: REP}, None), tmp_path, capsys)[0] == 0


def test_판정_불능은_통과가_아니라_종료코드_2(tmp_path, capsys):
    code, result, md = run(PrGh("Closes #7", {7: REP}, {F: ledger()}), tmp_path, capsys)  # 행 없음
    assert code == 2 and result["status"] == "unknown"
    assert "검사 불능" in md and "DEV-010" in md


def test_PR_을_읽지_못해도_판정_불능(tmp_path, capsys):
    code, result, md = run(PrGh("", {}, None, pr_error="net down"), tmp_path, capsys)
    assert code == 2 and "net down" in md


def test_pending_과_불능이_섞이면_위반이다(tmp_path, capsys):
    issues = {7: REP, 8: {"title": "[DEV-011] 다른 건", "body": ""}}
    gh = PrGh("Closes #7 Closes #8", issues, {F: ledger(row("DEV-010", "리뷰"))})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and "검사 불능" in md and "아직 '리뷰'" in md


@pytest.mark.parametrize("exc", [OSError("disk"), TypeError("t"), KeyError("k"), RuntimeError("r")])
def test_뜻밖의_예외도_위반이_아니라_판정_불능_2(tmp_path, capsys, exc):
    class Boom(PrGh):
        def get_json(self, path):
            raise exc

    code, result, md = run(Boom("Closes #7", {7: REP}, None), tmp_path, capsys)
    assert code == 2 and result["status"] == "unknown"
    assert "뜻밖의 오류" in md and type(exc).__name__ in md


@pytest.mark.parametrize("response", [None, [], {}, {"body": "Closes #7"}, {"body": "Closes #7", "head": {}},
                                      {"body": "Closes #7", "head": {"sha": ""}}])
def test_PR_응답이_비었거나_head_sha_가_없으면_판정_불능(tmp_path, capsys, response):
    class Empty(PrGh):
        def get_json(self, path):
            return response if path == f"repos/{REPO}/pulls/5" else super().get_json(path)

    code, result, md = run(Empty("", {7: REP}, {F: ledger(row("DEV-010", "완료"))}), tmp_path, capsys)
    assert code == 2 and result["status"] == "unknown" and "검사 불능" in md


def test_이슈_조회가_실패하면_판정_불능(tmp_path, capsys):
    gh = PrGh("Closes #7", {7: REP}, {F: ledger(row("DEV-010", "완료"))}, fail={"issues/7": "HTTP 500"})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 2 and "HTTP 500" in md


def test_head_에_원장_폴더가_없고_기본_브랜치에는_있으면_판정_불능(tmp_path, capsys):
    gh = PrGh("Closes #7", {7: REP}, None, default_files=[F])
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 2 and "기본 브랜치에는 있다" in md
