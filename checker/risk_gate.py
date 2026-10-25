"""PR 위험도를 판정해, 위험한 PR 에만 사람의 승인을 요구한다(#102).

처음에는 "모든 PR 에 승인" 을 요구하려 했다. 하지만 작성자는 자기 PR 을 승인할 수
없고 Claude 도 소유자 계정으로 PR 을 올리므로, 승인자가 한 명이면 그 방식은
돌아가지 않는다. 그래서 기계로 볼 수 있는 것은 엄격하게 검사하고, 위험하다고
판정된 PR 만 사람이 승인하게 한다. 위험하지 않은 PR 은 승인 없이 병합할 수 있다.

**기준은 데이터다(CLAUDE.md 원칙 2).** 대상 저장소의 `.github/risk-gate.yaml` 이
기준을 정하고, 이 파일이 없으면 게이트는 꺼진 것이다(통과, 종료코드 0). 파일은 PR 이
아니라 **base 브랜치**에서 읽는다 — PR 이 자기 기준을 스스로 느슨하게 만들 수 없게
하기 위해서다(`ssot-approvers`, `human-merge-paths` 와 같다). 기준 하나는 `criterion`
데코레이터로 등록한 작은 함수 하나다. 새 기준을 더할 때는 함수를 하나 등록하면
되고 판정 흐름(`evaluate`, `decide_pr`)은 고치지 않는다.

기준(`CRITERIA`):

- `size`      바뀐 줄(추가+삭제)과 파일 수가 기준을 넘는가. `size_warn_only_paths` 가 비어 있지 않고 PR 이 바꾼
              파일이 모두 그 접두어 아래면 승인 사유가 아니라 참고(note)로만 낸다(#436, 결과의 `notes`).
- `paths`     `high_risk_paths` 와 `.github/human-merge-paths` 의 경로를 바꿨는가.
- `secret`    추가된 줄에 토큰·키·비밀번호·웹훅 주소 모양이 있는가(CR-004 의 기계 검사).
              보고에는 파일:줄과 패턴 이름만 담고 값은 절대 담지 않는다.
- `checks`    이 PR 의 다른 검사(check run, commit status)가 실패했거나 진행 중인가.
              게이트 자신(`risk-gate`)과 같은 PR 에서 도는 `ssot-approval`, `alert` 는 뺀다.
              자신을 세면 "자기 자신이 끝나길 기다리는" 교착이 생기기 때문이다. 합친 job `pr-checks`·`pr-review`·`main-checks` 도
              같은 이유로 뺀다(#417) — 그 안의 단계 결과는 옛 이름의 commit status 로 센다.
- `split_hint` `srs_split_hint`(기본 켬)일 때, SRS 에 새 요구사항이 생겼고 기존 요구사항을 넓힌 것처럼
              보이는 근거(상세 절의 다른 번호 언급, 범위 "하지 않는 것" 줄 변경, 제목 겹침)가 있는가(#278).
              막는 기준이 아니라 승인자에게 근거를 보여 주는 사유다. SRS diff 를 못 읽으면 검사 불능 사유다.
- `write_auth` 바뀐 `.abap` 파일(head 내용)에 CR-009 경고가 있는가 — behavior pool 의 권한 메서드가
              `auth-allowed` 만 대입하고 파일에 `AUTHORITY-CHECK` 가 없다(#361). 쓰기 앱이 권한 검사 없이
              들어오는 것을 승인자가 보게 한다. 설정 키가 없다: 게이트가 켜져 있으면 항상 본다(옛 설정
              파일이 모르는 키로 판정 불능이 되지 않게). 파일을 못 읽으면 판정 불능 사유다.
- `ai_review` 설정에서 켠 때만 본다. 이름이 `ai-review` 인 check run 의 결론을 읽는다
              (success 면 통과, 그 밖의 결론이면 결론별 사유 — `ai_review_reasons`). 그 check run 은
              재사용 워크플로 `ai-review.yml`(#125)이 만든다. 심각한 지적, 일부만 봄, 검사 불능,
              취소, 시간 초과, 돌지 않음을 뭉개지 않고 나눠 적는다(#360).
              없거나 끝나지 않았으면 대기로 본다. 단 `ai_review_paths` 가 비어 있지 않은데 PR 이 바꾼
              파일 가운데 그 접두어 아래가 하나도 없으면 AI 리뷰 대상이 아니라 대기 없이 통과로 본다(#411).

위험한 PR 은 승인자 목록(`approvers_file`, 기본 `.github/ssot-approvers`)에서 **그 PR 작성자에게
정해진 승인자(작성자 본인 제외)가 PR 의 마지막 커밋에 Approve** 해야 통과한다. 목록은
`<작성자>: <승인자> ...` 줄(작성자 전용)과 `*:` 줄·옛 형식 줄(전용 줄이 없는 작성자 모두)로 적는다
(`ssot_approval.parse_approvers`). 이 판정은 `ssot_approval.evaluate_approval`(#119)을 그대로
쓴다. 작성자를 뺀 승인 가능한 사람이 하나도 없으면 승인으로 풀 수 없다고 사유와 다음 할 일을 밝힌다.

세 곳이 같은 `decide_pr` 를 부른다 — PR 검사 workflow(`risk-gate.yml` 의 `check`), 병합 뒤
감지(`after-merge`, `decide_commit`), Claude 병합 Hook. 셋이 같은 코드로 같은 판정을 내려야
"위험하다" 의 뜻이 갈라지지 않는다.

**종료코드.** 0 통과(게이트 꺼짐, 위험하지 않음, 위험하지만 최신 커밋에 승인됨), 1 승인
필요한데 없음, 2 판정 불가. 모르는 것을 통과로 답하지 않는다(원칙 7) — 네트워크·권한
오류, 설정 파일이 잘못된 경우, head 커밋을 모르는 경우 모두 2 다.

**검사 진행 중 대기.** PR 이 열리면 다른 검사와 게이트가 동시에 시작된다. `--wait-checks` 를
주면 사유가 "다른 검사가 아직 진행 중" 뿐일 때 그 검사가 끝날 때까지 정해진 시간 안에서
기다렸다가 다시 판정한다. 그래서 검사 순서 때문에 게이트가 헛되이 빨간불이 되지 않는다.

**AI 리뷰 사전 판정(`precheck-pr`, #125, #360).** AI 리뷰는 위험한 PR 에도 돌린다 — 위험한 PR
일수록 AI 가 한 번이라도 보는 안전망이 필요하다. 위험 PR 은 AI 리뷰에 더해 승인자 Approve 도
필요하다(승인 판정은 그대로). `ai-review.yml` 이 리뷰를 돌리기 전에 이 하위 명령으로 설정을 확인하고,
base 의 기준 가운데 `size`·`paths`·`secret` 을 평가해 `risky`·`reasons` 로 출력한다(코멘트에
"위험 PR" 안내를 적는 데 쓴다. 크기·경로 위험은 리뷰를 막지 않는다). `checks`·`ai_review` 는 뺀다 —
`checks` 는 이 AI 리뷰 자신을 기다리는 교착을 만들고, `ai_review` 는 이 리뷰의 결과를 읽는 기준이기 때문이다.
**유일한 예외는 비밀값이다.** 새로 들어온 줄에 `SECRET_PATTERNS` 가 실제로 보이면(`secret_found`, 패턴 이름은
`secret_patterns`) diff 를 외부 AI 에 보내지 않도록 리뷰를 돌리지 않는다. 대신 `ai-review` 검사를 실패시켜
통과로 보이지 않게 하고, "검사 불능 — 승인자가 직접 확인" 이라고 밝힌다. "변경이 너무 커서 비밀값 검사를 못 함"
(`unscanned_files`)은 여기에 넣지 않는다 — 큰 PR 은 계속 리뷰한다.
종료코드: 0 AI 리뷰를 돌려도 됨(설정이 있고 `ai_review: true`; 크기·경로 위험과 무관), 3 돌리지
않음(설정 없음, `ai_review: false`, `ai_review_paths` 에 걸린 파일 없음 — 사유를 출력), 4 비밀값이 보여 돌리지 않음(실패 처리), 2 판정 불가.
1 은 쓰지 않는다. 4 는 새 코드라 옛 워크플로는 "판정 불능"(2 와 같은 쪽)으로 읽고 역시 리뷰를 돌리지 않는다.

**AI 리뷰 결과 읽기(`ai_review_reasons`, #360).** `ai-review` check run 의 결론을 구분해 사유를
적는다 — success 는 통과, failure 는 같은 head sha 의 PR 코멘트 표식
(`<!-- ai-review-result {...} -->`)을 읽어 심각한 지적·일부만 봄·검사 불능을 가르고(표식이 없거나
sha 가 다르면 일반 문구; 비밀값 의심으로 리뷰를 건너뛴 표식 `secret` 은 "승인자가 직접 확인"), cancelled·timed_out·skipped·neutral 은 "검사하지 못함" 이다. 표식을 못 읽어도
(코멘트 조회 실패 포함) 판정 불능으로 뭉개지 않고 일반 문구로 둔다. 다른 검사(`checks`)의 `_run_state` 는 그대로다.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable

import yaml

from checker.code_rules import check_source, language_for_suffix
from checker.model import ConfigError as CodeConfigError
from checker.rules.req_cross_reference import DEFAULT_EXCLUDE, DEFAULT_PREFIX, collect_mentions, parse_sections
from checker.ssot_approval import (
    EXIT_NOT_APPROVED,
    EXIT_OK,
    EXIT_UNKNOWN,
    GhClient,
    GhError,
    ParsedApprovers,
    _normalize,
    evaluate_approval,
    fetch_commit_associated_prs,
    fetch_human_merge_paths,
    fetch_pr_info,
    fetch_pr_reviews,
    human_merge_hits,
    approvers_for,
    parse_approvers,
)

CONFIG_PATH = ".github/risk-gate.yaml"

# workflow 의 게이트 job 이름과 같아야 한다. caller 의 job id 가 이 값이라 check run 이름이
# `risk-gate / check` 처럼 나온다. 이름이 이 값(또는 `이 값 / ...`)인 check 는 세지 않는다.
OWN_CHECK_NAME = "risk-gate"
# 같은 PR 에서 함께 도는 보조 검사. `ssot-approval` 은 SRS 승인 여부를, `alert` 는
# human-merge-alert 의 알림 job 이다. 둘은 이 게이트의 사유(경로·승인)와 겹치거나 검사
# 결과가 아니라 알림이므로 "검사 실패" 로 세지 않는다.
# `merge-order` 는 pr-queue 워크플로가 다는 병합 순서 커밋 status(#370)다. 앞 PR 이 열려 있으면
# pending(#401 전엔 failure)인데, 그것은 이 PR 의 위험도나 검사 결과가 아니라 병합 시점의 문제이므로 같은 사유를
# 두 번 쌓거나 승인 판정을 오염시키지 않게 세지 않는다.
# 같은 이유로 그 워크플로의 job(`pr-queue / queue`)도 뺀다. 저장소 전체에 하나의 concurrency 그룹이라
# 다른 PR 의 실행이 이 실행을 취소하면 그 PR 의 커밋에 취소된 검사가 남아, 병합 순서와 무관한 PR 이
# "검사 실패" 로 보이기 때문이다. 이 job 이 실패한 사유(GitHub 를 못 읽음)는 PR 의 문제가 아니다.
MERGE_ORDER_CHECK = "merge-order"
PR_QUEUE_CHECK = "pr-queue"
# `pr-checks` 는 PR 검사를 한 job 으로 합친 워크플로의 job(`pr-checks / check`)이다(#412, #417).
# risk-gate 단계가 그 안에서 돌므로, 이 job 을 `checks` 기준이 세면 게이트가 자기가 든 job 이
# 끝나길 기다리는 교착이 된다. job 의 실패는 단계가 옛 이름(`gitleaks`·`doc-guard`·…)으로 단
# commit status 로 이미 세어진다.
# `pr-review`(리뷰 이벤트의 재판정)와 `main-checks`(main push 의 병합 뒤 감지)도 risk-gate 를
# 안에서 돌리는 합친 job 이라 같은 이유로 뺀다(#419).
PR_CHECKS_JOB = "pr-checks"
PR_REVIEW_JOB = "pr-review"
MAIN_CHECKS_JOB = "main-checks"
EXCLUDED_CHECK_GROUPS = frozenset(
    {OWN_CHECK_NAME, "ssot-approval", MERGE_ORDER_CHECK, PR_QUEUE_CHECK, PR_CHECKS_JOB, PR_REVIEW_JOB, MAIN_CHECKS_JOB}
)
EXCLUDED_CHECK_NAMES = frozenset({"alert"})
AI_REVIEW_CHECK_NAME = "ai-review"

DEFAULT_HIGH_RISK_PATHS = [
    "docs/ssot/",
    "docs/spec/",
    "rules/",
    "templates/",
    "conventions/",
    ".github/",
    ".claude/",
    "CLAUDE.md",
]

DEFAULT_CONFIG: dict = {
    "max_changed_lines": 300,
    "max_changed_files": 10,
    "high_risk_paths": DEFAULT_HIGH_RISK_PATHS,
    "secret_scan": True,
    "require_checks_green": True,
    "ai_review": False,
    # AI 리뷰 대상 경로(접두어). 비어 있으면 모든 PR 이 대상이다. 비어 있지 않으면 PR 이 바꾼 파일 가운데 이
    # 접두어 아래가 하나라도 있어야 대상이다. `high_risk_paths` 와 같은 접두어 매칭이라 `src/` 는 호출
    # 워크플로의 `paths: ['src/**']` 와 같은 뜻이다(#411).
    "ai_review_paths": [],
    # 비어 있지 않으면, PR 이 바꾼 파일이 모두 이 접두어 아래일 때 `size` 기준을 승인 사유 대신 참고(note)로 낸다(#436).
    "size_warn_only_paths": [],
    "srs_split_hint": True,
    "approvers_file": ".github/ssot-approvers",
}

_INT_KEYS = ("max_changed_lines", "max_changed_files")
_BOOL_KEYS = ("secret_scan", "require_checks_green", "ai_review", "srs_split_hint")
_LIST_KEYS = ("high_risk_paths", "ai_review_paths", "size_warn_only_paths")

_MAX_LISTED = 5  # 사유에 이름을 나열하는 최대 개수


class ConfigError(RuntimeError):
    """`.github/risk-gate.yaml` 을 해석하지 못했다. 판정 불가(EXIT_UNKNOWN)로 이어진다."""


# --- 설정 ---------------------------------------------------------------------


def load_config(text: str | None) -> dict:
    """`.github/risk-gate.yaml` 을 읽어 빠진 키를 기본값으로 채운다.

    비어 있거나 주석뿐인 파일은 전부 기본값이다. 모르는 키나 잘못된 타입은 조용히 넘기지
    않고 `ConfigError` 로 알린다 — 오타 하나(`secret_scna: false`)가 기준을 몰래 바꾸거나
    무시되는 것을 막기 위해서다.
    """
    try:
        data = yaml.safe_load(text) if text else None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{CONFIG_PATH} 이 올바른 YAML 이 아니다: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_PATH} 의 최상위는 키와 값의 목록이어야 한다")

    unknown = sorted(set(data) - set(DEFAULT_CONFIG))
    if unknown:
        raise ConfigError(f"{CONFIG_PATH} 에 알 수 없는 키가 있다: {', '.join(map(str, unknown))}")

    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_CONFIG.items()}
    for key, value in data.items():
        if key in _INT_KEYS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConfigError(f"{CONFIG_PATH} 의 {key} 는 0 이상의 정수여야 한다")
        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise ConfigError(f"{CONFIG_PATH} 의 {key} 는 true 또는 false 여야 한다")
        elif key in _LIST_KEYS:
            if value is None:
                value = []
            if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
                raise ConfigError(f"{CONFIG_PATH} 의 {key} 는 문자열 목록이어야 한다")
        elif key == "approvers_file":
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{CONFIG_PATH} 의 approvers_file 은 경로 문자열이어야 한다")
        cfg[key] = value
    return cfg


# --- 기준별 순수 함수 -----------------------------------------------------------


def size_reasons(files: list[dict], cfg: dict) -> list[str]:
    """바뀐 줄·파일 수가 기준을 넘으면 사유를 돌려준다. `files` 는 PR files API 의 항목."""
    lines = sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in files)
    reasons: list[str] = []
    if lines > cfg["max_changed_lines"]:
        reasons.append(f"바뀐 줄이 {lines}줄로 기준({cfg['max_changed_lines']}줄)을 넘음")
    if len(files) > cfg["max_changed_files"]:
        reasons.append(f"바뀐 파일이 {len(files)}개로 기준({cfg['max_changed_files']}개)을 넘음")
    return reasons


def ai_review_target(files: list[str], prefixes: list[str]) -> bool:
    """이 PR 이 AI 리뷰 대상인가(#411). 접두어 목록이 비면 모든 PR 이 대상이고, 아니면 바뀐 파일 중 하나라도
    접두어 아래여야 한다. 매칭은 `path_reasons` 와 같다."""
    normalized = [_normalize(p) for p in prefixes if _normalize(p)]
    if not normalized:
        return True
    return bool(human_merge_hits(files, normalized))


def all_under(files: list[str], prefixes: list[str]) -> bool:
    """접두어 목록이 비어 있지 않고, 바뀐 파일이 있고, 그 모두가 접두어 아래인가(#436). 매칭은 `path_reasons` 와 같다."""
    normalized = [_normalize(p) for p in prefixes if _normalize(p)]
    if not normalized or not files:
        return False
    return len(human_merge_hits(files, normalized)) == len(files)


def path_reasons(files: list[str], prefixes: list[str]) -> list[str]:
    """위험 경로 아래 파일을 바꿨으면 사유를 돌려준다."""
    normalized = [_normalize(p) for p in prefixes if _normalize(p)]
    hits = human_merge_hits(files, normalized)
    if not hits:
        return []
    shown = ", ".join(hits[:_MAX_LISTED])
    more = f" 등 {len(hits)}개" if len(hits) > _MAX_LISTED else ""
    return [f"위험 경로를 바꿈: {shown}{more}"]


# 비밀값 패턴. 값은 어디에도 남지 않고 패턴 이름과 위치(파일:줄)만 보고된다.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("비공개 키 블록", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS 액세스 키 ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub 토큰", re.compile(r"(?:gh[pos]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("Anthropic 키", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("Slack 토큰", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{8,}")),
    (
        "비밀번호·토큰 대입",
        re.compile(
            r"""(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*["'][^"'\s]{8,}["']""",
            re.IGNORECASE,
        ),
    ),
    (
        "Teams·Power Automate 웹훅 주소",
        re.compile(
            r"https?://[^\s\"'<>]*(?:logic\.azure\.com|environment\.api\.powerplatform\.com)"
            r"[^\s\"'<>]*[?&]sig=[A-Za-z0-9_\-]+"
        ),
    ),
]

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(files: list[dict]) -> list[tuple[str, int, str]]:
    """PR files 의 patch 에서 추가된 줄을 (파일, 새 파일의 줄 번호, 내용) 으로 뽑는다."""
    out: list[tuple[str, int, str]] = []
    for entry in files:
        patch = entry.get("patch")
        name = entry.get("filename") or ""
        if not patch:
            continue
        lineno = 0
        for raw in patch.splitlines():
            m = _HUNK.match(raw)
            if m:
                lineno = int(m.group(1))
                continue
            if raw.startswith("+"):
                out.append((name, lineno, raw[1:]))
                lineno += 1
            elif raw.startswith("-") or raw.startswith("\\"):
                continue
            else:
                lineno += 1
    return out


def secret_reasons(lines: list[tuple[str, int, str]]) -> list[str]:
    """추가된 줄에서 비밀값 모양을 찾아 패턴 이름별로 `파일:줄` 만 보고한다.

    값은 사유 문자열에 넣지 않는다 — 이 사유는 PR 코멘트·이슈·Hook 거부 메시지로 퍼지기
    때문이다.
    """
    found: dict[str, list[str]] = {}
    for name, lineno, text in lines:
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                found.setdefault(label, []).append(f"{name}:{lineno}")
    reasons: list[str] = []
    for label, places in found.items():
        shown = ", ".join(places[:_MAX_LISTED])
        more = f" 등 {len(places)}곳" if len(places) > _MAX_LISTED else ""
        reasons.append(f"비밀값으로 보이는 줄이 추가됨({label}): {shown}{more}")
    return reasons


def secret_pattern_names(lines: list[tuple[str, int, str]]) -> list[str]:
    """추가된 줄에서 보인 비밀값 패턴의 이름만(중복 없이 패턴 정의 순서로). 값·위치는 돌려주지 않는다.

    ai-review 코멘트·표식에 쓰인다. 위치(파일:줄)는 `secret_reasons` 사유로 job 로그에 따로 남는다.
    """
    return [label for label, pattern in SECRET_PATTERNS if any(pattern.search(text) for _n, _l, text in lines)]


def unscanned_files(files: list[dict]) -> list[str]:
    """바뀐 줄이 있는데 patch 가 없어(너무 큰 diff) 비밀값 검사를 못 한 파일."""
    return [
        f.get("filename") or ""
        for f in files
        if not f.get("patch") and int(f.get("additions") or 0) + int(f.get("deletions") or 0) > 0
    ]


def _check_group(name: str) -> str:
    return (name or "").split(" / ", 1)[0].strip()


def _is_excluded_check(name: str) -> bool:
    return _check_group(name) in EXCLUDED_CHECK_GROUPS or (name or "").strip() in EXCLUDED_CHECK_NAMES


def _run_state(run: dict) -> str:
    """check run 하나를 "pass" / "fail" / "pending" 으로 가른다."""
    if (run.get("status") or "") != "completed":
        return "pending"
    if (run.get("conclusion") or "") in ("success", "neutral", "skipped"):
        return "pass"
    return "fail"


def _names(runs: list[dict]) -> str:
    names = [r.get("name") or "이름 없는 검사" for r in runs]
    shown = ", ".join(names[:_MAX_LISTED])
    return shown + (f" 등 {len(names)}개" if len(names) > _MAX_LISTED else "")


def checks_reasons(check_runs: list[dict], skip_ai_review: bool = False) -> tuple[list[str], list[str]]:
    """다른 검사의 실패·진행 중 사유를 (실패 사유, 대기 사유) 로 돌려준다.

    게이트 자신과 보조 검사는 뺀다(모듈 docstring). `skip_ai_review` 면 `ai-review` 는
    여기서 세지 않고 `ai_review` 기준이 따로 읽는다.
    """
    failed: list[dict] = []
    pending: list[dict] = []
    for run in check_runs:
        name = run.get("name") or ""
        if _is_excluded_check(name):
            continue
        if skip_ai_review and _check_group(name) == AI_REVIEW_CHECK_NAME:
            continue
        state = _run_state(run)
        if state == "fail":
            failed.append(run)
        elif state == "pending":
            pending.append(run)
    fail_reasons = [f"다른 검사가 실패함({len(failed)}개): {_names(failed)}"] if failed else []
    wait_reasons = [f"다른 검사가 아직 끝나지 않음({len(pending)}개): {_names(pending)}"] if pending else []
    return fail_reasons, wait_reasons


AI_REVIEW_RESULT_MARKER = re.compile(r"<!--\s*ai-review-result\s+(\{.*?\})\s*-->", re.DOTALL)
AI_REVIEW_COMMENT_MARKER = "<!-- ai-review -->"
_AI_SUMMARY_LIMIT = 100  # 사유에 인용하는 AI 지적 요약의 최대 길이
_AI_FINDINGS_SHOWN = 3
_AI_GENERIC_FAIL = "AI 리뷰 검사가 실패함(심각한 지적 또는 AI 리뷰 검사 불능 — ai-review 결과 코멘트를 확인)"


AI_REVIEW_COMMENT_AUTHOR = "github-actions[bot]"
_AI_FILE_LIMIT = 200  # 사유에 인용하는 파일 경로의 최대 길이


def _is_ai_review_author(comment: dict) -> bool:
    """ai-review 코멘트를 쓴 계정인지. 워크플로가 `github.token` 으로 쓰므로 github-actions 봇이다.

    `type == "Bot"` 만으로는 어떤 GitHub App 이든 통과해서 login 도 함께 본다. 누구나 PR 에 코멘트를 쓸 수
    있으므로, 사람이 쓴 가짜 표식이 사유(와 `build_next` 안내)에 섞이지 않게 막는다.
    """
    user = comment.get("user")
    return isinstance(user, dict) and user.get("type") == "Bot" and user.get("login") == AI_REVIEW_COMMENT_AUTHOR


def _defuse(text: object, limit: int) -> str:
    """사유에 넣을 외부 문자열: 한 줄로 줄이고 길이를 자르고 `@` 멘션을 무력화한다."""
    text = " ".join(str(text).split()).replace("@", "@​")
    return text if len(text) <= limit else text[:limit] + "..."


def parse_ai_review_marker(comments: list[dict], head_sha: str) -> dict | None:
    """PR 코멘트에서 `head_sha` 와 같은 sha 의 ai-review 결과 표식을 찾아 돌려준다. 없으면 None.

    봇(`github-actions[bot]`)이 쓴 ai-review 코멘트(마커 `<!-- ai-review -->`)의 표식만 읽는다. 코멘트
    하나에 표식 모양이 여럿이면 마지막 것을 쓴다(진짜 표식은 항상 본문 맨 끝에 붙는다). 코멘트가 여럿이면
    마지막 코멘트의 것을 쓴다. 표식의 JSON 이 깨졌거나 sha 가 다르면(낡은 결과) 없는 것으로 본다.
    """
    found = None
    for c in comments:
        if not isinstance(c, dict) or not _is_ai_review_author(c):
            continue
        body = c.get("body") or ""
        if AI_REVIEW_COMMENT_MARKER not in body:
            continue
        matches = AI_REVIEW_RESULT_MARKER.findall(body)
        if not matches:
            continue
        try:
            data = json.loads(matches[-1])
        except ValueError:
            continue
        if isinstance(data, dict) and head_sha and data.get("sha") == head_sha:
            found = data
    return found


def _marker_reason(marker: dict) -> str | None:
    """표식 하나를 사유 문장으로. 사유로 쓸 수 없는 표식(pass 등)이면 None."""
    status = marker.get("status")
    if status == "fail":
        items = [i for i in (marker.get("findings") or []) if isinstance(i, dict)]
        shown = []
        for i in items[:_AI_FINDINGS_SHOWN]:
            summary = _defuse(i.get("summary") or "", _AI_SUMMARY_LIMIT)
            file = _defuse(i.get("file") or "?", _AI_FILE_LIMIT)
            shown.append(f"{file}:{i.get('line') or '?'} {summary}".rstrip())
        count = marker.get("serious")
        count = count if isinstance(count, int) and not isinstance(count, bool) else len(items)
        text = f"AI 리뷰 심각한 지적 {count}건"
        if shown:
            text += ": " + "; ".join(shown) + (" 등" if count > len(shown) else "")
        left = marker.get("unreviewed")
        if isinstance(left, int) and not isinstance(left, bool) and left > 0:
            text += f" (일부만 봄: 못 본 파일 {left}개)"
        return text
    if status == "partial":
        n = marker.get("unreviewed")
        n = n if isinstance(n, int) and not isinstance(n, bool) else 0
        left = f"못 본 파일 {n}개" if n else "못 본 파일 목록 없음"
        return f"AI 리뷰가 일부만 봄({left}) — 승인자가 나머지를 확인"
    if status == "unavailable":
        return "AI 리뷰 검사 불능 — 이 PR 의 코드 문제가 아니라 AI 리뷰를 돌리지 못함, ai-review 결과 코멘트를 확인하고 다시 실행"
    if status == "secret":
        return "비밀값 의심이라 AI 리뷰를 돌리지 않음(diff 를 외부 AI 에 보내지 않기 위해) — 승인자가 직접 확인"
    if status == "skip":
        return "AI 리뷰가 돌지 않음(표식 skip) — 검사하지 못함"
    return None


def ai_review_reasons(
    check_runs: list[dict],
    load_comments: Callable[[], list[dict]] | None = None,
    head_sha: str = "",
) -> tuple[list[str], list[str]]:
    """`ai-review` check run 을 읽어 (지적 사유, 대기 사유) 를 돌려준다.

    결론마다 사유를 나눈다(#360). failure·success 는 `load_comments` 로 PR 코멘트를 읽어 같은 `head_sha` 의
    결과 표식으로 보강한다. 코멘트를 못 읽거나 표식이 없거나 sha 가 다르면 표식 없음으로 둔다.
    """
    runs = [r for r in check_runs if _check_group(r.get("name") or "") == AI_REVIEW_CHECK_NAME]
    if not runs:
        return [], ["AI 리뷰 결과(ai-review 검사)가 아직 없음"]

    marker_cache: list[dict | None] = []

    def marker() -> dict | None:
        if not marker_cache:
            found = None
            if load_comments is not None:
                try:
                    found = parse_ai_review_marker(load_comments(), head_sha)
                except Exception:  # noqa: BLE001 - 코멘트를 못 읽는 것이 판정 불능이 되면 안 된다(일반 문구로 둔다)
                    found = None
            marker_cache.append(found)
        return marker_cache[0]

    reasons: list[str] = []
    pending = False
    for run in runs:
        if _run_state(run) == "pending":
            pending = True
            continue
        conclusion = run.get("conclusion") or ""
        if conclusion == "success":
            # 성공인데 같은 sha 의 표식이 다른 결과를 말하면 표식을 믿지 않고 check 결론을 따르는 대신,
            # 보수적으로 승인자가 보게 사유로 올린다(통과로 가린 실패보다 불필요한 사유가 낫다).
            m = marker()
            reason = _marker_reason(m) if m else None
            if reason:
                reasons.append(reason + " (검사 결론은 success 였으나 결과 코멘트가 다름)")
        elif conclusion == "failure":
            m = marker()
            reasons.append((_marker_reason(m) if m else None) or _AI_GENERIC_FAIL)
        elif conclusion == "cancelled":
            reasons.append("AI 리뷰가 취소돼 검사하지 못함 — ai-review 를 다시 실행")
        elif conclusion == "timed_out":
            reasons.append("AI 리뷰가 시간 초과로 검사하지 못함 — 다시 실행")
        elif conclusion in ("skipped", "neutral"):
            reasons.append(f"AI 리뷰가 돌지 않음(결론 {conclusion}) — 검사하지 못함")
        else:
            reasons.append(f"AI 리뷰 검사 불능 — 알 수 없는 결론({conclusion or '없음'}), ai-review 를 다시 실행")
    if reasons:
        return list(dict.fromkeys(reasons)), []
    if pending:
        return [], ["AI 리뷰가 아직 끝나지 않음"]
    return [], []


# --- SRS 쪼개짐 의심(#278) ---------------------------------------------------------

SRS_PATH = "docs/ssot/SRS.md"
# SRS 범위 절의 "- 하지 않는 것:" 목록 머리말(`templates/harness/SRS.md` 의 틀). 이 줄과 그 아래로 더 들여쓴 줄이 목록이다.
SCOPE_EXCLUDED_MARKER = "하지 않는 것"
MIN_TITLE_LEN = 4  # 포함 비교에서 이보다 짧은 제목은 뺀다(`reserve_number.py` 와 같은 기준)

_REQ_ROW = re.compile(r"^\s*\|\s*(REQ-\d+)\s*\|\s*([^|]*?)\s*\|")
_FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})")
_SCOPE_HEAD = re.compile(r"^(\s*)[-*]\s*" + re.escape(SCOPE_EXCLUDED_MARKER))
_SHORT = 60  # 사유에 인용하는 줄의 최대 길이


