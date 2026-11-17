"""판 번호 충돌 자동 해결(`checker/version_rebase.py`, #1074)을 임시 git 저장소에서 검증한다.

main 판 0.10.10, 다른 열린 PR 판 0.10.11·0.10.12(gh 는 가짜), 내 브랜치 0.10.11 로 리베이스·병합 충돌을 만들어
0.10.13 으로 풀리는지, 다른 파일이 섞이면 거절하는지, gh 를 못 읽으면 검사 불능인지 본다.
경로·줄바꿈은 Windows 에서도 같도록 바이트로 쓰고 읽는다.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from checker.plugin_version import PLUGIN_JSON
from checker.ssot_approval import GhError
from checker.version_rebase import CANNOT_CHECK, MERGED, NOT_APPLICABLE, REFUSED, WHATS_NEW, _Cannot, _resolve_plugin_json, main, rebase_version

FRAG = "plugins/harness/console/whats_new.d/"


def plugin(version: str, eol: str = "\n") -> str:
    return eol.join(['{', '  "name": "harness",', f'  "version": "{version}",', '  "author": {"name": "x"}', '}', ''])


def whats_new(blocks: dict, comment: str = "설명") -> str:
    return json.dumps({"_comment": comment, "versions": blocks}, ensure_ascii=False, indent=2) + "\n"


def git(repo: Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if ok:
        assert done.returncode == 0, done.stderr
    return done


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def commit(repo: Path, msg: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


class FakeGh:
    """열린 PR 목록(`prs`: 번호·브랜치·판)을 돌려주는 가짜 gh. `fail` 이면 모든 호출이 실패한다."""

    def __init__(self, prs: list[tuple[int, str, str]], fail: bool = False):
        self.prs, self.fail = prs, fail

    def run(self, args: list[str]) -> str:
        if self.fail:
            raise GhError("gh 실패")
        if args[:2] == ["repo", "view"]:
            return "o/r\n"
        assert args[:2] == ["pr", "list"] and "--base" in args
        return json.dumps([{"number": n, "headRefName": b, "headRefOid": f"sha{n}"} for n, b, _ in self.prs])

    def get_json_or_none_404(self, path: str):
        if self.fail:
            raise GhError("gh 실패")
        n = int(path.split("?ref=sha")[1])
        v = next(v for num, _, v in self.prs if num == n)
        return {"content": base64.b64encode(plugin(v).encode("utf-8")).decode()}


OTHERS = [(201, "feat/a", "0.10.11"), (202, "feat/b", "0.10.12"), (203, "feat/mine", "0.10.11")]


def conflict(tmp_path: Path, mode: str, with_wn: bool = False, eol: str = "\n", extra: bool = False, fragment: bool = False,
             mine_wn_edits_base: bool = False) -> Path:
    """mode 방식으로 판 줄이 충돌 중인 저장소. base 0.10.9 → main 0.10.10, 내 브랜치 0.10.11."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "false")
    write(repo, PLUGIN_JSON, plugin("0.10.9", eol))
    write(repo, WHATS_NEW, whats_new({"0.10.9": ["옛 줄"]}))
    write(repo, "other.txt", "a\nb\nc\n")
    commit(repo, "base")
    git(repo, "switch", "-q", "-c", "feat/mine")
    write(repo, PLUGIN_JSON, plugin("0.10.11", eol))
    if with_wn:
        blocks = {"0.10.11": ["내 줄"], "0.10.9": ["옛 줄 고침" if mine_wn_edits_base else "옛 줄"]}
        write(repo, WHATS_NEW, whats_new(blocks))
    if fragment:
        write(repo, FRAG + "1074.json", json.dumps({"version": "0.10.11", "lines": ["조각 줄"]}, ensure_ascii=False, indent=2) + "\n")
    if extra:
        write(repo, "other.txt", "a\nMINE\nc\n")
    commit(repo, "mine")
    git(repo, "switch", "-q", "main")
    write(repo, PLUGIN_JSON, plugin("0.10.10", eol))
    if with_wn:
        write(repo, WHATS_NEW, whats_new({"0.10.10": ["main 줄"], "0.10.9": ["옛 줄"]}))
    if extra:
        write(repo, "other.txt", "a\nMAIN\nc\n")
    commit(repo, "main")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    if mode == "rebase":
        git(repo, "switch", "-q", "feat/mine")
        assert git(repo, "rebase", "main", ok=False).returncode != 0
    else:
        git(repo, "switch", "-q", "feat/mine")
        assert git(repo, "merge", "--no-edit", "main", ok=False).returncode != 0
    return repo


