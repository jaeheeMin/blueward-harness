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

| ID | 내용 | Spec | 담당 | 상태 |
|---|---|---|---|---|
| DEV-001 | a | - | u | 완료 |
"""


def make_repo(tmp_path: Path, *, ledger: bool = True, srs: str = SRS) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    (work / "docs" / "ssot").mkdir(parents=True)
    (work / "docs" / "ssot" / "SRS.md").write_text(srs, encoding="utf-8")
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


def test_한글_이름의_원장_Spec_번호도_계산에_든다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    (work / "audit" / "ledger" / "판매오더조회.md").write_text(
        LEDGER.replace("DEV-001", "DEV-007"), encoding="utf-8"
    )
    (work / "docs" / "spec" / "DEV-009-판매오더조회앱.md").write_text("# DEV-009\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "한글 파일")
    _git(work, "push", "origin", "main")
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["next"])
    assert (code, out) == (0, "DEV-010")


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


def test_제목_끝_DEV_는_번호_계산에_안_잡힌다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    fake = FakeGh([
        {"number": 5, "title": "Launchpad 타일 노출 (DEV-009)"},
        {"number": 6, "title": "[DEV-004] 본 이슈 (DEV-008)"},
    ])
    assert rn.subtask_of("타일 노출 (DEV-002)") == 2
    assert rn.issue_tag("타일 노출 (DEV-002)") is None
    monkeypatch.chdir(work)
    monkeypatch.setattr(rn, "gh", fake)
    # main 최대 2, 찜 최대 4 → 5. 제목 끝 (DEV-009) 는 무시된다.
    assert rn.compute_next(str(work)) == 5


SRS_LIST = """# SRS

## 요구사항

| ID | LoB | Title | Status | 다음 단계 |
|---|---|---|---|---|
| REQ-001 | SD | 판매오더 | Done | 개발 |
| REQ-002 | SD | 조회 앱 | New | 설정 |
"""


def test_list_는_번호별로_모아_낸다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    (work / "docs" / "ssot" / "SRS.md").write_text(SRS_LIST, encoding="utf-8")
    _git(work, "commit", "-am", "srs")
    _git(work, "push", "origin", "main")
    fake = FakeGh([
        {"number": 5, "title": "[DEV-002] 조회 앱", "state": "OPEN"},
        {"number": 6, "title": "타일 노출 (DEV-002)", "state": "OPEN"},
        {"number": 7, "title": "엉뚱한 (DEV-099)", "state": "OPEN"},
    ])
    code, out = run(monkeypatch, capsys, work, fake, ["list"])
    res = json.loads(out)
    assert code == 0
    devs = {d["number"]: d for d in res["devs"]}
    assert set(devs) == {"DEV-001", "DEV-002"}
    assert devs["DEV-001"]["req_title"] == "판매오더"
    assert devs["DEV-001"]["lob"] == "SD" and devs["DEV-001"]["next_step"] == "개발"
    assert devs["DEV-001"]["status"] == "Done"
    assert devs["DEV-001"]["ledger"]["status"] == "완료"
    assert devs["DEV-002"]["spec"].startswith("docs/spec/DEV-002")
    assert [i["number"] for i in devs["DEV-002"]["issues"]] == [5]
    assert [i["number"] for i in devs["DEV-002"]["subtasks"]] == [6]
    # 사람용 표기(#308): SRS 제목
    assert devs["DEV-001"]["label"] == "DEV-001(판매오더)" and devs["DEV-002"]["label"] == "DEV-002(조회 앱)"


def test_list_label_은_SRS_에_없으면_원장_내용_이슈_제목_순으로_대신한다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path, srs="# SRS\n\n## 요구사항\n\n아직 작성 전\n")
    fake = FakeGh([{"number": 5, "title": "[DEV-099] 엉뚱한 일", "state": "OPEN"}])
    code, out = run(monkeypatch, capsys, work, fake, ["list"])
    devs = {d["number"]: d for d in json.loads(out)["devs"]}
    assert code == 0
    assert devs["DEV-001"]["label"] == "DEV-001(a)"  # 원장 내용
    assert devs["DEV-099"]["label"] == "DEV-099(엉뚱한 일)"  # 이슈 제목
    assert devs["DEV-002"]["label"] == "DEV-002(제목 미확인)"  # Spec 만 있고 어디에도 제목이 없다


def test_list_label_은_대시_후보를_건너뛴다(tmp_path, monkeypatch, capsys):
    srs = "# SRS\n\n## 요구사항\n\n| ID | Title | Status |\n|---|---|---|\n| REQ-001 | - | New |\n"
    work = make_repo(tmp_path, srs=srs)
    fake = FakeGh([{"number": 5, "title": "[DEV-001] 이슈에 쓴 제목", "state": "OPEN"}])
    code, out = run(monkeypatch, capsys, work, fake, ["list"])
    dev = {d["number"]: d for d in json.loads(out)["devs"]}["DEV-001"]
    assert code == 0 and dev["label"] == "DEV-001(a)"  # SRS 제목 `-` 는 건너뛰고 원장 내용


def test_titled_label_은_제목이_비면_추측하지_않는다():
    assert rn.titled_label("DEV-005", "조회 앱") == "DEV-005(조회 앱)"
    assert rn.titled_label("DEV-005", None) == "DEV-005(제목 미확인)"
    assert rn.titled_label("DEV-005", "-") == "DEV-005(제목 미확인)"


def test_list_는_열이_없으면_그_키를_생략한다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["list"])
    dev = {d["number"]: d for d in json.loads(out)["devs"]}["DEV-001"]
    assert code == 0
    assert "lob" not in dev and "next_step" not in dev
    assert dev["req_title"] == "a"


def test_list_는_한글_이름_원장의_줄도_담는다(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    (work / "audit" / "ledger" / "판매오더조회.md").write_text(
        LEDGER.replace("DEV-001 | a | - | u | 완료", "DEV-002 | b | - | u | 진행"), encoding="utf-8"
    )
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "한글 원장")
    _git(work, "push", "origin", "main")
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["list"])
    dev = {d["number"]: d for d in json.loads(out)["devs"]}["DEV-002"]
    assert code == 0
    assert dev["ledger"]["status"] == "진행"


def test_list_원장이_없으면_3_gh_실패는_2(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path, ledger=False)
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["list"])
    assert code == 3 and json.loads(out)["status"] == "no_ledger"
    work2 = make_repo(tmp_path / "b")
    code, out = run(monkeypatch, capsys, work2, FakeGh(fail=True), ["list"])
    assert code == 2 and json.loads(out)["status"] == "error"


SRS_TITLED = """# SRS

