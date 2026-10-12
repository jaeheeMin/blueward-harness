"""검사 엔진을 어느 판으로 받을지 정하는 한 곳(#149).

플러그인 판(plugin.json 의 version)과 같은 이름의 태그 `v{version}` 으로 엔진을 받는다.
`@main` 이면 main 에 방금 들어온 엔진 변경이 플러그인 갱신 없이 모든 팀원 PC 훅에 즉시
퍼진다. 태그로 고정하면 플러그인과 엔진이 한 짝으로 움직인다. 태그는 main 에 version 이
바뀌어 들어올 때 `.github/workflows/release-tag.yml` 이 붙인다.

훅 세 곳(`pre_write_guard.py`, `mcp_source_guard.py`, `pre-bash-git-guard.sh`)과 스킬이
모두 이 값을 쓴다. py 훅은 import 하고, sh 와 스킬은 이 파일을 실행해 stdout 을 받는다.

- `DOC_GUARD_ENGINE` 환경변수가 있으면 그것이 우선이다(로컬 체크아웃 경로로 개발·테스트).
- plugin.json 을 읽지 못하거나 version 이 이상하면 `@main` 으로 조용히 넘어가지 않고
  실패한다. 호출하는 쪽이 검사 불능으로 처리한다(CLAUDE.md 원칙 7).

stdlib 만 쓴다 — 훅은 프로젝트 의존성 없이 `uv run --no-project` 로 돈다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_URL = "git+https://github.com/jaeheeMin/blueward-harness"

# 이 파일은 `hooks/` 에 있고 plugin.json 은 한 칸 위 `.claude-plugin/` 에 있다.
PLUGIN_JSON = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"

_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


class EngineSpecError(Exception):
    """엔진 판을 정하지 못했다. 통과시키지 말고 검사 불능으로 처리한다."""


def plugin_version(plugin_json: Path | None = None) -> str:
    plugin_json = plugin_json or PLUGIN_JSON
    try:
        version = json.loads(plugin_json.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EngineSpecError(f"{plugin_json} 에서 version 을 읽지 못했다({exc})") from exc
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise EngineSpecError(f"{plugin_json} 의 version 이 `0.10.17` 같은 모양이 아니다: {version!r}")
    return version


def tag_spec(plugin_json: Path | None = None) -> str:
    return f"{REPO_URL}@v{plugin_version(plugin_json)}"


def engine_spec(plugin_json: Path | None = None) -> str:
    """`uvx --from` 에 넘길 값. 환경변수 우선, 없으면 plugin.json version 의 태그."""
    return os.environ.get("DOC_GUARD_ENGINE") or tag_spec(plugin_json)


def tag_hint(spec: str) -> str:
    """엔진을 못 받았을 때 원인 후보를 알려 주는 문장. 태그 고정이 아니면 빈 문자열."""
    match = re.search(r"@(v[0-9][0-9.]*)$", spec)
    if not match:
        return ""
    return (
        f"엔진 판 {match.group(1)} 을 받을 수 없을 수 있습니다(저장소에 그 태그가 아직 없을 수 있음: "
        "플러그인 새 판이 병합된 직후에는 태그가 붙기까지 잠시 걸립니다). "
    )


def main() -> int:
    # Windows 콘솔 기본 코드페이지(cp949)로 사유가 나가면 받는 쪽(sh 훅의 거부 문구)에서 깨진다.
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.stdout.write(engine_spec() + "\n")
    except EngineSpecError as exc:
        sys.stderr.write(f"검사 엔진 판을 정하지 못했다: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
