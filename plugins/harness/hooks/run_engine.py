"""스킬이 검사 엔진 모듈을 한 줄로 부르는 래퍼(#1043).

    uv run --no-project python "<플러그인>/hooks/run_engine.py" [--timeout 초] <모듈> [인자…]

안에서 `engine_spec.py` 로 엔진 판을 정하고 `uvx --from <판> python -P -m checker.<모듈> <인자…>` 를
실행해 종료 코드와 출력(stdout·stderr)을 그대로 넘긴다. 예전 스킬은 `e="$(…engine_spec.py)"` 다음 줄에
`uvx --from "$e" …` 를 적었는데, 두 줄을 한 줄로 합치면 `$( )` 가 들어가 웹 콘솔이 판정하지 못한다.

- 판을 정하지 못하면(엔진 판 확인 불능) uvx 로 넘어가지 않고 사유를 stderr 에 내고 종료 코드 2 로 끝난다.
  통과로도 위반으로도 뭉개지 않는다(CLAUDE.md 원칙 7). `@main` 이나 다른 판으로 대신 받지 않는다.
- 모듈은 아래 목록의 것만 부른다. 읽기·쓰기 구분은 웹 콘솔 `safe_tools.json` 의 `harness_modules` 가 따로 한다.
- 셸을 거치지 않고(리스트 인자, shell=False) 부르므로 경로의 공백·한글·`\\` 가 그대로 간다.

stdlib 만 쓴다 — `uv run --no-project` 로 프로젝트 의존성 없이 돈다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# 이 파일이 스크립트로 실행되면 이 폴더가 sys.path 맨 앞이지만, 다른 방식으로 불려도 같은 폴더를 찾게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_spec  # noqa: E402

# 스킬이 부르는 엔진 모듈. 목록에 없는 이름은 부르지 않는다.
MODULES = frozenset({
    "pr_queue", "pr_approvals", "branch_growth", "srs_automerge", "version_rebase", "srs_export_check", "export", "export_pptx",
    "blank_template", "manual_capture", "import_pptx", "cts_fill", "role_check", "cli",
})

CANNOT_CHECK = 2


def _fail(message: str) -> int:
    sys.stderr.write(f"확인 불능: {message}\n")
    return CANNOT_CHECK


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Windows 콘솔 기본 코드페이지(cp949)로 사유가 나가면 받는 쪽에서 깨진다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    timeout = None  # `--timeout 초` 는 `timeout` 명령 대신이다(Windows 에는 GNU timeout 이 없을 수 있다). 시간 안에 못 끝내면 확인 불능이다.
    if argv[:1] == ["--timeout"]:
        if len(argv) < 3 or not argv[1].isdecimal() or not 0 < int(argv[1]) <= 3600:
            return _fail("--timeout 뒤에는 1~3600 사이의 초가 와야 한다")
        timeout, argv = int(argv[1]), argv[2:]
    if not argv or argv[0] not in MODULES:
        return _fail(f"부를 수 있는 엔진 모듈이 아니다({argv[0] if argv else '없음'}). 허용: {', '.join(sorted(MODULES))}")
    module, args = argv[0], argv[1:]
    try:
        spec = engine_spec.engine_spec()
    except engine_spec.EngineSpecError as exc:
        return _fail(f"엔진 판을 정하지 못했다: {exc}")
    if not spec:
        return _fail("엔진 판을 정하지 못했다: 빈 값")
    uvx = shutil.which("uvx")
    if not uvx:
        return _fail("uvx 를 찾지 못했다(uv 가 설치돼 있는지 확인)")
    try:
        # 입출력은 부모 것을 그대로 물려받아 출력·종료 코드가 그대로 넘어간다.
        return subprocess.run([uvx, "--from", spec, "python", "-P", "-m", f"checker.{module}", *args], check=False, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        _fail(f"엔진이 {timeout}초 안에 끝나지 않았다(처음 받는 중일 수 있다)")
        return 124
    except OSError as exc:
        return _fail(f"uvx 를 실행하지 못했다: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
