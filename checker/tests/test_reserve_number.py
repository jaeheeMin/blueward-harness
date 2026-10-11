"""`reserve_number.py`(번호 찜, #227)를 검증한다.

git 은 진짜(임시 origin 과 clone)를 쓰고, gh 는 `reserve_number.gh` 를 가짜 이슈 저장소로
바꿔 흉내 낸다(PATH 가짜 실행 파일은 Windows 에서 확장자 없는 스크립트를 못 돌려 쓰지 않았다).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins" / "harness" / "skills" / "start" / "reserve_number.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("reserve_number_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rn = _load()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


SRS = """# SRS

## 요구사항

| ID | 요구사항 | 우선순위 | 출처 | 상태 |
|---|---|---|---|---|
| REQ-001 | a | 상 | x | 유효 |
| REQ-002 | b | 상 | x | 유효 |
"""

LEDGER = """# 프로그램

## 개발 건

| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |
|---|---|---|---|---|---|
| DEV-001 | a | - | u | 완료 |  |
"""


def make_repo(tmp_path: Path, *, ledger: bool = True) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    (work / "docs" / "ssot").mkdir(parents=True)
    (work / "docs" / "ssot" / "SRS.md").write_text(SRS, encoding="utf-8")
    (work / "docs" / "spec").mkdir()
    (work / "docs" / "spec" / "DEV-002-요약.md").write_text("# DEV-002\n", encoding="utf-8")
    if ledger:
        (work / "audit" / "ledger").mkdir(parents=True)
        (work / "audit" / "ledger" / "p.md").write_text(LEDGER, encoding="utf-8")
    else:
        (work / "README.md").write_text("x\n", encoding="utf-8")
    _git(work, "checkout", "-b", "main")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "init")
    _git(work, "push", "origin", "main")
    return work


class FakeGh:
    """gh issue list/create/edit/view 만 흉내 내는 이슈 저장소."""

    def __init__(self, issues=None, *, fail=False, rival_on_create: int | None = None):
        self.issues = {i["number"]: dict(i) for i in (issues or [])}
        self.fail = fail
        self.rival_on_create = rival_on_create
        self.edits: list[tuple[int, str]] = []

    def _next_no(self) -> int:
        return max(self.issues, default=0) + 1

    def __call__(self, args, cwd=None):
        if self.fail:
            raise rn.Undecidable("gh 실패(가짜)")
        if args[:2] == ["issue", "list"]:
            return json.dumps(list(self.issues.values()), ensure_ascii=False)
        if args[:2] == ["issue", "create"]:
            title = args[args.index("--title") + 1]
            if self.rival_on_create is not None:
                n = self._next_no()
                self.issues[n] = {"number": n, "title": f"[DEV-{self.rival_on_create:03d}] 남의 일"}
            n = self._next_no()
            self.issues[n] = {"number": n, "title": title}
            return f"https://github.com/o/r/issues/{n}\n"
        if args[:2] == ["issue", "edit"]:
            n = int(args[2])
            title = args[args.index("--title") + 1]
            self.issues[n]["title"] = title
            self.edits.append((n, title))
            return ""
        if args[:2] == ["issue", "view"]:
            n = int(args[2])
            return json.dumps({**self.issues[n], "url": f"https://github.com/o/r/issues/{n}"}, ensure_ascii=False)
        raise AssertionError(f"예상 밖 gh 호출: {args}")


def run(monkeypatch, capsys, work: Path, fake: FakeGh, argv: list[str]):
    monkeypatch.chdir(work)
    monkeypatch.setattr(rn, "gh", fake)
    code = rn.main(argv)
    return code, capsys.readouterr().out.strip()


def test_main_최대_2_이슈_찜_최대_4_이면_5(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh([
        {"number": 7, "title": "[DEV-004] 닫힌 이슈"},
        {"number": 8, "title": "[DEV-003] 다른 이슈"},
        {"number": 9, "title": "번호 없는 이슈"},
    ])
    code, out = run(monkeypatch, capsys, work, fake, ["next"])
    assert (code, out) == (0, "DEV-005")


def test_main_만_있으면_main_최대_다음(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["next"])
    assert (code, out) == (0, "DEV-003")


def test_reserve_는_제목에_번호를_붙여_이슈를_만든다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh([{"number": 5, "title": "[DEV-004] x"}])
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "새 기능", "--label", "type:feat"])
    res = json.loads(out)
    assert code == 0
    assert res["number"] == "DEV-005" and res["renumbered_from"] is None
    assert fake.issues[res["issue"]]["title"] == "[DEV-005] 새 기능"


def test_생성_직후_더_앞선_이슈가_같은_번호면_재번호(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh(rival_on_create=3)
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "새 기능"])
    res = json.loads(out)
    assert code == 0
    assert res["renumbered_from"] == "DEV-003"
    assert res["number"] == "DEV-004"
    assert "겹쳐" in res["notice"]
    assert fake.issues[res["issue"]]["title"] == "[DEV-004] 새 기능"


def test_더_뒤의_이슈가_같은_번호면_내_번호를_유지(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh([{"number": 50, "title": "[DEV-003] 나중 이슈"}])
    code, out = run(monkeypatch, capsys, work, fake, ["claim", "--issue", "50"])
    # 이슈 50 은 이미 DEV-003 을 찜했고 더 앞선 이슈가 없다.
    assert code == 0 and json.loads(out)["number"] == "DEV-003"
    assert fake.edits == []


def test_원장이_없는_저장소는_찜_안_함_종료코드_3(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path, ledger=False)
    fake = FakeGh()
    for argv in (["next"], ["reserve", "--title", "t"], ["claim", "--issue", "1"]):
        code, out = run(monkeypatch, capsys, work, fake, argv)
        assert code == 3
        assert json.loads(out)["status"] == "no_ledger"
    assert fake.issues == {}


def test_gh_실패는_판정_불능_종료코드_2(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    code, out = run(monkeypatch, capsys, work, FakeGh(fail=True), ["next"])
    assert code == 2
    assert json.loads(out)["status"] == "error"


def test_origin_main_을_못_읽으면_종료코드_2(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    _git(work, "remote", "remove", "origin")
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["next"])
    assert code == 2 and json.loads(out)["status"] == "error"


def test_claim_이미_번호가_있으면_그_번호(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh([{"number": 12, "title": "[DEV-009] 이미 찜"}])
    code, out = run(monkeypatch, capsys, work, fake, ["claim", "--issue", "12"])
    assert code == 0
    assert json.loads(out)["number"] == "DEV-009"
    assert fake.edits == []


def test_claim_번호가_없으면_붙인다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh([{"number": 12, "title": "번호 없는 이슈"}])
    code, out = run(monkeypatch, capsys, work, fake, ["claim", "--issue", "12"])
    assert code == 0
    assert json.loads(out)["number"] == "DEV-003"
    assert fake.issues[12]["title"] == "[DEV-003] 번호 없는 이슈"
