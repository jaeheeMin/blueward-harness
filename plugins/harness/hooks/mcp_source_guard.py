"""MCP ADT 도구(`setObjectSource`)로 SAP 오브젝트에 바로 쓰는 경로에도 공통 개발
규칙(CR-001, CR-002)을 건다(#60).

Claude 가 ADT MCP 서버(예: npm `mcp-abap-abap-adt-api`)의 `setObjectSource` 로
오브젝트에 바로 쓰면 Write/Edit 도구를 거치지 않으므로 `pre_write_guard.py` 가 이
경로를 보지 못한다. 이 훅은 `hooks.json` 의 `PreToolUse` 매처(`mcp__.*__setObjectSource`)
로 그 호출을 가로채, 같은 `checker.code_rules` 엔진으로 검사한다. 매처가 서버
이름에 매이지 않으므로 이 스크립트도 어떤 MCP 서버가 불렀는지 신경 쓰지 않는다.

**입력.** MCP 도구의 `tool_input` 은 `objectSourceUrl`(ADT 오브젝트 경로)과
`source`(코드 본문)를 담는다 — `mcp-abap-abap-adt-api` 의
`dist/handlers/ObjectSourceHandlers.js` 의 `inputSchema` 로 확인했다(이슈 #60).

**언어 판별.** `objectSourceUrl` 은 파일 확장자가 없는 ADT REST 경로다
(`.../source/main` 처럼 끝난다). `checker.code_rules` 는 파일 확장자로 언어를
정하므로, 이 경로가 어떤 언어인지는 URL 패턴으로 먼저 판별해야 한다. 그 매핑은
`mcp_object_source_map.json` 데이터로 둔다(CLAUDE.md 원칙 2) — 코드에 조건문을
늘어놓지 않는다. 목록에 없는 패턴은 "판별 못 함" 으로 보고 통과시키지 않는다
(CLAUDE.md 원칙 7) — 잘못 짚은 매핑으로 아무것도 안 보면서 통과하는 것보다, 새
패턴이 나올 때마다 검사 불능으로 드러나 매핑을 넓히게 하는 편이 안전하다.

**엔진.** 판정은 `pre_write_guard.py` 의 코드 검사 경로와 같은 `checker.code_rules`
를 `uvx` 로 부른다(엔진 import 금지, #12 사정과 동일). 이 파일도 `pre_write_guard.py`
와 같은 이유로 stdlib 만 쓴다 — 훅은 `uv run --no-project` 로 실행되어 프로젝트
의존성(pyyaml 등)이 없다. 그래서 URL 매핑도 YAML 이 아니라 표준 라이브러리
`json` 으로 읽을 수 있는 JSON 으로 둔다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

# 검사 엔진을 받아 오는 기본 위치. `pre_write_guard.py` 와 GitHub Actions 재사용
# 워크플로의 기본 `engine-ref` (main) 와 맞춘다.
DEFAULT_ENGINE_SPEC = "git+https://github.com/jaeheeMin/blueward-harness@main"

# 엔진을 실행할 시간. `pre_write_guard.py` 와 같은 이유로 넉넉히 둔다.
ENGINE_TIMEOUT_SECONDS = 110

# 이 매처와 짝이 맞는지 스스로도 한 번 더 확인한다(hooks.json 이 이미 걸러 주지만,
# 이 스크립트가 다른 매처에 잘못 물릴 경우에도 스스로를 지킨다).
_TOOL_NAME_RE = re.compile(r"^mcp__.*__setObjectSource$")

_URL_MAP_PATH = Path(__file__).with_name("mcp_object_source_map.json")

ALLOW = 0


def allow() -> None:
    sys.exit(ALLOW)


def deny(reason: str) -> None:
    """쓰기를 막고 사유를 사람과 Claude 에게 보여준다.

    입출력 인코딩은 `main()` 이 시작하자마자 `_force_utf8_io()` 로 한곳에서 못
    박는다(`pre_write_guard.py` 의 #14 대응과 같은 이유).
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def engine_spec() -> str:
    """검사 엔진을 어디서 받을지 정한다. `pre_write_guard.py` 의 같은 함수와 같다."""
    return os.environ.get("DOC_GUARD_ENGINE") or DEFAULT_ENGINE_SPEC


def _load_url_patterns() -> list[tuple[re.Pattern[str], str]]:
    raw = json.loads(_URL_MAP_PATH.read_text(encoding="utf-8"))
    return [
        (re.compile(item["regex"], re.IGNORECASE), item["suffix"])
        for item in raw.get("patterns", [])
    ]


def suffix_for_url(url: str) -> str | None:
    """`objectSourceUrl` 을 알려진 언어 확장자(`.abap`, `.cds`)로 바꾼다.

    쿼리스트링을 떼고 URL 디코딩을 한 경로에 패턴을 검색한다 — 인코딩된 경로나
    끝에 `?version=active` 같은 것이 붙어도 판별이 흔들리지 않게 하기 위해서다.
    아는 패턴이 없으면 None(=판별 못 함)이다.
    """
    path = unquote(urlsplit(url).path or url)
    for pattern, suffix in _load_url_patterns():
        if pattern.search(path):
            return suffix
    return None


def format_code_violations(report: dict) -> str:
    """`checker.code_rules` 의 리포트를 사람이 읽을 안내문으로 바꾼다.

    `pre_write_guard.py::format_code_violations` 와 같다 — `harness:allow` 로
    예외 처리된 발견은 보여주지 않는다.
    """
    lines = []
    for entry in report.get("files", []):
        if entry.get("status") != "violation":
            continue
        for f in entry.get("findings", []):
            if f.get("allowed"):
                continue
            lines.append(
                f"  - [{f.get('rule')}] {entry.get('file')}:{f.get('line')}:{f.get('col')} {f.get('message')}"
            )
            fix = f.get("fix")
            if fix:
                lines.append(f"      고치기: {fix}")
    return "\n".join(lines)


def _check_code(url: str, content: str, suffix: str) -> None:
    """공통 개발 규칙(CR-001, CR-002)을 MCP 로 쓰려는 코드에 적용한다.

    `pre_write_guard.py::_check_code` 와 같은 구조다. 다른 점은 검사 대상이 디스크
    파일이 아니라 MCP 호출의 `source` 문자열이라, 임시 파일 이름을 원래 경로가
    아니라 판별한 언어의 확장자로 직접 짓는다는 것뿐이다. `allow()`/`deny()` 는
    `sys.exit` 로 끝나므로 이 함수는 값을 돌려주지 않는다.
    """
    with tempfile.TemporaryDirectory(prefix="doc-guard-mcp-") as tmp:
        staged = Path(tmp) / f"mcp_source{suffix}"
        staged.write_text(content, encoding="utf-8")

        cmd = [
            "uvx", "--from", engine_spec(), "python", "-m", "checker.code_rules",
            "--json", str(staged),
        ]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            done = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", env=env,
                timeout=ENGINE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            deny(
                "harness 가 공통 개발 규칙 검사 엔진을 받거나 실행하지 못해 이 MCP 쓰기를 "
                "확인할 수 없었습니다.\n"
                f"objectSourceUrl: {url}\n"
                f"사유: {exc}\n\n"
                "확인할 것: uv 가 설치되어 있는가, 네트워크가 되는가. 로컬에서 개발·테스트 "
                "중이라면 DOC_GUARD_ENGINE 환경변수로 엔진 경로를 지정할 수 있습니다.\n"
                "확인되지 않는 상태로 통과시키지 않습니다."
            )

    if done.returncode == 0:
        allow()

    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        deny(
            "공통 개발 규칙 검사기의 출력을 해석하지 못했습니다.\n"
            f"objectSourceUrl: {url}\n"
            f"{(done.stderr or done.stdout or '').strip()[:500]}\n\n"
            "확인되지 않는 상태로 통과시키지 않습니다."
        )

    # 리포트의 file 은 임시 스테이징 경로다. 사람에게는 원래 objectSourceUrl 을 보여준다.
    for entry in report.get("files", []):
        entry["file"] = url

    if done.returncode == 1:
        deny(
            "harness: 이 MCP 쓰기(setObjectSource)가 공통 개발 규칙을 어겼습니다"
            "(conventions/common.md).\n"
            f"objectSourceUrl: {url}\n\n"
            + format_code_violations(report)
            + "\n\n위를 고치거나, 정말 예외라면 같은 줄이나 바로 위 줄에 주석으로 "
              "`harness:allow CR-00N <이유>` 를 남기고 다시 쓰십시오."
        )

    if done.returncode == 2:
        reasons = [f.get("reason", "") for f in report.get("files", []) if f.get("status") == "error"]
        deny(
            "공통 개발 규칙 검사기가 이 MCP 쓰기의 코드를 읽지 못했습니다.\n"
            f"objectSourceUrl: {url}\n"
            + "\n".join(r for r in reasons if r)
            + "\n\n확인되지 않는 상태로 통과시키지 않습니다."
        )

    # 0, 1, 2 는 checker.code_rules 가 약속한 종료코드다. 그 밖은 계약에 없다.
    deny(
        f"공통 개발 규칙 검사기가 알 수 없는 종료코드({done.returncode})로 끝나 이 MCP "
        "쓰기를 확인할 수 없었습니다.\n"
        f"objectSourceUrl: {url}\n"
        "확인되지 않는 상태로 통과시키지 않습니다."
    )


def _main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        # 입력을 읽지 못하면 이 호출이 setObjectSource 인지조차 알 수 없다. 모른다는
        # 것을 통과로 바꾸지 않는다(CLAUDE.md 원칙 7).
        deny(
            "harness 훅이 Claude Code 가 넘긴 입력을 해석하지 못해 이 MCP 쓰기를 확인할 "
            "수 없었습니다.\n확인되지 않는 상태로 통과시키지 않습니다."
        )

    tool = payload.get("tool_name") or ""
    if not _TOOL_NAME_RE.match(tool):
        allow()

    tool_input = payload.get("tool_input") or {}
    url = tool_input.get("objectSourceUrl")
    source = tool_input.get("source")

    if not isinstance(source, str) or not source:
        deny(
            "이 MCP 쓰기(setObjectSource)에 source(코드 본문)가 없거나 문자열이 아니어서 "
            "공통 개발 규칙을 확인할 수 없습니다.\n"
            f"objectSourceUrl: {url!r}\n\n확인되지 않는 상태로 통과시키지 않습니다."
        )

    if not isinstance(url, str) or not url:
        deny(
            "이 MCP 쓰기(setObjectSource)에 objectSourceUrl 이 없거나 문자열이 아니어서 "
            "어떤 언어인지 판별할 수 없어 공통 개발 규칙을 확인할 수 없습니다.\n\n"
            "확인되지 않는 상태로 통과시키지 않습니다."
        )

    suffix = suffix_for_url(url)
    if suffix is None:
        deny(
            "이 objectSourceUrl 이 알려진 ABAP/CDS 오브젝트 경로 패턴과 맞지 않아 어떤 "
            "언어인지 판별할 수 없어 공통 개발 규칙을 확인할 수 없습니다.\n"
            f"objectSourceUrl: {url}\n\n"
            "이 경로가 실제로 ABAP 이나 CDS 라면 "
            f"{_URL_MAP_PATH.name} 에 패턴을 추가하십시오({_URL_MAP_PATH}).\n"
            "확인되지 않는 상태로 통과시키지 않습니다."
        )

    _check_code(url, source, suffix)


def _force_utf8_io() -> None:
    """stdin·stdout·stderr 인코딩을 한곳에서 못 박는다.

    `pre_write_guard.py::_force_utf8_io` 와 같은 이유다(#14) — 인코딩 설정을
    여러 곳에 흩어 두면 한쪽만 고쳐지고 다른 쪽은 잊히는 일이 생긴다.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> None:
    """`_main` 을 감싸 무엇이 터지든 막는 쪽으로 떨어지게 한다.

    `pre_write_guard.py::main` 과 같은 fail-closed 방어다(CLAUDE.md 원칙 7).
    `allow()`/`deny()` 는 `sys.exit` 로 끝나므로(`SystemExit` 는 `Exception` 이
    아니다) 정상 종료 경로는 이 처리에 걸리지 않는다.
    """
    _force_utf8_io()
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 - 의도적으로 전부 잡아 fail-closed 로 만든다
        deny(
            "harness 훅에서 예상치 못한 오류가 나 이 MCP 쓰기를 확인할 수 없었습니다.\n"
            f"사유: {type(exc).__name__}: {exc}\n"
            "확인되지 않는 상태로 통과시키지 않습니다."
        )


if __name__ == "__main__":
    main()
