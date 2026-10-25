"""`.claude/settings.json` 의 enabledPlugins 에서 harness 가 빠지거나 꺼지는 변경을 막는다(#471).

`claude plugin uninstall` 이 묻지 않고 공유 `.claude/settings.json` 의 enabledPlugins 를 비운 일이 있다.
그 변경이 커밋·푸시되면 팀원 전체의 harness 가 꺼진다. `pre-bash-git-guard.sh` 가 git commit·push 를
가로챌 때 이 모듈을 불러 판정한다. 파일은 고치지 않는다.

사용법: python enabled_plugin_guard.py staged|push
- staged: HEAD 의 판과 index(staged) 의 판을 비교한다.
- push:   origin 기준(upstream, 없으면 origin/main) 과의 merge-base 판과 HEAD 의 판을 비교한다.

종료 코드(메시지는 stdout):
- 0  통과
- 1  거절 — 원래 켜져 있던 `harness@blueward-harness: true` 가 빠지거나 true 가 아니게 됐다
- 2  검사 불능 — JSON 을 못 읽었거나 git 이 실패했다(통과로 뭉개지 않는다)

"원래" 에 harness 항목이 없으면(파일이 없거나 항목이 없거나 이미 꺼져 있었으면) 통과한다.
키 순서·공백만 바뀐 것은 값이 같으므로 통과한다.
"""
from __future__ import annotations

import json
import subprocess
import sys

SETTINGS = ".claude/settings.json"
PLUGIN_ID = "harness@blueward-harness"
ABSENT = "absent"
UNREADABLE = "unreadable"


class GitFailed(Exception):
    pass


_TOP: list[str] = []


def _top() -> str:
    """저장소 루트. 하위 폴더에서 불려도 루트 기준 경로로 보려고 모든 git 호출을 여기서 실행한다."""
    if not _TOP:
        try:
            done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitFailed(f"저장소 루트를 찾지 못했다: {exc}") from exc
        if done.returncode != 0 or not done.stdout.strip():
            raise GitFailed("저장소 루트를 찾지 못했다")
        _TOP.append(done.stdout.decode("utf-8", "replace").strip())
    return _TOP[0]