## 요구사항

| ID | Title | Status |
|---|---|---|
| REQ-001 | 판매오더 조회 앱 | New |
| REQ-002 | AB | New |
"""


def _titled(tmp_path):
    return make_repo(tmp_path, srs=SRS_TITLED)


def test_새_제목이_기존_REQ_제목을_포함하면_4_이고_이슈를_안_만든다(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh()
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "[DEV-009] 판매오더 조회 앱 목록 필터 추가"])
    assert code == 4
    res = json.loads(out)
    assert res["status"] == "confirm"
    assert res["matches"] == [{"number": "DEV-001", "title": "판매오더 조회 앱", "label": "DEV-001(판매오더 조회 앱)"}]
    assert res["title"] == "판매오더 조회 앱 목록 필터 추가"
    assert fake.issues == {}


def test_기존_REQ_제목이_새_제목을_포함해도_4(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh()
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "조회  앱"])
    assert code == 4  # 공백 정리 뒤 "조회 앱" 은 "판매오더 조회 앱" 에 들어 있다
    assert fake.issues == {}


def test_반대_방향_포함은_4(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh()
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "판매오더 조회"])
    assert code == 4
    assert json.loads(out)["matches"][0]["number"] == "DEV-001"
    assert fake.issues == {}


def test_무관한_제목은_그대로_찜한다(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "구매요청 승인 흐름"])
    assert code == 0
    assert json.loads(out)["status"] == "ok"


def test_confirmed_new_는_확인을_건너뛴다(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh()
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "판매오더 조회 앱 개편", "--confirmed-new"])
    assert code == 0
    assert json.loads(out)["number"] == "DEV-003"
    assert len(fake.issues) == 1


def test_짧은_제목은_포함_비교에서_뺀다(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    # 기존 REQ-002 제목 "AB" 는 하한 미만이라 "AB 연동 개선" 이 걸리지 않는다. 새 제목이 짧을 때도 마찬가지.
    code, _ = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "AB 연동 개선"])
    assert code == 0
    code, _ = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "조회"])
    assert code == 0


def test_claim_번호가_없는_이슈도_겹치면_4_이고_제목을_안_고친다(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh([{"number": 12, "title": "판매오더 조회 앱 화면 개선"}])
    code, out = run(monkeypatch, capsys, work, fake, ["claim", "--issue", "12"])
    assert code == 4
    assert json.loads(out)["status"] == "confirm"
    assert fake.edits == []
    code, out = run(monkeypatch, capsys, work, fake, ["claim", "--issue", "12", "--confirmed-new"])
    assert code == 0
    assert fake.edits and fake.edits[0][1].startswith("[DEV-003]")


def test_claim_이미_번호가_있으면_겹쳐도_확인_안_함(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh([{"number": 12, "title": "[DEV-001] 판매오더 조회 앱 화면 개선"}])
    code, out = run(monkeypatch, capsys, work, fake, ["claim", "--issue", "12"])
    assert code == 0 and json.loads(out)["number"] == "DEV-001"


def test_SRS_가_없으면_확인_없이_기존_흐름(tmp_path, monkeypatch, capsys):
    work = make_repo(tmp_path)
    subprocess.run(["git", "rm", "-q", "docs/ssot/SRS.md"], cwd=work, check=True, capture_output=True)
    _git(work, "commit", "-m", "rm srs")
    _git(work, "push", "origin", "main")
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "판매오더 조회 앱"])
    assert code == 0


def test_SRS_를_읽다_실패하면_2_이고_번호를_안_준다(tmp_path, monkeypatch, capsys):
    work = _titled(tmp_path)
    fake = FakeGh()
    real = rn._show_main

    def boom(root, path):
        if path == "docs/ssot/SRS.md":
            raise rn.Undecidable("SRS 읽기 실패(가짜)")
        return real(root, path)

    monkeypatch.setattr(rn, "_show_main", boom)
    code, out = run(monkeypatch, capsys, work, fake, ["reserve", "--title", "구매요청 승인 흐름"])
    assert code == 2
    assert fake.issues == {}


# --- SRS 범위 "하지 않는 것" 항목 겹침(#304) ---------------------------------------------

SRS_SCOPE = """# SRS

