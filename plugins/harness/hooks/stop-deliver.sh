#!/usr/bin/env bash
set -euo pipefail

input="$(cat)"

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
  stdin_cwd="$(printf '%s' "$input" | grep -o '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | sed -E 's/.*"cwd"[[:space:]]*:[[:space:]]*"([^"]*)"/\1/')"
fi
stdin_cwd="$(printf '%s' "$stdin_cwd" | tr -d '\r')"
if [ -n "$stdin_cwd" ] && [ -d "$stdin_cwd" ]; then
  resolved_dir="$stdin_cwd"
else
  resolved_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"
fi
cd "$resolved_dir"

# 종료 코드 0 으로 끝나는 훅의 표준 오류는 디버그 로그로만 가고 사용자 화면에
# 닿지 않는다. 그래서 세션이 끝난 뒤에도 남아야 하는 정보는 파일에 적는다.
# 다음 세션의 시작 훅이 이 파일을 읽어 판정하고 필요한 것만 전한다(#224).
# 경로를 `.git` 으로 적지 않고 물어보는 이유는, 연결된 워크트리에서는 `.git` 이
# 디렉터리가 아니라 파일이어서 그 아래에 쓸 수 없기 때문이다. 파일 이름에
# 저장소 이름을 넣는 이유는, 이 훅이 harness 플러그인으로 여러 저장소에
# 설치되므로 특정 저장소 이름을 하드코딩하지 않기 위해서다.
#
# 기록 파일(첫 줄 `format=2`)은 대답마다 통째로 덮어쓴다. 예전처럼 경고를 덧붙여
# 쌓지 않는다. 키는 branch, head, snap_ref, snap_commit, snap_time, sig,
# snap_failed, snap_file(여러 줄, "상태 경로"), big_file(여러 줄), unpushed_branch,
# unpushed_head, unpushed_count 이다. 파일 이름에 줄바꿈이 든 경로는 다루지 않는다.
#
# 사본 ref(refs/harness/*)는 로컬 전용이다. 일반 push 로는 나가지 않으므로 --mirror
# 나 refs/harness 를 지정한 push 는 하지 않는다(사본에는 .gitignore 되지 않은 비밀
# 파일이 들어 있을 수 있다).
#
# 이 훅은 대답마다 돈다. Windows 에서는 프로세스 하나가 비싸므로 외부 프로세스
# 수가 변경 파일 수와 무관하도록(git status 한 번, stat 은 한꺼번에) 짠다.
{
  IFS= read -r git_dir_path || true
  IFS= read -r top || true
  IFS= read -r git_abs || true
} < <(git rev-parse --git-dir --show-toplevel --absolute-git-dir 2>/dev/null) || true
git_dir_path="${git_dir_path%$'\r'}"; top="${top%$'\r'}"; git_abs="${git_abs%$'\r'}"
if [ -z "$git_dir_path" ]; then
  exit 0
fi
if [ -z "$top" ]; then
  top="$resolved_dir"
fi
repo_name="${top##*/}"
CARRYOVER="${git_abs:-$git_dir_path}/${repo_name}-unfinished"

# 이후 git 명령과 경로가 저장소 꼭대기 기준이 되게 한다. 하위 폴더에서 열려도
# 같다.
if [ -d "$top" ]; then
  cd "$top"
fi

# 작업 사본을 붙잡는 ref 는 worktree 마다 달라야 한다(refs 는 worktree 간 공유).
case "$git_abs" in
  */worktrees/*) wt_id="wt-${git_abs##*/}" ;;
  *) wt_id="root" ;;
