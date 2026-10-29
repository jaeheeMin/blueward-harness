"""개발 도중 브랜치의 `src/` 변경이 커졌는지 센다(#536).

PR 은 하위 작업 하나 = PR 하나로 작게 나누는 것이 목적인데, 개발하다 보면 모르는 사이에 커진다.
`/harness:deliver` 8단계가 이 모듈로 `origin/{base}...HEAD` 의 `src/` 변경 줄(추가 + 삭제)을 세어,
기준을 넘으면 "여기까지를 PR 로 내고 나머지는 하위 작업으로 뺄까요?" 를 추천 보기로 묻는다.
**막지 않는다** — 알리기만 한다. 승인 판정(risk-gate)은 `src/` 크기를 보지 않는다(#436, #534).

기준은 데이터다(CLAUDE.md 원칙 2). 대상 저장소의 `.github/branch-growth.yaml` 의 `notify_src_lines`
(기본 1000)가 정한다. 파일이 없으면 기본값이다. 모르는 키나 잘못된 값은 조용히 넘기지 않고 검사
불능으로 낸다. `src/` 가 작업 트리에도 기준(`origin/{base}`)에도 없는 저장소(하네스 저장소 자신 등)는 적용하지 않는다.
브랜치가 `src/` 를 통째로 지웠으면 기준 쪽 추적 파일이 있으므로 지운 줄을 센다.

종료코드(원칙 7: 못 센 것을 통과로 뭉개지 않는다): 0 기준 이내 또는 적용 안 함, 1 기준 초과(알림),
2 검사 불능(git 실패, 설정 오류). `--json` 은 `status` 를 `ok`·`over`·`not_applicable`·`cannot_check` 로 낸다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

CONFIG_PATH = ".github/branch-growth.yaml"
DEFAULT_NOTIFY_LINES = 1000
SRC_PREFIX = "src/"
_KNOWN_KEYS = {"notify_src_lines"}

EXIT_OK = 0
EXIT_OVER = 1
EXIT_CANNOT_CHECK = 2


class GrowthError(RuntimeError):
    """줄 수를 셀 수 없다(설정 오류, git 실패). 검사 불능으로 이어진다."""


def load_threshold(text: str | None) -> int:
    """설정 파일 내용에서 알림 기준 줄 수를 읽는다. 없거나 비면 기본값."""
    try:
        data = yaml.safe_load(text) if text else None
    except yaml.YAMLError as exc:
        raise GrowthError(f"{CONFIG_PATH} 이 올바른 YAML 이 아니다: {exc}") from exc
    if data is None:
        return DEFAULT_NOTIFY_LINES
    if not isinstance(data, dict):
        raise GrowthError(f"{CONFIG_PATH} 의 최상위는 키와 값의 목록이어야 한다")
    unknown = sorted(set(data) - _KNOWN_KEYS)
    if unknown:
        raise GrowthError(f"{CONFIG_PATH} 에 알 수 없는 키가 있다: {', '.join(map(str, unknown))}")
    value = data.get("notify_src_lines", DEFAULT_NOTIFY_LINES)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GrowthError(f"{CONFIG_PATH} 의 notify_src_lines 는 1 이상의 정수여야 한다")
    return value


def count_src_lines(numstat: str, prefix: str = SRC_PREFIX) -> tuple[int, list[str]]:
    """`git diff --numstat -z --no-renames` 출력에서 `prefix` 아래 파일의 추가+삭제 줄을 합친다.

    `-z` 출력은 `추가<탭>삭제<탭>경로<NUL>` 레코드이고 경로를 따옴표로 감싸지 않는다(한글 경로도 그대로). 못 읽은
    레코드는 조용히 버리지 않고 `GrowthError`(검사 불능)로 낸다. 줄로 셀 수 없는 파일(바이너리, numstat 이 `-`
    로 냄)은 합에 넣지 않고 경로를 두 번째 값으로 돌려준다.
    """
    total = 0
    uncounted: list[str] = []
    for raw in numstat.split("\0"):
        if not raw:
            continue
        parts = raw.split("\t", 2)
        if len(parts) != 3 or not parts[2]:
            raise GrowthError(f"git numstat 출력을 읽지 못했다: {raw!r}")
        added, deleted, path = parts
        if not path.startswith(prefix):
            continue
        if added == "-" and deleted == "-":
            uncounted.append(path)
            continue
        try:
            total += int(added) + int(deleted)
        except ValueError as exc:
            raise GrowthError(f"git numstat 줄 수를 읽지 못했다: {raw!r}") from exc
    return total, uncounted


def judge(lines: int, threshold: int) -> str:
    """기준을 넘으면(초과) `over`, 아니면 `ok`."""
    return "over" if lines > threshold else "ok"


def _git(args: list[str], cwd: Path) -> str:
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=cwd
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GrowthError(f"git 을 실행하지 못했다: {exc}") from exc
    if done.returncode != 0:
        raise GrowthError(f"git {' '.join(args[:2])} 실패: {(done.stderr or '').strip()[:200]}")
    return done.stdout


def evaluate(base: str, repo: Path) -> dict:
    """저장소 `repo` 에서 `origin/{base}...HEAD` 의 `src/` 변경 줄을 기준과 견준 결과를 돌려준다."""
    if not (repo / "src").is_dir():
        # 브랜치가 src/ 를 통째로 지웠을 수 있다. 기준 쪽에 src/ 추적 파일이 있으면 지운 줄을 세야 하므로 적용한다.
        tracked = _git(["ls-tree", "-r", "--name-only", f"origin/{base}", "--", SRC_PREFIX], repo)
        if not tracked.strip():
            return {"status": "not_applicable", "reason": "src/ 가 없는 저장소"}
    config = repo / CONFIG_PATH
    try:
        text = config.read_text(encoding="utf-8") if config.is_file() else None
    except OSError as exc:
        raise GrowthError(f"{CONFIG_PATH} 을 읽지 못했다: {exc}") from exc
    threshold = load_threshold(text)
    numstat = _git(["diff", "--numstat", "-z", "--no-renames", f"origin/{base}...HEAD", "--", SRC_PREFIX], repo)
    lines, uncounted = count_src_lines(numstat)
    return {
        "status": judge(lines, threshold),
        "src_lines": lines,
        "threshold": threshold,
        "uncounted": uncounted,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="branch_growth", description="브랜치의 src/ 변경 줄이 알림 기준을 넘었는지 본다.")
    p.add_argument("--base", default="main", help="기준 브랜치 이름(origin/{base} 와 견준다)")
    p.add_argument("--repo", default=".", help="저장소 폴더")
    p.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로 낸다")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = evaluate(args.base, Path(args.repo))
    except GrowthError as exc:
        result = {"status": "cannot_check", "reason": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        st = result["status"]
        if st in ("ok", "over"):
            print(f"{st}: src/ 변경 {result['src_lines']}줄 (기준 {result['threshold']}줄)")
            if result["uncounted"]:
                print(f"줄 수를 셀 수 없는 파일 {len(result['uncounted'])}개: {', '.join(result['uncounted'])}")
        else:
            print(f"{st}: {result['reason']}")
    return {"ok": EXIT_OK, "not_applicable": EXIT_OK, "over": EXIT_OVER}.get(result["status"], EXIT_CANNOT_CHECK)


if __name__ == "__main__":
    sys.exit(main())