def read(repo: Path, rel: str) -> str:
    return (repo / rel).read_bytes().decode("utf-8")


def version_in(repo: Path) -> str:
    return json.loads(read(repo, PLUGIN_JSON))["version"]


@pytest.mark.parametrize("mode", ["rebase", "merge"])
def test_판_줄만_충돌하면_열린_PR_판_다음으로_다시_매긴다(tmp_path, mode):
    repo = conflict(tmp_path, mode)
    out = rebase_version(repo, mode, client=FakeGh(OTHERS))
    assert out["status"] == MERGED and out["version"] == "0.10.13", out  # max(main 0.10.10, 0.10.11, 0.10.12) + 1. 내 PR(203) 은 뺀다
    assert version_in(repo) == "0.10.13" and "<<<<" not in read(repo, PLUGIN_JSON)
    assert git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    if mode == "rebase":
        done = subprocess.run(["git", "-C", str(repo), "rebase", "--continue"], capture_output=True, env={**os.environ, "GIT_EDITOR": "true"})
        assert done.returncode == 0, done.stderr
    else:
        git(repo, "commit", "-q", "--no-edit")
    assert git(repo, "show", "HEAD:" + PLUGIN_JSON).stdout.count("0.10.13") == 1
    assert git(repo, "status", "--porcelain").stdout.strip() == ""


def test_main_판이_가장_크면_main_다음_판(tmp_path):
    repo = conflict(tmp_path, "rebase")
    out = rebase_version(repo, "rebase", client=FakeGh([(201, "feat/a", "0.10.3")]))
    assert out["status"] == MERGED and out["version"] == "0.10.11"


def test_숫자로_비교한다_0_10_9_보다_0_10_10_이_크다(tmp_path):
    repo = conflict(tmp_path, "rebase")
    out = rebase_version(repo, "rebase", client=FakeGh([(201, "feat/a", "0.10.9")]))
    assert out["version"] == "0.10.11"


def test_CRLF_plugin_json_은_줄바꿈을_지킨다(tmp_path):
    repo = conflict(tmp_path, "rebase", eol="\r\n")
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == MERGED
    raw = (repo / PLUGIN_JSON).read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") and b'"version": "0.10.13"' in raw


def test_진행_중인_브랜치_이름을_알아내어_내_PR_을_뺀다(tmp_path):
    repo = conflict(tmp_path, "rebase")
    # 내 PR(feat/mine)만 0.10.20 이면 빼야 한다 — 빼지 않으면 0.10.21 이 된다
    out = rebase_version(repo, "rebase", client=FakeGh([(201, "feat/a", "0.10.11"), (203, "feat/mine", "0.10.20")]))
    assert out["status"] == MERGED and out["version"] == "0.10.12"


def test_whats_new_충돌은_양쪽_블록을_살리고_내_블록을_새_판_키_맨_위에(tmp_path):
    repo = conflict(tmp_path, "rebase", with_wn=True)
    assert "whats_new.json" in git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == MERGED and out["version"] == "0.10.13"
    data = json.loads(read(repo, WHATS_NEW))
    assert list(data["versions"]) == ["0.10.13", "0.10.10", "0.10.9"]
    assert data["versions"] == {"0.10.13": ["내 줄"], "0.10.10": ["main 줄"], "0.10.9": ["옛 줄"]} and data["_comment"] == "설명"
    assert read(repo, WHATS_NEW).endswith("}\n") and git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""


def test_whats_new_merge_방식도_stage_가_뒤집혀도_같은_결과(tmp_path):
    repo = conflict(tmp_path, "merge", with_wn=True)
    out = rebase_version(repo, "merge", client=FakeGh(OTHERS))
    assert out["status"] == MERGED
    assert json.loads(read(repo, WHATS_NEW))["versions"] == {"0.10.13": ["내 줄"], "0.10.10": ["main 줄"], "0.10.9": ["옛 줄"]}


def test_기존_판_블록을_내가_고쳤으면_거절하고_아무것도_안_바꾼다(tmp_path):
    repo = conflict(tmp_path, "rebase", with_wn=True, mine_wn_edits_base=True)
    before = read(repo, PLUGIN_JSON)
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == REFUSED and "0.10.9" in out["reason"]
    assert read(repo, PLUGIN_JSON) == before and "<<<<" in before