esac
# 공용 git 디렉터리(refs 와 config 가 있는 곳). 프로세스를 아끼려고 파일을 직접 읽는 데 쓴다.
case "$git_abs" in
  */worktrees/*) git_common="${git_abs%/worktrees/*}" ;;
  *) git_common="$git_abs" ;;
esac
wt_id="${wt_id//[^A-Za-z0-9._-]/_}"
SNAP_REF="refs/harness/unfinished/${wt_id}"

# 이 크기를 넘는 새 파일은 사본에 넣지 않고 이름만 남긴다.
BIG_LIMIT="${HARNESS_SNAPSHOT_MAX_BYTES:-$((50 * 1024 * 1024))}"

warn() {
  printf '%s\n' "$1"
}

# 사본에서 뺄 경로: deliver 가 스테이징에서 빼는 것(.superpowers/, *handoff*.md)과 같다(#59).
is_excluded_path() {
  case "$1" in
    .superpowers/* | */.superpowers/* | *handoff*.md) return 0 ;;
  esac
  return 1
}

# git status --porcelain=v2 -z 한 번으로 브랜치·HEAD·upstream·앞선 커밋 수와 바뀐 파일을 읽는다.
# 채우는 값: s_branch s_oid s_upstream s_ahead s_has_ab changed(= "상태 경로" 줄들)
#           untracked_arr tracked_arr (사본에서 뺀 경로 제외) sig_status
tok_rest=""
strip_tokens() {
  tok_rest="$1"
  local n="$2"
  while [ "$n" -gt 0 ]; do
    tok_rest="${tok_rest#* }"
    n=$((n - 1))
  done
}

scan_status() {
  s_branch=""; s_oid=""; s_upstream=""; s_ahead=""; s_has_ab=0
  changed=""; sig_status=""
  untracked_arr=(); tracked_arr=()
  local entry skip=0 xy rest
  while IFS= read -r -d '' entry; do
    if [ "$skip" -eq 1 ]; then
      skip=0
      sig_status="${sig_status}orig ${entry}"$'\n'
      continue
    fi
    case "$entry" in
      "# branch.oid "*) s_oid="${entry#\# branch.oid }" ;;
      "# branch.head "*) s_branch="${entry#\# branch.head }" ;;
      "# branch.upstream "*) s_upstream="${entry#\# branch.upstream }" ;;
      "# branch.ab "*)
        s_has_ab=1
        rest="${entry#\# branch.ab +}"
        s_ahead="${rest%% *}"
        ;;
      "# "*) ;;
      "? "*)
        rest="${entry#\? }"
        is_excluded_path "$rest" && continue
        changed="${changed}?? ${rest}"$'\n'
        untracked_arr+=("$rest")
        sig_status="${sig_status}?? ${rest}"$'\n'
        ;;
      "1 "* | "2 "* | "u "*)
        xy="${entry:2:2}"
        case "$entry" in
          "1 "*) strip_tokens "$entry" 8 ;;
          "2 "*) strip_tokens "$entry" 9; skip=1 ;;
          *) strip_tokens "$entry" 10 ;;
        esac
        is_excluded_path "$tok_rest" && continue
        changed="${changed}${xy} ${tok_rest}"$'\n'
        tracked_arr+=("$tok_rest")
        sig_status="${sig_status}${xy} ${tok_rest}"$'\n'
        ;;
    esac
  done < <(git status --porcelain=v2 -z --branch --untracked-files=all)
  changed="${changed%$'\n'}"
  [ "$s_branch" = "(detached)" ] && s_branch=""
  [ "$s_oid" = "(initial)" ] && s_oid=""
  return 0
}

# "크기 수정시각 이름" 줄들을 한 번의 stat 호출로 얻는다(파일이 많아도 xargs 가 몇 번만 부른다).
# 지워진 파일은 줄이 없다. GNU stat 이 안 되면 BSD stat 으로 다시 시도한다.
stat_many() {
  [ "$#" -gt 0 ] || return 0
  local out=""
  if command -v xargs >/dev/null 2>&1; then
    out="$(printf '%s\0' "$@" | xargs -0 stat -c '%s %Y %n' -- 2>/dev/null || true)"
    [ -n "$out" ] || out="$(printf '%s\0' "$@" | xargs -0 stat -f '%z %m %N' -- 2>/dev/null || true)"
  else
    out="$(stat -c '%s %Y %n' -- "$@" 2>/dev/null || stat -f '%z %m %N' -- "$@" 2>/dev/null || true)"
  fi
  printf '%s' "$out"
}

# 이전 기록을 r_* 변수로 읽는다. 없거나 옛 형식이면 r_format 이 비어 있다.
reset_record_vars() {
  r_format=""; r_branch=""; r_head=""; r_snap_ref=""; r_snap_commit=""; r_snap_time=""
  r_sig=""; r_snap_failed=""; r_snap_files=""; r_big_files=""
  r_unpushed_branch=""; r_unpushed_head=""; r_unpushed_count=""
}

read_record() {
  local line first=1
  reset_record_vars
  [ -f "$CARRYOVER" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    if [ "$first" -eq 1 ]; then
      first=0
      [ "$line" = "format=2" ] || { reset_record_vars; return 0; }
      r_format=2
      continue
    fi
    case "$line" in
      branch=*) r_branch="${line#branch=}" ;;
      head=*) r_head="${line#head=}" ;;
      snap_ref=*) r_snap_ref="${line#snap_ref=}" ;;
      snap_commit=*) r_snap_commit="${line#snap_commit=}" ;;
      snap_time=*) r_snap_time="${line#snap_time=}" ;;
      sig=*) r_sig="${line#sig=}" ;;
      snap_failed=*) r_snap_failed="${line#snap_failed=}" ;;
      snap_file=*) r_snap_files="${r_snap_files}${line#snap_file=}"$'\n' ;;
      big_file=*) r_big_files="${r_big_files}${line#big_file=}"$'\n' ;;
      unpushed_branch=*) r_unpushed_branch="${line#unpushed_branch=}" ;;
      unpushed_head=*) r_unpushed_head="${line#unpushed_head=}" ;;
      unpushed_count=*) r_unpushed_count="${line#unpushed_count=}" ;;
    esac
  done < "$CARRYOVER"
  return 0
}

emit_list() {
  local key="$1" text="$2" l
  [ -n "$text" ] || return 0
  while IFS= read -r l; do
    [ -n "$l" ] && printf '%s=%s\n' "$key" "$l"
  done <<< "$text"
  return 0
}

# w_* 변수로 기록 파일을 통째로 쓴다. 임시 파일에 쓴 뒤 옮겨 반쯤 쓴 기록이 남지 않게 한다.
write_record() {
  local tmp="${CARRYOVER}.tmp.$$"
  {
    printf 'format=2\n'
    printf 'branch=%s\n' "$w_branch"
    printf 'head=%s\n' "$w_head"
    printf 'snap_ref=%s\n' "$w_snap_ref"
    printf 'snap_commit=%s\n' "$w_snap_commit"
    printf 'snap_time=%s\n' "$w_snap_time"
    printf 'sig=%s\n' "$w_sig"
    printf 'snap_failed=%s\n' "$w_snap_failed"
    emit_list snap_file "$w_snap_files"
    emit_list big_file "$w_big_files"
    printf 'unpushed_branch=%s\n' "$w_unpushed_branch"
    printf 'unpushed_head=%s\n' "$w_unpushed_head"
    printf 'unpushed_count=%s\n' "$w_unpushed_count"
  } > "$tmp" && mv -f "$tmp" "$CARRYOVER"
}

# 저장소 config 에 [remote "..."] 가 있는지 본다(git 프로세스를 띄우지 않는다).
has_remote() {
  local l
  [ -f "$git_common/config" ] || return 1
  while IFS= read -r l || [ -n "$l" ]; do
    case "$l" in
      "[remote "*) return 0 ;;
    esac
  done < "$git_common/config"
  return 1
}

# push 안 된 커밋이 있는 현재 브랜치를 u_* 에 담는다. 없으면 비워 둔다.
# 판정하지 못하면 u_err=1 (없다고 단정하지 않는다). 앞선 커밋 수는 status 가 이미 알려 준다.
compute_unpushed() {
  u_branch=""; u_head=""; u_count=""; u_err=0
  local cnt=0
  [ -n "$branch" ] && [ -n "$head" ] || return 0
  if [ -n "$s_upstream" ]; then
    # upstream 이 설정돼 있는데 앞선 수가 없으면 원격 브랜치가 사라진(gone) 것이다.
    [ "$s_has_ab" -eq 1 ] || return 0
    cnt="$s_ahead"
  else
    # upstream 이 없으면 어느 원격 ref 에도 없는 커밋을 센다. 원격이 아예 없으면 푸시할 곳이 없다.
    has_remote || return 0
    cnt="$(git rev-list --count HEAD --not --remotes 2>/dev/null)" || { u_err=1; return 0; }
  fi
  if [ "${cnt:-0}" -gt 0 ]; then
    u_branch="$branch"
    u_head="$head"
    u_count="$cnt"
  fi
  return 0
}

# 바뀐 파일 목록 + 크기 + 수정 시각 + HEAD 의 해시(sig), 새 파일 중 큰 것(big_arr, big_text).
compute_sig() {
  local stat_u stat_t line rest size
  stat_u="$(stat_many ${untracked_arr[@]+"${untracked_arr[@]}"})"
  stat_t="$(stat_many ${tracked_arr[@]+"${tracked_arr[@]}"})"
  big_arr=(); big_text=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    size="${line%% *}"
    rest="${line#* }"
    rest="${rest#* }"
    case "$size" in '' | *[!0-9]*) continue ;; esac
    if [ "$size" -gt "$BIG_LIMIT" ]; then
      big_arr+=("$rest")
      big_text="${big_text}${rest}"$'\n'
    fi
  done <<< "$stat_u"
  sig="$(printf '%s\n%s\n%s\n%s' "$head" "$sig_status" "$stat_u" "$stat_t" | git hash-object --stdin 2>/dev/null || true)"
}

# 실제 index 와 작업 트리는 건드리지 않고, 임시 index 에 작업 사본을 떠 commit 으로 만들어
# SNAP_REF 로 붙잡는다. 성공하면 n_commit, n_files 를 채운다(담을 변경이 없으면 n_commit 은 비어 있다).
# 커밋이 하나도 없는 저장소(HEAD 없음)는 빈 트리를 기준으로 삼는다. 어느 단계든 실패하면 1.
take_snapshot() {
  n_commit=""; n_files=""
  local tmp pf idx path tree rc=0 st parent_args=()
  tmp="$(mktemp)" || return 1
  pf="${tmp}.list"

  if [ -n "$head" ]; then
    parent_args=(-p HEAD)
  fi

  # 실제 index 를 복사한다. 없으면 HEAD 로 채운다.
  idx="$git_abs/index"
  if [ -f "$idx" ]; then
    cp "$idx" "$tmp" || { rm -f "$tmp" "$pf"; return 1; }
  else
    rm -f "$tmp"
    if [ -n "$head" ]; then
      GIT_INDEX_FILE="$tmp" git read-tree HEAD >/dev/null 2>&1 || { rm -f "$tmp" "$pf"; return 1; }
    fi
  fi

  # 너무 큰 새 파일은 뺀다(compute_sig 가 이미 골라 두었다).
  {
    printf '%s\0' '.' ':(exclude,glob)**/*handoff*.md' ':(exclude)*handoff*.md' \
      ':(exclude).superpowers' ':(exclude)*/.superpowers/*'
    for path in ${big_arr[@]+"${big_arr[@]}"}; do
      printf '%s\0' ":(exclude,literal)${path}"
    done
  } > "$pf" || rc=1

  if [ "$rc" -eq 0 ]; then
    local t_cmd=()
    command -v timeout >/dev/null 2>&1 && t_cmd=(timeout 40)
    GIT_INDEX_FILE="$tmp" ${t_cmd[@]+"${t_cmd[@]}"} git add -A --pathspec-from-file="$pf" --pathspec-file-nul >/dev/null 2>&1 || rc=1
  fi
  if [ "$rc" -eq 0 ]; then
    tree="$(GIT_INDEX_FILE="$tmp" git write-tree 2>/dev/null)" || rc=1
  fi
  rm -f "$tmp"
  if [ "$rc" -ne 0 ]; then rm -f "$pf"; return 1; fi

  # HEAD 와 같은 트리면 사본에 담을 것이 없다. NUL 이 든 출력이라 파일을 거친다.
  # HEAD 가 없으면 트리에 든 파일이 전부 새 파일이다(빈 트리 객체는 새 저장소에 없을 수 있어
  # 비교하지 않고 나열한다).
  if [ -n "$head" ]; then
    if ! git diff-tree -r -z --no-renames --name-status HEAD "$tree" > "$pf" 2>/dev/null; then
      rm -f "$pf"
      return 1
    fi
    while IFS= read -r -d '' st && IFS= read -r -d '' path; do
      n_files="${n_files}${st} ${path}"$'\n'
    done < "$pf"
  else
    if ! git ls-tree -r -z --name-only "$tree" > "$pf" 2>/dev/null; then
      rm -f "$pf"
      return 1
    fi
    while IFS= read -r -d '' path; do
      n_files="${n_files}A ${path}"$'\n'
    done < "$pf"
  fi
  rm -f "$pf"
  if [ -z "$n_files" ]; then
    return 0
  fi

  n_commit="$(git -c user.name=harness -c user.email=harness@localhost -c commit.gpgsign=false \
    commit-tree "$tree" ${parent_args[@]+"${parent_args[@]}"} -m "harness unfinished snapshot" 2>/dev/null)" || { n_commit=""; return 1; }
  git update-ref "$SNAP_REF" "$n_commit" >/dev/null 2>&1 || { n_commit=""; return 1; }
  return 0
}

scan_status
branch="${s_branch:-알수없음}"
head="$s_oid"
if [ "$branch" = "알수없음" ]; then
  s_branch=""
fi

read_record
# 옛 형식 기록이 남아 있으면 덮어쓰기 전에 옆으로 옮긴다. 세션 시작 훅이 한 번 보여 준다.
if [ -f "$CARRYOVER" ] && [ -z "$r_format" ]; then
  mv -f "$CARRYOVER" "${CARRYOVER}.legacy" 2>/dev/null || true
fi

compute_unpushed

w_branch="$branch"; w_head="$head"; w_snap_ref="$SNAP_REF"
w_snap_commit="$r_snap_commit"; w_snap_time="$r_snap_time"; w_sig="$r_sig"
w_snap_failed="$r_snap_failed"; w_snap_files="$r_snap_files"; w_big_files="$r_big_files"
w_unpushed_branch="$u_branch"; w_unpushed_head="$u_head"; w_unpushed_count="$u_count"

# 변경이 없으면 jq 유무와 무관하게 조용히 끝난다. jq 유무 검사를 이 앞에
# 두면 변경이 없어도 매번 경고가 나가 버린다.
# /harness:deliver 가 스테이징에서 빼는 것(.superpowers/, *handoff*.md)은 여기서도
# 세지 않는다(#59). 세면 인계 메모 하나만 남아도 deliver 로 없앨 수 없는
# 경고가 매번 뜬다. 파일 단위(--untracked-files=all)로 본다. 기본값은 추적 안 된 폴더를
# `?? docs/` 한 줄로 접어, 그 안에 인계 메모만 있어도 걸러 내지 못한다.
if [ -z "$changed" ]; then
  # 변경이 없다. 사본 쪽 기록과 ref 는 건드리지 않는다(다음 세션 시작에서 판정한다).
  # push 안 된 커밋 정보만 지금 상태로 갱신하고, 남길 것이 없으면 기록을 지운다.
  # 판정하지 못했으면(u_err) 지난 기록의 push 정보를 그대로 둔다.
  if [ "$u_err" -eq 1 ]; then
    w_unpushed_branch="$r_unpushed_branch"; w_unpushed_head="$r_unpushed_head"; w_unpushed_count="$r_unpushed_count"
  fi
  if [ -n "$w_snap_commit" ] || [ -n "$w_snap_failed" ] || [ -n "$w_big_files" ] || [ -n "$w_unpushed_branch" ]; then
    # 지난 기록과 달라진 것이 없으면 다시 쓰지 않는다.
    if [ -z "$r_format" ] || [ "$w_branch" != "$r_branch" ] || [ "$w_head" != "$r_head" ] \
       || [ "$w_unpushed_branch" != "$r_unpushed_branch" ] || [ "$w_unpushed_head" != "$r_unpushed_head" ] \
       || [ "$w_unpushed_count" != "$r_unpushed_count" ]; then
      write_record || true
    fi
  elif [ -n "$r_format" ]; then
    rm -f "$CARRYOVER"
  fi
  exit 0
fi

# 변경이 있다. 변화 서명이 지난번과 같으면 사본을 다시 뜨지 않는다(Stop 은 대답마다 돈다).
compute_sig
# 사본 ref 가 그대로인지 파일에서 직접 읽어 본다(packed 로 옮겨졌으면 못 읽어 다시 뜬다).
reused=0
cur_ref=""
if [ -n "$r_snap_commit" ] && [ -f "$git_common/$SNAP_REF" ]; then
  IFS= read -r cur_ref < "$git_common/$SNAP_REF" || true
  cur_ref="${cur_ref%$''}"
fi
if [ -n "$sig" ] && [ "$sig" = "$r_sig" ] && [ -z "$r_snap_failed" ] \
   && { [ -z "$r_snap_commit" ] || [ "$cur_ref" = "$r_snap_commit" ]; }; then
  reused=1   # 같은 상태 — 사본·큰 파일 목록을 그대로 둔다
else
  if take_snapshot; then
    w_snap_commit="$n_commit"; w_snap_files="$n_files"; w_big_files="$big_text"
    w_snap_time="${EPOCHSECONDS:-$(date +%s)}"; w_sig="$sig"; w_snap_failed=""
    if [ -z "$n_commit" ]; then
      # 사본에 담을 변경이 없다. 남아 있던 지난 사본은 이번 상태가 아니므로 버린다.
      git update-ref -d "$SNAP_REF" >/dev/null 2>&1 || true
      w_snap_time=""
    fi
  else
    # 사본을 못 떴다. 지난 사본 정보는 두고 실패를 표시해 다음 시작에서 확인 불능으로 알린다.
    w_snap_failed=1
  fi
fi
if [ "$u_err" -eq 1 ]; then
  w_unpushed_branch="$r_unpushed_branch"; w_unpushed_head="$r_unpushed_head"; w_unpushed_count="$r_unpushed_count"
fi
# 사본을 그대로 쓰고 기록할 내용도 지난번과 같으면 다시 쓰지 않는다.
if [ "$reused" = "1" ] && [ -n "$r_format" ] && [ "$w_branch" = "$r_branch" ] && [ "$w_head" = "$r_head" ]    && [ "$w_unpushed_branch" = "$r_unpushed_branch" ] && [ "$w_unpushed_head" = "$r_unpushed_head" ]    && [ "$w_unpushed_count" = "$r_unpushed_count" ]; then
  exit 0
fi
write_record || true

has_jq=1
command -v jq >/dev/null 2>&1 || has_jq=0

if [ "$has_jq" -eq 1 ]; then
  # 입력이 유효한 JSON 이 아니면 jq 가 실패한다. pipefail 아래에서 스크립트가
  # 그대로 죽지 않도록 받아 내고, 거짓으로 본다. 거짓 쪽이 /harness:deliver 를 지시하는
  # 안전한 경로다.
  stop_hook_active="$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)"
  # Windows 네이티브 jq.exe 는 텍스트 모드로 출력해 LF 를 CRLF 로 바꾼다.
  # 그대로 두면 "true\r" 가 "true" 와 달라 무한 반복 방지 분기가 걸리지 않는다.
  stop_hook_active="$(printf '%s' "$stop_hook_active" | tr -d '\r')"
else
  # jq 없이 원시 입력 문자열에서 stop_hook_active 값을 찾는다. 엄밀한
  # 파서는 아니지만 무한 반복을 막는 목적에는 이 근사치로 충분하다.
  if printf '%s' "$input" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    stop_hook_active=true
  else
    stop_hook_active=false
  fi
fi

if [ "$stop_hook_active" = "true" ]; then
  # 한 번 되돌려 보냈는데도 변경이 남아 있다. 무한 반복을 피해 세션을 끝내되
  # 유실 가능성을 남긴다.
  warn "[경고] 커밋되지 않은 변경이 ${branch} 브랜치에 남은 채로 세션이 끝났습니다."
  warn "$changed"
  warn "다음 세션에서 /harness:deliver 를 실행해 정리하십시오."
  exit 0
fi

reason="커밋되지 않은 변경이 ${branch} 브랜치에 남아 있습니다. /harness:deliver 를 실행해 커밋과 동기화와 푸시와 PR 까지 마치십시오. 이번 세션에서 끝내지 못한 작업이 따로 있으면 이어서 /harness:wrapup 으로 이슈에 등록하십시오."

# hookSpecificOutput.additionalContext 는 세션 종료를 막지 못하고 참고
# 정보로만 붙는다. decision:"block" 을 최상위로 낸다. continue 키는 일부러
# 뺐다. 같은 런타임 구현 안에 continue:true 가 "훅이 아무 일도 하지 않고
# 넘어간다" 는 뜻으로도 쓰이는 자리가 있어, continue:false 를 함께 쓰면
# decision:"block" 을 덮어써 세션이 그냥 끝나 버릴 가능성을 배제할 수
# 없었다. 이 형식이 실제로 세션을 계속시키는지는 이 검사만으로 확인할 수
# 없다. 검사는 출력 JSON 의 모양만 보고, 실제 판정은 Claude Code 런타임이
# 한다. 원격을 연결하고 실제 세션을 한 번 돌려 봐야 확인된다.
if [ "$has_jq" -eq 1 ]; then
  jq -n --arg r "$reason" \
    '{decision: "block", reason: $r}'
else
  # jq 가 없다고 통과시키지 않는다. pre-bash-git-guard.sh 와 같은 태도다.
  # printf 로 직접 JSON 을 내므로, 사유 문자열에서 JSON 을 깨뜨릴 수 있는
  # 큰따옴표와 역슬래시를 미리 지운다.
  reason="jq 가 설치되어 있지 않습니다. 사람이 할 일 - PowerShell 에서 winget install --id jqlang.jq -e 로 jq 를 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오. ${reason}"
  reason="$(printf '%s' "$reason" | tr -d '"\\')"
  printf '{"decision":"block","reason":"%s"}\n' "$reason"
fi

exit 0
