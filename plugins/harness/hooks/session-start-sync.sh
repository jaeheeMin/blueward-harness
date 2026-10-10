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
# 옛 형식(경고 텍스트가 덧붙여 쌓인 파일, 첫 줄이 format=2 가 아니다)은 한 번 그대로
# 보여 주고 지운다(#224). 새 형식(format=2)은 원격을 가져온 뒤 아래에서 판정한다.
# stop-deliver.sh 가 덮어쓰기 전에 옆으로 옮겨 둔 `.legacy` 파일도 같게 다룬다.
LEGACY_PENDING=()
for legacy_file in "$CARRYOVER" "${CARRYOVER}.legacy"; do
  if [ -f "$legacy_file" ] && [ "$(head -n1 "$legacy_file" | tr -d '\r')" != "format=2" ]; then
    add "지난 세션에서 남은 경고가 있습니다."
    add "$(cat "$legacy_file")"
    LEGACY_PENDING+=("$legacy_file")
  fi
done

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

# --- 지난 세션 기록 판정(#224) --------------------------------------------
#
# stop-deliver.sh 가 대답마다 덮어쓰는 기록(format=2)을 읽어, 이미 처리된 것은 조용히
# 지우고 처리 안 된 것만 알린다. 원격을 가져온 뒤에 불러야 원격 반영이 보인다.
# 판정 중 git 명령이 실패하면 통과로 뭉개지 않고 "확인 불능" 으로 알리고 기록을 남긴다.
# 기록을 어떻게 고칠지는 keep_snap, keep_unpushed 로 정하고 finish_carryover 가 적용한다.
keep_snap=0
keep_unpushed=0
clean_ref=""
carry_active=0

# 경로를 글롭으로 해석하지 않게 한다(pages/[id].tsx 같은 이름).
CG() { git --literal-pathspecs -C "$repo_top" "$@"; }

# 작은따옴표로 감싸 셸에 그대로 붙여 넣을 수 있게 한다.
shq() {
  local s="$1" out="" q="'" bs=$'\\' pre
  while [[ "$s" == *"$q"* ]]; do
    pre="${s%%"$q"*}"
    out="$out$pre$q$bs$q$q"
    s="${s#*"$q"}"
  done
  printf '%s' "'$out$s'"
}

judge_carryover() {
  [ -f "$CARRYOVER" ] || return 0
  [ "$(head -n1 "$CARRYOVER" | tr -d '\r')" = "format=2" ] || return 0
  carry_active=1

  local line first=1
  local r_snap_ref="" r_snap_commit="" r_snap_time="" r_snap_failed="" r_snap_files="" r_big_files=""
  local r_unpushed_branch="" r_unpushed_head=""
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    if [ "$first" -eq 1 ]; then first=0; continue; fi
    case "$line" in
      snap_ref=*) r_snap_ref="${line#snap_ref=}" ;;
      snap_commit=*) r_snap_commit="${line#snap_commit=}" ;;
      snap_time=*) r_snap_time="${line#snap_time=}" ;;
      snap_failed=*) r_snap_failed="${line#snap_failed=}" ;;
      snap_file=*) r_snap_files="${r_snap_files}${line#snap_file=}"$'\n' ;;
      big_file=*) r_big_files="${r_big_files}${line#big_file=}"$'\n' ;;
      unpushed_branch=*) r_unpushed_branch="${line#unpushed_branch=}" ;;
      unpushed_head=*) r_unpushed_head="${line#unpushed_head=}" ;;
    esac
  done < "$CARRYOVER"

  # 1) 작업 사본
  if [ -n "$r_snap_commit" ] || [ -n "$r_snap_failed" ] || [ -n "$r_big_files" ]; then
    if [ -n "$changed" ]; then
      # 아직 변경이 남아 있다. 아래 "커밋되지 않은 변경" 안내로 충분하다. 기록과 ref 는 둔다.
      keep_snap=1
    else
      judge_snapshot "$r_snap_ref" "$r_snap_commit" "$r_snap_time" "$r_snap_failed" "$r_snap_files" "$r_big_files"
    fi
  fi

  # 2) push 안 된 커밋
  if [ -n "$r_unpushed_branch" ]; then
    judge_unpushed "$r_unpushed_branch" "$r_unpushed_head"
  fi
}