## 범위

- 하는 것: 조회
- 하지 않는 것:
  - 판매오더 생성·변경·삭제 (조회 전용)
  - Fiori Launchpad 노출(IAM App, Role) (REQ-002)
  - 회계전표 역분개·취소, 승인 워크플로 (REQ-001, REQ-003)
  - 외부 API
  - 취소

## 요구사항

| ID | Title | Status |
|---|---|---|
| REQ-001 | 회계전표 업로드 | New |
| REQ-002 | 판매오더 조회 앱 | New |
"""


def _scoped(tmp_path):
    return make_repo(tmp_path, srs=SRS_SCOPE)


def test_하지_않는_것_항목이_꼬리표_없이_겹치면_4_이고_reqs_는_빈_목록(tmp_path, monkeypatch, capsys):
    # 항목 "판매오더 생성·변경·삭제 (조회 전용)" 안에 새 제목 "판매오더 생성·변경" 이 들어 있다
    fake = FakeGh()
    code, out = run(monkeypatch, capsys, _scoped(tmp_path), fake, ["reserve", "--title", "판매오더 생성·변경"])
    assert code == 4 and fake.issues == {}
    assert json.loads(out)["matches"] == []
    assert json.loads(out)["excluded_matches"] == [{"item": "판매오더 생성·변경·삭제 (조회 전용)", "reqs": [], "reqs_labeled": []}]


def test_꼬리표가_있으면_그_REQ_번호를_낸다(tmp_path, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, _scoped(tmp_path), FakeGh(), ["reserve", "--title", "Fiori Launchpad 노출(IAM App, Role) 정리"])
    assert code == 4
    assert json.loads(out)["excluded_matches"] == [
        {"item": "Fiori Launchpad 노출(IAM App, Role)", "reqs": ["REQ-002"], "reqs_labeled": ["REQ-002(판매오더 조회 앱)"]}
    ]


def test_꼬리표에_번호가_여럿이면_모두_낸다(tmp_path, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, _scoped(tmp_path), FakeGh(), ["reserve", "--title", "승인 워크플로"])
    assert code == 4
    # 들여쓴 줄은 줄마다 한 항목이라 쉼표 뒤까지 한 항목이다
    assert json.loads(out)["excluded_matches"] == [
        {"item": "회계전표 역분개·취소, 승인 워크플로", "reqs": ["REQ-001", "REQ-003"],
         # REQ-003 은 SRS 표에 없어 제목을 추측하지 않는다
         "reqs_labeled": ["REQ-001(회계전표 업로드)", "REQ-003(제목 미확인)"]}
    ]


def test_짧은_단어나_짧은_항목은_하지_않는_것_비교에서_뺀다(tmp_path, monkeypatch, capsys):
    work = _scoped(tmp_path)
    # 새 제목이 하한(4자) 미만이면 걸리지 않고, 정규화 뒤 4자 미만인 항목 "취소" 가 긴 제목에 들어 있어도 걸리지 않는다.
    code, _ = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "생성"])
    assert code == 0
    code, _ = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "구매요청 취소 알림 배치"])
    assert code == 0


def test_기존_제목_겹침만_있으면_excluded_matches_는_빈_목록(tmp_path, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, _titled(tmp_path), FakeGh(), ["reserve", "--title", "판매오더 조회 앱 개편"])
    assert code == 4
    res = json.loads(out)
    assert res["matches"] and res["excluded_matches"] == []
    assert set(res) == {"status", "matches", "excluded_matches", "title"}


def test_하지_않는_것_과_겹치지_않으면_그대로_찜한다(tmp_path, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, _scoped(tmp_path), FakeGh(), ["reserve", "--title", "구매요청 승인 흐름"])
    assert code == 0 and json.loads(out)["status"] == "ok"


def test_하지_않는_것_confirmed_new_는_건너뛴다(tmp_path, monkeypatch, capsys):
    fake = FakeGh()
    code, out = run(monkeypatch, capsys, _scoped(tmp_path), fake, ["reserve", "--title", "판매오더 생성·변경", "--confirmed-new"])
    assert code == 0 and len(fake.issues) == 1


def test_하지_않는_것_이_없는_SRS_는_기존_동작_그대로(tmp_path, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, _titled(tmp_path), FakeGh(), ["reserve", "--title", "판매오더 생성"])
    assert code == 0


def test_제목_겹침과_하지_않는_것_겹침이_함께_나온다(tmp_path, monkeypatch, capsys):
    srs = SRS_SCOPE.replace("| REQ-002 | 판매오더 조회 앱 | New |", "| REQ-002 | 판매오더 생성·변경 앱 | New |")
    code, out = run(monkeypatch, capsys, make_repo(tmp_path, srs=srs), FakeGh(), ["reserve", "--title", "판매오더 생성·변경"])
    assert code == 4
    res = json.loads(out)
    assert res["matches"][0]["number"] == "DEV-002" and res["excluded_matches"]


def test_scope_excluded_items_파서(tmp_path):
    items = rn.scope_excluded_items(SRS_SCOPE)
    by_item = {i["item"]: i["reqs"] for i in items}
    assert by_item["Fiori Launchpad 노출(IAM App, Role)"] == ["REQ-002"]
    assert by_item["회계전표 역분개·취소, 승인 워크플로"] == ["REQ-001", "REQ-003"]
    assert by_item["외부 API"] == []
    # 머리말 줄에 이어 쓴 항목은 쪼개고, 꼬리표는 그 항목에만 붙는다
    one_line = rn.scope_excluded_items("- 하지 않는 것: 노출(IAM App, Role), 외부 API (REQ-005), 이관.")
    assert one_line == [
        {"item": "노출(IAM App, Role)", "reqs": []},
        {"item": "외부 API", "reqs": ["REQ-005"]},
        {"item": "이관", "reqs": []},
    ]
    # 코드 펜스 안의 예시와 다른 목록은 보지 않는다
    assert rn.scope_excluded_items("```\n- 하지 않는 것: 예시 (REQ-001)\n```\n") == []


def test_꼬리표_정규식은_엔진과_같다():
    from checker import risk_gate

    assert rn.EXCLUDED_TAG_RE.pattern == risk_gate.EXCLUDED_TAG_RE.pattern
    assert rn.SCOPE_EXCLUDED_MARKER == risk_gate.SCOPE_EXCLUDED_MARKER


# 핵심 단어 겹침(#304): 포함 판정이 못 잡는 사건 항목. 사건 직전 public-cloud SRS 의 범위 절을 줄였다.
SRS_INCIDENT = """# SRS

