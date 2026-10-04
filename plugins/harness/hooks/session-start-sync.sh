#!/usr/bin/env bash
set -euo pipefail

# 공통 개발 규칙 요약(#53)에 쓸 Plugin 루트를 cd 전에 구해 둔다. Plugin 훅으로
# 불릴 때는 CLAUDE_PLUGIN_ROOT 가 있지만, 없으면 이 스크립트 위치에서 구한다.
# cd 뒤에는 "$0" 이 상대 경로일 때 깨질 수 있어 미리 계산한다.
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

input="$(cat)"

# uv·jq·gh 가 있는지 보고 Windows 에서는 없는 것을 winget 으로 설치한다(#116).
# 아래에서 jq 를 쓰기 전에 해 둔다. 실패해도 세션 시작을 막지 않는다.
tools_notice=""
if [ -f "${plugin_root}/hooks/ensure-tools.sh" ]; then
  tools_notice="$(bash "${plugin_root}/hooks/ensure-tools.sh" </dev/null 2>/dev/null || true)"
fi

# 세션이 다른 git worktree 로 옮겨가도(#71) 그 worktree 기준으로 판단하기
# 위해, 훅에 오는 stdin JSON 의 cwd 를 최우선으로 쓴다. CLAUDE_PROJECT_DIR 은
# 세션을 "처음 연" 폴더라 세션 도중 다른 worktree 로 옮기면 더는 맞지 않는다.
# cwd 가 없거나 존재하지 않는 디렉터리면 CLAUDE_PROJECT_DIR 로, 그것도 없으면
# 지금 디렉터리로 되돌아간다.
if command -v jq >/dev/null 2>&1; then
  stdin_cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)"
else
  # jq 가 없으면 근사 정규식으로 뽑는다. 아래에서 존재하는 디렉터리인지 다시
  # 검증하므로 완벽한 JSON 파서가 아니어도 안전하다.
  stdin_cwd="$(printf '%s' "$input" | grep -o '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | sed -E 's/.*"cwd"[[:space:]]*:[[:space:]]*"([^"]*)"/\1/' || true)"
fi
stdin_cwd="$(printf '%s' "$stdin_cwd" | tr -d '\r')"
if [ -n "$stdin_cwd" ] && [ -d "$stdin_cwd" ]; then
  resolved_dir="$stdin_cwd"
else
  resolved_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"
fi
cd "$resolved_dir"

lines=""
add() {
  lines="${lines}$1
"
}

if [ -n "$tools_notice" ]; then
  add "$tools_notice"
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  printf '%s' "$lines"
  echo "이 디렉터리는 git 저장소가 아닙니다. harness 의 자동 동기화가 동작하지 않습니다. 다음: 작업할 프로젝트 폴더(git 저장소)에서 Claude Code 를 다시 여십시오."
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
repo_name="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$resolved_dir")")"
CARRYOVER="$(git rev-parse --git-dir)/${repo_name}-unfinished"
CARRYOVER_PENDING=""
if [ -f "$CARRYOVER" ]; then
  add "지난 세션에서 남은 경고가 있습니다."
  add "$(cat "$CARRYOVER")"
  CARRYOVER_PENDING="$CARRYOVER"
fi

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 알수없음)"
add "현재 브랜치: $branch"

# SAP ADT MCP 를 쓰는 저장소(.mcp.json 이 있다)인데 env/adt-tiers.yaml 이 없으면 테넌트별
# 쓰기 차단이 꺼져 있다(#148, 파일 없음은 코드 규칙만 검사하고 데이터 도구만 되묻는다).
# 조용히 넘기면 꺼진 줄 모르므로 알린다. .mcp.json 이 없는 저장소는 말하지 않는다.
repo_top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ -f "$repo_top/.mcp.json" ] && [ ! -f "$repo_top/env/adt-tiers.yaml" ]; then
  add "env/adt-tiers.yaml 이 없어 테넌트별 쓰기 차단이 꺼져 있습니다. 다음: 사람이 env/adt-tiers.yaml 에 MCP 서버별 writes_allowed 와 write_tools 를 적으십시오(예시: env/adt-tiers.example.yaml 또는 harness README 의 \"테넌트별 쓰기 차단\" 절)."
