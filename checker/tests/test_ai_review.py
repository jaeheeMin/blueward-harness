"""`checker.ai_review`(#460)를 검증한다. 실제 claude 는 부르지 않고 `runner` 를 주입한다."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from checker import ai_review as ar


def _ch(path, status="M", binary=False):
    return {"path": path, "status": status, "binary": binary}


# --- 대상/제외 분류 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change,expected",
    [
        (_ch("src/app.py"), ("target", "")),
        (_ch("src/ui/view.js"), ("target", "")),
        (_ch("src/zcl_x.abap"), ("target", "")),
        (_ch(".github/workflows/x.yml"), ("target", "")),
        (_ch("README.md"), ("excluded", "문서")),
        (_ch("src/NOTES.MD"), ("excluded", "문서")),
        (_ch("docs/guide/a.html"), ("excluded", "docs 폴더")),
        (_ch("docs/code.py"), ("excluded", "docs 폴더")),
        (_ch("spec/개발사양서_v0.1.xlsx"), ("excluded", "오피스 문서")),
        (_ch("a.docx"), ("excluded", "오피스 문서")),
        (_ch("a.pptx"), ("excluded", "오피스 문서")),
        (_ch("a.pdf"), ("excluded", "PDF")),
        (_ch("img/a.PNG"), ("excluded", "이미지")),
        (_ch("img/a.svg"), ("excluded", "이미지")),
        (_ch("src/blob.bin", binary=True), ("excluded", "바이너리")),
        (_ch("src/old.py", status="D"), ("deleted", "삭제")),
        (_ch("docs/old.md", status="D"), ("deleted", "삭제")),  # 삭제는 어디 있든 삭제로 남긴다
    ],
)
def test_대상_제외_삭제_분류(change, expected):
    assert ar.classify(change) == expected


# --- 묶음 나누기 ----------------------------------------------------------------------------------


def _diff(path, hunks):
    head = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
    return head + "".join(f"@@ -{i},1 +{i},1 @@\n-old\n+" + body + "\n" for i, body in enumerate(hunks, 1))


def test_작은_파일들은_한_묶음에_모이고_상한을_넘으면_나뉜다():
    diffs = [(f"f{i}.py", "x" * 100) for i in range(5)]
    plan = ar.plan_batches(diffs, batch_chars=250, max_batches=10)
    assert [b["files"] for b in plan["batches"]] == [["f0.py", "f1.py"], ["f2.py", "f3.py"], ["f4.py"]]
    assert all(b["chars"] <= 250 for b in plan["batches"]) and plan["dropped"] == []


def test_큰_파일은_hunk_단위로_쪼개_그_파일만의_묶음이_된다():
    big = _diff("big.py", ["a" * 100, "b" * 100, "c" * 100])
    plan = ar.plan_batches([("small.py", "y" * 50), ("big.py", big), ("after.py", "z" * 50)], batch_chars=len(big) - 20,
                           max_batches=10)
    files = [b["files"] for b in plan["batches"]]
    assert files[0] == ["small.py"]
    big_batches = [b for b in plan["batches"] if b["files"] == ["big.py"]]
    assert len(big_batches) >= 2
    for b in big_batches:
        assert b["text"].startswith("diff --git a/big.py")  # 쪼갠 조각마다 파일 머리가 붙는다
        assert b["chars"] <= len(big) - 20 and not b["oversize"]
    # 모든 hunk 가 한 번씩 들어 있다
    text = "".join(b["text"] for b in big_batches)
    assert all(ch * 100 in text for ch in "abc")
    assert files[-1] == ["after.py"]


def test_hunk_하나가_상한을_넘으면_그_hunk_만의_oversize_묶음():
    big = _diff("big.py", ["a" * 500])
    plan = ar.plan_batches([("big.py", big)], batch_chars=100, max_batches=10)
    assert len(plan["batches"]) == 1 and plan["batches"][0]["oversize"] is True


def test_묶음_상한을_넘는_묶음의_파일은_dropped():
    diffs = [(f"f{i}.py", "x" * 100) for i in range(4)]
    plan = ar.plan_batches(diffs, batch_chars=100, max_batches=2)
    assert [b["files"] for b in plan["batches"]] == [["f0.py"], ["f1.py"]]
    assert plan["dropped"] == ["f2.py", "f3.py"]


def test_빈_diff는_묶음에_넣지_않는다():
    plan = ar.plan_batches([("mode.sh", ""), ("a.py", "x")], batch_chars=100, max_batches=5)
    assert [b["files"] for b in plan["batches"]] == [["a.py"]]


# --- 결과 합치기 ----------------------------------------------------------------------------------


def _ok(files, findings=()):
    return {"files": list(files), "chars": 1, "ok": True, "reason": "", "findings": list(findings),
            "num_turns": 2, "duration_ms": 10, "total_cost_usd": 0.01}


def _bad(files, reason="시간 초과(300초)"):
    return {"files": list(files), "chars": 1, "ok": False, "reason": reason, "findings": [],
            "num_turns": None, "duration_ms": None, "total_cost_usd": None}


F = {"severity": "serious", "file": "a.py", "line": 3, "summary": "문제"}


def test_모든_묶음이_성공하면_full():
    m = ar.merge_results(["a.py", "b.py"], [{"file": "x.md", "reason": "문서"}], ["gone.py"], [],
                         [_ok(["a.py"], [F]), _ok(["b.py"])])
    assert m["coverage"] == "full" and m["unreviewed"] == [] and m["serious"] == 1
    assert m["reviewed"] == ["a.py", "b.py"] and m["excluded"] == [{"file": "x.md", "reason": "문서"}]
    assert m["deleted"] == ["gone.py"] and m["no_code_to_review"] is False
    assert [b["ok"] for b in m["batches"]] == [True, True] and m["batches"][0]["num_turns"] == 2


def test_일부_묶음이_실패하면_partial_이고_사유를_남긴다():
    m = ar.merge_results(["a.py", "b.py", "c.py"], [], [], [], [_ok(["a.py"]), _bad(["b.py", "c.py"], "종료코드 1")])
    assert m["coverage"] == "partial" and m["unreviewed"] == ["b.py", "c.py"]
    assert m["unreviewed_reasons"]["b.py"] == "묶음 실패(종료코드 1)"
    assert m["reviewed"] == ["a.py"]


def test_묶음_상한으로_빠진_파일도_partial():
    m = ar.merge_results(["a.py", "b.py"], [], [], ["b.py"], [_ok(["a.py"])])
    assert m["coverage"] == "partial" and m["unreviewed"] == ["b.py"]
    assert m["unreviewed_reasons"] == {"b.py": "묶음 상한"}


def test_한_파일의_조각_중_하나라도_실패하면_그_파일은_못_본_것():
    m = ar.merge_results(["big.py"], [], [], [], [_ok(["big.py"]), _bad(["big.py"])])
    assert m["coverage"] == "partial" and m["unreviewed"] == ["big.py"] and m["reviewed"] == []


def test_성공한_묶음의_지적만_합친다():
    m = ar.merge_results(["a.py", "b.py"], [], [], [], [_ok(["a.py"], [F]), _bad(["b.py"])])
    assert m["findings"] == [F]


def test_전부_실패하면_검사_불능():
    with pytest.raises(ar.Unavailable, match="성공한 묶음이 없다: 시간 초과"):
        ar.merge_results(["a.py"], [], [], [], [_bad(["a.py"])])


def test_대상_코드가_0개면_full_이고_그_사실을_키로_남긴다():
    m = ar.merge_results([], [{"file": "README.md", "reason": "문서"}], [], [], [])
    assert m["coverage"] == "full" and m["findings"] == [] and m["serious"] == 0
    assert m["no_code_to_review"] is True and m["excluded"][0]["file"] == "README.md"


# --- run_batch: claude 호출과 structured_output 파싱 ------------------------------------------------


BATCH = {"files": ["a.py"], "chars": 10, "text": "diff", "oversize": False}


def _runner(code=0, out="", err="", record=None):
    def run(cmd, stdin, env, timeout, cwd):
        if record is not None:
            record.update(cmd=cmd, stdin=stdin, env=env, timeout=timeout, cwd=cwd)
        return code, out, err
    return run


def _result(structured, **extra):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
                       "duration_ms": 1234, "total_cost_usd": 0.05, "structured_output": structured, **extra})


def _go(runner, **kw):
    return ar.run_batch(BATCH, repo=".", claude="claude", model="sonnet", max_turns=15, timeout=300,
                        runner=runner, env={"PATH": "x"}, **kw)


def test_성공한_묶음은_지적과_턴_시간_비용을_기록한다():
    rec = {}
    r = _go(_runner(out=_result({"findings": [F]}), record=rec))
    assert r["ok"] and r["findings"] == [F] and "outside_batch" not in r["findings"][0]
    assert (r["num_turns"], r["duration_ms"], r["total_cost_usd"]) == (3, 1234, 0.05)
    cmd = rec["cmd"]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"] == ["findings"]
    assert cmd[cmd.index("--allowedTools") + 1] == "Read,Glob,Grep"
    assert cmd[cmd.index("--max-turns") + 1] == "15" and cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--setting-sources") + 1] == "" and cmd[cmd.index("--permission-prompts") + 1] == "none"
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd and "--bare" not in cmd
    assert rec["stdin"].decode("utf-8").endswith("diff")  # 프롬프트는 stdin 으로, diff 가 맨 끝
    assert rec["timeout"] == 300 and rec["cwd"] == "."


def test_묶음_밖_파일의_지적은_버리지_않고_표시한다():
    other = {"severity": "minor", "file": "other.py", "line": 1, "summary": "x"}
    r = _go(_runner(out=_result({"findings": [other]})))
    assert r["ok"] and r["findings"][0]["outside_batch"] is True


@pytest.mark.parametrize(
    "structured",
    [None, {}, {"findings": "x"}, {"findings": [{"severity": "high", "file": "a", "line": 1, "summary": "x"}]},
     {"findings": [{"severity": "minor", "file": "a", "line": "1", "summary": "x"}]},
     {"findings": [{"severity": "minor", "file": "a", "line": True, "summary": "x"}]},
     {"findings": [{"severity": "minor", "line": 1, "summary": "x"}]}],
)
def test_structured_output_이_스키마에_안_맞으면_실패(structured):
    r = _go(_runner(out=_result(structured)))
    assert not r["ok"] and r["reason"].startswith("형식 오류")
    assert r["num_turns"] == 3  # 실패해도 턴·비용은 기록한다


def test_종료코드가_0_이_아니면_실패():
    r = _go(_runner(code=1, out="", err="boom\nfatal: 인증 실패"))
    assert not r["ok"] and r["reason"] == "종료코드 1: fatal: 인증 실패"


@pytest.mark.parametrize("out", ["", "not json", "[]"])
def test_결과가_JSON_객체가_아니면_실패(out):
    r = _go(_runner(out=out))
    assert not r["ok"] and r["reason"] == "결과가 JSON 이 아니다"


def test_claude_가_오류로_끝나면_실패():
    out = json.dumps({"subtype": "error_max_turns", "is_error": True, "num_turns": 15,
                      "structured_output": {"findings": []}})
    r = _go(_runner(out=out))
    assert not r["ok"] and "error_max_turns" in r["reason"] and r["num_turns"] == 15


def test_시간_초과와_실행_실패는_사유를_남긴다():
    def timeout(*a):
        raise subprocess.TimeoutExpired("claude", 300)

    def missing(*a):
        raise FileNotFoundError("claude")

    assert _go(timeout)["reason"] == "시간 초과(300초)"
    assert "실행하지 못했다(FileNotFoundError)" in _go(missing)["reason"]


def test_ANTHROPIC_API_KEY_는_자식_환경에서_뺀다():
    env = ar.child_env({"ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": "t", "PATH": "p"})
    assert "ANTHROPIC_API_KEY" not in env and env["CLAUDE_CODE_OAUTH_TOKEN"] == "t"


# --- git 저장소로 하는 통합 -----------------------------------------------------------------------


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "src").mkdir()
    (r / "docs").mkdir()
    (r / "src" / "keep.py").write_text("a = 1\n" * 30, encoding="utf-8")
    (r / "src" / "gone.py").write_text("x = 1\n", encoding="utf-8")
    (r / "README.md").write_text("# t\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()
    (r / "src" / "keep.py").write_text("a = 1\n" * 15 + "a = 2\n" + "a = 1\n" * 14, encoding="utf-8")
    (r / "src" / "new.py").write_text("print('hi')\n", encoding="utf-8")
    (r / "src" / "gone.py").unlink()
    (r / "src" / "logo.png").write_bytes(b"\x89PNG\x00\x01\x02")
    (r / "src" / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    (r / "docs" / "a.md").write_text("doc\n", encoding="utf-8")
    (r / "README.md").write_text("# t2\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "head")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()
    return r, base, head


def test_git_변경을_대상_제외_삭제로_나누고_dry_run_이_계획을_낸다(repo):
    r, base, head = repo
    plan = ar.dry_run(str(r), base, head, batch_chars=60000, max_batches=8)
    assert plan["targets"] == ["src/keep.py", "src/new.py"]
    assert plan["deleted"] == ["src/gone.py"]
    assert {e["file"]: e["reason"] for e in plan["excluded"]} == {
        "README.md": "문서", "docs/a.md": "docs 폴더", "src/data.bin": "바이너리", "src/logo.png": "이미지"}
    assert len(plan["batches"]) == 1 and plan["batches"][0]["files"] == ["src/keep.py", "src/new.py"]
    assert plan["dropped_by_batch_cap"] == []


def test_run_이_결과_파일을_쓴다(repo, tmp_path):
    r, base, head = repo
    out = tmp_path / "out"
    seen = {}
    merged = ar.run(str(r), base, head, str(out), runner=_runner(out=_result({"findings": [
        {"severity": "serious", "file": "src/new.py", "line": 1, "summary": "문제"}]}), record=seen), env={})
    assert merged["coverage"] == "full" and merged["serious"] == 1
    data = json.loads((out / "ai-review.json").read_text(encoding="utf-8"))
    assert data == merged and not (out / "ai-review-unavailable.json").exists()
    prompt = seen["stdin"].decode("utf-8")
    assert "src/keep.py" in prompt and "src/new.py" in prompt and "docs/a.md" not in prompt
    assert "README.md" not in prompt and "gone.py" not in prompt
    # 형식이 워크플로 "결과 정리" 가 읽는 것과 맞는다
    assert set(data) >= {"coverage", "unreviewed", "serious", "findings"}


def test_코드가_없는_PR_은_claude_를_부르지_않고_full(repo, tmp_path):
    r, base, head = repo
    # 문서만 바뀐 범위: base 와 head 를 문서 변경 커밋 하나로 잡는다
    (r / "docs" / "b.md").write_text("more\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "docs only")
    new_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()

    def never(*a):
        raise AssertionError("claude 를 부르면 안 된다")

    merged = ar.run(str(r), head, new_head, str(tmp_path / "o"), runner=never)
    assert merged["coverage"] == "full" and merged["no_code_to_review"] is True
    assert merged["excluded"] == [{"file": "docs/b.md", "reason": "docs 폴더"}]


def test_전체_시간_상한을_넘으면_남은_묶음은_못_본_것으로_센다(repo, tmp_path):
    r, base, head = repo
    ticks = iter([0, 0, 1000, 1000, 1000])  # started, 첫 묶음 남은 시간 계산, 둘째 묶음 계산 ...
    calls = []

    def runner(cmd, stdin, env, timeout, cwd):
        calls.append(timeout)
        return 0, _result({"findings": []}), ""

    merged = ar.run(str(r), base, head, str(tmp_path / "o"), batch_chars=1, runner=runner, env={},
                    total_timeout=100, clock=lambda: next(ticks))
    assert len(calls) == 1
    assert merged["coverage"] == "partial" and merged["unreviewed"] == ["src/new.py"]
    assert merged["unreviewed_reasons"]["src/new.py"] == "묶음 실패(전체 시간 상한)"


def test_main_성공한_묶음이_없으면_종료코드_2_이고_결과_파일을_쓰지_않는다(repo, tmp_path, monkeypatch, capsys):
    r, base, head = repo
    out = tmp_path / "o"
    out.mkdir()
    (out / "ai-review.json").write_text("{}", encoding="utf-8")  # 낡은 결과가 남아 있어도 지운다
    monkeypatch.setattr(ar, "_default_runner", _runner(code=1, err="인증 실패"))
    code = ar.main(["run", "--repo", str(r), "--base", base, "--head", head, "--out", str(out)])
    assert code == 2
    assert not (out / "ai-review.json").exists()
    reason = json.loads((out / "ai-review-unavailable.json").read_text(encoding="utf-8"))["reason"]
    assert "성공한 묶음이 없다" in reason and "종료코드 1" in reason
    assert "검사 불능" in capsys.readouterr().err


def test_main_git_범위를_못_읽으면_검사_불능(repo, tmp_path):
    r, _, head = repo
    out = tmp_path / "o"
    assert ar.main(["run", "--repo", str(r), "--base", "0" * 40, "--head", head, "--out", str(out)]) == 2
    assert "git diff" in json.loads((out / "ai-review-unavailable.json").read_text(encoding="utf-8"))["reason"]


def test_main_dry_run_은_claude_를_부르지_않고_JSON_을_낸다(repo, capsys, monkeypatch):
    r, base, head = repo
    monkeypatch.setattr(ar, "_default_runner", lambda *a: (_ for _ in ()).throw(AssertionError("호출 금지")))
    assert ar.main(["run", "--repo", str(r), "--base", base, "--head", head, "--out", "unused", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["targets"] == ["src/keep.py", "src/new.py"]


def test_스크립트_진입점이_모듈을_부른다(repo):
    r, base, head = repo
    script = Path(__file__).resolve().parents[2] / "scripts" / "ai_review.py"
    proc = subprocess.run([sys.executable, str(script), "run", "--repo", str(r), "--base", base, "--head", head,
                           "--out", "unused", "--dry-run"], capture_output=True, check=True, cwd=script.parents[1])
    assert json.loads(proc.stdout.decode("utf-8"))["targets"] == ["src/keep.py", "src/new.py"]


# --- 줄 번호(#460 정확성) -------------------------------------------------------------------------


def test_diff_줄_앞에_새_파일_기준_번호를_붙인다():
    raw = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -10,3 +10,4 @@ def f():\n ctx\n-old\n+new\n+new2\n tail\n"
           "\\ No newline at end of file\n@@ -50,1 +60,1 @@\n-a\n+b\n")
    lines = ar.number_diff(raw).splitlines()
    assert lines[:3] == raw.splitlines()[:3]  # 파일 머리와 @@ 줄은 그대로
    assert lines[3] == "@@ -10,3 +10,4 @@ def f():"
    assert lines[4:9] == ["     10| ctx", "-      | old", "+    11| new", "+    12| new2", "     13| tail"]
    assert lines[9] == "\\ No newline at end of file"
    assert lines[10] == "@@ -50,1 +60,1 @@"
    assert lines[11:] == ["-      | a", "+    60| b"]


def test_번호_붙인_diff도_hunk_로_쪼갠다():
    numbered = ar.number_diff(_diff("big.py", ["a" * 100, "b" * 100]))
    head, hunks = ar.split_hunks(numbered)
    assert head.startswith("diff --git") and len(hunks) == 2 and hunks[0].startswith("@@ ")


def test_프롬프트가_번호_사용과_지적_범위를_안내한다():
    p = ar.PROMPT_HEAD
    assert "그대로 쓴다" in p and "`|` 앞의 숫자" in p
    assert "바뀐 줄(+/-)과 관계없는 지적은 하지 않는다" in p and "그 의도 자체가 틀렸거나 위험할 때만" in p


# --- 비신뢰 입력 방어 -----------------------------------------------------------------------------


def test_명령은_도구를_읽기로_줄이고_민감_경로_읽기를_거부한다():
    cmd = ar.build_command("claude", "sonnet", 15)
    assert cmd[cmd.index("--tools") + 1] == "Read,Glob,Grep"
    deny = json.loads(cmd[cmd.index("--settings") + 1])["permissions"]["deny"]
    assert "Read(//proc/**)" in deny and "Read(//**/.git/**)" in deny and "Read(~/.claude.json)" in deny
    assert "Read(~/**)" not in deny  # 러너의 작업 폴더가 홈 아래라 홈 전체는 막지 않는다


def test_자식_환경은_허용_목록만_남긴다():
    env = ar.child_env({
        "PATH": "p", "HOME": "h", "LANG": "ko", "LC_ALL": "C", "TMPDIR": "/t", "SystemRoot": "C:/Windows",
        "CLAUDE_CODE_OAUTH_TOKEN": "t", "DISABLE_UPDATES": "1",
        "GITHUB_TOKEN": "g", "ACTIONS_RUNTIME_TOKEN": "a", "RUNNER_TEMP": "/r", "ANTHROPIC_API_KEY": "k",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "i", "GITHUB_WORKSPACE": "/w",
    })
    assert set(env) == {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SystemRoot", "CLAUDE_CODE_OAUTH_TOKEN",
                        "DISABLE_UPDATES"}


def test_설정_파일을_지운다_엔진_폴더와_git_은_건드리지_않는다(tmp_path):
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sub" / ".claude").mkdir(parents=True)
    (tmp_path / "sub" / "CLAUDE.md").write_text("x", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".claude.json").write_text("{}", encoding="utf-8")
    (tmp_path / "keep.py").write_text("x", encoding="utf-8")
    (tmp_path / ".harness-engine").mkdir()
    (tmp_path / ".harness-engine" / "CLAUDE.md").write_text("engine", encoding="utf-8")
    removed = ar.scrub_config(str(tmp_path))
    assert removed == [".claude", ".claude.json", ".mcp.json", "sub/.claude", "sub/CLAUDE.md"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [".harness-engine", "keep.py", "sub"]
    assert (tmp_path / ".harness-engine" / "CLAUDE.md").exists()


def test_run_은_scrub_를_켜면_claude_를_부르기_전에_설정을_지운다(repo, tmp_path):
    r, base, head = repo
    (r / ".mcp.json").write_text("{}", encoding="utf-8")
    seen = {}

    def runner(cmd, stdin, env, timeout, cwd):
        seen["mcp"] = (Path(cwd) / ".mcp.json").exists()
        return 0, _result({"findings": []}), ""

    ar.run(str(r), base, head, str(tmp_path / "o"), runner=runner, env={}, scrub=True)
    assert seen["mcp"] is False
    # 기본은 끈다(로컬에서 작업 폴더를 건드리지 않는다)
    (r / ".mcp.json").write_text("{}", encoding="utf-8")
    ar.run(str(r), base, head, str(tmp_path / "o2"), runner=runner, env={})
    assert seen["mcp"] is True


LEAKS = [
    "sk-ant-oat01-abcdefghijklmnop", "ghp_" + "a" * 30, "ghs_" + "B" * 20, "github_pat_" + "c" * 30,
    "Authorization: basic dXNlcjpwYXNzd29yZA==", "x" * 3 + "Ab1" * 20,
    'password = "hunter2hunter2"', "-----BEGIN RSA PRIVATE KEY-----",
]


@pytest.mark.parametrize("text", LEAKS)
def test_토큰_모양_문자열이_있으면_누출로_본다(text):
    assert ar.scan_leaks([f"설명 {text} 끝"], env={}) is True


def test_env_의_토큰_실제_값이_있으면_누출로_본다():
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "  opaque-value-123  ", "GITHUB_TOKEN": "short"}
    assert ar.scan_leaks(["x opaque-value-123 y"], env) is True
    assert ar.scan_leaks(["short"], env) is False  # 8자 미만 값은 비교하지 않는다


def test_평범한_지적과_경로는_누출로_보지_않는다():
    texts = [json.dumps({"severity": "serious", "file": "checker/tests/test_ai_review_workflow.py", "line": 3,
                         "summary": "권한 검사 없이 값을 쓴다. docs/guide/harness-guide.html 참고"}, ensure_ascii=False)]
    assert ar.scan_leaks(texts, env={}) is False


def test_결과에_비밀값이_섞이면_결과_파일을_쓰지_않고_검사_불능(repo, tmp_path, capsys):
    r, base, head = repo
    out = tmp_path / "o"
    secret = "tok-" + "z9" * 12
    bad = _result({"findings": [{"severity": "serious", "file": "src/new.py", "line": 1, "summary": f"환경: {secret}"}]})
    with pytest.raises(ar.Unavailable, match="결과에 비밀값으로 보이는 문자열") as exc:
        ar.run(str(r), base, head, str(out), runner=_runner(out=bad), env={},
               secret_env={"CLAUDE_CODE_OAUTH_TOKEN": secret})
    assert secret not in str(exc.value)  # 값은 어디에도 싣지 않는다
    assert not (out / "ai-review.json").exists()


def test_main_누출이면_종료코드_2_이고_사유_파일에_값이_없다(repo, tmp_path, monkeypatch, capsys):
    r, base, head = repo
    out = tmp_path / "o"
    bad = _result({"findings": [{"severity": "minor", "file": "src/new.py", "line": 1, "summary": "ghp_" + "q" * 30}]})
    monkeypatch.setattr(ar, "_default_runner", _runner(out=bad))
    assert ar.main(["run", "--repo", str(r), "--base", base, "--head", head, "--out", str(out)]) == 2
    text = (out / "ai-review-unavailable.json").read_text(encoding="utf-8")
    assert "비밀값으로 보이는 문자열" in text and "ghp_" not in text
    assert "ghp_" not in capsys.readouterr().err and not (out / "ai-review.json").exists()


# --- 시작 시점 의존 확인 / 예상 못 한 예외 ---------------------------------------------------------


def test_비밀값_패턴을_못_불러오면_claude_를_부르기_전에_검사_불능(repo, tmp_path, monkeypatch):
    r, base, head = repo
    monkeypatch.setitem(sys.modules, "checker.risk_gate", None)  # import 가 ImportError 를 낸다(yaml 이 없는 환경과 같다)
    called = []

    def runner(*a):
        called.append(1)
        return 0, _result({"findings": []}), ""

    with pytest.raises(ar.Unavailable, match="비밀값 패턴을 불러오지 못했다"):
        ar.run(str(r), base, head, str(tmp_path / "o"), runner=runner, env={})
    assert called == []  # 비용을 쓰기 전에 멈췄다


def test_main_의존_모듈이_없으면_종료코드_2_와_사유_파일(repo, tmp_path, monkeypatch, capsys):
    r, base, head = repo
    out = tmp_path / "o"
    monkeypatch.setitem(sys.modules, "checker.risk_gate", None)
    monkeypatch.setattr(ar, "_default_runner", lambda *a: (_ for _ in ()).throw(AssertionError("호출 금지")))
    assert ar.main(["run", "--repo", str(r), "--base", base, "--head", head, "--out", str(out)]) == 2
    assert "불러오지 못했다" in json.loads((out / "ai-review-unavailable.json").read_text(encoding="utf-8"))["reason"]
    assert not (out / "ai-review.json").exists()


def test_main_예상_못_한_예외도_검사_불능으로_남기고_트레이스백은_stderr_에만(repo, tmp_path, monkeypatch, capsys):
    r, base, head = repo
    out = tmp_path / "o"
    out.mkdir()
    (out / "ai-review.json").write_text("{}", encoding="utf-8")  # 낡은 결과는 지운다

    def boom(*a, **k):
        raise RuntimeError("내부 값 abc")

    monkeypatch.setattr(ar, "collect", boom)
    assert ar.main(["run", "--repo", str(r), "--base", base, "--head", head, "--out", str(out)]) == 2
    reason = json.loads((out / "ai-review-unavailable.json").read_text(encoding="utf-8"))["reason"]
    assert reason == "예상하지 못한 오류(RuntimeError)" and "abc" not in reason
    assert "Traceback" in capsys.readouterr().err and not (out / "ai-review.json").exists()


# --- 권한 거부 기록 -------------------------------------------------------------------------------


def test_묶음_기록에_권한_거부와_턴을_남기되_내용은_싣지_않는다():
    denials = [
        {"tool_name": "Read", "tool_use_id": "t1", "tool_input": {"file_path": "/proc/self/environ", "limit": 5}},
        {"tool_name": "Grep", "tool_input": {"pattern": "TOKEN", "path": "/etc", "output_mode": "content"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat /etc/passwd"}},  # 경로 필드가 없으면 대상은 비운다
        "이상한 항목",
    ]
    out = _result({"findings": []}, permission_denials=denials)
    r = _go(_runner(out=out))
    assert r["ok"] and r["num_turns"] == 3
    assert r["permission_denials"] == [
        {"tool": "Read", "target": "/proc/self/environ"},
        {"tool": "Grep", "target": "/etc"},
        {"tool": "Bash", "target": ""},
    ]
    assert "cat /etc/passwd" not in json.dumps(r) and "output_mode" not in json.dumps(r)


def test_결과_파일의_batches_에_permission_denials_가_들어간다(repo, tmp_path):
    r, base, head = repo
    out = _result({"findings": []}, permission_denials=[{"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}}])
    merged = ar.run(str(r), base, head, str(tmp_path / "o"), runner=_runner(out=out), env={})
    batch = merged["batches"][0]
    assert batch["permission_denials"] == [{"tool": "Read", "target": "/etc/hosts"}] and batch["num_turns"] == 3
    saved = json.loads((tmp_path / "o" / "ai-review.json").read_text(encoding="utf-8"))
    assert saved["batches"][0]["permission_denials"] == batch["permission_denials"]


def test_실패한_묶음도_권한_거부를_남긴다():
    out = json.dumps({"subtype": "error_max_turns", "is_error": True, "num_turns": 15,
                      "permission_denials": [{"tool_name": "Read", "tool_input": {"file_path": "/proc/1/environ"}}]})
    r = _go(_runner(out=out))
    assert not r["ok"] and r["permission_denials"] == [{"tool": "Read", "target": "/proc/1/environ"}]


def test_권한_거부_대상에_비밀값이_있어도_결과를_쓰지_않는다(repo, tmp_path):
    r, base, head = repo
    out = _result({"findings": []}, permission_denials=[
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/ghp_" + "w" * 30}}])
    with pytest.raises(ar.Unavailable, match="비밀값으로 보이는 문자열"):
        ar.run(str(r), base, head, str(tmp_path / "o"), runner=_runner(out=out), env={})