def _unfenced(text: str) -> list[str]:
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        fm = _FENCE_LINE.match(line)
        if fm:
            fence = fm.group(1)[0] if fence is None else (None if fm.group(1)[0] == fence else fence)
            continue
        if fence is None:
            out.append(line)
    return out


def req_titles(text: str) -> dict[str, str]:
    """요구사항 표의 `| REQ-nnn | 제목 |` 줄에서 {번호: 제목}."""
    titles: dict[str, str] = {}
    for line in _unfenced(text):
        m = _REQ_ROW.match(line)
        if m:
            titles.setdefault(m.group(1), m.group(2))
    return titles


_ID_NUM = re.compile(r"^(REQ|DEV)-(\d+)$")


def titled_id(rid: str, *title_maps: dict[str, str]) -> str:
    """`REQ-001` → `REQ-001(제목)`(#308). DEV 번호는 같은 숫자의 REQ 제목을 쓴다. 어느 표에도 없으면 `(제목 미확인)`."""
    m = _ID_NUM.match(rid)
    if not m:
        return rid
    n = int(m.group(2))
    for titles in title_maps:
        for key, title in titles.items():
            km = _ID_NUM.match(key)
            if km and int(km.group(2)) == n and title:
                return f"{rid}({title})"
    return f"{rid}(제목 미확인)"