fi

# 기준 폴더(templates/ 와 rules/ 를 함께 가진 폴더)가 하나도 없는 Project Repository 는
# doc-guard 가 걸리지 않는다. scaffold 를 모르면 모른 채 작업을 시작하므로 안내한다(#128).
# 자동 실행은 묻지 않고 파일을 만드는 일이라 하지 않는다. 플러그인 저장소(marketplace.json
# 이 꼭대기에 있다)와 HARNESS_NO_SCAFFOLD_HINT=1 은 안내하지 않는다. 작업 트리를 보므로
# 아직 커밋하지 않은 scaffold 결과도 인정한다. 꼭대기에서 3단계 아래 폴더까지만 찾고
# .git·node_modules·.venv 같은 폴더는 들어가지 않는다. 판정이 실패해도 훅은 계속 간다.
if [ "${HARNESS_NO_SCAFFOLD_HINT:-}" != "1" ] && [ ! -f "$repo_top/.claude-plugin/marketplace.json" ]; then
  has_standards=""
  while IFS= read -r tpl_dir; do
    tpl_dir="${tpl_dir%$'\r'}"
    if [ -d "$(dirname "$tpl_dir")/rules" ]; then
      has_standards="1"
      break
    fi
  done < <(find "$repo_top" -maxdepth 4 \
    \( -name .git -o -name node_modules -o -name .venv -o -name venv -o -name __pycache__ \) -prune \
    -o -type d -name templates -print 2>/dev/null || true)
  if [ -z "$has_standards" ]; then
    add "기준 폴더(templates/ 와 rules/)가 없습니다. 다음: /harness:scaffold 를 실행해 표준 구조를 만드십시오(이 저장소가 Project Repository 가 아니면 HARNESS_NO_SCAFFOLD_HINT=1 로 이 안내를 끌 수 있습니다)."
  fi
fi

git_dir="$(git rev-parse --git-dir)"

# 리베이스를 실행하고 성공·충돌·그 밖의 실패를 메시지로 남긴다. 실패해도
# 이 함수 자체는 항상 0 을 반환한다 — set -e 때문에 스크립트 전체가
# 죽어 세션 시작 요약이 통째로 사라지는 것을 막기 위해서다.
run_rebase() {
  local target="$1"
  local success_msg="$2"
  local rebase_output
  if rebase_output="$(git rebase "$target" 2>&1)"; then
    add "$success_msg"
    return 0
  fi
  # 리베이스가 중간에 멈췄으면 되돌린다. 세션을 매끄럽게 시작하려고 만든
  # 훅이 저장소를 충돌 상태로 남겨 두면, 그다음에 무엇을 해도 막힌다.
  if [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ]; then
    if git rebase --abort >/dev/null 2>&1; then
      add "$target 기준 리베이스가 충돌해 원래 상태로 되돌렸습니다. 원격과의 차이는 /harness:sync 로 다시 확인하십시오."
    else
      # abort 실패를 성공으로 보고하면, 리베이스가 진행 중인 상태로 남아
      # .githooks/pre-commit 의 브랜치 검사가 통째로 건너뛰어지는데도
      # 그 사실이 드러나지 않는다.
      add "$target 기준 리베이스가 충돌했고 되돌리기(git rebase --abort)도 실패했습니다. 저장소가 리베이스 진행 중 상태로 남아 있습니다. 다음: git status 로 상태를 확인하고 git rebase --abort 를 직접 실행하십시오(어려우면 사람에게 도움을 요청)."
    fi
  else
    # 첫 줄만 담는다 — git 오류는 대개 첫 줄에 원인이 있고, 전체를 실으면
    # 세션 시작 요약이 리베이스 로그로 채워진다.
    local rebase_err
    rebase_err="$(printf '%s\n' "$rebase_output" | head -n1)"
    add "$target 기준 리베이스가 실패했습니다: ${rebase_err:-원인을 알 수 없습니다}. /harness:sync 로 상황을 직접 확인하십시오."
  fi
  return 0
}

if [ "$branch" = "main" ]; then
  add "main 에서는 커밋할 수 없습니다. 작업을 시작하려면 /harness:start 를 실행하십시오."