def _git(*args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(["git", "-C", _top(), *args], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitFailed(f"git {args[0]} 실행 실패: {exc}") from exc
    if done.returncode not in ok:
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitFailed(f"git {' '.join(args[:2])} 실패(종료코드 {done.returncode}) {err[-1] if err else ''}".strip())
    return done


def _parse(raw: bytes):
    """파싱한 settings 객체, 못 읽으면 UNREADABLE."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return UNREADABLE
    return data if isinstance(data, dict) else UNREADABLE


def _at_ref(ref: str):
    """ref 커밋의 settings. 파일이 없으면 ABSENT."""
    tree = _git("ls-tree", ref, "--", SETTINGS).stdout
    if not tree.strip():
        return ABSENT
    return _parse(_git("show", f"{ref}:{SETTINGS}").stdout)


def _at_index():
    staged = _git("ls-files", "-s", "--", SETTINGS).stdout
    if not staged.strip():
        return ABSENT
    return _parse(_git("show", f":{SETTINGS}").stdout)


def _head_or_absent():
    done = _git("rev-parse", "--verify", "-q", "HEAD", ok=(0, 1))
    return ABSENT if done.returncode == 1 else _at_ref("HEAD")


def is_enabled(settings) -> bool:
    plugins = settings.get("enabledPlugins") if isinstance(settings, dict) else None
    return isinstance(plugins, dict) and plugins.get(PLUGIN_ID) is True


def _base_ref() -> tuple[str | None, str]:
    """(비교 기준 ref, 못 찾은 사유). 기준이 필요 없으면 (None, "")."""
    for ref in ("@{u}", "origin/main", "origin/HEAD"):
        done = _git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", ok=(0, 1))
        if done.returncode == 0:
            return ref, ""
    remotes = _git("for-each-ref", "--count=1", "refs/remotes").stdout.strip()
    if not remotes:
        return None, ""  # 받아 둔 원격 브랜치가 없으면 견줄 "원래" 가 없다
    return None, "upstream 도 origin/main 도 찾지 못했다"


def _verdict(before, after, where: str, base_label: str) -> tuple[int, str]:
    if before == UNREADABLE:
        if is_enabled(after):
            return 0, ""
        return 2, f"검사 불능: {base_label} 의 {SETTINGS} 를 JSON 으로 읽지 못해 harness 가 원래 켜져 있었는지 알 수 없습니다. 검사하지 못한 상태로 통과시키지 않습니다. 다음: 사람이 그 파일의 JSON 문법을 확인하십시오."
    if not is_enabled(before):
        return 0, ""  # 원래 없거나 이미 꺼져 있었다
    if after == UNREADABLE:
        return 2, f"검사 불능: {where}의 {SETTINGS} 를 JSON 으로 읽지 못해 harness 가 켜져 있는지 확인할 수 없습니다. 검사하지 못한 상태로 통과시키지 않습니다. 다음: JSON 문법을 고치거나 git restore --staged --worktree {SETTINGS} 로 되돌린 뒤 다시 시도하십시오."
    if is_enabled(after):
        return 0, ""
    return 1, ""


def check_staged() -> tuple[int, str]:
    try:
        before, after = _head_or_absent(), _at_index()
    except GitFailed as exc:
        return 2, f"검사 불능: {SETTINGS} 의 변경을 git 으로 읽지 못했습니다({exc}). 검사하지 못한 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오."
    code, msg = _verdict(before, after, "커밋에 들어갈 변경", "HEAD")
    if code == 1:
        msg = (
            f"{SETTINGS} 의 enabledPlugins 에서 {PLUGIN_ID} 가 빠지거나 꺼지는 변경이 커밋에 들어갑니다. "
            "이 변경이 올라가면 팀원 전체의 harness 가 꺼집니다(claude plugin uninstall 이 묻지 않고 이 항목을 비우는 일이 있었습니다, #471). "
            f"다음: git restore --staged --worktree {SETTINGS} 로 되돌린 뒤 다시 커밋하십시오. "
            "harness 를 끄는 것이 진짜 의도라면 사람이 정할 일이므로 사용자에게 먼저 알리십시오."
        )
    return code, msg


def check_push() -> tuple[int, str]:
    try:
        base, why = _base_ref()
        if base is None:
            if why:
                return 2, f"검사 불능: 푸시 범위의 기준을 정하지 못했습니다({why}). {SETTINGS} 에서 harness 가 빠졌는지 확인할 수 없어 통과시키지 않습니다. 다음: git fetch origin 을 실행한 뒤 같은 명령을 다시 시도하십시오."
            return 0, ""
        merge_base = _git("merge-base", base, "HEAD").stdout.decode("utf-8", "replace").strip()
        before, after = _at_ref(merge_base), _at_ref("HEAD")
    except GitFailed as exc:
        return 2, f"검사 불능: 푸시 범위의 {SETTINGS} 변경을 git 으로 읽지 못했습니다({exc}). 검사하지 못한 상태로 통과시키지 않습니다. 다음: git fetch origin 뒤 같은 명령을 다시 시도하십시오."
    code, msg = _verdict(before, after, "푸시할 커밋", f"{base} 와의 공통 조상")
    if code == 1:
        msg = (
            f"푸시할 커밋에서 {SETTINGS} 의 enabledPlugins 의 {PLUGIN_ID} 가 빠지거나 꺼집니다. "
            "이대로 올리면 팀원 전체의 harness 가 꺼집니다(#471). "
            f"다음: git restore --source={base} --staged --worktree {SETTINGS} 로 원래대로 되돌려 새 커밋을 만든 뒤 다시 푸시하십시오. "
            "harness 를 끄는 것이 진짜 의도라면 사람이 정할 일이므로 사용자에게 먼저 알리십시오."
        )
    return code, msg


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("staged", "push"):
        sys.stdout.write("사용법: enabled_plugin_guard.py staged|push\n")
        return 2
    code, msg = check_staged() if argv[1] == "staged" else check_push()
    if msg:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(msg + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
