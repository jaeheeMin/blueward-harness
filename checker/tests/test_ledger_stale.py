"""내 열린 PR 의 원장 미완료 판정과 pr_queue 출력(#454). GitHub 호출은 가짜로 바꾼다."""
from __future__ import annotations

import base64
import json

from checker import ledger_stale, pr_queue
from checker.ssot_approval import GhError

REPO = "o/r"
SHA = "headsha1"
HEAD = (
    "# 원장\n\n## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n"
)


def ledger(*rows: str) -> str:
    return HEAD + "".join(r + "\n" for r in rows)


def row(dev: str, state: str) -> str:
    return f"| {dev} | 내용 | - | me | {state} | #1 |"


def _content(text: str) -> dict:
    return {"type": "file", "content": base64.b64encode(text.encode("utf-8")).decode()}


class Gh:
    """issues: {번호: {title, body}}, files: {경로: 텍스트} (None 이면 원장 폴더 없음)."""

    def __init__(self, issues=None, files=None, prs=None, fail=None, default_files=None):
        self.default_files = default_files  # ref 없이(기본 브랜치) 본 원장 폴더. None 이면 없음
        self.issues = issues or {}
        self.files = files
        self.prs = prs or []
        self.fail = fail or {}
        self.calls: list[str] = []

    def run(self, args):
        if args[:2] == ["pr", "list"]:
            return json.dumps(self.prs)
        raise AssertionError(args)

    def get_json(self, path):
        self.calls.append(path)
        for key, msg in self.fail.items():
            if key in path:
                raise GhError(msg)
        if path == "user":
            return {"login": "me"}
        if "/issues/" in path:
            return self.issues[int(path.rsplit("/", 1)[1])]
        raise AssertionError(path)

    def get_all(self, path):
        return []

    def get_json_or_none_404(self, path):
        self.calls.append(path)
        for key, msg in self.fail.items():
            if key in path:
                raise GhError(msg)
        if path.endswith("contents/audit/ledger"):  # ref 없음 = 기본 브랜치
            return None if self.default_files is None else [{"path": p, "type": "file"} for p in self.default_files]
        if "contents/audit/ledger?ref=" in path:
            if self.files is None:
                return None
            return [{"path": p, "type": "file"} for p in sorted(self.files)]
        if "contents/audit/ledger/" in path:
            from urllib.parse import unquote

            p = unquote(path.split("/contents/")[1].split("?")[0])
            return _content(self.files[p]) if p in (self.files or {}) else None
        return None


REP = {"title": "[DEV-010] 고객매출주가분석", "body": ""}
SUB = {"title": "고객매출 화면 (DEV-010)", "body": ""}
F = "audit/ledger/a.md"


def judge(gh, closes=(7,)):
    return ledger_stale.judge(gh, REPO, list(closes), SHA)


def test_대표_이슈를_닫고_원장이_리뷰면_pending():
    out = judge(Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}))
    assert [(f["dev"], f["title"], f["status"], f["state"], f["file"]) for f in out] == [
        ("DEV-010", "고객매출주가분석", "pending", "리뷰", F)
    ]


def test_대표_이슈를_닫고_원장이_완료면_없음():
    assert judge(Gh({7: REP}, {F: ledger(row("DEV-010", "완료"))})) == []


def test_하위_작업_이슈만_닫으면_원장을_읽지_않는다():
    gh = Gh({7: SUB}, {F: ledger(row("DEV-010", "리뷰"))})
    assert judge(gh) == []
    assert not any("contents/audit" in c for c in gh.calls)


def test_Closes_가_없으면_아무것도_읽지_않는다():
    gh = Gh({}, {F: ledger(row("DEV-010", "리뷰"))})
    assert judge(gh, closes=()) == []
    assert gh.calls == []


def test_head_와_기본_브랜치_모두_원장_폴더가_없으면_조용히_건너뛴다():
    assert judge(Gh({7: REP}, None, default_files=None)) == []


