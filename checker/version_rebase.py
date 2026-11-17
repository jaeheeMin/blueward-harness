"""판 번호만 겹친 리베이스·병합 충돌을 자동으로 푼다(#1074).

배포되는 파일을 바꾸는 PR 은 모두 `plugins/harness/.claude-plugin/plugin.json` 의 version 을 올리므로, 하나가 병합되면 남은
열린 PR 이 같은 줄에서 충돌한다. deliver(rebase)·sync(rebase·merge)에서 충돌이 났을 때 충돌 파일이 plugin.json(과 있으면
`console/whats_new.json`)뿐이고 plugin.json 의 충돌이 version 줄뿐이면 판을 다시 매겨 푼다.

    python -m checker.version_rebase --mode merge|rebase --root . [--base main] [--branch 이름]

새 판 = max(기준 브랜치 판, 다른 열린 PR head 판들) 의 patch+1. 기준 브랜치 판은 `origin/{base}` 에서 읽고(여러 커밋을 되풀이해
리베이스해도 같은 값이 나온다), 다른 열린 PR 은 gh 로 읽는다(`--branch`, 없으면 지금 진행 중인 브랜치의 PR 은 뺀다).
- plugin.json: 충돌 덩어리를 새 판 줄로 바꾼다(들여쓰기·쉼표·줄바꿈 그대로). 결과가 JSON 이고 version 이 새 판이어야 한다.
- whats_new.json: 양쪽 판 블록을 모두 살리고, 내 쪽이 새로 더한 블록을 새 판 키로 바꿔 맨 위에 둔다(stage 로 읽어 다시 쓴다).
  base 에 있던 블록을 내가 고쳤거나 지웠으면 거절한다.
- `whats_new.d/*.json` 조각: 이 브랜치가 기준 브랜치에 더한 조각의 version 을 새 판으로 바꾼다.

결과(stdout JSON, 종료코드): `merged`(0, 작업 폴더에 쓰고 `git add` 까지 함) / `refused`(1, 판 충돌만이 아님 — 아무것도 안 바꿈) /
`not_applicable`(1, plugin.json 이 없는 저장소) / `cannot_check`(2, git·gh 를 못 읽음 — 통과가 아니다. 아무것도 안 바꿈).
커밋·`rebase --continue` 는 호출하는 쪽이 한다. 새 판은 열린 PR 이 그 사이 더 올리면 다시 겹칠 수 있다(PR 검사가 잡는다).

방식마다 stage 의 뜻이 반대다. merge: ours(:2)=내 쪽, theirs(:3)=main. rebase: ours(:2)=main, theirs(:3)=내 쪽.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

from checker.plugin_version import PLUGIN_JSON, parse_version
from checker.ssot_approval import GhClient, GhError

MERGED = "merged"
REFUSED = "refused"
CANNOT_CHECK = "cannot_check"
NOT_APPLICABLE = "not_applicable"

WHATS_NEW = "plugins/harness/console/whats_new.json"
WHATS_NEW_DIR = "plugins/harness/console/whats_new.d/"
PR_LIMIT = 100

_VERSION_LINE = re.compile(r'^(\s*"version"\s*:\s*")([^"]*)(".*)$')


class _Refuse(Exception):
    pass


class _Cannot(Exception):
    pass


class _Na(Exception):
    pass


class _RootGh(GhClient):
    """저장소 폴더에서 gh 를 부른다(`gh repo view` 가 그 폴더의 원격을 보도록)."""

    def __init__(self, root: Path):
        self.root = root

    def run(self, args: list[str]) -> str:
        try:
            done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=str(self.root))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GhError(f"gh {' '.join(args)} 실행에 실패했다: {exc}") from exc
        if done.returncode != 0:
            from checker.ssot_approval import _http_status

            raise GhError(f"gh {' '.join(args)} 가 종료코드 {done.returncode} 로 실패했다: {done.stderr.strip()}", status=_http_status(done.stderr))
        return done.stdout


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except OSError as exc:
        raise _Cannot(f"git 을 실행하지 못했다: {exc}") from exc
    if check and done.returncode != 0:
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise _Cannot(f"git {' '.join(args)} 실패: {err[0] if err else done.returncode}")
    return done


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _Cannot(f"{what} 이 UTF-8 이 아니다: {exc}") from exc


def _next_patch(version: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in (*version[:-1], version[-1] + 1))


def _version_of(text: str, what: str) -> str:
    try:
        version = json.loads(text)["version"]
        parse_version(version)
    except (ValueError, KeyError, TypeError) as exc:
        raise _Cannot(f"{what} 의 version 을 읽지 못했다: {exc}") from exc
    return version


def _branch_name(root: Path, branch: str | None) -> str | None:
    """이 브랜치 PR 을 열린 PR 에서 빼기 위한 이름. 못 알아내면 None(빼지 않아도 판이 더 커질 뿐이라 안전하다)."""
    if branch:
        return branch
    for sub in ("rebase-merge", "rebase-apply"):
        done = _git(root, "rev-parse", "--git-path", f"{sub}/head-name", check=False)
        if done.returncode != 0:
            continue
        p = Path(done.stdout.decode("utf-8", "replace").strip())
        p = p if p.is_absolute() else root / p
        if p.is_file():
            name = p.read_text(encoding="utf-8").strip()
            return name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
    done = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    name = done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else ""
    return name or None


def _open_pr_versions(client: GhClient, base: str, branch: str | None) -> list[str]:
    """기준 브랜치로 열린 다른 PR 들의 head plugin.json version. 하나라도 못 읽으면 _Cannot."""
    try:
        repo = client.run(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()
        if not repo:
            raise GhError("현재 폴더의 GitHub 저장소를 알아내지 못했다")
        raw = client.run(["pr", "list", "--repo", repo, "--state", "open", "--base", base, "--limit", str(PR_LIMIT),
                          "--json", "number,headRefName,headRefOid"])
        prs = json.loads(raw or "[]")
        if not isinstance(prs, list):
            raise GhError("gh pr list 의 출력이 목록이 아니다")
        if len(prs) >= PR_LIMIT:
            raise GhError(f"열린 PR 이 {PR_LIMIT}개 이상이라 다 읽지 못한다")
        out = []
        for pr in prs:
            if branch and pr.get("headRefName") == branch:
                continue
            sha = pr["headRefOid"]
            data = client.get_json_or_none_404(f"repos/{repo}/contents/{PLUGIN_JSON}?ref={sha}")
            if not data:
                raise GhError(f"PR #{pr['number']} head({sha[:7]}) 에서 {PLUGIN_JSON} 를 찾지 못했다")
            text = base64.b64decode(data.get("content", "") or "").decode("utf-8")
            out.append(_version_of(text, f"PR #{pr['number']} head({sha[:7]}) 의 {PLUGIN_JSON}"))
        return out
    except (GhError, ValueError, KeyError, TypeError) as exc:
        raise _Cannot(f"다른 열린 PR 의 판을 읽지 못했다: {exc}") from exc


def _resolve_plugin_json(raw: bytes, new_version: str) -> bytes:
    """충돌 표시가 든 plugin.json 의 덩어리를 새 판 줄로 바꾼다. 덩어리 안에 version 줄 말고 다른 줄이 있으면 _Refuse."""
    text = _decode(raw, "plugin.json")
    out: list[str] = []
    hunk: list[str] | None = None
    section = ""
    count = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if hunk is None:
            if body.startswith("<<<<<<<"):
                hunk, section = [], "ours"
            elif body.startswith(("|||||||", ">>>>>>>")) or body == "=======":
                raise _Refuse("plugin.json 의 충돌 표시가 예상한 모양이 아니다")
            else:
                out.append(line)
            continue
        if body.startswith("|||||||"):
            section = "base"
        elif body == "=======":
            section = "theirs"
        elif body.startswith(">>>>>>>"):
            if not hunk:
                raise _Refuse("plugin.json 의 충돌 덩어리에 줄이 없다")
            m = _VERSION_LINE.match(hunk[0].rstrip("\r\n"))
            eol = line[len(body):] or hunk[0][len(hunk[0].rstrip("\r\n")):]
            out.append(f"{m.group(1)}{new_version}{m.group(3)}{eol}")
            hunk, count = None, count + 1
        else:
            if not _VERSION_LINE.match(body):
                raise _Refuse(f"plugin.json 충돌이 version 줄만이 아니다: {body.strip()[:60]}")
            if section != "base":
                hunk.append(line)
    if hunk is not None:
        raise _Refuse("plugin.json 의 충돌 표시가 닫히지 않았다")
    if count == 0:
        raise _Refuse("plugin.json 에 충돌 덩어리가 없다")
    result = "".join(out)
    if _version_of(result, "고친 plugin.json") != new_version:
        raise _Cannot("고친 plugin.json 의 version 이 새 판과 다르다")
    return result.encode("utf-8")


def _json_stage(root: Path, n: int, path: str, what: str) -> tuple[dict, str]:
    text = _decode(_git(root, "show", f":{n}:{path}").stdout, what)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _Cannot(f"{what} 이 JSON 이 아니다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
        raise _Refuse(f"{what} 의 모양이 예상과 다르다")
    return data, text


def _resolve_whats_new(root: Path, main_n: int, mine_n: int, new_version: str) -> bytes:
    """양쪽 판 블록을 살리고, 내가 새로 더한 블록은 새 판 키 맨 위로. base 블록을 내가 고쳤으면 _Refuse."""
    base, _ = _json_stage(root, 1, WHATS_NEW, "whats_new.json base")
    main, main_text = _json_stage(root, main_n, WHATS_NEW, "whats_new.json main 판")
    mine, mine_text = _json_stage(root, mine_n, WHATS_NEW, "whats_new.json 내 판")
    bv, mv = base["versions"], mine["versions"]
    changed = [k for k in bv if mv.get(k) != bv[k]]
    if changed:
        raise _Refuse(f"whats_new.json 에서 이 브랜치가 기존 판 블록을 고치거나 지웠다: {', '.join(changed)}")
    lines: list = []
    for k, v in mv.items():
        if k not in bv:
            if not isinstance(v, list):
                raise _Refuse(f"whats_new.json 의 {k} 블록이 목록이 아니다")
            lines += v
    result = {k: v for k, v in main.items() if k != "versions"}
    for k, v in mine.items():  # `_comment` 같은 다른 키: 내가 고친 것만 이긴다. 양쪽이 다르게 고쳤으면 거절.
        if k == "versions":
            continue
        if v != base.get(k):
            if k in main and main[k] != base.get(k) and main[k] != v:
                raise _Refuse(f"whats_new.json 의 `{k}` 를 양쪽이 다르게 고쳤다")
            result[k] = v
    versions = dict(main["versions"])
    if lines:
        versions = {new_version: list(versions.pop(new_version, [])) + lines, **versions}
    result["versions"] = versions
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if "\r\n" in mine_text or "\r\n" in main_text:
        text = text.replace("\n", "\r\n")
        tail = "\r\n"
    else:
        tail = "\n"
    if main_text.endswith(("\n", "\r\n")):
        text += tail
    return text.encode("utf-8")


def _update_fragments(root: Path, base_ref: str, new_version: str) -> list[str]:
    """기준 브랜치에 없던(이 브랜치가 더한) 새 소식 조각의 version 을 새 판으로 바꿔 git add. 바꾼 경로 목록."""
    names = _git(root, "diff", "--name-only", "--diff-filter=A", "-z", base_ref, "--", WHATS_NEW_DIR).stdout
    changed = []
    for rel in (n for n in names.decode("utf-8", "replace").split("\0") if n):
        if not rel.endswith(".json"):
            continue
        p = root / rel
        if not p.is_file():
            continue
        raw = p.read_bytes()
        text = _decode(raw, rel)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise _Refuse(f"{rel} 가 JSON 이 아니다: {exc}") from exc
        if not isinstance(data, dict):
            raise _Refuse(f"{rel} 의 모양이 예상과 다르다")
        if data.get("version") == new_version:
            continue
        data["version"] = new_version
        out = json.dumps(data, ensure_ascii=False, indent=2)
        if "\r\n" in text:
            out = out.replace("\n", "\r\n")
        if text.endswith("\n"):
            out += "\r\n" if "\r\n" in text else "\n"
        p.write_bytes(out.encode("utf-8"))
        _git(root, "add", "--", rel)
        changed.append(rel)
    return changed


def rebase_version(root: Path, mode: str, base: str = "main", branch: str | None = None, client: GhClient | None = None) -> dict:
    """충돌 중인 저장소 `root` 에서 판 충돌을 풀어 새 판으로 다시 매긴다. `client` 는 시험이 가짜 gh 를 넣는 자리."""
    try:
        if mode not in ("merge", "rebase"):
            raise _Cannot(f"모드가 merge 도 rebase 도 아니다: {mode}")
        if not (root / PLUGIN_JSON).exists() and not _git(root, "ls-files", "-u", "--", PLUGIN_JSON).stdout.strip():
            raise _Na(f"{PLUGIN_JSON} 가 없는 저장소다")
        unmerged = _git(root, "diff", "--name-only", "--diff-filter=U", "-z").stdout.decode("utf-8", "replace")
        files = [f for f in unmerged.split("\0") if f]
        if PLUGIN_JSON not in files or not set(files) <= {PLUGIN_JSON, WHATS_NEW}:
            raise _Refuse(f"충돌 파일이 {PLUGIN_JSON}(과 whats_new.json)만이 아니다: {', '.join(files) or '없음'}")
        for path in files:
            stages = {int(l.split()[2]) for l in _git(root, "ls-files", "-u", "--", path).stdout.decode("utf-8", "replace").splitlines()}
            if stages != {1, 2, 3}:
                raise _Refuse(f"{path} 가 base·양쪽 판이 다 있는 수정 충돌이 아니다(추가·삭제 충돌)")
        base_ref = f"origin/{base}"
        main_version = _version_of(_decode(_git(root, "show", f"{base_ref}:{PLUGIN_JSON}").stdout, "기준 브랜치 plugin.json"), f"{base_ref} 의 {PLUGIN_JSON}")
        others = _open_pr_versions(client or _RootGh(root), base, _branch_name(root, branch))
        top = max((main_version, *others), key=parse_version)
        new_version = _next_patch(parse_version(top))
        # 충돌 파일은 모두 고칠 수 있다고 확인된 뒤에만 쓴다(중간에 거절하면 아무것도 안 바뀌게 먼저 다 만든다).
        main_n, mine_n = (3, 2) if mode == "merge" else (2, 3)
        plugin_bytes = _resolve_plugin_json((root / PLUGIN_JSON).read_bytes(), new_version)
        wn_bytes = _resolve_whats_new(root, main_n, mine_n, new_version) if WHATS_NEW in files else None
        (root / PLUGIN_JSON).write_bytes(plugin_bytes)
        _git(root, "add", "--", PLUGIN_JSON)
        if wn_bytes is not None:
            (root / WHATS_NEW).write_bytes(wn_bytes)
            _git(root, "add", "--", WHATS_NEW)
        fragments = _update_fragments(root, base_ref, new_version)
        return {"status": MERGED, "version": new_version, "files": files, "fragments": fragments}
    except _Refuse as exc:
        return {"status": REFUSED, "reason": str(exc)}
    except _Na as exc:
        return {"status": NOT_APPLICABLE, "reason": str(exc)}
    except _Cannot as exc:
        return {"status": CANNOT_CHECK, "reason": str(exc)}
    except OSError as exc:
        return {"status": CANNOT_CHECK, "reason": f"파일을 읽거나 쓰지 못했다: {exc}"}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="checker.version_rebase")
    ap.add_argument("--mode", required=True, choices=["merge", "rebase"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--base", default="main")
    ap.add_argument("--branch")
    args = ap.parse_args(argv)
    result = rebase_version(Path(args.root), args.mode, args.base, args.branch)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return {MERGED: 0, REFUSED: 1, NOT_APPLICABLE: 1}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
