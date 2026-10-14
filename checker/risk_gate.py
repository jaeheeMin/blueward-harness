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

- `size`      바뀐 줄(추가+삭제)과 파일 수가 기준을 넘는가.
- `paths`     `high_risk_paths` 와 `.github/human-merge-paths` 의 경로를 바꿨는가.
- `secret`    추가된 줄에 토큰·키·비밀번호·웹훅 주소 모양이 있는가(CR-004 의 기계 검사).
              보고에는 파일:줄과 패턴 이름만 담고 값은 절대 담지 않는다.
- `checks`    이 PR 의 다른 검사(check run, commit status)가 실패했거나 진행 중인가.
              게이트 자신(`risk-gate`)과 같은 PR 에서 도는 `ssot-approval`, `alert` 는 뺀다.
              자신을 세면 "자기 자신이 끝나길 기다리는" 교착이 생기기 때문이다.
- `split_hint` `srs_split_hint`(기본 켬)일 때, SRS 에 새 요구사항이 생겼고 기존 요구사항을 넓힌 것처럼
              보이는 근거(상세 절의 다른 번호 언급, 범위 "하지 않는 것" 줄 변경, 제목 겹침)가 있는가(#278).
              막는 기준이 아니라 승인자에게 근거를 보여 주는 사유다. SRS diff 를 못 읽으면 검사 불능 사유다.
- `ai_review` 설정에서 켠 때만 본다. 이름이 `ai-review` 인 check run 의 결론을 읽는다
              (success 면 통과, 그 밖의 결론이면 실패). 그 check run 은 재사용 워크플로
              `ai-review.yml`(#125)이 만든다. 실패는 "심각한 지적" 일 수도, "AI 리뷰를 못 돌린
              검사 불능" 일 수도 있어 사유가 둘을 뭉개지 않고 PR 코멘트를 보라고 안내한다.
              없거나 끝나지 않았으면 대기로 본다.

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

**AI 리뷰 사전 판정(`precheck-pr`, #125).** AI 리뷰는 위험도가 낮은 PR 에만 돌린다(위험한 PR
은 어차피 사람이 본다). `ai-review.yml` 이 리뷰를 돌리기 전에 이 하위 명령으로 base 의 기준
가운데 `size`·`paths`·`secret` 만 평가한다. `checks`·`ai_review` 는 뺀다 — `checks` 는 이 AI
리뷰 자신을 기다리는 교착을 만들고, `ai_review` 는 이 리뷰의 결과를 읽는 기준이기 때문이다.
종료코드: 0 AI 리뷰를 돌려도 됨(설정이 있고 `ai_review: true` 이며 위험하지 않음), 3 돌리지
않음(설정 없음, `ai_review: false`, 이미 위험함 — 사유를 출력), 2 판정 불가. 1 은 쓰지 않는다.
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
from typing import Callable

import yaml

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
EXCLUDED_CHECK_GROUPS = frozenset({OWN_CHECK_NAME, "ssot-approval"})
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
    "srs_split_hint": True,
    "approvers_file": ".github/ssot-approvers",
}

_INT_KEYS = ("max_changed_lines", "max_changed_files")
_BOOL_KEYS = ("secret_scan", "require_checks_green", "ai_review", "srs_split_hint")

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
        elif key == "high_risk_paths":
            if value is None:
                value = []
            if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
                raise ConfigError(f"{CONFIG_PATH} 의 high_risk_paths 는 문자열 목록이어야 한다")
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


def path_reasons(files: list[str], prefixes: list[str]) -> list[str]:
    """위험 경로 아래 파일을 바꿨으면 사유를 돌려준다."""
    normalized = [_normalize(p) for p in prefixes if _normalize(p)]
    hits = human_merge_hits(files, normalized)
    if not hits:
        return []
    shown = ", ".join(hits[:_MAX_LISTED])
    more = f" 등 {len(hits)}개" if len(hits) > _MAX_LISTED else ""
    return [f"위험 경로를 바꿈: {shown}{more}"]


# 비밀값 패턴. 이름만 보고되고 값은 어디에도 남지 않는다.
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


def ai_review_reasons(check_runs: list[dict]) -> tuple[list[str], list[str]]:
    """`ai-review` check run 을 읽어 (지적 사유, 대기 사유) 를 돌려준다."""
    runs = [r for r in check_runs if _check_group(r.get("name") or "") == AI_REVIEW_CHECK_NAME]
    if not runs:
        return [], ["AI 리뷰 결과(ai-review 검사)가 아직 없음"]
    states = [_run_state(r) for r in runs]
    if "fail" in states:
        return ["AI 리뷰 검사가 실패함(심각한 지적 또는 AI 리뷰 검사 불능 — ai-review 결과 코멘트를 확인)"], []
    if "pending" in states:
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
                evidence.append(f"(a) 상세 절이 다른 번호를 말함: {', '.join(others)}")
        if changed_scope:
            shown = "; ".join(
                f"\"{_cut(ln)}\"" + (f" ({', '.join(reqs)} 의 {SCOPE_EXCLUDED_MARKER})" if reqs else "")
                for ln, reqs in changed_scope[:2]
            )
            more = f" 등 {len(changed_scope)}개" if len(changed_scope) > 2 else ""
            evidence.append(f"(b) 범위 \"{SCOPE_EXCLUDED_MARKER}\" 항목이 지워지거나 바뀜: {shown}{more}")
        new = _norm_title(head_titles[rid])
        if len(new) >= MIN_TITLE_LEN:
            overlaps = [
                f"{old_id} '{old_title}'"
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
    """기준 하나가 낸 사유. `waiting` 이면 시간이 지나면 풀릴 수 있는 사유(진행 중인 검사)다."""

    criterion: str
    message: str
    waiting: bool = False


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
    return [Finding("size", r) for r in size_reasons(ctx.files, ctx.cfg)]


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
        Finding("split_hint", f"SRS 새 요구사항 {rid} 이 기존 요구사항을 넓힌 것일 수 있음(확장 의심, 승인자가 확인): {'; '.join(ev)}")
        for rid, ev in split_hint_evidence(base, head).items()
    ]


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
    flagged, waiting = ai_review_reasons(ctx.check_runs())
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
    waiting = any(f.waiting for f in findings)
    failing = any(f.criterion == "checks" and not f.waiting for f in findings)
    if failing:
        steps.append("실패한 검사의 로그를 보고 고쳐 모든 검사를 통과시키십시오")
    if waiting:
        steps.append("진행 중인 검사가 끝난 뒤 PR 의 risk-gate 검사를 다시 실행하십시오")
    if any(f.criterion == "ai_review" and not f.waiting for f in findings):
        steps.append(
            "PR 의 ai-review 결과 코멘트를 확인해, 심각한 지적이면 고치고 AI 리뷰 검사 불능이면 "
            "원인(시크릿·토큰 등)을 해결한 뒤 ai-review 검사를 다시 실행하십시오"
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
        "requires_approval": False,
        "approved": None,
        "stale_approvers": [],
        "waiting_on_checks": False,
        "approval_note": "",
        "next": "",
    }


def _result_from(findings: list[Finding], approval_state: str, approved: bool | None, note: str,
                 stale: list[str], approvers_file: str) -> dict:
    high = bool(findings)
    waiting_only = high and approved is not True and all(f.waiting for f in findings)
    return {
        "enabled": True,
        "risk": "high" if high else "low",
        "reasons": [f.message for f in findings],
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
        # `ref` 는 기준 브랜치의 지금 끝(또는 병합 직전 main)이라 PR 이 갈라진 뒤 main 이 앞서가면 PR 이
        # 건드리지 않은 줄까지 달라 보인다. SRS 비교는 갈라진 지점을 기준으로 한다.
        merge_base=lambda: fetch_merge_base(client, repo, ref, head_sha),
    )
    findings = evaluate(ctx)
    if not findings:
        return _result_from([], "none", None, "", [], cfg["approvers_file"])

    author = (info.get("user") or {}).get("login", "")
    approvers = parse_approvers(fetch_text(client, repo, ref, cfg["approvers_file"]))
    state, approved, note, stale = _judge_approval(
        author, fetch_pr_reviews(client, repo, pr), approvers, head_sha
    )
    return _result_from(findings, state, approved, note, stale, cfg["approvers_file"])


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


# AI 리뷰 사전 판정에서 평가하는 기준. 나머지(checks, ai_review)는 이름으로 거른다.
PRECHECK_CRITERIA = frozenset({"size", "paths", "secret"})

EXIT_SKIP = 3  # precheck-pr: AI 리뷰를 돌리지 않는다(설정 없음·꺼짐·이미 위험)


def precheck_pr(client: GhClient, repo: str, pr: int) -> dict:
    """AI 리뷰를 돌려도 되는 PR 인지 가린다(#125). `size`·`paths`·`secret` 기준만 평가한다."""
    info = fetch_pr_info(client, repo, pr)
    ref = (info.get("base") or {}).get("ref") or "main"
    cfg_text = fetch_text(client, repo, ref, CONFIG_PATH)
    if cfg_text is None:
        return {"enabled": False, "gate": False, "risky": False, "reasons": ["risk-gate 설정 없음"]}
    cfg = load_config(cfg_text)
    if not cfg["ai_review"]:
        return {"enabled": False, "gate": True, "risky": False, "reasons": ["ai_review 가 꺼져 있음"]}

    def _no_check_runs() -> list[dict]:
        raise AssertionError("precheck 는 다른 검사의 결과를 읽지 않는다")

    ctx = Context(
        cfg=cfg,
        files=fetch_pr_file_entries(client, repo, pr),
        prefixes=cfg["high_risk_paths"] + fetch_human_merge_paths(client, repo, ref),
        load_check_runs=_no_check_runs,
    )
    findings = []
    for name, fn in CRITERIA:
        if name in PRECHECK_CRITERIA:
            findings.extend(fn(ctx))
    return {
        "enabled": True,
        "gate": True,
        "risky": bool(findings),
        "reasons": [f.message for f in findings],
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
    findings = [f for f in evaluate(ctx) if not f.waiting]
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
    return EXIT_OK if result["enabled"] and not result["risky"] else EXIT_SKIP


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
        help="AI 리뷰를 돌려도 되는 PR 인지 가린다. 종료코드 0 돌려도 됨, 3 돌리지 않음(사유 출력), 2 판정 불가",
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