def test_head_만_404_이고_기본_브랜치에는_있으면_판정_불능():
    out = judge(Gh({7: REP}, None, default_files=[F]))
    assert out[0]["status"] == "unknown" and "기본 브랜치에는 있다" in out[0]["reason"]


def test_기본_브랜치_조회가_실패하면_판정_불능():
    gh = Gh({7: REP}, None)
    gh.get_json_or_none_404 = lambda path, _o=gh.get_json_or_none_404: (
        (_ for _ in ()).throw(GhError("net")) if path.endswith("contents/audit/ledger") else _o(path)
    )
    out = judge(gh)
    assert out[0]["status"] == "unknown" and "net" in out[0]["reason"]


def test_한글_공백_경로는_인코딩해서_부른다():
    name = "audit/ledger/고객 원장.md"
    gh = Gh({7: REP}, {name: ledger(row("DEV-010", "리뷰"))})
    out = judge(gh)
    assert out[0]["status"] == "pending" and out[0]["file"] == name
    assert any("%EA%B3%A0" in c and "%20" in c for c in gh.calls)


def test_행이_없으면_판정_불능():
    out = judge(Gh({7: REP}, {F: ledger(row("DEV-011", "리뷰"))}))
    assert [(f["dev"], f["status"]) for f in out] == [("DEV-010", "unknown")]
    assert "찾지 못했다" in out[0]["reason"]


def test_행이_둘_이상이면_판정_불능():
    gh = Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰")), "audit/ledger/b.md": ledger(row("DEV-010", "완료"))})
    out = judge(gh)
    assert out[0]["status"] == "unknown" and "둘 이상" in out[0]["reason"]


def test_표_형식을_못_읽으면_판정_불능():
    out = judge(Gh({7: REP}, {F: "## 개발 건\n\n표 없음\n"}))
    assert out[0]["status"] == "unknown"


def test_이슈_조회가_실패하면_판정_불능():
    out = judge(Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, fail={"/issues/7": "boom"}))
    assert out[0]["status"] == "unknown" and "boom" in out[0]["reason"] and out[0]["issue"] == 7


def test_원장_폴더_조회가_실패하면_판정_불능():
    out = judge(Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, fail={"contents/audit/ledger?": "net"}))
    assert out[0]["status"] == "unknown" and "net" in out[0]["reason"]


def test_head_가_없으면_판정_불능():
    out = ledger_stale.judge(Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}), REPO, [7], "")
    assert out[0]["status"] == "unknown"


def test_이슈_본문이_가리킨_원장_파일만_본다():
    issue = {"title": "[DEV-010] 고객매출", "body": f"진행 원장: DEV-010 ({F})"}
    files = {F: ledger(row("DEV-010", "리뷰")), "audit/ledger/b.md": ledger(row("DEV-010", "완료"))}
    out = judge(Gh({7: issue}, files))
    assert out[0]["status"] == "pending" and out[0]["file"] == F


# --- pr_queue 출력 ------------------------------------------------------------


def raw_pr(number, body, head="feat/x"):
    return {
        "number": number, "title": f"feat: 제목 {number}", "author": {"login": "me"}, "baseRefName": "main",
        "headRefName": head, "headRefOid": SHA, "isDraft": False, "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [{"__typename": "CheckRun", "name": "doc-guard / check", "status": "COMPLETED",
                               "conclusion": "SUCCESS"}],
        "files": [{"path": "a.py"}], "body": body, "url": f"https://github.com/{REPO}/pull/{number}",
    }


def run(gh, *argv):
    args = pr_queue.build_parser().parse_args(["--repo", REPO, *argv])
    return pr_queue.run(args, gh)


