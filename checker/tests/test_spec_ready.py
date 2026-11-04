"""병합 전 관문 `spec_ready.py check-pr`(#668). GitHub 호출은 가짜로 바꾼다."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from checker import spec_ready
from checker.ssot_approval import GhError

REPO = "o/r"
LEDGER_HEAD = "# 원장\n\n## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 |\n|---|---|---|---|---|\n"
LEDGER_F = "audit/ledger/a.md"


def ledger(*rows: str) -> str:
    return LEDGER_HEAD + "".join(r + "\n" for r in rows)


def lrow(dev: str, spec: str) -> str:
    return f"| {dev} | 내용 | {spec} | me | 진행 |"


class Gh:
    """base_files: base 의 파일 {경로: 텍스트}. folders 는 base_files 경로에서 만든다.

    pr: PR 응답, files: [(경로, status)], open_prs: {번호: (제목, 브랜치, [파일])}."""

    def __init__(self, title="기능 (DEV-010)", body="", branch="feat/1-x", files=(("src/a.abap", "modified"),),
                 base_files=None, open_prs=None, fail=None, base="main"):
        self.title, self.body, self.branch, self.base = title, body, branch, base
        self.files = list(files)
        self.base_files = base_files if base_files is not None else {}
        self.open_prs = open_prs or {}
        self.fail = fail or {}

    def _maybe_fail(self, path):
        for key, msg in self.fail.items():
            if key in path:
                raise GhError(msg)

    def get_json(self, path):
        self._maybe_fail(path)
        if path == f"repos/{REPO}/pulls/5":
            return {"title": self.title, "body": self.body, "head": {"ref": self.branch}, "base": {"ref": self.base}}
        raise AssertionError(path)

    def get_all(self, path):
        self._maybe_fail(path)
        if path == f"repos/{REPO}/pulls/5/files":
            return [{"filename": p, "status": s} for p, s in self.files]
        if path == f"repos/{REPO}/pulls?state=open":
            return [{"number": n, "title": t, "head": {"ref": b}, "body": ""} for n, (t, b, _) in self.open_prs.items()]
        for n, (_, _, fs) in self.open_prs.items():
            if path == f"repos/{REPO}/pulls/{n}/files":
                return [{"filename": f} for f in fs]
        raise AssertionError(path)

    def get_json_or_none_404(self, path):
        self._maybe_fail(path)
        rest = path.split("/contents/")[1]
        target, ref = rest.split("?ref=")
        assert unquote(ref) == self.base  # base(병합 대상)에서 읽는다. head 가 아니다
        target = unquote(target)
        if target in self.base_files:
            return {"type": "file", "content": base64.b64encode(self.base_files[target].encode("utf-8")).decode()}
        kids = sorted(p for p in self.base_files if p.startswith(target + "/"))
        if kids:
            return [{"path": p, "type": "file"} for p in kids]
        return None


def run(gh, tmp_path, capsys, _mp=pytest.MonkeyPatch()):
    md = tmp_path / "out.md"
    _mp.setattr(spec_ready, "GhClient", lambda: gh)
    try:
        code = spec_ready.main(["check-pr", "--repo", REPO, "--pr", "5", "--markdown-file", str(md)])
    finally:
        _mp.undo()
    return code, json.loads(capsys.readouterr().out), md.read_text(encoding="utf-8")


SPEC10 = {"docs/spec/DEV-010-앱.md": "# Spec\n"}


def test_src_변경이_없으면_해당_없음_통과(tmp_path, capsys):
    gh = Gh(files=(("docs/a.md", "modified"), ("README.md", "modified")), title="문서")
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 0 and result["status"] == "ok" and result["applicable"] is False and md == ""


def test_base_에_Spec_이_있으면_통과이고_코멘트는_빈다(tmp_path, capsys):
    code, result, md = run(Gh(base_files=SPEC10), tmp_path, capsys)
    assert code == 0 and result["status"] == "ok" and result["applicable"] is True and md == ""


def test_src_아래_비코드도_개발_변경으로_본다(tmp_path, capsys):
    gh = Gh(files=(("src/package.devc.xml", "modified"),), base_files={})
    assert run(gh, tmp_path, capsys)[0] == 1


def test_DEV_를_못_찾으면_위반이고_제목_끝에_적으라고_안내(tmp_path, capsys):
    code, result, md = run(Gh(title="기능 추가", branch="feat/1-x", base_files=SPEC10), tmp_path, capsys)
    assert code == 1 and result["items"][0]["kind"] == "no_dev"
    assert "<!-- spec-ready -->" in md and "(DEV-xxx)" in md
    assert "새 커밋을 올리거나 Actions 에서 Re-run" in md


def test_Spec_이_base_에_없으면_위반이고_harness_spec_을_안내(tmp_path, capsys):
    code, result, md = run(Gh(base_files={"docs/spec/DEV-011-다른.md": "x"}), tmp_path, capsys)
    assert code == 1 and result["items"][0]["kind"] == "no_spec" and result["items"][0]["dev"] == "DEV-010"
    assert "DEV-010" in md and "/harness:spec" in md
    assert "따로 먼저 승인·병합" not in md


def test_docs_spec_폴더가_base_에_없어도_위반(tmp_path, capsys):
    code, result, _ = run(Gh(base_files={}), tmp_path, capsys)
    assert code == 1 and result["items"][0]["kind"] == "no_spec"


def test_같은_PR_에서_Spec_을_새로_추가하면_위반이고_먼저_병합하라고_적는다(tmp_path, capsys):
    gh = Gh(files=(("src/a.abap", "modified"), ("docs/spec/DEV-010-앱.md", "added")), base_files={})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and result["items"][0]["added_here"] is True
    assert "Spec 은 따로 먼저 승인·병합해야 합니다" in md


def test_열린_Spec_PR_이_있으면_알리고_병합_뒤_재실행을_안내(tmp_path, capsys):
    gh = Gh(base_files={}, open_prs={9: ("DEV-010 Spec", "docs/9-spec-DEV-010", ["docs/spec/DEV-010-앱.md"])})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and result["items"][0]["open_prs"][0]["number"] == 9
    assert "#9" in md and "다시 돌려" in md


def test_열린_PR_목록을_못_읽어도_지어내지_않고_위반만_낸다(tmp_path, capsys):
    gh = Gh(base_files={}, fail={"pulls?state=open": "net"})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and result["items"][0]["open_prs"] == [] and "열린 Spec PR" not in md


def test_여러_DEV_중_하나만_없어도_그것만_위반(tmp_path, capsys):
    gh = Gh(title="기능 (DEV-010, DEV-011)", base_files=SPEC10)
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and [i["dev"] for i in result["items"]] == ["DEV-011"]


def test_번호_0_채움이_달라도_같은_DEV_로_본다(tmp_path, capsys):
    gh = Gh(title="기능 (DEV-10)", base_files={"docs/spec/DEV-0010-앱.md": "x"})
    assert run(gh, tmp_path, capsys)[0] == 0


@pytest.mark.parametrize("body", [
    "Closes #7\n\nDEV-010 하위 작업. 대표 이슈 링크",
    "## Summary\n\nx\n\n## 진행 원장\n\n[DEV-010(앱)](audit/ledger/a.md)\n\n## Changes\n\n- y",
    "진행 원장: DEV-010 (audit/ledger/a.md)",
])
def test_제목에_번호가_없으면_본문의_하네스_표시로_폴백(tmp_path, capsys, body):
    gh = Gh(title="기능 추가", body=body, base_files=SPEC10)
    assert run(gh, tmp_path, capsys)[0] == 0
    gh = Gh(title="기능 추가", body=body, base_files={})
    code, result, _ = run(gh, tmp_path, capsys)
    assert code == 1 and result["items"][0]["dev"] == "DEV-010"


@pytest.mark.parametrize("body", [
    "이 PR 은 DEV-010 을 구현한다. DEV-011 과는 무관",
    "REQ-010 관련",
    "## Changes\n\n- DEV-010 참고\n\n## 진행 원장 없음 메모\n",
    "```\n진행 원장: DEV-010\n```",
])
def test_본문에_스친_번호로는_DEV_를_찾은_것으로_치지_않는다(tmp_path, capsys, body):
    """Spec 이 있는 DEV 가 본문에 언급돼도 통과하면 안 된다 — DEV 를 못 찾은 위반이다."""
    code, result, _ = run(Gh(title="기능 추가", body=body, base_files=SPEC10), tmp_path, capsys)
    assert code == 1 and result["items"][0]["kind"] == "no_dev"


def test_제목에_번호가_있으면_본문_표시는_읽지_않는다(tmp_path, capsys):
    gh = Gh(title="기능 (DEV-011)", body="DEV-010 하위 작업", base_files=SPEC10)
    code, result, _ = run(gh, tmp_path, capsys)
    assert code == 1 and [i["dev"] for i in result["items"]] == ["DEV-011"]


def test_srcx_폴더는_대상이_아니다(tmp_path, capsys):
    gh = Gh(files=(("srcx/a.txt", "modified"), ("docs/src/b.md", "modified")), title="문서")
    code, result, _ = run(gh, tmp_path, capsys)
    assert code == 0 and result["applicable"] is False


def test_파일이_100개_넘어도_뒤쪽의_src_변경을_본다(tmp_path, capsys):
    files = tuple((f"docs/f{i}.md", "modified") for i in range(120)) + (("src/z.abap", "modified"),)
    code, result, _ = run(Gh(files=files, base_files={}), tmp_path, capsys)
    assert code == 1 and result["applicable"] is True


def test_src_파일을_지우거나_옮겨도_개발_변경이다(tmp_path, capsys):
    assert run(Gh(files=(("src/a.abap", "removed"),), base_files={}), tmp_path, capsys)[0] == 1

    class Renamed(Gh):
        def get_all(self, path):
            if path.endswith("/pulls/5/files"):
                return [{"filename": "docs/a.abap", "previous_filename": "src/a.abap", "status": "renamed"}]
            return super().get_all(path)

    assert run(Renamed(base_files={}), tmp_path, capsys)[0] == 1


def test_base_가_main_이_아니어도_그_브랜치에서_읽는다(tmp_path, capsys):
    gh = Gh(base="release/1", base_files=SPEC10)
    code, result, _ = run(gh, tmp_path, capsys)
    assert code == 0 and result["applicable"] is True
    assert run(Gh(base="release/1", base_files={}), tmp_path, capsys)[0] == 1


def test_원장_Spec_칸이_설정이면_src_변경은_위반(tmp_path, capsys):
    gh = Gh(base_files={LEDGER_F: ledger(lrow("DEV-010", "설정"))})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 1 and result["items"][0]["kind"] == "config"
    assert "설정은 개발이 아닙니다" in md and "/harness:spec" not in md


def test_원장_Spec_칸이_링크면_설정이_아니라_Spec_으로_판정(tmp_path, capsys):
    base = {LEDGER_F: ledger(lrow("DEV-010", "[Spec](../../docs/spec/DEV-010-앱.md)")), **SPEC10}
    assert run(Gh(base_files=base), tmp_path, capsys)[0] == 0


def test_원장이_없는_저장소도_Spec_판정은_docs_spec_으로_한다(tmp_path, capsys):
    assert run(Gh(base_files=SPEC10), tmp_path, capsys)[0] == 0
    assert run(Gh(base_files={}), tmp_path, capsys)[0] == 1


def test_원장_표를_못_읽으면_검사_불능(tmp_path, capsys):
    gh = Gh(base_files={LEDGER_F: "# 원장\n\n## 개발 건\n\n표 없음\n", **SPEC10})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 2 and result["status"] == "unknown" and "검사 불능" in md


def test_원장에_Spec_열이_없으면_그_DEV_를_판정_못해_검사_불능(tmp_path, capsys):
    text = "# 원장\n\n## 개발 건\n\n| ID | 내용 | 상태 |\n|---|---|---|\n| DEV-010 | a | 진행 |\n"
    code, _, _ = run(Gh(base_files={LEDGER_F: text, **SPEC10}), tmp_path, capsys)
    assert code == 2


@pytest.mark.parametrize("key", ["pulls/5/files", "contents/docs/spec", "contents/audit/ledger"])
def test_읽기_실패는_통과가_아니라_종료코드_2(tmp_path, capsys, key):
    gh = Gh(base_files=SPEC10, fail={key: "net down"})
    code, result, md = run(gh, tmp_path, capsys)
    assert code == 2 and result["status"] == "unknown"
    assert "net down" in md and "검사 불능" in md


def test_PR_을_읽지_못해도_검사_불능(tmp_path, capsys):
    code, _, md = run(Gh(fail={"pulls/5": "net down"}), tmp_path, capsys)
    assert code == 2 and "net down" in md


def test_뜻밖의_예외도_위반이_아니라_검사_불능(tmp_path, capsys, monkeypatch):
    def boom(*a, **k):
        raise KeyError("x")

    monkeypatch.setattr(spec_ready, "_base_spec_numbers", boom)
    code, result, md = run(Gh(base_files=SPEC10), tmp_path, capsys)
    assert code == 2 and result["status"] == "unknown" and "KeyError" in md


def test_진입점은_얇은_래퍼다():
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts" / "spec_ready.py").read_text(encoding="utf-8")
    assert "from checker.spec_ready import main" in text


def test_start_스킬의_Spec_판정과_같은_이름_규칙을_쓴다():
    """start 의 `reserve_number.py list` 는 origin/main 의 `docs/spec/DEV-…` 를 `spec` 키로 낸다. 엔진과 같은 정의여야 한다."""
    script = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "start" / "reserve_number.py"
    spec = importlib.util.spec_from_file_location("reserve_number_for_spec_ready", script)
    rn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rn)
    for name, num in [("docs/spec/DEV-002-요약.md", 2), ("docs/spec/DEV-010-앱.md", 10), ("docs/spec/DEV-0010-앱.md", 10)]:
        a = spec_ready._SPEC_FILE.match(name)
        b = rn.SPEC_NAME_RE.search(name)
        assert a and b and int(a.group(1)) == int(b.group(1)) == num
    for name in ["docs/spec/README.md", "docs/other/DEV-002-x.md"]:
        assert spec_ready._SPEC_FILE.match(name) is None