def scope_exclusions(text: str) -> list[str]:
    """범위 "하지 않는 것" 목록의 줄들(머리말 줄과 그 아래로 더 들여쓴 줄, 공백 정리)."""
    lines = _unfenced(text)
    for i, line in enumerate(lines):
        m = _SCOPE_HEAD.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        out = [line.strip()]
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            if len(nxt) - len(nxt.lstrip()) <= indent:
                break
            out.append(nxt.strip())
        return out
    return []


def _norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _cut(text: str) -> str:
    return text if len(text) <= _SHORT else text[:_SHORT] + "…"


_ITEM_SEP = ",、;；，"
_ITEM_TRAIL = " \t.。,、;；，"
_ITEM_HEAD = re.compile(r"^[-*]\s*" + re.escape(SCOPE_EXCLUDED_MARKER) + r"\s*[:：]?")
_ITEM_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


def _split_items(text: str) -> list[str]:
    """한 줄 형태의 항목을 `,`·`、`·`;`·` · ` 로 쪼갠다. 괄호 안은 쪼개지 않는다."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for i, ch in enumerate(text):
        if ch in "(（[":
            depth += 1
        elif ch in ")）]":
            depth = max(depth - 1, 0)
        sep = depth == 0 and (ch in _ITEM_SEP or (ch == "·" and text[i - 1:i].isspace() and text[i + 1:i + 2].isspace()))
        if sep:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


# 항목 끝의 꼬리표 `(REQ-001)`, `(REQ-001, REQ-002)` — 그 요구사항에서 뺀 일이라는 표기(#304).
# `plugins/harness/skills/start/reserve_number.py` 의 EXCLUDED_TAG_RE 와 같은 식이어야 한다(테스트가 같은지 본다).
EXCLUDED_TAG_RE = re.compile(r"\s*[(（]\s*(REQ-\d+(?:\s*[,，、]\s*REQ-\d+)*)\s*[)）]\s*$")


def split_excluded_tag(item: str) -> tuple[str, list[str]]:
    """항목 끝의 꼬리표를 떼어 (꼬리표 없는 항목, [REQ 번호…]) 로 돌려준다. 꼬리표가 없으면 번호 목록은 빈 목록."""
    m = EXCLUDED_TAG_RE.search(item)
    if not m:
        return item, []
    return item[:m.start()].rstrip(_ITEM_TRAIL).strip(), re.findall(r"REQ-\d+", m.group(1))


def _scope_entries(text: str) -> dict[str, tuple[str, list[str]]]:
    """"하지 않는 것" 목록의 항목 {정규화한 꼬리표 없는 항목: (꼬리표 없는 원문, REQ 번호 목록)}.

    머리말 줄에 이어 쓴 항목은 쪼개고, 들여쓴 줄은 줄마다 항목이다. 키에 꼬리표가 들어가지 않으므로
    꼬리표만 붙이거나 떼거나 바꾼 변경은 같은 항목이다(항목이 바뀐 근거로 세지 않는다).
    """
    items: dict[str, tuple[str, list[str]]] = {}

    def add(raw: str) -> None:
        shown = re.sub(r"\s+", " ", raw).strip(_ITEM_TRAIL).strip()
        body, reqs = split_excluded_tag(shown)
        if not body:
            return
        if body.casefold() in items:  # 같은 본문이 꼬리표만 달리 두 번 나오면 번호를 합친다
            prev = items[body.casefold()][1]
            prev += [r for r in reqs if r not in prev]
        else:
            items[body.casefold()] = (body, reqs)

    lines = scope_exclusions(text)
    if not lines:
        return items
    for raw in _split_items(_ITEM_HEAD.sub("", lines[0], count=1)):
        add(raw)
    for line in lines[1:]:
        add(_ITEM_BULLET.sub("", line, count=1))
    return items


def scope_items(text: str) -> dict[str, str]:
    """"하지 않는 것" 목록의 항목 {정규화한 항목: 원문}. 끝의 `(REQ-xxx)` 꼬리표는 뗀 항목이다."""
    return {key: body for key, (body, _reqs) in _scope_entries(text).items()}


def split_hint_evidence(base_text: str, head_text: str) -> dict[str, list[str]]:
    """SRS 에 새로 생긴 REQ 마다 "기존 요구사항을 넓힌 것일 수 있다" 는 근거를 모은다. 근거가 없는 REQ 는 뺀다.

    (a) 새 REQ 상세 절이 다른 REQ·DEV 번호를 말한다(`req_cross_reference` 와 같은 파싱, 관계 줄 유무와 무관).
    (b) 같은 PR 에서 범위 "하지 않는 것" 항목이 지워지거나 바뀌었다(항목 단위 비교, 덧붙인 항목은 근거가 아니다).
    (c) 새 제목이 기존 REQ 제목을 포함하거나 그 반대다.

    `base_text` 는 PR 이 갈라진 지점(merge-base)의 SRS 여야 한다. 번호만 바뀐 REQ(head 에서 사라진
    base 번호와 제목이 같은 새 번호)는 새 REQ 로 보지 않는다.
    """
    base_titles = req_titles(base_text)
    head_titles = req_titles(head_text)
    vanished = {_norm_title(t) for rid, t in base_titles.items() if rid not in head_titles}
    new_ids = [
        rid for rid, title in head_titles.items()
        if rid not in base_titles and _norm_title(title) not in vanished
    ]
    if not new_ids:
        return {}

    head_scope = _scope_entries(head_text)
    changed_scope = [
        (orig, reqs) for key, (orig, reqs) in _scope_entries(base_text).items() if key not in head_scope
    ]
    sections = dict(parse_sections(head_text))
    excludes = [re.compile(p) for p in DEFAULT_EXCLUDE]

    result: dict[str, list[str]] = {}
    for rid in new_ids:
        evidence: list[str] = []
        if rid in sections:
            others, _ok, _misplaced = collect_mentions(rid, sections[rid], DEFAULT_PREFIX, excludes)
            if others:
                shown_ids = ", ".join(titled_id(o, head_titles, base_titles) for o in others)
                evidence.append(f"(a) 상세 절이 다른 번호를 말함: {shown_ids}")
        if changed_scope:
            shown = "; ".join(
                f"\"{_cut(ln)}\"" + (f" ({', '.join(titled_id(r, base_titles, head_titles) for r in reqs)} 의 {SCOPE_EXCLUDED_MARKER})" if reqs else "")
                for ln, reqs in changed_scope[:2]
            )
            more = f" 등 {len(changed_scope)}개" if len(changed_scope) > 2 else ""
            evidence.append(f"(b) 범위 \"{SCOPE_EXCLUDED_MARKER}\" 항목이 지워지거나 바뀜: {shown}{more}")
        new = _norm_title(head_titles[rid])
        if len(new) >= MIN_TITLE_LEN:
            overlaps = [
                titled_id(old_id, base_titles)
                for old_id, old_title in base_titles.items()
                if len(_norm_title(old_title)) >= MIN_TITLE_LEN
                and (_norm_title(old_title) in new or new in _norm_title(old_title))
            ]
            if overlaps:
                evidence.append(f"(c) 제목이 기존 요구사항과 겹침: {', '.join(overlaps)}")
        if evidence:
            result[rid] = evidence
    return result


# --- 기준 등록과 판정 흐름 --------------------------------------------------------


@dataclass
class Finding:
    """기준 하나가 낸 사유. `waiting` 이면 시간이 지나면 풀릴 수 있는 사유(진행 중인 검사)다.
    `note` 면 보여 주기만 하고 승인을 요구하지 않는 참고다(#436)."""

    criterion: str
    message: str
    waiting: bool = False
    note: bool = False


@dataclass
class Context:
    """기준 함수들이 읽는 입력. GitHub 호출은 필요할 때만 한다(검사 목록은 느리다)."""

    cfg: dict
    files: list[dict]
    prefixes: list[str]
    load_check_runs: Callable[[], list[dict]]
    # (ref, 경로) -> 파일 내용. 없으면 None. SRS 전문이 필요한 기준(`split_hint`)만 쓴다.
    read_text: Callable[[str, str], str | None] | None = None
    base_ref: str = ""
    head_ref: str = ""
    # PR 이 갈라진 지점(merge-base) 커밋. 주면 `split_hint` 가 base_ref 대신 이것을 기준으로 읽는다.
    merge_base: Callable[[], str | None] | None = None
    # PR 코멘트 목록. `ai_review` 기준이 ai-review 결과 표식을 읽는 데만 쓴다(#360). 없으면 표식 없음으로 본다.
    load_comments: Callable[[], list[dict]] | None = None
    _check_runs: list[dict] | None = field(default=None, repr=False)

    @property
    def filenames(self) -> list[str]:
        return [f.get("filename") or "" for f in self.files]

    def check_runs(self) -> list[dict]:
        if self._check_runs is None:
            self._check_runs = self.load_check_runs()
        return self._check_runs


CRITERIA: list[tuple[str, Callable[[Context], list[Finding]]]] = []


def criterion(name: str):
    """기준 함수를 등록한다. 함수는 `Context` 를 받아 `Finding` 목록을 돌려준다."""

    def register(fn: Callable[[Context], list[Finding]]):
        CRITERIA.append((name, fn))
        return fn

    return register


@criterion("size")
def _crit_size(ctx: Context) -> list[Finding]:
    reasons = size_reasons(ctx.files, ctx.cfg)
    if reasons and all_under(ctx.filenames, ctx.cfg["size_warn_only_paths"]):
        return [Finding("size", f"{r} — 소스만 바뀐 PR 이라 승인은 필요 없음(경고)", note=True) for r in reasons]
    return [Finding("size", r) for r in reasons]


@criterion("paths")
def _crit_paths(ctx: Context) -> list[Finding]:
    return [Finding("paths", r) for r in path_reasons(ctx.filenames, ctx.prefixes)]


@criterion("secret")
def _crit_secret(ctx: Context) -> list[Finding]:
    if not ctx.cfg["secret_scan"]:
        return []
    findings = [Finding("secret", r) for r in secret_reasons(added_lines(ctx.files))]
    skipped = unscanned_files(ctx.files)
    if skipped:
        # 검사를 못 한 것을 안전하다고 뭉개지 않는다(원칙 7). 큰 diff 는 위험으로 본다.
        shown = ", ".join(skipped[:_MAX_LISTED])
        more = f" 등 {len(skipped)}개" if len(skipped) > _MAX_LISTED else ""
        findings.append(Finding("secret", f"변경이 너무 커서 비밀값 검사를 못 한 파일이 있음: {shown}{more}"))
    return findings


def _split_hint_unknown(why: str) -> list[Finding]:
    # 검사를 못 한 것을 안전하다고 뭉개지 않는다(원칙 7).
    return [Finding("split_hint", f"SRS 새 요구사항이 기존 요구사항을 넓힌 것인지 검사 불능: {why}. 승인자가 SRS 변경을 직접 확인")]


@criterion("split_hint")
def _crit_split_hint(ctx: Context) -> list[Finding]:
    if not ctx.cfg["srs_split_hint"]:
        return []
    entry = next((f for f in ctx.files if f.get("filename") == SRS_PATH), None)
    if entry is None or entry.get("status") == "removed":
        return []
    if not entry.get("patch"):
        if int(entry.get("additions") or 0) + int(entry.get("deletions") or 0) == 0:
            return []
        return _split_hint_unknown("변경이 너무 커서 SRS diff 를 못 읽음")
    # 새 요구사항 표 줄이 추가되지 않았으면 쪼개질 일이 없다. 전문은 읽지 않는다.
    if not any(_REQ_ROW.match(text) for _n, _l, text in added_lines([entry])):
        return []
    if ctx.read_text is None:
        return _split_hint_unknown("SRS 전문을 읽는 방법이 없음")
    try:
        head = ctx.read_text(ctx.head_ref, SRS_PATH)
    except (AttributeError, TypeError):  # 디렉터리 응답 등 파일이 아닌 응답
        head = None
    # 빈 문자열은 디코딩 실패나 1MB 초과(content 가 비어 옴)다. 새 REQ 행이 있는 SRS 가 비었을 리 없다.
    # 패치에 새 REQ 행이 있는데 전문에서 REQ 행이 하나도 안 나오면 깨진 내용을 읽은 것이다.
    if not head or not req_titles(head):
        return _split_hint_unknown("PR 의 SRS 를 읽지 못함")
    base_ref = ctx.merge_base() if ctx.merge_base is not None else ctx.base_ref
    if not base_ref:
        return _split_hint_unknown("PR 이 갈라진 지점(merge-base)을 구하지 못함")
    try:
        base = ctx.read_text(base_ref, entry.get("previous_filename") or SRS_PATH)
    except (AttributeError, TypeError):
        base = ""
    if base is None:
        if entry.get("status") != "added":
            return _split_hint_unknown("PR 이 갈라진 지점의 SRS 를 읽지 못함")
        base = ""
    elif not base.strip() and entry.get("status") != "added":
        return _split_hint_unknown("PR 이 갈라진 지점의 SRS 를 읽지 못함")
    return [
        Finding("split_hint", f"SRS 새 요구사항 {titled_id(rid, req_titles(head))} 이 기존 요구사항을 넓힌 것일 수 있음(확장 의심, 승인자가 확인): {'; '.join(ev)}")
        for rid, ev in split_hint_evidence(base, head).items()
    ]


def _write_auth_unknown(path: str, why: str) -> Finding:
    # 검사를 못 한 것을 안전하다고 뭉개지 않는다(원칙 7).
    return Finding("write_auth", f"권한 검사 여부를 확인하지 못함({why}): {path}. 승인자가 직접 확인")


@criterion("write_auth")
def _crit_write_auth(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for entry in ctx.files:
        path = entry.get("filename") or ""
        if entry.get("status") == "removed" or language_for_suffix(PurePosixPath(path)) != "abap":
            continue
        if ctx.read_text is None:
            findings.append(_write_auth_unknown(path, "파일을 읽는 방법이 없음"))
            continue
        try:
            text = ctx.read_text(ctx.head_ref, path)
        except (AttributeError, TypeError):  # 디렉터리 응답 등 파일이 아닌 응답
            text = None
        if not text:
            # 빈 문자열은 디코딩 실패나 1MB 초과(content 가 비어 옴)다.
            findings.append(_write_auth_unknown(path, "파일을 읽지 못함"))
            continue
        try:
            found = check_source(path, text, language="abap")
        except CodeConfigError as exc:  # code_checks.yaml 설정 오류 — 통과로 뭉개지 않는다
            findings.append(_write_auth_unknown(path, f"검사 오류: {exc}"))
            continue
        if any(f["rule"] == "CR-009" and not f["allowed"] for f in found):
            findings.append(Finding("write_auth", f"쓰기 앱인데 권한 검사 없음: {path}"))
    return findings


@criterion("checks")
def _crit_checks(ctx: Context) -> list[Finding]:
    if not ctx.cfg["require_checks_green"]:
        return []
    failed, waiting = checks_reasons(ctx.check_runs(), skip_ai_review=ctx.cfg["ai_review"])
    return [Finding("checks", r) for r in failed] + [Finding("checks", r, waiting=True) for r in waiting]


@criterion("ai_review")
def _crit_ai_review(ctx: Context) -> list[Finding]:
    if not ctx.cfg["ai_review"]:
        return []
    if not ai_review_target(ctx.filenames, ctx.cfg["ai_review_paths"]):
        return []  # 대상 아님: ai-review 가 돌지 않는 PR 이라 결과를 기다리지 않는다(#411)
    flagged, waiting = ai_review_reasons(ctx.check_runs(), ctx.load_comments, ctx.head_ref)
    return [Finding("ai_review", r) for r in flagged] + [Finding("ai_review", r, waiting=True) for r in waiting]


def evaluate(ctx: Context) -> list[Finding]:
    """등록된 모든 기준을 돌려 위험 사유를 모은다. 사유가 없으면 위험하지 않다."""
    findings: list[Finding] = []
    for _name, fn in CRITERIA:
        findings.extend(fn(ctx))
    return findings


# --- 다음 할 일 -----------------------------------------------------------------


def build_next(findings: list[Finding], approval: str, approvers_file: str) -> str:
    """사유에 맞춘 "다음:" 안내를 만든다(#113 형식). `approval` 은
    "ok" | "missing" | "stale" | "no_approvers" | "none"(위험하지 않음) 이다."""
    if approval in ("ok", "none"):
        return ""
    kinds = {f.criterion for f in findings}
    steps: list[str] = []
    if "secret" in kinds:
        steps.append(
            "Claude 가 추가된 비밀값을 코드에서 지우고 새 커밋을 올리십시오. 이미 원격에 올라간 "
            "키·토큰은 사람이 폐기하고 새로 발급해야 합니다"
        )
    if "split_hint" in kinds:
        steps.append(
            "승인자가 SRS diff 에서 새 요구사항이 기존 요구사항의 확장인지 확인하십시오. 같은 개발이면 "
            "새 REQ 를 지우고 기존 REQ 의 범위를 넓히십시오"
        )
    if "write_auth" in kinds:
        steps.append(
            "Claude 가 behavior pool 에 AUTHORITY-CHECK 를 넣거나, 검사하지 않기로 한 것이면 Spec 권한 절과 "
            "harness:allow CR-009 에 이유·결정자를 남기고, 승인자가 그 결정을 확인하십시오"
        )
    waiting = any(f.waiting for f in findings)
    failing = any(f.criterion == "checks" and not f.waiting for f in findings)
    if failing:
        steps.append("실패한 검사의 로그를 보고 고쳐 모든 검사를 통과시키십시오")
    if waiting:
        steps.append("진행 중인 검사가 끝난 뒤 PR 의 risk-gate 검사를 다시 실행하십시오")
    if any(f.criterion == "ai_review" and not f.waiting for f in findings):
        steps.append(
            "PR 의 ai-review 결과 코멘트를 확인해, 심각한 지적이면 고치고, 일부만 봤으면 승인자가 못 본 "
            "파일을 확인하고, 검사 불능·취소·시간 초과·돌지 않음이면 원인(시크릿·토큰 등)을 해결한 뒤 "
            "ai-review 검사를 다시 실행하십시오"
        )

    split = " 또는 PR 을 나눠 기준 이하로 줄이십시오" if kinds & {"size", "paths"} else ""
    if approval == "no_approvers":
        steps.append(
            f"사람이 할 일 - {approvers_file} 에 이 PR 작성자가 아닌 승인자의 GitHub 아이디를 추가하십시오"
            f"(이 파일은 기준 브랜치에서 읽으므로 따로 먼저 반영해야 합니다).{split}"
        )
    elif approval == "stale":
        steps.append(
            f"사람이 할 일 - 승인자({approvers_file} 에서 이 PR 작성자에게 정해진 사람, 작성자 제외)에게 "
            "최신 커밋을 보고 다시 Approve 를 요청하십시오"
        )
    else:
        steps.append(
            f"사람이 할 일 - 승인자({approvers_file} 에서 이 PR 작성자에게 정해진 사람, 작성자 제외)에게 "
            f"최신 커밋을 보고 Approve 를 요청하십시오.{split}"
        )
    steps = [s.rstrip(".") for s in steps]
    if len(steps) == 1:
        return f"다음: {steps[0]}."
    numbered = " ".join(f"({i}) {s}." for i, s in enumerate(steps, start=1))
    return f"다음: {numbered}"


# --- GitHub 에서 읽어오는 부분 --------------------------------------------------------


def fetch_text(client: GhClient, repo: str, ref: str, path: str) -> str | None:
    """`ref` 의 파일 내용을 텍스트로 읽는다. 없으면 None."""
    data = client.get_json_or_none_404(f"repos/{repo}/contents/{path}?ref={ref}")
    if not data:
        return None
    try:
        return base64.b64decode(data.get("content", "") or "").decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def fetch_merge_base(client: GhClient, repo: str, base: str, head: str) -> str | None:
    """`base` 와 `head` 가 갈라진 지점(merge-base) 커밋 SHA. 못 구하면 None."""
    data = client.get_json_or_none_404(f"repos/{repo}/compare/{base}...{head}?per_page=1")
    sha = ((data or {}).get("merge_base_commit") or {}).get("sha") if isinstance(data, dict) else None
    return sha or None


def fetch_pr_file_entries(client: GhClient, repo: str, pr: int) -> list[dict]:
    return [e for e in client.get_all(f"repos/{repo}/pulls/{pr}/files") if "filename" in e]


def fetch_pr_comments(client: GhClient, repo: str, pr: int) -> list[dict]:
    return [c for c in client.get_all(f"repos/{repo}/issues/{pr}/comments") if isinstance(c, dict)]


def fetch_check_runs(client: GhClient, repo: str, sha: str) -> list[dict]:
    """커밋의 check run(최신 것만)과 commit status 를 check run 모양으로 모아 돌려준다."""
    runs: list[dict] = []
    page = 1
    while True:
        data = client.get_json(f"repos/{repo}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}")
        batch = (data or {}).get("check_runs") or []
        runs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    status = client.get_json(f"repos/{repo}/commits/{sha}/status?per_page=100") or {}
    for s in status.get("statuses") or []:
        state = s.get("state")
        runs.append(
            {
                "name": s.get("context") or "commit status",
                "status": "in_progress" if state == "pending" else "completed",
                "conclusion": "success" if state == "success" else "failure",
            }
        )
    return runs


# --- 판정 ---------------------------------------------------------------------


def _disabled_result() -> dict:
    return {
        "enabled": False,
        "risk": "low",
        "reasons": ["risk-gate 설정 없음"],
        "notes": [],
        "requires_approval": False,
        "approved": None,
        "stale_approvers": [],
        "waiting_on_checks": False,
        "approval_note": "",
        "next": "",
    }


def _result_from(findings: list[Finding], approval_state: str, approved: bool | None, note: str,
                 stale: list[str], approvers_file: str, notes: list[str] | None = None) -> dict:
    """`findings` 는 위험 사유만(note 아님). 참고(note)는 `notes` 문구로 따로 받아 `reasons` 와 섞지 않는다(#436)."""
    high = bool(findings)
    waiting_only = high and approved is not True and all(f.waiting for f in findings)
    return {
        "enabled": True,
        "risk": "high" if high else "low",
        "reasons": [f.message for f in findings],
        "notes": list(notes or []),
        "requires_approval": high,
        "approved": approved,
        "stale_approvers": stale,
        "waiting_on_checks": waiting_only,
        "approval_note": note,
        "next": build_next(findings, approval_state, approvers_file),
    }


def _judge_approval(author: str, reviews: list[dict], approvers: ParsedApprovers, head_sha: str) -> tuple[str, bool, str, list[str]]:
    """(상태, 승인 여부, 설명, 낡은 승인자) 를 돌려준다. 승인자는 이 작성자에게 정해진 사람이다."""
    eligible = approvers_for(approvers, author)
    if not eligible:
        return "no_approvers", False, "승인자 목록이 비어 있거나 이 작성자 외에 승인할 수 있는 사람이 없음", []
    approved, note, stale = evaluate_approval(author, reviews, eligible, head_sha)
    if approved:
        return "ok", True, note, []
    if stale:
        return "stale", False, note, [e["login"] for e in stale]
    return "missing", False, note, []


def decide_pr(client: GhClient, repo: str, pr: int, config_ref: str | None = None) -> dict:
    """PR 하나의 위험도와 승인 여부를 판정한다.

    `config_ref` 를 주면 기준·승인자 목록을 그 ref 에서 읽는다(병합 뒤 감지는 병합 직전
    main 을 준다). 생략하면 PR 의 base 브랜치다.
    """
    info = fetch_pr_info(client, repo, pr)
    ref = config_ref or (info.get("base") or {}).get("ref") or "main"
    cfg_text = fetch_text(client, repo, ref, CONFIG_PATH)
    if cfg_text is None:
        return _disabled_result()
    cfg = load_config(cfg_text)

    head_sha = (info.get("head") or {}).get("sha")
    if not head_sha:
        raise GhError(f"PR #{pr} 의 head 커밋을 응답에서 찾지 못했다")

    ctx = Context(
        cfg=cfg,
        files=fetch_pr_file_entries(client, repo, pr),
        prefixes=cfg["high_risk_paths"] + fetch_human_merge_paths(client, repo, ref),
        load_check_runs=lambda: fetch_check_runs(client, repo, head_sha),
        read_text=lambda at, path: fetch_text(client, repo, at, path),
        base_ref=ref,
        head_ref=head_sha,
        load_comments=lambda: fetch_pr_comments(client, repo, pr),
        # `ref` 는 기준 브랜치의 지금 끝(또는 병합 직전 main)이라 PR 이 갈라진 뒤 main 이 앞서가면 PR 이
        # 건드리지 않은 줄까지 달라 보인다. SRS 비교는 갈라진 지점을 기준으로 한다.
        merge_base=lambda: fetch_merge_base(client, repo, ref, head_sha),
    )
    evaluated = evaluate(ctx)
    findings = [f for f in evaluated if not f.note]
    notes = [f.message for f in evaluated if f.note]
    if not findings:
        return _result_from([], "none", None, "", [], cfg["approvers_file"], notes)

    author = (info.get("user") or {}).get("login", "")
    approvers = parse_approvers(fetch_text(client, repo, ref, cfg["approvers_file"]))
    state, approved, note, stale = _judge_approval(
        author, fetch_pr_reviews(client, repo, pr), approvers, head_sha
    )
    return _result_from(findings, state, approved, note, stale, cfg["approvers_file"], notes)


def decide_pr_waiting(
    client: GhClient,
    repo: str,
    pr: int,
    wait_seconds: int = 0,
    interval: int = 20,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """`decide_pr` 를 부르되, 사유가 진행 중인 검사뿐이면 `wait_seconds` 안에서 기다려 다시 판정한다."""
    deadline = clock() + wait_seconds
    while True:
        result = decide_pr(client, repo, pr)
        if not result.get("waiting_on_checks") or clock() + interval > deadline:
            return result
        print(f"다른 검사가 끝나길 기다린다: {'; '.join(result['reasons'])}", file=sys.stderr)
        sleep(interval)


# AI 리뷰 사전 판정에서 평가하는 기준(위험 안내용). 나머지(checks, ai_review)는 이름으로 거른다.
PRECHECK_CRITERIA = frozenset({"size", "paths", "secret"})

EXIT_SKIP = 3  # precheck-pr: AI 리뷰를 돌리지 않는다(설정 없음·꺼짐). 위험한 PR 도 돌린다(#360)
EXIT_SECRET = 4  # precheck-pr: 새 줄에 비밀값 패턴이 보여 diff 를 AI 에 보내지 않는다(#360)


def precheck_pr(client: GhClient, repo: str, pr: int) -> dict:
    """AI 리뷰를 돌려도 되는 PR 인지 가린다(#125). 위험한 PR 도 돌린다(#360) — `risky`·`reasons` 는 코멘트 안내용이다.

    `size`·`paths`·`secret` 기준만 평가한다.
    """
    info = fetch_pr_info(client, repo, pr)
    ref = (info.get("base") or {}).get("ref") or "main"
    cfg_text = fetch_text(client, repo, ref, CONFIG_PATH)
    if cfg_text is None:
        return {"enabled": False, "gate": False, "risky": False, "reasons": ["risk-gate 설정 없음"]}
    cfg = load_config(cfg_text)
    if not cfg["ai_review"]:
        return {"enabled": False, "gate": True, "risky": False, "reasons": ["ai_review 가 꺼져 있음"]}
    entries = fetch_pr_file_entries(client, repo, pr)
    if not ai_review_target([e.get("filename") or "" for e in entries], cfg["ai_review_paths"]):
        return {"enabled": False, "gate": True, "risky": False,
                "reasons": ["AI 리뷰 대상 아님(ai_review_paths 에 걸린 파일 없음)"]}

    def _no_check_runs() -> list[dict]:
        raise AssertionError("precheck 는 다른 검사의 결과를 읽지 않는다")

    ctx = Context(
        cfg=cfg,
        files=entries,
        prefixes=cfg["high_risk_paths"] + fetch_human_merge_paths(client, repo, ref),
        load_check_runs=_no_check_runs,
    )
    evaluated = []
    for name, fn in CRITERIA:
        if name in PRECHECK_CRITERIA:
            evaluated.extend(fn(ctx))
    findings = [f for f in evaluated if not f.note]  # 참고(note)는 위험이 아니다(#436)
    notes = [f.message for f in evaluated if f.note]
    # 비밀값 패턴이 새 줄에서 실제로 보였는지. `_crit_secret` 의 "너무 커서 검사 못 함"(unscanned)은 여기에 넣지
    # 않는다 — 큰 PR 은 계속 리뷰한다(그 파일 안의 비밀값은 AI 리뷰로 나갈 수 있다). secret_patterns 는 패턴 이름만
    # 담는다. 위치(파일:줄)는 `reasons` 에 있다.
    patterns = secret_pattern_names(added_lines(ctx.files)) if cfg["secret_scan"] else []
    return {
        "enabled": True,
        "gate": True,
        "risky": bool(findings),
        "reasons": [f.message for f in findings],
        "notes": notes,
        # 사유를 낸 기준 이름(size·paths·secret). 워크플로가 사유 문자열 대신 이걸로 크기 위험을 구분한다.
        "criteria": list(dict.fromkeys(f.criterion for f in findings)),
        "secret_found": bool(patterns),
        "secret_patterns": patterns,
    }


LINK_RETRIES = 3  # 커밋-PR 연결이 비어 있을 때 조회하는 최대 횟수(처음 포함)
LINK_RETRY_INTERVAL = 5  # 다시 조회하기 전에 쉬는 시간(초)

_TITLE_PR_NUMBER = re.compile(r"\(#(\d+)\)\s*$")


def _merged_prs_for_commit(
    client: GhClient,
    repo: str,
    sha: str,
    commit: dict,
    retries: int = LINK_RETRIES,
    interval: float = LINK_RETRY_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """main 커밋을 병합해 들여온 PR 을 찾는다. 못 찾으면 빈 목록(직접 push 로 본다).

    병합 직후에는 GitHub 가 `commits/{sha}/pulls` 의 연결을 늦게 돌려줄 수 있어(#130) 비면 바로
    단정하지 않는다. (1) 짧게 몇 번 다시 조회하고, (2) 그래도 비면 squash 병합 커밋 제목 끝의
    `(#123)` 을 근거로 `pulls/123` 을 읽어 그 PR 이 병합됐고 `merge_commit_sha` 가 이 커밋일 때만
    그 PR 로 본다. 조회 실패(GhError)는 그대로 올려 판정 불가로 이어지게 한다 — 단, 제목 번호가
    PR 이 아니라 404 인 경우는 근거 없음으로 본다.
    """
    for attempt in range(max(retries, 1)):
        if attempt:
            sleep(interval)
        merged = [p for p in fetch_commit_associated_prs(client, repo, sha) if p.get("merged_at")]
        if merged:
            return merged

    message = ((commit.get("commit") or {}).get("message") or "").splitlines()
    match = _TITLE_PR_NUMBER.search(message[0].strip()) if message else None
    if not match:
        return []
    number = int(match.group(1))
    try:
        info = fetch_pr_info(client, repo, number) or {}
    except GhError as exc:
        if exc.status == 404:
            return []
        raise
    if info.get("merged_at") and info.get("merge_commit_sha") == sha:
        return [{"number": number, "merged_at": info["merged_at"], "html_url": info.get("html_url", "")}]
    return []


def decide_commit(
    client: GhClient,
    repo: str,
    sha: str,
    sleep: Callable[[float], None] = time.sleep,
    retry_interval: float = LINK_RETRY_INTERVAL,
) -> dict:
    """병합 뒤(push) 이 커밋이 승인 없이 들어온 위험한 변경인지 판정한다.

    기준은 병합 직전 main(첫 부모)에서 읽는다 — 병합된 PR 이 기준을 바꿨다면 그 바뀐 기준이
    아니라 병합 전 기준으로 판정해야 PR 이 자기 게이트를 풀 수 없다.

    PR 없이 들어온 커밋으로 볼 때는 "다른 검사가 아직 진행 중" 같은 대기 사유(`waiting`)를 위험으로
    세지 않는다. 이 판정은 push 직후 돌아 검사가 진행 중인 것이 정상이고, 끝나길 기다리면 push
    워크플로가 길어진다. 실패한 검사·크기·경로·비밀값은 그대로 위험이다.
    """
    commit = client.get_json(f"repos/{repo}/commits/{sha}") or {}
    parents = commit.get("parents") or []
    ref = (parents[0].get("sha") if parents else None) or sha

    merged = _merged_prs_for_commit(client, repo, sha, commit, interval=retry_interval, sleep=sleep)
    if merged:
        problems = []
        enabled = False
        for pr in merged:
            result = decide_pr(client, repo, pr.get("number"), config_ref=ref)
            enabled = enabled or result["enabled"]
            if result["requires_approval"] and not result["approved"]:
                problems.append(
                    {"pr": pr.get("number"), "url": pr.get("html_url", ""), "reasons": result["reasons"],
                     "next": result["next"]}
                )
        if problems:
            reasons = [r for p in problems for r in p["reasons"]]
            return _commit_result(True, "high", False, reasons, problems, problems[0]["next"])
        return _commit_result(enabled, "low", True, [], [p.get("number") for p in merged], "")

    # PR 없이 main 에 직접 들어온 커밋. 승인받을 PR 자체가 없다.
    cfg_text = fetch_text(client, repo, ref, CONFIG_PATH)
    if cfg_text is None:
        return _commit_result(False, "low", True, ["risk-gate 설정 없음"], [], "")
    cfg = load_config(cfg_text)
    ctx = Context(
        cfg=cfg,
        files=[f for f in (commit.get("files") or []) if "filename" in f],
        prefixes=cfg["high_risk_paths"] + fetch_human_merge_paths(client, repo, ref),
        load_check_runs=lambda: fetch_check_runs(client, repo, sha),
        read_text=lambda at, path: fetch_text(client, repo, at, path),
        base_ref=ref,
        head_ref=sha,
    )
    findings = [f for f in evaluate(ctx) if not f.waiting and not f.note]
    if not findings:
        return _commit_result(True, "low", True, [], [], "")
    reasons = ["PR 없이 main 에 직접 들어옴"] + [f.message for f in findings]
    nxt = "다음: 사람이 할 일 - 소유자가 이 커밋을 사후 검토하고 필요하면 되돌리십시오. 앞으로는 PR 로만 반영하십시오."
    return _commit_result(True, "high", False, reasons, [], nxt)


def _commit_result(enabled: bool, risk: str, approved: bool, reasons: list[str], prs: list, nxt: str) -> dict:
    return {
        "enabled": enabled,
        "risk": risk,
        "reasons": reasons,
        "requires_approval": risk == "high",
        "approved": approved,
        "prs": prs,
        "next": nxt,
    }


# --- CLI ---------------------------------------------------------------------


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _unknown(exc: Exception) -> dict:
    return {
        "enabled": None,
        "risk": None,
        "reasons": [f"판정 불가: {exc}"],
        "notes": [],
        "requires_approval": None,
        "approved": None,
        "stale_approvers": [],
        "waiting_on_checks": False,
        "approval_note": "",
        "next": "",
    }


def _exit_for(result: dict) -> int:
    if not result["requires_approval"] or result["approved"]:
        return EXIT_OK
    return EXIT_NOT_APPROVED


def _unexpected(exc: Exception) -> dict:
    """예상 못 한 예외. 파이썬 기본 종료코드 1 은 EXIT_NOT_APPROVED 와 겹치므로 판정 불가로 바꾼다."""
    traceback.print_exc(file=sys.stderr)
    return _unknown(RuntimeError(f"예상 못 한 오류 {type(exc).__name__}: {exc}"))


def cmd_check_pr(args: argparse.Namespace) -> int:
    client = GhClient()
    try:
        result = decide_pr_waiting(
            client, args.repo, args.pr, getattr(args, "wait_checks", 0) or 0,
            getattr(args, "wait_interval", 20) or 20,
        )
    except (GhError, ConfigError) as exc:
        _print(_unknown(exc))
        return EXIT_UNKNOWN
    except Exception as exc:  # noqa: BLE001 - 어떤 오류도 "승인 필요"(1)로 보이면 안 된다
        _print(_unexpected(exc))
        return EXIT_UNKNOWN
    _print(result)
    return _exit_for(result)


def cmd_precheck_pr(args: argparse.Namespace) -> int:
    client = GhClient()
    try:
        result = precheck_pr(client, args.repo, args.pr)
    except (GhError, ConfigError) as exc:
        _print({"enabled": None, "gate": None, "risky": None, "reasons": [f"판정 불가: {exc}"]})
        return EXIT_UNKNOWN
    except Exception as exc:  # noqa: BLE001 - 어떤 오류도 "돌려도 됨"(0)으로 보이면 안 된다
        traceback.print_exc(file=sys.stderr)
        reason = f"판정 불가: 예상 못 한 오류 {type(exc).__name__}: {exc}"
        _print({"enabled": None, "gate": None, "risky": None, "reasons": [reason]})
        return EXIT_UNKNOWN
    _print(result)
    if not result["enabled"]:
        return EXIT_SKIP
    # 비밀값이 보이면 diff 를 외부 AI 에 보내지 않도록 리뷰를 멈춘다. 옛 워크플로는 이 코드를 모르고 "판정 불능" 으로
    # 읽어 역시 리뷰를 돌리지 않는다(실패 쪽으로 안전하다).
    return EXIT_SECRET if result.get("secret_found") else EXIT_OK


def cmd_check_commit(args: argparse.Namespace) -> int:
    client = GhClient()
    try:
        result = decide_commit(client, args.repo, args.sha)
    except (GhError, ConfigError) as exc:
        payload = _unknown(exc)
        payload["prs"] = []
        _print(payload)
        return EXIT_UNKNOWN
    except Exception as exc:  # noqa: BLE001 - 위와 같은 이유
        payload = _unexpected(exc)
        payload["prs"] = []
        _print(payload)
        return EXIT_UNKNOWN
    _print(result)
    return _exit_for(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="risk_gate",
        description="PR 위험도를 판정하고, 위험한 PR 은 승인 여부를 확인한다.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    check_pr = sub.add_parser("check-pr", help="PR 하나의 위험도와 승인 여부를 판정한다")
    check_pr.add_argument("--repo", required=True, help="owner/repo")
    check_pr.add_argument("--pr", required=True, type=int, help="PR 번호")
    check_pr.add_argument(
        "--wait-checks", type=int, default=0, metavar="SECONDS",
        help="사유가 다른 검사의 진행 중뿐이면 이 시간(초) 안에서 끝나길 기다린다. 기본 0(기다리지 않음)",
    )
    check_pr.add_argument("--wait-interval", type=int, default=20, metavar="SECONDS", help="기다리는 동안 다시 보는 간격")
    check_pr.set_defaults(func=cmd_check_pr)

    precheck = sub.add_parser(
        "precheck-pr",
        help="AI 리뷰를 돌려도 되는 PR 인지 가린다. 종료코드 0 돌려도 됨(위험한 PR 도), 3 돌리지 않음(설정 없음·꺼짐, 사유 출력), 2 판정 불가",
    )
    precheck.add_argument("--repo", required=True, help="owner/repo")
    precheck.add_argument("--pr", required=True, type=int, help="PR 번호")
    precheck.set_defaults(func=cmd_precheck_pr)

    check_commit = sub.add_parser("check-commit", help="병합된(또는 직접 push 된) 커밋의 위험도·승인 여부를 판정한다")
    check_commit.add_argument("--repo", required=True, help="owner/repo")
    check_commit.add_argument("--sha", required=True, help="커밋 SHA")
    check_commit.set_defaults(func=cmd_check_commit)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
