"""MCP ADT 도구로 SAP 오브젝트에 바로 쓰거나 이름을 새로 붙이는 경로에도 공통
개발 규칙(CR-001, CR-002, CR-003, CR-007)을 건다(#60, #61, #81).

Claude 가 ADT MCP 서버(예: npm `mcp-abap-abap-adt-api`)의 도구로 오브젝트에 바로
쓰거나 리팩토링으로 새 이름을 붙이면 Write/Edit 도구를 거치지 않으므로
`pre_write_guard.py` 가 이 경로를 보지 못한다. 이 훅은 `hooks.json` 의
`PreToolUse` 매처로 그 호출들을 가로채, 같은 `checker.code_rules` 엔진으로
검사한다. 매처가 서버 이름에 매이지 않으므로 이 스크립트도 어떤 MCP 서버가
불렀는지 신경 쓰지 않는다 — 도구 이름 끝(마지막 `__` 뒤)으로만 갈래를 나눈다.

**테넌트 판정(#148).** 코드 규칙 검사 앞에 `adt_tiers.py` 의 판정이 먼저 돈다 —
프로젝트의 `env/adt-tiers.yaml` 에서 `writes_allowed: false` 인 서버의 `write_tools`
도구는 거절, `data_tools`(기본 `tableContents`, `runQuery`)는 사용자에게 되묻는다
(`ask`). 파일이 없으면 쓰기 도구는 아래 코드 규칙만, 데이터 도구는 되묻기만 한다.
파일이 있는데 읽지 못하면 거절한다. 테넌트 판정을 통과한 호출만 아래 두 갈래로
간다. 서버 이름은 이 판정에서만 쓰고, 아래 갈래는 여전히 도구 이름 끝으로만 나눈다.

**두 갈래.**

1. `setObjectSource` — 코드 본문(`source`)을 통째로 검사한다(#60). 엔진이
   아는 규칙을 전부 본다 — 지금은 CR-001, CR-002, CR-003(SELECT *, ABAP),
   CR-007(빈 CATCH, ABAP)이다(#81). 규칙이 늘어도 이 경로는 고치지 않는다 —
   `checker.code_rules` 가 `code_checks.yaml` 을 보고 언어에 맞는 규칙을
   알아서 고른다(CLAUDE.md 원칙 2).
2. `renamePreview`, `renameExecute`, `extractMethodPreview`,
   `extractMethodExecute`, `createObject` — 리팩토링/생성이 새로 붙이는
   **이름**만 검사한다(#61). 이 도구들은 기존 코드를 옮기거나 이름만 바꿀 뿐이고
   이름 하나짜리 텍스트에는 반복문도 SELECT 문도 CATCH 블록도 있을 수 없으므로,
   CR-002/CR-003/CR-007 의 대상이 아니다 — **CR-001 만** 본다(`_filter_report_to_rules`).
   `extractMethodExecute` 만 예외적으로 이름 필드가 따로 없다 — 새 메서드 이름은
   `refactoring.affectedObjects[].textReplaceDeltas[].contentNew` 안의 ABAP
   코드 조각에만 있어서, 그 조각들을 이어 붙여 검사한다.

**입력 모양.** #61 조사로 확인한 각 도구의 `tool_input` 모양:

| 도구 | 새 이름 위치 | 형태 |
|---|---|---|
| `setObjectSource` | `objectSourceUrl` + `source` | 문자열 |
| `renamePreview` | `renameRefactoring.newName` | 객체(방어적으로 JSON 문자열도 받는다) |
| `renameExecute` | `refactoring.newName` | 객체(방어적으로 JSON 문자열도 받는다) |
| `extractMethodPreview` | `proposal` 을 JSON.parse 한 `.name` | JSON 문자열(방어적으로 객체도 받는다) |
| `extractMethodExecute` | 이름 필드 없음 — `refactoring` 을 JSON.parse 한 `.affectedObjects[].textReplaceDeltas[].contentNew` | JSON 문자열(방어적으로 객체도 받는다) |
| `createObject` | `name` | 문자열 |

모양이 예상과 다르면(필드가 없거나, JSON 파싱이 안 되거나, 이름이 빈 문자열이거나
문자열이 아니면) 검사 불능으로 거절한다(CLAUDE.md 원칙 7) — 짐작해서 통과시키지
않는다.

**`setObjectSource` 의 언어 판별.** `objectSourceUrl` 은 파일 확장자가 없는 ADT
REST 경로다(`.../source/main` 처럼 끝난다). `checker.code_rules` 는 파일
확장자로 언어를 정하므로, 이 경로가 어떤 언어인지는 URL 패턴으로 먼저 판별해야
한다. 그 매핑은 `mcp_object_source_map.json` 데이터로 둔다(CLAUDE.md 원칙 2) —
코드에 조건문을 늘어놓지 않는다. 목록에 없는 패턴은 "판별 못 함" 으로 보고
통과시키지 않는다 — 잘못 짚은 매핑으로 아무것도 안 보면서 통과하는 것보다, 새
패턴이 나올 때마다 검사 불능으로 드러나 매핑을 넓히게 하는 편이 안전하다. 이름만
보는 나머지 다섯 도구는 모두 ABAP 리팩토링/생성 도구라 언어 판별 없이 `.abap`
로 고정한다.

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

# 스크립트로 실행되면 이 폴더가 sys.path 맨 앞이라 바로 import 되지만, 다른 방식으로
# 불려도 같은 폴더의 모듈을 찾게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import adt_tiers  # noqa: E402

# 검사 엔진을 받아 오는 기본 위치. `pre_write_guard.py` 와 GitHub Actions 재사용
# 워크플로의 기본 `engine-ref` (main) 와 맞춘다.
DEFAULT_ENGINE_SPEC = "git+https://github.com/jaeheeMin/blueward-harness@main"

# 엔진을 실행할 시간. `pre_write_guard.py` 와 같은 이유로 넉넉히 둔다.
ENGINE_TIMEOUT_SECONDS = 110

# 이 매처와 짝이 맞는지 스스로도 한 번 더 확인한다(hooks.json 이 이미 걸러 주지만,
# 이 스크립트가 다른 매처에 잘못 물릴 경우에도 스스로를 지킨다). 그룹 1 이 도구
# 이름 끝(마지막 `__` 뒤)이고, `_main()` 이 이 값으로 갈래를 나눈다.
_TOOL_NAME_RE = re.compile(
    r"^mcp__.*__"
    r"(setObjectSource|renamePreview|renameExecute"
    r"|extractMethodPreview|extractMethodExecute|createObject)$"
)

# 이름만 보는 도구들 중 새 이름이 `{필드}.{키}` 에 있고, 그 필드가 객체 또는 JSON
# 문자열로 올 수 있는 것들(CLAUDE.md 원칙 2 — 도구마다 분기 대신 표로 둔다).
# `createObject` 는 `name` 이 바로 문자열이라 이 표에 없다(따로 다룬다).
_NAME_FIELD_BY_TOOL_KIND = {
    "renamePreview": ("renameRefactoring", "newName"),
    "renameExecute": ("refactoring", "newName"),
    "extractMethodPreview": ("proposal", "name"),
}

_URL_MAP_PATH = Path(__file__).with_name("mcp_object_source_map.json")

ALLOW = 0

# 거부 메시지는 "왜 막혔는지" 와 "다음에 할 일" 을 함께 담는다(#113 Hook 거부 메시지에
# 원인과 다음 할 일 함께 안내). `pre_write_guard.py` 의 같은 이름 문구와 맞춘다 —
# Claude 가 스스로 못 하는 일(프로그램 설치)은 "사람이 할 일" 로 밝힌다.
NEXT_ENGINE_FAIL = (
    "다음: 사람이 할 일 — uv 가 없다면 PowerShell 에서 `winget install --id astral-sh.uv -e` "
    "로 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오. 이미 설치돼 있다면 네트워크"
    "(엔진을 처음 받을 때 필요)를 확인하고 같은 작업을 다시 시도하십시오. 계속되면 위 사유를 "
    "붙여 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."
)
NEXT_RETRY = (
    "다음: 같은 작업을 한 번 더 시도하십시오. 계속되면 위 내용을 붙여 "
    "jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오(사람이 할 일)."
)
NEXT_FIX_INPUT = (
    "다음: Claude 가 이 MCP 호출의 입력을 확인해 올바른 형태로 다시 호출하십시오. 같은 "
    "현상이 계속되면 호출 내용을 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 "
    "알리십시오(사람이 할 일)."
)


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


def _engine_command(staged: Path) -> list[str]:
    """검사 엔진을 부르는 명령을 짓는다. `setObjectSource` 경로와 이름만 보는
    경로가 함께 쓴다(설계: "엔진 호출은 같은 훅에서 공유한다")."""
    return [
        "uvx", "--from", engine_spec(), "python", "-m", "checker.code_rules",
        "--json", str(staged),
    ]


def _check_code(url: str, content: str, suffix: str) -> None:
    """공통 개발 규칙(CR-001, CR-002, CR-003, CR-007)을 MCP 로 쓰려는 코드에 적용한다.

    `pre_write_guard.py::_check_code` 와 같은 구조다. 다른 점은 검사 대상이 디스크
    파일이 아니라 MCP 호출의 `source` 문자열이라, 임시 파일 이름을 원래 경로가
    아니라 판별한 언어의 확장자로 직접 짓는다는 것뿐이다. `allow()`/`deny()` 는
    `sys.exit` 로 끝나므로 이 함수는 값을 돌려주지 않는다.
    """
    with tempfile.TemporaryDirectory(prefix="doc-guard-mcp-") as tmp:
        staged = Path(tmp) / f"mcp_source{suffix}"
        staged.write_text(content, encoding="utf-8")

        cmd = _engine_command(staged)
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
                f"사유: {exc}\n"
                "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                + NEXT_ENGINE_FAIL
                + " 로컬에서 개발·테스트 중이라면 DOC_GUARD_ENGINE 환경변수로 엔진 경로를 "
                "지정할 수 있습니다."
            )

    if done.returncode == 0:
        allow()

    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        deny(
            "공통 개발 규칙 검사기의 출력을 해석하지 못했습니다.\n"
            f"objectSourceUrl: {url}\n"
            f"{(done.stderr or done.stdout or '').strip()[:500]}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
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
            + "\n\n다음: Claude 가 위 항목을 고쳐 다시 쓰십시오. 정말 예외라면 같은 줄이나 "
              "바로 위 줄에 주석으로 `harness:allow CR-00N <이유>` 를 남기고 다시 쓰십시오."
        )

    if done.returncode == 2:
        reasons = [f.get("reason", "") for f in report.get("files", []) if f.get("status") == "error"]
        deny(
            "공통 개발 규칙 검사기가 이 MCP 쓰기의 코드를 읽지 못했습니다.\n"
            f"objectSourceUrl: {url}\n"
            + "\n".join(r for r in reasons if r)
            + "\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            "다음: 위 사유가 코드 내용(문법, 인코딩)의 문제라면 Claude 가 고쳐 다시 쓰십시오. "
            "그렇지 않으면 같은 작업을 한 번 더 시도하고, 계속되면 위 내용을 붙여 "
            "jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오(사람이 할 일)."
        )

    # 0, 1, 2 는 checker.code_rules 가 약속한 종료코드다. 그 밖은 계약에 없다.
    deny(
        f"공통 개발 규칙 검사기가 알 수 없는 종료코드({done.returncode})로 끝나 이 MCP "
        "쓰기를 확인할 수 없었습니다.\n"
        f"objectSourceUrl: {url}\n"
        "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
        + NEXT_RETRY
    )


def _parse_json_or_dict(value: object) -> dict | None:
    """MCP 도구 입력이 이미 파싱된 객체로도, JSON 문자열로도 올 수 있어(#61 조사) 둘
    다 방어적으로 받는다. 그 밖의 모양이거나 JSON 이 객체가 아니면 None(=판별 못
    함)이다."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _filter_report_to_rules(report: dict, keep_rules: set[str]) -> bool:
    """리포트에서 `keep_rules` 에 없는 규칙의 발견을 지운다.

    이름만 보는 경로(rename*, extractMethodPreview, createObject, extractMethodExecute)
    는 CR-002(반복문 안 DB 조회)의 대상이 아니다 — 이름 하나짜리 코드나 옮기기만
    하는 코드 조각에는 반복문 판정이 의미가 없다. 엔진이 그래도 다른 규칙을 얹어
    내더라도 여기서 걸러 이 경로 밖의 규칙으로 막지 않는다. `report` 를 제자리에서
    고치고, 필터링 뒤에도 예외 처리되지 않은 위반이 남아 있으면 True 를 돌려준다.
    """
    still_violation = False
    for entry in report.get("files", []):
        kept = [f for f in entry.get("findings", []) if f.get("rule") in keep_rules]
        entry["findings"] = kept
        has_violation = any(not f.get("allowed") for f in kept)
        entry["status"] = "violation" if has_violation else "pass"
        if has_violation:
            still_violation = True
    return still_violation


def _run_engine_and_get_violations(tool: str, content: str, suffix: str, context: str) -> dict:
    """스테이징한 코드를 엔진으로 검사한다.

    통과(0)면 여기서 끝낸다(`allow()`). 엔진을 못 받거나 실행하지 못했거나
    (`OSError`/타임아웃), 출력을 해석하지 못했거나, 종료코드가 2(검사 불능)이거나
    0/1/2 어디에도 없으면 여기서 끝낸다(`deny()`) — `_check_code` 와 같은 fail-closed
    (CLAUDE.md 원칙 7). 위반(1)일 때만 리포트를 돌려줘 호출부가 규칙별로 다시
    걸러 판정하게 한다(이름/코드 조각 경로는 CR-001 만 본다, `_filter_report_to_rules`).

    `context` 는 실패 메시지에 넣을 한 줄 설명이다(예: "새 이름: 주문번호").
    """
    with tempfile.TemporaryDirectory(prefix="doc-guard-mcp-") as tmp:
        staged = Path(tmp) / f"mcp_source{suffix}"
        staged.write_text(content, encoding="utf-8")

        cmd = _engine_command(staged)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            done = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", env=env,
                timeout=ENGINE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            deny(
                f"harness 가 공통 개발 규칙 검사 엔진을 받거나 실행하지 못해 이 MCP 쓰기"
                f"({tool})를 확인할 수 없었습니다.\n"
                f"{context}\n"
                f"사유: {exc}\n"
                "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                + NEXT_ENGINE_FAIL
                + " 로컬에서 개발·테스트 중이라면 DOC_GUARD_ENGINE 환경변수로 엔진 경로를 "
                "지정할 수 있습니다."
            )

    if done.returncode == 0:
        allow()

    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        deny(
            "공통 개발 규칙 검사기의 출력을 해석하지 못했습니다.\n"
            f"MCP 도구: {tool}\n{context}\n"
            f"{(done.stderr or done.stdout or '').strip()[:500]}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    if done.returncode == 2:
        reasons = [f.get("reason", "") for f in report.get("files", []) if f.get("status") == "error"]
        deny(
            f"공통 개발 규칙 검사기가 이 MCP 쓰기({tool})의 코드를 읽지 못했습니다.\n"
            f"{context}\n"
            + "\n".join(r for r in reasons if r)
            + "\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            "다음: 위 사유가 입력 내용의 문제라면 Claude 가 고쳐 다시 호출하십시오. 그렇지 "
            "않으면 같은 작업을 한 번 더 시도하고, 계속되면 위 내용을 붙여 "
            "jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오(사람이 할 일)."
        )

    if done.returncode != 1:
        deny(
            f"공통 개발 규칙 검사기가 알 수 없는 종료코드({done.returncode})로 끝나 이 MCP "
            f"쓰기({tool})를 확인할 수 없었습니다.\n{context}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    for entry in report.get("files", []):
        entry["file"] = f"{tool} ({context})"

    return report


def _check_name(tool: str, name: str) -> None:
    """rename*/extractMethodPreview/createObject 가 새로 붙이려는 이름에 CR-001 만
    적용한다(#61) — 이름 하나짜리 코드에는 CR-002 대상(반복문)이 있을 수 없지만,
    엔진 쪽이 나중에 바뀌어도 흔들리지 않게 방어적으로 걸러 둔다."""
    context = f"새 이름: {name}"
    report = _run_engine_and_get_violations(tool, name + "\n", ".abap", context)

    if not _filter_report_to_rules(report, {"CR-001"}):
        allow()

    deny(
        f"harness: 이 MCP 쓰기({tool})가 새로 붙이려는 이름이 공통 개발 규칙을 어겼습니다"
        "(conventions/common.md).\n"
        f"{context}\n\n"
        + format_code_violations(report)
        + "\n\n다음: Claude 가 이름을 영문으로 바꿔 같은 MCP 도구를 다시 호출하십시오."
    )


def _check_extract_method_execute_content(tool: str, content: str) -> None:
    """`extractMethodExecute` 가 반영하려는 코드 조각(`contentNew` 이어붙임)에
    CR-001 만 적용한다(#61) — 옮기기만 할 뿐인 데다 조각이 온전한 오브젝트가
    아니므로 CR-002(반복문 안 DB 조회)는 이 경로의 관할이 아니다."""
    context = "새 메서드 이름은 아래 코드 조각 안에서만 확인할 수 있다"
    report = _run_engine_and_get_violations(tool, content, ".abap", context)

    if not _filter_report_to_rules(report, {"CR-001"}):
        allow()

    deny(
        f"harness: 이 MCP 쓰기({tool})가 반영하려는 코드에 공통 개발 규칙 CR-001 위반이 "
        "있습니다(conventions/common.md). extractMethodExecute 는 기존 코드를 옮기는 "
        "것뿐이라 CR-002(반복문 안 DB 조회)는 여기서 보지 않습니다.\n\n"
        + format_code_violations(report)
        + "\n\n다음: Claude 가 위 이름을 고쳐 다시 시도하십시오. 정말 예외라면 해당 코드 줄이나 "
          "바로 위 줄에 주석으로 `harness:allow CR-001 <이유>` 를 남기고 다시 시도하십시오."
    )


def _extract_name(tool: str, tool_kind: str, tool_input: dict) -> str:
    """rename*/extractMethodPreview/createObject 호출에서 새로 붙이려는 이름을
    뽑는다. 입력 모양이 예상과 다르면(#61 조사, 모듈 docstring 의 표) 검사 불능으로
    거절한다 — 짐작해서 통과시키지 않는다(CLAUDE.md 원칙 7)."""
    if tool_kind == "createObject":
        name = tool_input.get("name")
        if not isinstance(name, str) or not name.strip():
            deny(
                f"이 MCP 쓰기({tool})의 name 이 없거나 빈 문자열이거나 문자열이 아니어서 "
                "새 이름을 확인할 수 없습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                + NEXT_FIX_INPUT
            )
        return name

    sub_field, key = _NAME_FIELD_BY_TOOL_KIND[tool_kind]
    raw = tool_input.get(sub_field)
    parsed = _parse_json_or_dict(raw)
    if parsed is None:
        deny(
            f"이 MCP 쓰기({tool})의 {sub_field} 를 객체로도, JSON 문자열로도 해석하지 못해 "
            "새 이름을 확인할 수 없습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_FIX_INPUT
        )

    name = parsed.get(key)
    if not isinstance(name, str) or not name.strip():
        deny(
            f"이 MCP 쓰기({tool})의 {sub_field}.{key} 가 없거나 빈 문자열이거나 문자열이 "
            "아니어서 새 이름을 확인할 수 없습니다.\n확인되지 않는 상태로 통과시키지 "
            "않습니다.\n\n"
            + NEXT_FIX_INPUT
        )
    return name


def _handle_extract_method_execute(tool: str, tool_input: dict) -> None:
    """`refactoring` 안의 코드 조각(`contentNew`)들을 모아 검사한다(#61).

    이 도구는 이름을 담는 필드가 따로 없다 — 새 메서드 이름은
    `affectedObjects[].textReplaceDeltas[].contentNew` 안의 ABAP 코드 조각에만
    있다. 구조가 예상과 다르면(`refactoring` 을 해석할 수 없거나, `affectedObjects`
    가 배열이 아니거나, 조각을 하나도 못 찾으면) 검사 불능으로 거절한다.
    """
    raw = tool_input.get("refactoring")
    parsed = _parse_json_or_dict(raw)
    if parsed is None:
        deny(
            f"이 MCP 쓰기({tool})의 refactoring 을 객체로도, JSON 문자열로도 해석하지 못해 "
            "검사할 코드를 찾을 수 없습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_FIX_INPUT
        )

    affected = parsed.get("affectedObjects")
    if not isinstance(affected, list):
        deny(
            f"이 MCP 쓰기({tool})의 refactoring.affectedObjects 가 없거나 배열이 아니어서 "
            "검사할 코드를 찾을 수 없습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_FIX_INPUT
        )

    contents: list[str] = []
    for obj in affected:
        if not isinstance(obj, dict):
            continue
        deltas = obj.get("textReplaceDeltas")
        if not isinstance(deltas, list):
            continue
        for delta in deltas:
            if not isinstance(delta, dict):
                continue
            content_new = delta.get("contentNew")
            if isinstance(content_new, str) and content_new:
                contents.append(content_new)

    if not contents:
        deny(
            f"이 MCP 쓰기({tool})의 "
            "refactoring.affectedObjects[].textReplaceDeltas[].contentNew 에서 검사할 "
            "코드를 하나도 찾지 못했습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_FIX_INPUT
        )

    _check_extract_method_execute_content(tool, "\n".join(contents))


def ask(reason: str) -> None:
    """사용자에게 되묻는다. 사유는 권한 대화상자에 보인다(Claude Code 훅 문서)."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def _check_tenant(tool: str, tool_input: object, cwd: object) -> None:
    """`env/adt-tiers.yaml` 로 테넌트별 쓰기 차단과 데이터 추출 되묻기를 건다(#148).

    막거나 되물으면 여기서 끝나고(`deny()`/`ask()`), 그대로 두면 돌아가 기존 코드 규칙
    검사가 이어진다. 판정 로직은 `adt_tiers.py` 의 순수 함수다.
    """
    if adt_tiers.split_mcp_tool_name(tool) is None:
        return

    tiers = None
    path = adt_tiers.find_tiers_file(cwd if isinstance(cwd, str) and cwd else None)
    if path is not None:
        try:
            tiers = adt_tiers.load_tiers(path)
        except adt_tiers.TiersError as exc:
            deny(adt_tiers.load_error_reason(path, exc))

    try:
        default_data_tools = adt_tiers.load_default_data_tools()
    except (OSError, ValueError, adt_tiers.TiersError) as exc:
        deny(
            "harness: 기본 데이터 도구 목록(mcp_default_tools.json)을 읽지 못해 이 MCP 호출을 "
            f"확인할 수 없었습니다.\n사유: {exc}\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    decision = adt_tiers.decide(tool, tool_input, tiers, default_data_tools)
    if decision.kind == "deny":
        deny(decision.reason)
    if decision.kind == "ask":
        ask(decision.reason)


def _main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        # 입력을 읽지 못하면 이 호출이 setObjectSource 인지조차 알 수 없다. 모른다는
        # 것을 통과로 바꾸지 않는다(CLAUDE.md 원칙 7).
        deny(
            "harness 훅이 Claude Code 가 넘긴 입력을 해석하지 못해 이 MCP 쓰기를 확인할 "
            "수 없었습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    # 1단계(#148): 테넌트 판정. 쓰기 금지 서버의 쓰기 도구는 코드 규칙을 보기 전에
    # 막고, 데이터 추출 도구는 되묻는다. 통과하면 2단계(기존 코드 규칙 검사)로 간다.
    _check_tenant(tool, tool_input, payload.get("cwd"))

    # 2단계: 기존 코드 규칙(CR) 검사. 여섯 도구만 대상이고 나머지는 여기서 통과한다.
    match = _TOOL_NAME_RE.match(tool)
    if not match:
        allow()

    tool_kind = match.group(1)

    if tool_kind == "setObjectSource":
        url = tool_input.get("objectSourceUrl")
        source = tool_input.get("source")

        if not isinstance(source, str) or not source:
            deny(
                "이 MCP 쓰기(setObjectSource)에 source(코드 본문)가 없거나 문자열이 아니어서 "
                "공통 개발 규칙을 확인할 수 없습니다.\n"
                f"objectSourceUrl: {url!r}\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                "다음: Claude 가 source 에 코드 본문(문자열)을 담아 setObjectSource 를 "
                "다시 호출하십시오."
            )

        if not isinstance(url, str) or not url:
            deny(
                "이 MCP 쓰기(setObjectSource)에 objectSourceUrl 이 없거나 문자열이 아니어서 "
                "어떤 언어인지 판별할 수 없어 공통 개발 규칙을 확인할 수 없습니다.\n"
                "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                "다음: Claude 가 objectSourceUrl 에 오브젝트의 source 경로(/sap/bc/adt/... "
                "/source/main)를 담아 setObjectSource 를 다시 호출하십시오."
            )

        suffix = suffix_for_url(url)
        if suffix is None:
            deny(
                "이 objectSourceUrl 이 알려진 ABAP/CDS 오브젝트 경로 패턴과 맞지 않아 어떤 "
                "언어인지 판별할 수 없어 공통 개발 규칙을 확인할 수 없습니다.\n"
                f"objectSourceUrl: {url}\n"
                "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                "다음: 이 경로가 실제로 ABAP 이나 CDS 라면 "
                f"{_URL_MAP_PATH.name} 에 패턴을 추가하십시오({_URL_MAP_PATH}). 패턴 추가는 "
                "harness Plugin 을 고치는 일이므로 jaeheeMin/blueward-harness 저장소에 "
                "이슈로 요청하십시오(사람이 할 일). 경로를 잘못 넣은 것이라면 Claude 가 "
                "올바른 objectSourceUrl 로 다시 호출하십시오."
            )

        _check_code(url, source, suffix)
        return

    if tool_kind == "extractMethodExecute":
        _handle_extract_method_execute(tool, tool_input)
        return

    # renamePreview, renameExecute, extractMethodPreview, createObject — 새
    # 이름 하나만 CR-001 로 본다(#61, 모듈 docstring).
    name = _extract_name(tool, tool_kind, tool_input)
    _check_name(tool, name)


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
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )


if __name__ == "__main__":
    main()
