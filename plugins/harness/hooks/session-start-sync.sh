#!/usr/bin/env bash
set -euo pipefail

# 공통 개발 규칙 요약(#53)에 쓸 Plugin 루트를 cd 전에 구해 둔다. Plugin 훅으로
# 불릴 때는 CLAUDE_PLUGIN_ROOT 가 있지만, 없으면 이 스크립트 위치에서 구한다.
# cd 뒤에는 "$0" 이 상대 경로일 때 깨질 수 있어 미리 계산한다.
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

lines=""
add() {
  lines="${lines}$1
"
}

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "이 디렉터리는 git 저장소가 아닙니다. harness 의 자동 동기화가 동작하지 않습니다."
  exit 0
fi

hooks_path="$(git config --get core.hooksPath || true)"
# git hook 은 그 저장소가 .githooks/ 와 설치 스크립트를 가진 경우에만 설치한다.
# 이 Plugin 을 설치한 모든 저장소가 그 구조를 갖지는 않으므로, 없으면 조용히 넘어간다.
if [ "$hooks_path" != ".githooks" ] && [ -d .githooks ] && [ -f scripts/install-hooks.sh ]; then
  if bash scripts/install-hooks.sh >/dev/null 2>&1; then
    add "git hook 을 자동으로 설치했습니다. main 직접 커밋과 규칙 밖 브랜치 이름이 이제 거부됩니다."
  else
    add "git hook 설치에 실패했습니다. scripts/install-hooks.sh 를 직접 실행해야 합니다."
  fi
fi

# 저장소마다 다른 인수인계 파일을 쓰기 위해 저장소 이름을 구한다. 연결된
# 워크트리에서는 `.git` 이 파일이므로 실제 디렉터리를 물어서 쓴다.
repo_name="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-$PWD}")")"
CARRYOVER="$(git rev-parse --git-dir)/${repo_name}-unfinished"
CARRYOVER_PENDING=""
if [ -f "$CARRYOVER" ]; then
  add "지난 세션에서 남은 경고가 있습니다."
  add "$(cat "$CARRYOVER")"
  CARRYOVER_PENDING="$CARRYOVER"
fi

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 알수없음)"
add "현재 브랜치: $branch"

if git remote get-url origin >/dev/null 2>&1; then
  if git fetch --all --prune --quiet >/dev/null 2>&1; then
    add "원격을 가져왔습니다."
    if git pull --rebase --quiet >/dev/null 2>&1; then
      add "최신 상태로 맞췄습니다."
    else
      # 리베이스가 중간에 멈췄으면 되돌린다. 세션을 매끄럽게 시작하려고 만든
      # 훅이 저장소를 충돌 상태로 남겨 두면, 그다음에 무엇을 해도 막힌다.
      git_dir="$(git rev-parse --git-dir)"
      if [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ]; then
        if git rebase --abort >/dev/null 2>&1; then
          add "pull --rebase 가 충돌해 원래 상태로 되돌렸습니다. 원격과의 차이를 직접 확인해야 합니다."
        else
          # abort 실패를 성공으로 보고하면, 리베이스가 진행 중인 상태로 남아
          # .githooks/pre-commit 의 브랜치 검사가 통째로 건너뛰어지는데도
          # 그 사실이 드러나지 않는다.
          add "pull --rebase 가 충돌했고 되돌리기(git rebase --abort)도 실패했습니다. 저장소가 리베이스 진행 중 상태로 남아 있으니 직접 확인하십시오."
        fi
      else
        add "pull --rebase 가 실패했습니다. 로컬 변경이나 인증 상태를 먼저 확인해야 합니다."
      fi
    fi
  else
    add "fetch 에 실패했습니다. 네트워크나 인증 상태를 확인해야 합니다."
  fi
else
  add "원격 저장소가 연결되어 있지 않습니다. 푸시와 PR 과 이슈 관련 동작은 원격을 연결한 뒤에 가능합니다."
fi

if [ "$branch" = "main" ]; then
  add "main 에서는 커밋할 수 없습니다. 작업을 시작하려면 /harness:start 를 실행하십시오."
fi

# /harness:deliver 가 스테이징에서 빼는 것(.superpowers/, *handoff*.md)은 여기서도
# 세지 않는다(#59). 세면 인계 메모 하나만 남아도 deliver 로 없앨 수 없는
# 경고가 매번 뜬다. 한글 경로는 porcelain 이 따옴표로 감싸므로 따옴표도 허용한다.
# --untracked-files=all 로 파일 단위로 본다. 기본값은 추적 안 된 폴더를 `?? docs/`
# 한 줄로 접어, 그 안에 인계 메모만 있어도 걸러 내지 못한다.
changed="$(git status --porcelain --untracked-files=all | grep -Ev '^.. "?((.*/)?\.superpowers/|.*handoff.*\.md"?$)' || true)"
if [ -n "$changed" ]; then
  add "커밋되지 않은 변경이 있습니다."
  # 파일 단위로 보므로 목록이 길어질 수 있다. 세션 맥락을 채우지 않게 20줄까지만 싣는다.
  add "$(printf '%s\n' "$changed" | head -n 20)"
  total="$(printf '%s\n' "$changed" | wc -l | tr -d ' ')"
  if [ "$total" -gt 20 ]; then
    add "... 외 $((total - 20))개"
  fi
  add "작업을 마칠 때 /harness:deliver 로 커밋과 푸시와 PR 까지 정리하십시오."
fi

# 공통 개발 규칙 요약(#53). 목록은 common.md 의 `## CR-` 헤딩에서 파싱해
# 만든다 — 여기 코드에 CR 목록을 다시 적으면 common.md 와 따로 놀 수 있다
# (CLAUDE.md 원칙 2). 파싱에 실패하면(파일이 없거나 헤딩을 못 찾으면) 목록
# 없이 경로만 알린다 — 검사를 못 했다고 조용히 통과시키지 않는 것과 같은
# 이유로, 요약을 못 만들었다는 사실도 숨기지 않는다.
common_md="${plugin_root}/conventions/common.md"
cr_lines="$(grep '^## CR-' "$common_md" 2>/dev/null | sed 's/^## //' || true)"
if [ -n "$cr_lines" ]; then
  add "공통 개발 규칙(harness):"
  while IFS= read -r cr_line; do
    add "- $cr_line"
  done <<< "$cr_lines"
fi
add "전문: $common_md"

# 이 저장소 자체 conventions/ 가 있으면(README.md 만 있는 경우는 빼고) 함께
# 안내한다. 최대 5개까지만 이름을 보여 준다.
if [ -d conventions ]; then
  proj_conventions=""
  proj_conv_count=0
  for f in conventions/*.md; do
    [ -e "$f" ] || continue
    name="$(basename "$f")"
    [ "$name" = "README.md" ] && continue
    proj_conv_count=$((proj_conv_count + 1))
    [ "$proj_conv_count" -gt 5 ] && continue
    if [ -z "$proj_conventions" ]; then
      proj_conventions="conventions/$name"
    else
      proj_conventions="${proj_conventions}, conventions/$name"
    fi
  done
  if [ -n "$proj_conventions" ]; then
    add "이 저장소의 Convention: $proj_conventions"
    add "공통 규칙과 부딪히면 이 저장소 Convention 을 따른다(CR-004 제외)."
  fi
fi

printf '%s' "$lines"

# 전달이 끝난 뒤에 지운다. 지우고 나서 출력에 실패하면 경고가 사라진다.
if [ -n "$CARRYOVER_PENDING" ]; then
  rm -f "$CARRYOVER_PENDING"
fi

exit 0