## 범위

- 하지 않는 것:
  - 판매오더 생성·변경·삭제 (조회 전용)
  - 커스텀 권한 규칙(DCL). 표준 접근 제어를 그대로 따른다
  - Fiori Launchpad 노출(IAM App, Business Catalog, Role)과 외부 소비용 API 서비스
  - 개발사양서 xlsx 작성

## 요구사항

| ID | Title | Status |
|---|---|---|
| REQ-002 | 판매오더 조회 앱 | In Process |
"""


@pytest.mark.parametrize("title", ["Launchpad 타일 노출", "launchpad  노출 타일", "타일 노출 Launchpad"])
def test_핵심_단어가_둘_이상_겹치면_포함이_아니어도_4(tmp_path, monkeypatch, capsys, title):
    work = make_repo(tmp_path, srs=SRS_INCIDENT)
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", title])
    assert code == 4
    res = json.loads(out)
    assert res["matches"] == [] and res["excluded_matches"][0]["item"].startswith("Fiori Launchpad 노출(IAM App")


@pytest.mark.parametrize("title", [
    "구매요청 승인", "재고 조회 앱", "판매오더 엑셀 다운로드", "Launchpad 타일", "노출 보고서 출력 화면",
    "Launchpad 노출 타일 신규 추가",  # 공유 2개지만 새 제목 토큰 5개의 2/3 미만
])
def test_핵심_단어가_하나만_겹치거나_비율이_모자라면_안_멈춘다(tmp_path, monkeypatch, capsys, title):
    work = make_repo(tmp_path, srs=SRS_INCIDENT)
    code, _ = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", title])
    assert code == 0


def test_토큰_겹침은_REQ_제목_비교에는_쓰지_않는다(tmp_path, monkeypatch, capsys):
    srs = SRS_INCIDENT.replace("판매오더 조회 앱", "판매오더 조회 화면 개선")
    code, _ = run(monkeypatch, capsys, make_repo(tmp_path, srs=srs), FakeGh(), ["reserve", "--title", "개선 조회 화면 추가"])
    assert code == 0


def test_토큰화는_구두점으로_나누고_짧은_토큰은_뺀다():
    assert rn._tokens("Fiori Launchpad 노출(IAM App, Role)·a") == {"fiori", "launchpad", "노출", "iam", "app", "role"}


@pytest.mark.parametrize("title", ["판매오더 조회", "판매오더 상세 조회", "조회 전용 화면"])
def test_괄호_속_부연은_비교에서_빠져_핵심_기능_제목이_안_멈춘다(tmp_path, monkeypatch, capsys, title):
    # 항목 "판매오더 생성·변경·삭제 (조회 전용)". REQ 제목 겹침이 끼지 않게 표의 제목은 다른 것으로 바꾼다.
    work = make_repo(tmp_path, srs=SRS_INCIDENT.replace("판매오더 조회 앱", "재고 이동 등록"))
    code, _ = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", title])
    assert code == 0


def test_경계_사례_판매오더_변경_이력은_멈춘다(tmp_path, monkeypatch, capsys):
    # 변경을 안 하기로 한 항목과 핵심 단어 둘(판매오더·변경)이 겹친다. 멈춰도 질문 하나라 허용한다.
    work = make_repo(tmp_path, srs=SRS_INCIDENT)
    code, out = run(monkeypatch, capsys, work, FakeGh(), ["reserve", "--title", "판매오더 변경 이력"])
    assert code == 4 and json.loads(out)["excluded_matches"][0]["item"].startswith("판매오더 생성")


def test_괄호_속_내용을_빼도_사건_항목은_멈춘다():
    body = rn._strip_parens("Fiori Launchpad 노출(IAM App, Business Catalog, Role)과 외부 소비용 API 서비스")
    assert "iam" not in rn._tokens(body) and rn._token_overlap(rn._tokens("Launchpad 타일 노출"), rn._tokens(body))
    assert rn._strip_parens("A (b (c)) D") .split() == ["A", "D"]


def test_같은_본문의_항목이_다른_꼬리표로_두_번_나오면_번호를_합친다():
    items = rn.scope_excluded_items("- 하지 않는 것:\n  - 승인 워크플로 (REQ-001)\n  - 승인 워크플로 (REQ-002, REQ-001)\n  - 승인 워크플로\n")
    assert items == [{"item": "승인 워크플로", "reqs": ["REQ-001", "REQ-002"]}]


@pytest.mark.parametrize("raw", ["항목 (REQ-001/REQ-002)", "항목 (REQ-001~002)", "항목 (req-001)", "항목 (REQ-001/ REQ-002)"])
def test_꼬리표로_안_읽히는_표기(raw):
    (item,) = rn.scope_excluded_items("- 하지 않는 것:\n  - " + raw + "\n")
    assert item["reqs"] == []
