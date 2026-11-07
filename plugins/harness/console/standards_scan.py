"""기준 폴더(templates/ 와 rules/)와 고객 양식 원본을 찾는 판정. 웹 콘솔 서버와 세션 시작 훅(session-start-sync.sh)이 함께 쓴다.

훅은 `python standards_scan.py <저장소 꼭대기>` 로 불러 한 줄(`has`/`none`/`unknown`)을 받는다.
"""
from __future__ import annotations

import os
import sys

PRUNE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}  # session-start-sync.sh 의 기준 폴더 찾기와 같다


def standard_folders(root: str, names: list[str], depth: int):
    """root 와 그 아래 depth 단계까지의 폴더 중 names 를 모두 하위 폴더로 가진 곳을 차례로 낸다."""
    start = len(os.path.normpath(root).split(os.sep))
    for cur, dirs, _files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
        if all(n in dirs for n in names):
            yield cur
        if len(os.path.normpath(cur).split(os.sep)) - start >= depth:
            dirs[:] = []


def has_standard_folder(root: str, names: list[str], depth: int) -> bool:
    """root 와 그 아래 depth 단계까지의 폴더 중 names 를 모두 하위 폴더로 가진 곳이 있는가."""
    return next(standard_folders(root, names, depth), None) is not None


# 고객 양식 원본으로 치는 사무 문서 확장자. templates/README.md 가 "고객사에게 받은 Template 원본"(xlsx 등)을 넣는 자리라고 한다.
# templates/harness/(scaffold 가 만든 기본 틀)와 templates/forms/(양식 지도 yaml)는 고객 양식이 아니라 건너뛴다.
FORM_EXTS = {".xlsx", ".xlsm", ".xls", ".pptx", ".pptm", ".ppt", ".docx", ".docm", ".doc", ".hwp", ".hwpx"}
FORM_SKIP_DIRS = {"harness", "forms"}
FORM_DEPTH = 3


def customer_forms(root: str, depth: int = 3) -> bool | None:
    """root 아래 templates/ (templates 와 rules 를 함께 가진 폴더들)에 고객 양식 원본이 하나라도 있는가. 읽지 못하면 None."""
    failed = []
    for base in standard_folders(root, ["templates", "rules"], depth):
        top = os.path.join(base, "templates")
        for cur, dirs, files in os.walk(top, onerror=failed.append):
            if os.path.normpath(cur) == os.path.normpath(top):
                dirs[:] = [d for d in dirs if d not in FORM_SKIP_DIRS]
            if len(os.path.normpath(cur).split(os.sep)) - len(os.path.normpath(top).split(os.sep)) >= FORM_DEPTH:
                dirs[:] = []
            if any(os.path.splitext(f)[1].lower() in FORM_EXTS and not f.startswith("~$") for f in files):
                return True
    return None if failed else False


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 2
    try:
        # 훅의 기준 폴더 찾기(find)와 범위가 어긋나 여기서 기준 폴더를 못 찾으면, 양식이 "없다" 가 아니라
        # 따질 수 없는 것이다. none 으로 답해 거짓 안내를 띄우지 않는다.
        found = customer_forms(argv[1]) if has_standard_folder(argv[1], ["templates", "rules"], 3) else None
    except OSError:
        found = None
    print("unknown" if found is None else ("has" if found else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