judge_snapshot() {
  local snap_ref="$1" snap_commit="$2" snap_time="$3" snap_failed="$4" snap_files="$5" big_files="$6"
  local ent st f cnt head_blob snap_blob eval_err=0
  local lost_files=() lost_del=() missing_big=()

  if [ -n "$snap_failed" ]; then
    add "지난 세션 종료 때 커밋되지 않은 변경이 있었으나 작업 사본을 뜨지 못했습니다. 그 변경이 지금 남아 있는지 확인할 수 없습니다(지난 작업 확인 불능). 다음: git log 와 git status 로 직접 확인하십시오."
  fi

  # 크기 때문에 사본에 담지 못한 새 파일이 커밋도 안 된 채 사라졌는지 본다(사본이 없어도 본다).
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -e "$repo_top/$f" ] && continue
    CG rev-parse -q --verify "HEAD:$f" >/dev/null 2>&1 && continue
    missing_big+=("$f")
  done <<< "$big_files"

  if [ -z "$snap_commit" ]; then
    for f in ${missing_big[@]+"${missing_big[@]}"}; do
      add "크기 상한(50MB)을 넘어 작업 사본에 담지 못한 파일이 커밋되지 않은 채 사라졌습니다(복구할 수 없음): ${f}"
    done
    return 0
  fi

  if ! CG cat-file -e "${snap_commit}^{commit}" 2>/dev/null; then
    add "지난 세션의 작업 사본(${snap_commit:0:7})을 찾을 수 없어 확인할 수 없습니다(지난 작업 확인 불능)."
    keep_snap=1
    return 0
  fi

  while IFS= read -r ent; do
    [ -n "$ent" ] || continue
    st="${ent%% *}"
    f="${ent#* }"
    head_blob="$(CG rev-parse -q --verify "HEAD:$f" 2>/dev/null || true)"
    if [ "$st" = "D" ]; then
      [ -z "$head_blob" ] && continue
    else
      snap_blob="$(CG rev-parse -q --verify "${snap_commit}:$f" 2>/dev/null || true)"
      if [ -z "$snap_blob" ]; then eval_err=1; continue; fi
      [ "$head_blob" = "$snap_blob" ] && continue
    fi
    # 사본 이후 어느 ref(원격 포함, refs/harness 제외)에서든 이 파일을 건드린 커밋이 있으면 처리된 것으로 본다.
    if cnt="$(CG rev-list --count --since="$snap_time" --exclude='refs/harness/*' --all "^${snap_commit}" -- "$f" 2>/dev/null)"; then
      [ "${cnt:-0}" -gt 0 ] && continue
    else
      eval_err=1
      continue
    fi
    if [ "$st" = "D" ]; then lost_del+=("$f"); else lost_files+=("$f"); fi
  done <<< "$snap_files"

  if [ "$eval_err" -eq 1 ]; then
    add "지난 세션의 미커밋 작업을 일부 판정하지 못했습니다(지난 작업 확인 불능). 작업 사본 ${snap_commit} 는 남겨 두었습니다. 다음: git diff --name-status HEAD ${snap_commit} 로 직접 비교하십시오."
    keep_snap=1
    return 0
  fi

  if [ "${#lost_files[@]}" -gt 0 ] || [ "${#lost_del[@]}" -gt 0 ] || [ "${#missing_big[@]}" -gt 0 ]; then
    local n=$(( ${#lost_files[@]} + ${#lost_del[@]} )) shown=0 args=""
    if [ "$n" -gt 0 ]; then
      add "지난 세션의 미커밋 작업 가운데 커밋되지 않고 사라진 것이 ${n}개 있습니다. 작업 사본: ${snap_commit}"
      for f in ${lost_files[@]+"${lost_files[@]}"}; do
        [ "$shown" -lt 10 ] || break
        shown=$((shown + 1))
        add "- ${f}"
        args="${args} $(shq "$f")"
      done
      for f in ${lost_del[@]+"${lost_del[@]}"}; do
        [ "$shown" -lt 10 ] || break
        shown=$((shown + 1))
        add "- ${f} (사본에서는 삭제된 파일이나 지금 HEAD 에 남아 있음)"
      done
      if [ "$n" -gt "$shown" ]; then
        add "... 외 $((n - shown))개. 전체: git diff --name-status HEAD ${snap_commit}"
      fi
      if [ -n "$args" ]; then
        add "다음: git --literal-pathspecs restore --source=${snap_commit} --${args}"
      fi
      add "복구가 끝나면 사본 ref 를 지울 수 있습니다: git update-ref -d ${snap_ref}"
    fi
    for f in ${missing_big[@]+"${missing_big[@]}"}; do
      add "크기 상한(50MB)을 넘어 작업 사본에 담지 못한 파일이 커밋되지 않은 채 사라졌습니다(복구할 수 없음): ${f}"
    done
    # 같은 경고가 되풀이되지 않게 기록은 지우되, 복구용 사본 ref 는 남긴다.
    return 0
  fi

  # 전부 처리됐다. 조용히 기록과 ref 를 지운다.
  case "$snap_ref" in
    refs/harness/unfinished/*) clean_ref="$snap_ref" ;;
  esac
}

judge_unpushed() {
  local ub="$1" uh="$2" tr_state contains cnt up
  if ! CG show-ref -q --verify "refs/heads/$ub" 2>/dev/null; then
    return 0   # 브랜치가 지워졌다
  fi
  tr_state="$(CG for-each-ref --format='%(upstream:track)' "refs/heads/$ub" 2>/dev/null || true)"
  if [ "$tr_state" = "[gone]" ]; then
    return 0   # 원격 브랜치가 병합 뒤 지워졌다. squash 병합은 커밋을 포함 관계로 알 수 없어 이것으로 본다.
  fi
  if [ -n "$uh" ] && CG cat-file -e "${uh}^{commit}" 2>/dev/null; then
    if contains="$(CG branch -r --contains "$uh" 2>/dev/null)"; then
      [ -n "$contains" ] && return 0   # 어느 원격 ref 에 들어갔다
    else
      add "push 안 한 커밋이 있었는지 판정하지 못했습니다(지난 작업 확인 불능). 다음: git status -sb 로 ${ub} 브랜치를 확인하십시오."
      keep_unpushed=1
      return 0
    fi
  else
    # 커밋이 리베이스·amend 로 바뀌었다. 지금 브랜치 기준으로 다시 센다.
    up="$(CG rev-parse --abbrev-ref --symbolic-full-name "${ub}@{u}" 2>/dev/null || true)"
    if [ -n "$up" ]; then
      cnt="$(CG rev-list --count "${ub}@{u}..${ub}" 2>/dev/null || echo 0)"
    elif [ -n "$(CG remote 2>/dev/null || true)" ]; then
      cnt="$(CG rev-list --count "$ub" --not --remotes 2>/dev/null || echo 0)"
    else
      cnt=0
    fi
    [ "${cnt:-0}" -gt 0 ] || return 0
  fi
  add "push 안 한 커밋이 ${ub} 브랜치에 있습니다. 다음: /harness:deliver"
  keep_unpushed=1
}

# 판정 결과를 기록에 반영한다. 남길 것이 없으면 파일을 지우고, 한쪽만 남기면 다른 쪽 줄을 뺀다.
finish_carryover() {
  [ "$carry_active" -eq 1 ] || return 0
  if [ "$keep_snap" -eq 0 ] && [ "$keep_unpushed" -eq 0 ]; then
    rm -f "$CARRYOVER"
  else
    local drop=""
    [ "$keep_snap" -eq 1 ] || drop='^(snap_commit|snap_time|sig|snap_failed|snap_file|big_file)='
    if [ "$keep_unpushed" -eq 0 ]; then
      drop="${drop:+${drop}|}^unpushed_(branch|head|count)="
    fi
    if [ -n "$drop" ]; then
      grep -Ev "$drop" "$CARRYOVER" > "${CARRYOVER}.tmp.$$" || true
      mv -f "${CARRYOVER}.tmp.$$" "$CARRYOVER"
    fi
  fi
  if [ -n "$clean_ref" ]; then
    CG update-ref -d "$clean_ref" >/dev/null 2>&1 || true
  fi
}

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
# 지난 세션 기록 판정은 원격을 가져온 뒤에만 한다(원격에 병합됐는지, 원격 브랜치가 지워졌는지
# 알아야 하므로). ok: fetch 성공, none: 원격이 없어 가져올 것이 없다, 그 밖: 판정하지 않는다.
fetch_state="skipped"
if [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ] || [ -f "$git_dir/MERGE_HEAD" ]; then
  add "이미 리베이스나 병합이 진행 중이라 자동 동기화를 건너뜁니다. 다음: git status 로 상태를 확인하고 git rebase --continue(또는 --abort), git merge --abort 로 마무리한 뒤 /harness:sync 를 실행하십시오."
elif git remote get-url origin >/dev/null 2>&1; then
  # fetch 는 작업 트리를 건드리지 않으므로 미커밋 변경이 있어도 한다. 건너뛰는
  # 것은 리베이스뿐이다 — 그래야 /harness:sync 를 부르기 전에도 원격 상태를 본다.
  fetch_state="failed"
  if fetch_output="$(git fetch --all --prune 2>&1)"; then
    fetch_state="ok"
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
  fetch_state="none"
  add "원격 저장소가 연결되어 있지 않습니다. 푸시와 PR 과 이슈 관련 동작은 원격을 연결한 뒤에 가능합니다. 다음: 사람이 할 일 - 프로젝트의 GitHub 저장소 주소를 확인해 git remote add origin 주소 로 연결하십시오."
fi

case "$fetch_state" in
  ok | none) judge_carryover ;;
  *)
    # 원격 상태를 모르면 병합·삭제 여부를 판정할 수 없다. 통과시키지 않고 기록을 남긴다.
    if [ -f "$CARRYOVER" ] && [ "$(head -n1 "$CARRYOVER" | tr -d '')" = "format=2" ]; then
      add "원격을 가져오지 못해 지난 작업을 판정하지 못했습니다(지난 작업 확인 불능). 기록은 남겨 두었으니 원격 연결을 확인한 뒤 다음 세션에서 다시 판정합니다."
    fi
    ;;
esac

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
for legacy_file in ${LEGACY_PENDING[@]+"${LEGACY_PENDING[@]}"}; do
  rm -f "$legacy_file"
done
finish_carryover

exit 0