def test_이_브랜치가_더한_새_소식_조각의_판을_새_판으로_바꾼다(tmp_path):
    repo = conflict(tmp_path, "rebase", fragment=True)
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == MERGED and out["fragments"] == [FRAG + "1074.json"]
    assert json.loads(read(repo, FRAG + "1074.json")) == {"version": "0.10.13", "lines": ["조각 줄"]}
    assert git(repo, "diff", "--cached", "--name-only").stdout.count("1074.json") == 1  # git add 까지 했다


def test_다른_파일_충돌이_섞이면_거절한다(tmp_path):
    repo = conflict(tmp_path, "rebase", extra=True)
    assert set(git(repo, "diff", "--name-only", "--diff-filter=U").stdout.split()) == {PLUGIN_JSON, "other.txt"}
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == REFUSED and "other.txt" in out["reason"]
    assert "<<<<" in read(repo, PLUGIN_JSON)


def test_plugin_json_충돌이_version_줄만이_아니면_거절한다(tmp_path):
    repo = conflict(tmp_path, "rebase")
    # 충돌 덩어리 안에 name 줄을 끼워 넣는다
    text = read(repo, PLUGIN_JSON).replace("=======\n", '  "name": "x",\n=======\n', 1)
    write(repo, PLUGIN_JSON, text)
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == REFUSED and "version 줄만이 아니다" in out["reason"]


def test_gh_를_못_읽으면_검사_불능이고_아무것도_안_바꾼다(tmp_path):
    repo = conflict(tmp_path, "rebase")
    before = read(repo, PLUGIN_JSON)
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS, fail=True))
    assert out["status"] == CANNOT_CHECK and "열린 PR" in out["reason"]
    assert read(repo, PLUGIN_JSON) == before


def test_열린_PR_한_건의_판을_못_읽어도_검사_불능이다(tmp_path):
    class Half(FakeGh):
        def get_json_or_none_404(self, path):
            return None if "sha202" in path else super().get_json_or_none_404(path)

    repo = conflict(tmp_path, "rebase")
    out = rebase_version(repo, "rebase", client=Half(OTHERS))
    assert out["status"] == CANNOT_CHECK and "#202" in out["reason"]


def test_origin_기준_브랜치가_없으면_검사_불능(tmp_path):
    repo = conflict(tmp_path, "rebase")
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == CANNOT_CHECK


def test_충돌이_없거나_plugin_json_이_충돌_목록에_없으면_거절한다(tmp_path):
    repo = conflict(tmp_path, "rebase", with_wn=True)
    git(repo, "checkout", "-q", "--ours", "--", PLUGIN_JSON)
    git(repo, "add", PLUGIN_JSON)
    out = rebase_version(repo, "rebase", client=FakeGh(OTHERS))
    assert out["status"] == REFUSED


def test_plugin_json_이_없는_저장소는_해당_없음(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    out = rebase_version(repo, "rebase", client=FakeGh([]))
    assert out["status"] == NOT_APPLICABLE


def test_모드가_이상하면_검사_불능(tmp_path):
    assert rebase_version(tmp_path, "squash", client=FakeGh([]))["status"] == CANNOT_CHECK


def test_cli_종료코드와_json(tmp_path, capsys, monkeypatch):
    import checker.version_rebase as mod

    repo = conflict(tmp_path, "rebase")
    monkeypatch.setattr(mod, "_RootGh", lambda root: FakeGh(OTHERS))
    assert main(["--mode", "rebase", "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.10.13"
    assert main(["--mode", "rebase", "--root", str(repo)]) == 1  # 이제 충돌이 없다
    assert json.loads(capsys.readouterr().out)["status"] == REFUSED
    monkeypatch.setattr(mod, "_RootGh", lambda root: FakeGh([], fail=True))
    (tmp_path / "b").mkdir()
    repo2 = conflict(tmp_path / "b", "rebase")
    assert main(["--mode", "rebase", "--root", str(repo2)]) == 2


def test_덩어리_밖에_version_줄이_또_있으면_고친_결과를_내지_않는다():
    """웹 충돌 해결이 version 줄을 둘 남긴 일(#1075). 고친 결과에 같은 키가 두 번이면 검사 불능."""
    raw = '{\n<<<<<<< a\n  "version": "0.10.1",\n=======\n  "version": "0.10.2",\n>>>>>>> b\n  "version": "0.10.2",\n  "name": "x"\n}\n'
    with pytest.raises(_Cannot, match="두 번"):
        _resolve_plugin_json(raw.encode("utf-8"), "0.10.3")
