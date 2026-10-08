"""문서를 저장하기 전에 검사하고, 템플릿을 벗어나면 거절한다.

검사 엔진은 판정만 한다. 거절은 여기서 한다. 엔진이 위반을 종료코드 1 로 알리고,
이 훅이 그것을 받아 Claude 의 쓰기를 막는다.

**왜 PreToolUse 인가.** 막을 수 있는 훅 시점은 여기뿐이다. PostToolUse 는 도구가
이미 실행된 뒤라 되돌릴 수 없다. 대신 이 시점에는 파일이 아직 디스크에 없거나 옛
내용이므로, 저장될 최종 모습을 훅이 직접 만들어 봐야 한다.

- `Write` 는 `tool_input.content` 에 최종 내용이 그대로 온다.
- `Edit` 은 바꿀 조각만 오므로, 디스크의 현재 내용을 읽어 치환을 적용해 본다.

**왜 Python 인가.** 엔진이 이미 Python 이라 새 의존성이 늘지 않고, `jq` 없이 동작하며,
Windows 에서 CRLF 와 한글 인코딩을 다루기 쉽다. 이 저장소의 bash 훅들이 그 둘 때문에
따로 손을 봐야 했다.

**왜 이 파일이 `checker` 를 import 하지 않는가.** 마켓플레이스로 설치된 플러그인
캐시에는 `plugins/harness/` 만 들어가고 `checker/` 는 따라오지 않는다(#12). 예전에는
`sys.path` 에 저장소 루트를 얹어 `checker.locate` 를 가져다 썼는데, 설치본에는 그
루트 자체가 없어 `ModuleNotFoundError` 로 죽었고, Claude Code 는 이 훅의 0/2 가 아닌
종료코드를 "막지 않음" 으로 여겨 조용히 통과시켰다(CLAUDE.md 원칙 7 위반). 그래서 이
파일은 stdlib 만 쓰고, 검사 엔진 자체도 `uvx` 로 이 저장소의 GitHub 원격에서 매번
받아 온다 — 훅과 GitHub Actions 가 같은 엔진을 쓰게 하기 위해서다(이슈 #12 결정).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 검사 엔진을 받아 오는 기본 위치. GitHub Actions 재사용 워크플로의 기본
# `engine-ref` (main) 와 맞춘다 — 두 관문이 같은 엔진을 쓰는 것이 이 구조의 전제다.
DEFAULT_ENGINE_SPEC = "git+https://github.com/jaeheeMin/blueward-harness@main"

# 엔진을 실행할 시간. uvx 가 처음 이 저장소를 받아 빌드하는 데 시간이 걸릴 수 있어
# 넉넉히 둔다. 이후에는 uv 캐시에 남아 빠르다. hooks.json 의 훅 타임아웃(120초)보다
# 짧게 두어, 타임아웃이 나더라도 이 스크립트가 먼저 붙잡아 deny 로 답할 여유를 남긴다.
ENGINE_TIMEOUT_SECONDS = 110

# 이 훅이 내용을 재조립할 수 있는 형식. docx·xlsx·pptx 는 바이너리라 Write/Edit 도구로
# 의미 있게 만들어지지 않으므로 손대지 않는다. 그쪽은 GitHub Actions 검사가 잡는다.
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".csv"}

# 공통 개발 규칙(CR-001, CR-002, CR-003, CR-007, `checker.code_rules`, #54, #81)의
# 검사 대상 확장자. 문서
# 검사와는 다른 소관이라 따로 둔다 — 기준 폴더(`templates/` 와 `rules/` 를 함께 가진
# 폴더)를 요구하지 않고, 어느 Project Repository 어느 폴더의 코드에도 똑같이
# 적용된다(`conventions/common.md`).
#
# 정확히 어느 언어에 어느 규칙을 적용할지는 엔진 쪽 데이터(`checker/code_checks.yaml`)가
# 정한다 — 이 훅은 그 설정을 가져다 쓰지 않는다(설치본에는 엔진이 따라오지 않으므로,
# 위 STANDARDS_MARKERS 와 같은 사정이다). 그래서 여기 목록은 "검사 엔진에 보낼 만한
# 확장자인가" 만 작게 판단하는 손으로 옮겨 적은 사본이고, 언어별로 정확히 어떤 규칙이
# 도는지는 엔진이 결정한다. 언어가 늘면 이 목록과 `code_checks.yaml` 을 함께 고친다.
CODE_SUFFIXES = {".abap", ".js", ".ts", ".mjs", ".cjs", ".cds", ".asbdef"}

# 기준 폴더는 이 둘을 함께 가진 디렉터리다. `checker/locate.py` 의 `find_standards_root`
# 와 같은 판단이다. 설치된 플러그인에는 엔진(checker 패키지)이 따라오지 않아 가져다
# 쓸 수 없으므로 여기 그대로 옮겨 적는다 — `checker/locate.py` 가 바뀌면 이쪽도 손으로
# 맞춰야 한다는 뜻이고, 그 대가는 알고 지는 것이다(#12 결정 사항).
STANDARDS_MARKERS = ("templates", "rules")

ALLOW = 0  # 통과. 아무것도 출력하지 않으면 통과다.

# 거부 메시지는 "왜 막혔는지" 와 "다음에 할 일" 을 함께 담는다(#113 Hook 거부 메시지에
# 원인과 다음 할 일 함께 안내). 이 메시지는 Claude 가 먼저 읽고 개발자가 아닐 수도 있는
# 팀원에게 전한다 — Claude 가 스스로 못 하는 일(프로그램 설치, 로그인)은 "사람이 할 일" 로
# 밝히고 명령을 그대로 적는다. 아래 두 문구를 여러 거부에서 같이 쓴다.
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


def allow() -> None:
    sys.exit(ALLOW)


def _has_broken_encoding(text: str) -> bool:
    """복원할 수 없게 깨진 문자가 섞여 있는지 본다.

    U+FFFD 는 디코더가 원래 바이트를 되살리지 못해 대신 끼워 넣는 대체 문자다.
    서로게이트(U+D800~U+DFFF)는 짝을 이루지 못한 UTF-16 코드 단위가 파이썬
    문자열에 그대로 남을 때 나온다. 둘 다 원래 경로가 이미 사라졌다는 신호다.
    """
    return any(ch == "�" or 0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def allow_with_notice(notice: str) -> None:
    """쓰기는 허용하되 사유를 Claude 에게 보여 준다. 조용한 통과가 아니다(#209).

    `permissionDecision` 은 싣지 않는다 — 허용을 이 훅이 선언하지 않고 평소 권한
    흐름에 맡기며, 알림만 `additionalContext` 로 덧붙인다.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": notice,
        }
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def deny(reason: str) -> None:
    """쓰기를 막고 사유를 사람과 Claude 에게 보여준다.

    입출력 인코딩은 `main()` 이 시작하자마자 `_force_utf8_io()` 로 한곳에서 못
    박아 둔다(#14). 여기서 다시 손대지 않는다 — stdout 조치만 있고 stdin 조치가
    빠져 있던 것이 바로 이 결함의 원인이었으므로, 인코딩 설정은 두 번 다시
    흩어 두지 않는다.
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


def find_standards_root(path: Path) -> Path | None:
    """문서에서 위로 올라가며 기준 폴더를 찾는다. 없으면 None.

    `checker/locate.py` 의 같은 이름 함수를 그대로 옮긴 것이다. 위 STANDARDS_MARKERS
    주석을 본다.
    """
    try:
        start = path.resolve()
    except OSError:
        start = path
    for parent in [start.parent, *start.parent.parents]:
        if all((parent / marker).is_dir() for marker in STANDARDS_MARKERS):
            return parent
    return None


def is_config_file(relative: Path) -> bool:
    """기준 폴더 기준 상대 경로가 규칙 설정 자체인지 본다(#209).

    `rules/` 아래 `*.yaml`·`*.yml`, 또는 `templates/` 아래 모든 파일이다. 호출하는 쪽이
    `resolve()` 로 `..` 를 걷어낸 경로를 넘기므로 `rules/../docs/x.md` 는 `docs/x.md`
    로 판정된다. Windows 의 대소문자 차이는 `normcase` 로 맞춘다.
    """
    parts = [os.path.normcase(p) for p in relative.parts]
    if len(parts) < 2 or ".." in parts:
        return False
    if parts[0] == "templates":
        return True
    return parts[0] == "rules" and parts[-1].endswith((".yaml", ".yml"))


def engine_spec() -> str:
    """검사 엔진을 어디서 받을지 정한다.

    기본은 이 저장소의 main 브랜치이고, GitHub Actions 의 기본 `engine-ref` 와
    맞춘다. `DOC_GUARD_ENGINE` 환경변수를 두면 그것을 `uvx --from` 에 그대로
    넘긴다 — 개발과 테스트가 로컬 체크아웃 경로를 가리켜 네트워크 없이 빠르게
    돌리는 통로다.
    """
    return os.environ.get("DOC_GUARD_ENGINE") or DEFAULT_ENGINE_SPEC


def proposed_content(tool: str, tool_input: dict, path: Path) -> str | None:
    """저장되고 나면 파일이 어떤 모습일지 만들어 본다."""
    if tool == "Write":
        return tool_input.get("content") or ""

    # Edit: 디스크의 현재 내용에 치환을 적용해 최종 모습을 얻는다.
    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    if old is None or new is None:
        return None
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # 읽을 수 없으면 최종 모습을 알 수 없다. 막지 않는다 — 검사 대상이 아닐
        # 가능성이 크고, 잘못 막으면 팀원이 손쓸 방법이 없다.
        return None
    if old not in current:
        # 치환이 실패할 상황이다. Claude 자신의 오류로 처리되게 둔다.
        return None
    return current.replace(old, new) if tool_input.get("replace_all") else current.replace(old, new, 1)


def format_violations(report: dict) -> str:
    lines = []
    for entry in report.get("files", []):
        if entry.get("status") != "violation":
            continue
        lines.append(f"[{entry.get('type')}] {entry.get('file')}")
        for v in entry.get("violations", []):
            lines.append(f"  - {v.get('message')}")
            expected, actual = v.get("expected"), v.get("actual")
            if expected not in (None, ""):
                lines.append(f"      기대: {expected}")
            if actual not in (None, ""):
                lines.append(f"      실제: {actual}")
        template = entry.get("template")
        if template:
            lines.append(f"  쓸 템플릿: {template}")
    return "\n".join(lines)


def format_code_violations(report: dict) -> str:
    """`checker.code_rules` 의 리포트를 사람이 읽을 안내문으로 바꾼다.

    `harness:allow` 로 예외 처리된 발견(`allowed`)은 보여주지 않는다 — 이미 인정된
    예외를 다시 늘어놓으면 무엇을 진짜 고쳐야 하는지 흐려진다.
    """
    lines = []
    for entry in report.get("files", []):
        if entry.get("status") != "violation":
            continue
        for f in entry.get("findings", []):
            if f.get("allowed"):
                continue
            lines.append(f"  - [{f.get('rule')}] {entry.get('file')}:{f.get('line')}:{f.get('col')} {f.get('message')}")
            fix = f.get("fix")
            if fix:
                lines.append(f"      고치기: {fix}")
    return "\n".join(lines)


def _check_code(path: Path, content: str) -> None:
    """공통 개발 규칙(CR-001, CR-002, CR-003, CR-007)을 코드에 적용한다(#54, #81).

    문서 검사(`_main` 의 나머지 절반)와 소관이 다르다 — 기준 폴더(`templates`/`rules`)
    를 요구하지 않는다. 이 두 규칙은 어느 Project Repository, 어느 폴더의 코드에도
    똑같이 적용되기 때문이다(`conventions/common.md`). 무엇이 위반인지는 전부
    `checker.code_rules` 가 판정하고, 이 훅은 대상 확장자를 고르고 판정을 받아 막을지
    정할 뿐이다 — 언어나 CR 코드가 늘어도 이 함수는 고치지 않는다.

    엔진을 받거나 실행하지 못하면(doc-guard 와 같은 이유로) 통과가 아니라 거절한다.
    `allow()`/`deny()` 는 `sys.exit` 로 끝나므로 이 함수는 값을 돌려주지 않는다.
    """
    with tempfile.TemporaryDirectory(prefix="doc-guard-code-") as tmp:
        # 파일 이름(정확히는 확장자)으로 언어를 판정하므로 원래 이름 그대로 옮겨 적는다.
        staged = Path(tmp) / path.name
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
                "harness 가 공통 개발 규칙 검사 엔진을 받거나 실행하지 못해 이 코드를 "
                "확인할 수 없었습니다.\n"
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
            f"{(done.stderr or done.stdout or '').strip()[:500]}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    # 리포트의 file 은 임시 스테이징 경로다. 사람에게는 원래 저장하려던 경로를 보여준다.
    for entry in report.get("files", []):
        entry["file"] = str(path)

    if done.returncode == 1:
        deny(
            "harness: 이 코드가 공통 개발 규칙을 어겼습니다(conventions/common.md).\n\n"
            + format_code_violations(report)
            + "\n\n다음: Claude 가 위 항목을 고쳐 다시 저장하십시오. 정말 예외라면 같은 줄이나 "
              "바로 위 줄에 주석으로 `harness:allow CR-00N <이유>` 를 남기고 다시 저장하십시오."
        )

    if done.returncode == 2:
        reasons = [f.get("reason", "") for f in report.get("files", []) if f.get("status") == "error"]
        deny(
            "공통 개발 규칙 검사기가 이 코드를 읽지 못했습니다.\n"
            + "\n".join(r for r in reasons if r)
            + "\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            "다음: 위 사유가 코드 내용(문법, 인코딩)의 문제라면 Claude 가 고쳐 다시 저장하십시오. "
            "그렇지 않으면 같은 작업을 한 번 더 시도하고, 계속되면 위 내용을 붙여 "
            "jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오(사람이 할 일)."
        )

    # 0, 1, 2 는 checker.code_rules 가 약속한 종료코드다. 그 밖은 계약에 없다.
    deny(
        f"공통 개발 규칙 검사기가 알 수 없는 종료코드({done.returncode})로 끝나 이 코드를 "
        "확인할 수 없었습니다.\n"
        "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
        + NEXT_RETRY
    )


def _check_activation_gate(path: Path) -> None:
    """저장소 루트의 `src/` 아래에 쓰려는데 활성화되지 않은 ABAP 오브젝트가 있으면 막는다(#190).

    `src/` 스냅샷에는 활성화에 성공한 소스만 담는다. 저장소를 찾지 못하거나 `src/` 밖이면
    아무것도 하지 않고 아래 기존 판정으로 넘어간다. 걸리지 않으면 돌아온다.
    """
    start = path.parent
    while not start.is_dir() and start != start.parent:
        start = start.parent
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=str(start),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    top = done.stdout.strip()
    if done.returncode != 0 or not top:
        return
    # Windows 의 대소문자·단축 경로(8.3)가 달라도 같은 폴더로 보게 양쪽을 맞춘다.
    src_dir = os.path.normcase(os.path.realpath(os.path.join(top, "src")))
    target = os.path.normcase(os.path.realpath(str(path)))
    if target != src_dir and not target.startswith(src_dir + os.sep):
        return

    # 관문을 실행하지 못하면(import 실패 포함) 통과가 아니라 검사 불능으로 막는다.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import adt_activation  # noqa: E402

        ok, message = adt_activation.gate(top)
    except Exception as exc:  # noqa: BLE001
        deny(
            "harness: 활성화 관문을 실행하지 못해 ABAP 오브젝트의 활성화 성공을 확인할 수 없습니다(검사 불능).\n"
            f"사유: {type(exc).__name__}: {exc}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n" + NEXT_RETRY
        )
    if not ok:
        deny("harness: src/ 에는 활성화에 성공한 소스만 담습니다. " + message)


def _main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        # 입력을 읽지 못하면 이 파일이 doc-guard 소관인지조차 알 수 없다. 모른다는 것을
        # 통과로 바꾸지 않는다(CLAUDE.md 원칙 7).
        deny(
            "doc-guard 훅이 Claude Code 가 넘긴 입력을 해석하지 못해 이 문서를 확인할 수 "
            "없었습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    tool = payload.get("tool_name") or ""
    if tool not in ("Write", "Edit"):
        allow()

    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path")
    if not raw_path:
        allow()

    path = Path(raw_path)
    suffix = path.suffix.lower()

    _check_activation_gate(path)

    if suffix in CODE_SUFFIXES:
        # 공통 개발 규칙(#54)은 문서 검사와 소관이 다르다 — 기준 폴더를 요구하지
        # 않으므로 아래 doc-guard 절차(find_standards_root 등)를 타지 않는다.
        if _has_broken_encoding(raw_path):
            deny(
                "코드 경로가 깨져 들어와(인코딩 문제) 이 파일을 확인할 수 없습니다.\n"
                "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
                "다음: Claude 가 파일 경로를 확인해 정확한 경로로 다시 저장하십시오. 같은 "
                "현상이 계속되면 그 경로를 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 "
                "알리십시오(사람이 할 일)."
            )
        content = proposed_content(tool, tool_input, path)
        if content is None:
            allow()
        _check_code(path, content)
        return  # _check_code 는 allow()/deny() 로 끝나므로 여기 닿지 않는다

    if suffix not in TEXT_SUFFIXES:
        allow()

    if _has_broken_encoding(raw_path):
        # 경로 문자열에 U+FFFD(대체 문자)나 짝을 잃은 서로게이트가 섞여 있다면,
        # 어딘가에서 인코딩이 깨져 들어왔다는 뜻이다. 원래 경로를 잃어버렸으므로
        # 이 문서가 기준 폴더 아래(=doc-guard 소관)인지조차 판단할 수 없다.
        # 판단 불능을 관할 밖으로 뭉개면, 진짜 위반 문서가 깨진 경로 덕에 조용히
        # 통과해 버린다 — 이슈 #14, CLAUDE.md 원칙 7("검사를 못 했다" 를 "통과" 나
        # "위반" 으로 뭉개지 않는다).
        deny(
            "문서 경로가 깨져 들어와(인코딩 문제) 이 문서가 doc-guard 소관인지 "
            "판단할 수 없습니다.\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            "다음: Claude 가 문서 경로를 확인해 정확한 경로로 다시 저장하십시오. 같은 "
            "현상이 계속되면 그 경로를 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 "
            "알리십시오(사람이 할 일)."
        )

    standards_root = find_standards_root(path)
    if standards_root is None:
        allow()  # doc-guard 의 소관이 아니다

    content = proposed_content(tool, tool_input, path)
    if content is None:
        allow()

    try:
        relative = path.resolve().relative_to(standards_root.resolve())
    except ValueError:
        allow()

    with tempfile.TemporaryDirectory(prefix="doc-guard-") as tmp:
        staged = Path(tmp) / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(content, encoding="utf-8")

        # 규칙은 기준 폴더의 진짜 것을 쓰고(템플릿 경로가 거기서 풀린다), 관할을 맞춰 볼
        # 기준만 임시 폴더로 둔다. 그래야 파일명·위치 규칙이 원래 자리 기준으로 판정된다.
        #
        # 엔진 자체는 이 저장소에 있지 않고 uvx 로 GitHub 에서 받는다. 처음 받을 때는
        # 네트워크가 필요하고 시간이 걸리지만, uv 캐시에 남아 이후로는 빠르다.
        cmd = [
            "uvx", "--from", engine_spec(), "doc-guard",
            "--rules", str(standards_root / "rules"),
            "--root", tmp,
            str(staged),
        ]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            done = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", env=env,
                timeout=ENGINE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            # 여기까지 왔다는 것은 이 파일이 doc-guard 소관이라는 뜻이다. 검사할 수 없는
            # 상태로 통과시키면 정확히 필요한 순간에 보호가 사라진다.
            deny(
                "doc-guard 가 검사 엔진을 받거나 실행하지 못해 이 문서를 확인할 수 없었습니다.\n"
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
            "doc-guard 검사기의 출력을 해석하지 못했습니다.\n"
            f"{(done.stderr or done.stdout or '').strip()[:500]}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )

    if done.returncode == 2:
        if is_config_file(relative):
            # 설정이 깨진 상태에서 설정 자체를 고치는 쓰기까지 막으면 스스로 풀 수 없는
            # 교착이 된다(#209). 허용하되 문서 검사를 못 한 상태임을 숨기지 않는다.
            allow_with_notice(
                "doc-guard: 규칙 설정에 오류가 있어 문서 검사를 못 하는 상태다. "
                "설정 파일 수정이라 허용한다.\n"
                f"사유: {report.get('message', '')}\n"
                "이 쓰기는 검사를 통과한 것이 아니다. 설정을 고친 뒤 다시 확인하라."
            )
        # 설정 오류는 문서 위반과 받는 사람이 다르다. 문서를 쓰는 팀원은 규칙 파일을
        # 고칠 권한도 지식도 없으므로, 자기 문서를 들여다보며 헤매게 두면 안 된다.
        deny(
            "doc-guard 규칙 파일에 문제가 있어 검사할 수 없습니다.\n"
            f"{report.get('message', '')}\n\n"
            "이것은 문서의 문제가 아닙니다.\n"
            "다음: 사람이 할 일 — 이 Project Repository 의 rules/ 파일을 고칠 수 있는 담당자"
            "(저장소 소유자)에게 위 메시지를 그대로 전달해 rules/ 를 고치게 하십시오. 고쳐질 "
            "때까지 이 문서는 저장할 수 없습니다. 엔진 쪽 문제로 보이면 "
            "jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."
        )

    if done.returncode == 1:
        deny(
            "doc-guard: 이 문서가 템플릿을 따르지 않습니다.\n\n"
            + format_violations(report)
            + "\n\n다음: Claude 가 위 템플릿을 보고 문서를 고친 뒤 다시 저장하십시오."
        )

    # 0, 1, 2 는 검사기가 약속한 종료코드다(checker/cli.py). 그 밖은 계약에 없으므로
    # 통과도 위반도 아니다 — 검사를 할 수 없었던 것으로 보고 막는다.
    deny(
        f"doc-guard 검사기가 알 수 없는 종료코드({done.returncode})로 끝나 이 문서를 "
        "확인할 수 없었습니다.\n"
        "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
        + NEXT_RETRY
    )


def _force_utf8_io() -> None:
    """stdin·stdout·stderr 인코딩을 한곳에서 못 박는다.

    예전에는 stdout 은 `deny()` 안에서, stdin 은 `_main()` 안에서 따로따로
    손댔다. 그러다 stdout 조치만 남고 stdin 조치가 빠지는 일이 실제로 있었다
    (#14) — Windows 콘솔 기본 코드페이지로 표준입력을 읽으면 한글이 섞인
    경로가 깨지고, `find_standards_root` 가 기준 폴더를 찾지 못해 위반 문서를
    조용히 통과시켰다. 입출력 인코딩을 이 함수 하나로 모아, 한쪽만 고쳐지고
    다른 쪽은 잊히는 일이 다시 생기지 않게 한다.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> None:
    """`_main` 을 감싸 무엇이 터지든 막는 쪽으로 떨어지게 한다.

    예전 결함은 `ModuleNotFoundError` 가 이 함수 바깥, import 시점에 나서 훅 전체가
    처리되지 않은 예외로 죽었고, Claude Code 는 0 도 2 도 아닌 그 종료코드를 "막지
    않음" 으로 여겨 조용히 통과시켰다(CLAUDE.md 원칙 7). 이제 이 파일은 stdlib 만
    import 하므로 그 경로 자체가 사라졌지만, 앞으로 또 다른 예상 못한 예외가 나더라도
    같은 실패로 되풀이되지 않도록 여기서 한 번 더 막는다. `allow()`/`deny()` 는
    `sys.exit` 로 끝나므로(`SystemExit` 는 `Exception` 이 아니다) 정상 종료 경로는
    이 처리에 걸리지 않는다.
    """
    _force_utf8_io()
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 - 의도적으로 전부 잡아 fail-closed 로 만든다
        deny(
            "doc-guard 훅에서 예상치 못한 오류가 나 이 문서를 확인할 수 없었습니다.\n"
            f"사유: {type(exc).__name__}: {exc}\n"
            "확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            + NEXT_RETRY
        )


if __name__ == "__main__":
    main()