def test_내_PR_출력에_원장_주의_줄과_기호가_붙는다():
    gh = Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, prs=[raw_pr(347, "Closes #7")])
    code, text = run(gh, "--mine")
    assert code == 0
    assert (
        f"⚠ [#347](https://github.com/{REPO}/pull/347) 원장 DEV-010(고객매출주가분석) 이 '리뷰' 야 — "
        "병합 전에 '완료' 로 고쳐야 해. Claude 에게 '원장 고쳐서 다시 올려줘' 라고 하면 돼"
    ) in text
    assert "✅⚠" in text  # 표의 PR 칸에도 주의 기호


def test_완료_하위_작업_원장_없음이면_줄이_없다():
    for issues, files in (
        ({7: REP}, {F: ledger(row("DEV-010", "완료"))}),
        ({7: SUB}, {F: ledger(row("DEV-010", "리뷰"))}),
        ({7: REP}, None),
    ):
        _, text = run(Gh(issues, files, prs=[raw_pr(347, "Closes #7")]), "--mine")
        assert "원장" not in text and "✅⚠" not in text


def test_판정_불능은_물음표_줄로_따로_나온다():
    gh = Gh({7: REP}, {F: ledger(row("DEV-011", "리뷰"))}, prs=[raw_pr(347, "Closes #7")])
    _, text = run(gh, "--mine")
    assert "❓ [#347]" in text and "판정 불능" in text and "고쳐야 해" not in text


def test_이슈_조회_실패는_상황에_맞는_문구로_나온다():
    gh = Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, prs=[raw_pr(347, "Closes #7")], fail={"/issues/7": "boom"})
    _, text = run(gh, "--mine")
    assert "이 닫는 이슈 #7 을 읽지 못해 원장 확인 불능 — " in text and "boom" in text
    assert "인지 판정 불능" not in text


def test_no_ledger_는_판정도_조회도_하지_않는다():
    gh = Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, prs=[raw_pr(347, "Closes #7")])
    _, text = run(gh, "--mine", "--no-ledger")
    assert "원장" not in text and not any("issues/" in c or "contents/audit" in c for c in gh.calls)


def test_json_에_ledger_필드가_있다():
    gh = Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, prs=[raw_pr(347, "Closes #7")])
    _, text = run(gh, "--mine", "--json")
    item = json.loads(text)["prs"][0]
    assert item["closes"] == [7]
    assert item["ledger"][0]["status"] == "pending" and item["ledger"][0]["dev"] == "DEV-010"


def test_Closes_없는_PR_은_이슈도_원장도_읽지_않는다():
    gh = Gh({}, {F: ledger(row("DEV-010", "리뷰"))}, prs=[raw_pr(347, "본문")])
    _, text = run(gh, "--mine")
    assert "원장" not in text
    assert not any("issues/" in c or "contents/audit" in c for c in gh.calls)


def test_all_은_판정하지_않는다():
    gh = Gh({7: REP}, {F: ledger(row("DEV-010", "리뷰"))}, prs=[raw_pr(347, "Closes #7")])
    _, text = run(gh, "--all")
    assert "원장" not in text
    assert not any("issues/" in c for c in gh.calls)


def test_세션_시작_알림은_원장_줄이_있을_때만_제안_안내를_붙인다(tmp_path):
    import subprocess
    import sys

    from checker.tests.test_plugin_layout import PLUGIN_ROOT

    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
    import pr_table_notice as pn

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    def context(body):
        (tmp_path / ".git" / "harness-pr-table.s1").write_text(f"rc=0\n{body}\n", encoding="utf-8", newline="\n")
        out = pn.run({"session_id": "s1", "cwd": str(tmp_path)})
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    with_ledger = context(f"⚠ [#347](x) 원장 DEV-010 이 '리뷰' 야 — Claude 에게 '{pr_queue.LEDGER_ASK}' 라고 하면 돼")
    assert pn.LEDGER_ASK == pr_queue.LEDGER_ASK
    assert "원장을 완료로 고쳐 다시 올릴까" in with_ledger and "/harness:deliver" in with_ledger
    assert "미커밋 변경" in with_ledger
    assert "원장을 완료로 고쳐" not in context("o/r 내 PR 1개")