fi

# /harness:deliver 가 스테이징에서 빼는 것(.superpowers/, *handoff*.md)은 여기서도
# 세지 않는다(#59). 세면 인계 메모 하나만 남아도 deliver 로 없앨 수 없는
# 경고가 매번 뜬다. 한글 경로는 porcelain 이 따옴표로 감싸므로 따옴표도 허용한다.
# --untracked-files=all 로 파일 단위로 본다. 기본값은 추적 안 된 폴더를 `?? docs/`
# 한 줄로 접어, 그 안에 인계 메모만 있어도 걸러 내지 못한다.
#
# 이 값은 아래 자동 동기화를 할지 말지도 정한다 — dirty 한 트리에서 훅이
# 알아서 stash 하거나 커밋하면 사용자 모르게 작업 내용이 섞이거나 사라질 수
# 있어서, 그런 경우 자동 동기화 자체를 건너뛴다(자동 stash·자동 커밋 금지).
changed="$(git status --porcelain --untracked-files=all | grep -Ev '^.. "?((.*/)?\.superpowers/|.*handoff.*\.md"?$)' || true)"

# 이미 진행 중인 리베이스나 병합이 있으면 자동 동기화를 시도하지 않는다. 그
# 위에 또 리베이스를 걸면 실패하거나, 진행 중이던 것과 뒤섞여 저장소를 더
# 꼬아 놓을 수 있다.
if [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ] || [ -f "$git_dir/MERGE_HEAD" ]; then
  add "이미 리베이스나 병합이 진행 중이라 자동 동기화를 건너뜁니다. 다음: git status 로 상태를 확인하고 git rebase --continue(또는 --abort), git merge --abort 로 마무리한 뒤 /harness:sync 를 실행하십시오."
elif git remote get-url origin >/dev/null 2>&1; then
  # fetch 는 작업 트리를 건드리지 않으므로 미커밋 변경이 있어도 한다. 건너뛰는
  # 것은 리베이스뿐이다 — 그래야 /harness:sync 를 부르기 전에도 원격 상태를 본다.
  if fetch_output="$(git fetch --all --prune 2>&1)"; then
    add "원격을 가져왔습니다."
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
    if [ -n "$changed" ]; then
      add "커밋되지 않은 변경이 있어 자동 동기화(리베이스)를 건너뛰었습니다. /harness:sync 로 당겨받으십시오."
    elif [ -n "$upstream" ]; then
      behind="$(git rev-list --count "HEAD..$upstream" 2>/dev/null || echo 0)"
      if [ "$behind" = "0" ]; then
        add "이미 최신 상태입니다($upstream 기준)."
      else
        run_rebase "$upstream" "$upstream 기준으로 최신 상태로 맞췄습니다."
      fi
    elif git rev-parse --verify -q origin/main >/dev/null 2>&1; then
      behind="$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
      if [ "$behind" = "0" ]; then
        add "이미 최신 상태입니다(origin/main 기준). 원격 짝 브랜치가 없어 origin/main 을 기준으로 확인했습니다."
      else
        run_rebase origin/main "원격 짝 브랜치가 없어 origin/main 기준으로 맞췄습니다."
      fi
    else
      add "원격 짝 브랜치가 없고 origin/main 도 없어 자동 동기화를 건너뜁니다. 다음: 원격에 main 브랜치가 있는지 확인하고, 작업을 마칠 때 /harness:deliver 로 푸시하십시오."
    fi
  else
    fetch_err="$(printf '%s\n' "$fetch_output" | head -n1)"
    add "fetch 에 실패했습니다: ${fetch_err:-원인을 알 수 없습니다}. 다음: 네트워크를 확인하고 gh auth status 로 로그인 상태를 보십시오(로그인 안 됨이면 사람이 gh auth login 실행). 확인한 뒤 /harness:sync 를 실행하십시오."
  fi
else
  add "원격 저장소가 연결되어 있지 않습니다. 푸시와 PR 과 이슈 관련 동작은 원격을 연결한 뒤에 가능합니다. 다음: 사람이 할 일 - 프로젝트의 GitHub 저장소 주소를 확인해 git remote add origin 주소 로 연결하십시오."
fi

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
