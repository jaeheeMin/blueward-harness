#!/usr/bin/env bash
set -euo pipefail

input="$(cat)"

# 아래에서 cd 하기 전에 이 스크립트가 있는 폴더를 잡아 둔다(상대 경로로 불렸을 수 있다).
hook_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 세션이 다른 git worktree 로 옮겨가도(#71) 그 worktree 기준으로 판단하기
# 위해, 훅에 오는 stdin JSON 의 cwd 를 최우선으로 쓴다. CLAUDE_PROJECT_DIR 은
# 세션을 "처음 연" 폴더라 세션 도중 다른 worktree 로 옮기면 더는 맞지 않는다.
# cwd 가 없거나 존재하지 않는 디렉터리면 CLAUDE_PROJECT_DIR 로, 그것도 없으면
# 지금 디렉터리로 되돌아간다.
#
# 한계: 이 검사는 명령이 실제로 "실행되는" 디렉터리가 아니라 세션의 cwd 를
# 본다. `cd 다른곳 && git commit` 처럼 명령 자체가 다른 저장소로 옮겨 가면
# 이 훅은 여전히 cwd(세션이 있는 저장소) 기준으로 판단한다 — 이 스크립트는
# 명령 문자열을 셸처럼 실행하지 않으므로 그 이동을 알 수 없다. 이 범위
# 밖의 한계이며, 최종 방어선은 위쪽 주석대로 `.githooks/pre-push` 와 GitHub
# 브랜치 보호 규칙이다.
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

# 거부는 jq 없이도 낼 수 있어야 한다. 이 훅이 막아야 하는 상황 중 하나가
# jq 부재이기 때문이다. 그래서 사유 문자열에 큰따옴표와 역슬래시를 쓰지 않는다.
deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}

# 거부 메시지는 "왜 막혔는지" 와 "다음에 할 일" 을 함께 담는다(#113 Hook 거부 메시지에
# 원인과 다음 할 일 함께 안내). Claude 가 먼저 읽고 개발자가 아닐 수도 있는 팀원에게
# 전하므로, Claude 가 스스로 못 하는 일(설치, 로그인)은 "사람이 할 일" 로 밝히고 명령을
# 그대로 적는다. deny() 에 그대로 끼워 넣는 문자열이라 큰따옴표·역슬래시·백틱·달러
# 기호를 쓰지 않는다.
next_install_uv="다음: 🚨 직접 해 주세요: PowerShell 에서 winget install --id astral-sh.uv -e 를 실행해 uv 를 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오."
next_install_gh="다음: 🚨 직접 해 주세요: PowerShell 에서 winget install --id GitHub.cli -e 로 GitHub CLI 를 설치하고 gh auth login 으로 로그인한 뒤 Claude Code 를 새 터미널에서 다시 여십시오."
next_retry="다음: 네트워크를 확인하고 잠시 뒤 같은 명령을 다시 시도하십시오. gh auth status 가 로그인 안 됨을 보이면 사람이 gh auth login 을 실행해야 합니다. 계속되면 이 메시지 전체를 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."

if ! command -v jq >/dev/null 2>&1; then
  # 판단할 수 없을 때 통과시키지 않는다. 통과시키면 정확히 이 상황에서
  # 보호가 사라진다. 다만 검사 대상이 git 명령이나 `gh pr merge` 이므로
  # 그 밖의 명령은 막지 않는다. `gh pr merge` 도 여기 넣은 이유는 아래
  # SRS 승인 검사가 이 훅 안에서 jq 로 결과를 읽기 때문이다(#49).
  # 첫 관문은 일부러 느슨하다: pr 와 대상 하위 명령이 각각 낱말로 있으면 걸린다
  # (gh -R o/r pr comment, gh pr -R o/r comment 처럼 사이에 옵션이 와도 놓치지 않으려고).
  # 진짜 gh pr 호출인지는 엔진(checker.merge_command)이 가려낸다.
  pr_word_re='(^|[^[:alnum:]_-])pr([^[:alnum:]_-]|$)'
  pr_sub_re='(^|[^[:alnum:]_-])(merge|edit|close|reopen|comment|review|ready)([^[:alnum:]_-]|$)'
  if [[ "$input" =~ $pr_word_re ]] && [[ "$input" =~ $pr_sub_re ]]; then
    deny "jq 가 없어 gh pr 명령의 대상 PR 작성자를 확인하지 못했습니다. 검사할 수 없는 상태로 통과시키지 않습니다. 다음: 🚨 직접 해 주세요: PowerShell 에서 winget install --id jqlang.jq -e 를 실행해 jq 를 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오(macOS 는 brew install jq)."
  fi
  case "$input" in
    *git*|*pr*merge*)
      deny "jq 가 없어 git/gh 명령을 검사하지 못했습니다. 검사할 수 없는 상태로 통과시키지 않습니다. 다음: 🚨 직접 해 주세요: PowerShell 에서 winget install --id jqlang.jq -e 를 실행해 jq 를 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오(macOS 는 brew install jq)."
      ;;
    *)
      exit 0
      ;;
  esac
fi

set +e
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)"
jq_rc=$?
set -e

if [ "$jq_rc" -ne 0 ]; then
  deny "훅이 입력을 해석하지 못해 이 명령을 검사할 수 없었습니다. 검사할 수 없는 상태로 통과시키지 않습니다. 다음: 같은 명령을 한 번 더 시도하십시오. 계속되면 사람이 jq --version 이 동작하는지 확인하고, 그래도 안 되면 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."
fi

# Windows 네이티브 jq.exe 는 텍스트 모드로 출력해 LF 를 CRLF 로 바꾼다.
# 명령 치환은 끝의 LF 만 벗기므로 CR 이 하위 명령 토큰 끝에 남아 비교가
# 어긋난다(`push\r` 는 `push` 와 다른 문자열이다).
cmd="$(printf '%s' "$cmd" | tr -d '\r')"

if [ -z "$cmd" ]; then
  exit 0
fi

# git 명령의 하위 명령을 찾는다. git 과 하위 명령 사이에는 -C 나 -c 나
# --no-pager 같은 전역 옵션이 올 수 있으므로 둘이 붙어 있는지를 보지 않고,
# git 뒤의 첫 비옵션 토큰을 하위 명령으로 본다. 토큰을 그냥 훑기만 하면
# `git log --grep push` 같은 조회 명령까지 막혀 사람들이 훅을 꺼 버린다.
#
# 이 방식에도 원리적 한계가 있다. 이 함수는 문자열을 공백으로 쪼개 볼 뿐,
# 실제로 셸이 그 문자열을 어떻게 실행하는지는 모른다. `git push$IFS--force`
# 처럼 IFS 를 다른 문자로 바꿔 치환하거나 `x=push; git $x --force` 처럼
# 변수로 하위 명령을 감추면 이 함수도 알아채지 못한다. 이런 형태를 막는
# 최종 방어선은 이 훅이 아니라 `.githooks/pre-push` 와 GitHub 브랜치 보호
# 규칙이다. 이 훅은 그 앞에서 흔히 쓰는 형태를 걸러내는 첫 번째 방어선일
# 뿐이다.
git_subcommand() {
  # 결과는 gs_sub 에 둔다(서브셸을 쓰지 않으려고 출력 대신 변수로 돌려준다 - 조각마다 불러도 빠르다).
  local tok base found=0 skip_next=0
  gs_sub=""
  set -f
  for tok in $1; do
    # 셸이 벗겨 줄 따옴표가 문자열에는 남아 있으므로 여기서 벗긴다.
    tok="${tok#\"}"; tok="${tok%\"}"
    tok="${tok#\'}"; tok="${tok%\'}"
    if [ "$skip_next" -eq 1 ]; then skip_next=0; continue; fi
    if [ "$found" -eq 0 ]; then
      # Windows 는 `git.exe` 로 부르고 경로 구분자로 `\` 를 쓴다. `/` 와 `\`
      # 양쪽 기준으로 마지막 경로 성분을 떼어 낸 뒤, 대소문자와 `.exe` 확장자
      # 차이를 가리지 않고 git 인지 비교한다(bash 3.2 호환을 위해 `${var,,}` 대신 패턴).
      base="${tok##*/}"
      base="${base##*\\}"
      case "$base" in
        [Gg][Ii][Tt]|[Gg][Ii][Tt].[Ee][Xx][Ee]) found=1 ;;
      esac
      continue
    fi
    case "$tok" in
      -C|-c) skip_next=1 ;;
      -*) : ;;
      *) set +f; gs_sub="$tok"; return 0 ;;
    esac
  done
  set +f
  return 0
}

# 명령을 조각으로 나눠 한 줄에 하나씩 낸다. 첫 줄은 #OPAQUE:0 또는 #OPAQUE:1 이다.
# - heredoc 본문은 걷어 낸다.
# - 따옴표 안 문자열은 Q 한 글자로 바꾼다. 다만 공백·특수문자 없는 한 낱말("git", push)은
#   따옴표만 벗겨 낱말 그대로 둔다(`"git" push`, `git "push"` 를 놓치지 않으려고).
# - 큰따옴표 안에 $( 나 역따옴표가 있으면 그 안은 실행되는 코드이므로 따옴표 없는 글처럼 읽는다.
# - 역따옴표와 ( ) { } 는 공백으로 바꾼다. \" 와 \' 는 따옴표가 아닌 글자(E)로 바꾼다.
# - ; | & 개행에서 조각을 나눈다.
# - 닫히지 않은 따옴표는 끝까지를 Q 로 보되, 그 안에 git 과 push(또는 commit) 낱말이 있으면
#   OPAQUE:1 이다(어차피 셸이 실행하지 못할 문법 오류인 경우가 대부분이다).
strip_for_scan() {
  printf '%s\n' "$1" \
    | awk -v q="'" '
        skip { t = $0; sub(/^[ \t]+/, "", t); if (t == w) skip = 0; next }
        { buf = buf $0 "\n"
          if (match($0, "(^|[^<])<<-?[ \t]*[\"" q "]?[A-Za-z_][A-Za-z0-9_]*")) {
            s = substr($0, RSTART, RLENGTH)
            sub(/^[^<]?<<-?[ \t]*/, "", s); sub("^[\"" q "]", "", s)
            w = s; skip = 1
          } }
        function put(body) {
          if (body ~ /^[A-Za-z0-9_.\/:+@%=,~][A-Za-z0-9_.\/:+@%=,~^-]*$/) seg = seg body
          else seg = seg "Q"
        }
        function cut() { out = out seg "\n"; seg = "" }
        END {
          n = length(buf); opaque = 0; dyn_end = 0; seg = ""; out = ""
          for (i = 1; i <= n; i++) {
            c = substr(buf, i, 1)
            if (i == dyn_end) { seg = seg " "; continue }
            if (c == "\\") {
              nc = substr(buf, i + 1, 1)
              if (nc == "\"" || nc == q) { seg = seg "E"; i++ }
              else if (nc == "\n") { seg = seg " "; i++ }
              else seg = seg c
              continue
            }
            if (c == "\"") {
              j = i + 1
              while (j <= n) {
                d = substr(buf, j, 1)
                if (d == "\\") { j += 2; continue }
                if (d == "\"") break
                j++
              }
              if (j > n) { tail = substr(buf, i + 1); unterminated(tail); seg = seg "Q"; break }
              body = substr(buf, i + 1, j - i - 1)
              if (index(body, "$(") || index(body, "`")) { dyn_end = j; seg = seg " "; continue }
              put(body); i = j; continue
            }
            if (c == q) {
              rest = substr(buf, i + 1); j = index(rest, q)
              if (j == 0) { unterminated(rest); seg = seg "Q"; break }
              put(substr(rest, 1, j - 1)); i = i + j; continue
            }
            if (c == "`" || c == "(" || c == ")" || c == "{" || c == "}") { seg = seg " "; continue }
            if (c == ";" || c == "|" || c == "&" || c == "\n") { cut(); continue }
            seg = seg c
          }
          cut()
          printf "#OPAQUE:%d\n%s", opaque, out
        }
        function unterminated(t) {
          if (t ~ /(^|[^A-Za-z0-9_-])git([^A-Za-z0-9_-]|$)/ && t ~ /(^|[^A-Za-z0-9_-])(push|commit)([^A-Za-z0-9_-]|$)/) opaque = 1
        }'
}

# push·commit 판정은 첫 git 하위 명령이 아니라 조각(; && || | 개행)마다 한다(#264).
# `git status && git push` 처럼 앞에 다른 git 명령이 붙어도 push 조각을 찾는다. 따옴표 안
# 문자열(gh issue create --title "... git push ...")과 heredoc 본문은 걷어 낸 뒤 보므로
# 명령으로 읽지 않는다. 결과: push_found, push_force, commit_found (1/0). 조각 목록은
# scan_segs, 조각별 git 하위 명령은 scan_subs 에 남겨 아래 검사들(2-1, 2-3)이 함께 쓴다.
#
# 속도: 훅은 모든 Bash 명령마다 도는데 Windows 에서는 프로세스 하나가 0.1초 이상이다.
# 그래서 명령에 git 낱말도 래퍼(bash, sh, eval, ssh, pwsh, cmd 등)도 없으면 스캔하지 않고,
# 따옴표·역슬래시·$( ) { } 가 없는 단순한 명령은 awk 없이 bash 치환으로 나눈다.
#
# 조각으로 확실히 나눌 수 없는 경우는 원칙 7 에 따라 보수적으로 본다(OPAQUE 이면 명령 전체에
# git 과 push 낱말이 있을 때 푸시로 치고 거부한다). OPAQUE 는 (a) 따옴표 문자열을 다시 셸이
# 실행하는 래퍼(bash -c "git push", eval, ssh 등), (b) 닫히지 않은 따옴표 속에 git 과 push 가
# 있는 경우다. 한계: 변수·$IFS 로 감춘 하위 명령, 래퍼의 인자가 아닌데 래퍼 낱말이 든 명령에서
# 따옴표 밖에 git 과 push 낱말이 따로 있으면 거부될 수 있다.
push_found=0
push_force=0
commit_found=0
opaque_push=0
scan_n=0
scan_segs=()
scan_subs=()
scan_opaque=0
force_re='(^|[[:space:]])(-[a-zA-Z]*f[a-zA-Z]*|--force)([[:space:]]|$)'
git_word_re='(^|[^[:alnum:]_-])git([^[:alnum:]_-]|$)'
wrapper_word_re='(^|[^[:alnum:]_-])(bash|sh|zsh|dash|ksh|eval|ssh|pwsh|powershell|cmd)([^[:alnum:]_-]|$)'
slow_re='["'\''`\\$(){}]|<<'
shopt -s nocasematch
if [[ "$cmd" =~ $git_word_re ]] || [[ "$cmd" =~ $wrapper_word_re ]]; then
  if [[ "$cmd" =~ $slow_re ]]; then
    scan_text="$(strip_for_scan "$cmd")"
  else
    scan_text="$cmd"
    scan_text="${scan_text//;/$'\n'}"
    scan_text="${scan_text//|/$'\n'}"
    scan_text="${scan_text//&/$'\n'}"
    scan_text="#OPAQUE:0"$'\n'"$scan_text"
  fi
  scan_first=1
  while IFS= read -r seg; do
    if [ "$scan_first" -eq 1 ]; then
      scan_first=0
      if [ "$seg" = "#OPAQUE:1" ]; then scan_opaque=1; fi
      continue
    fi
    case "$seg" in *[![:space:]]*) ;; *) continue ;; esac
    git_subcommand "$seg"
    scan_segs[$scan_n]="$seg"
    scan_subs[$scan_n]="$gs_sub"
    scan_n=$((scan_n + 1))
    if [ "$gs_sub" = "push" ]; then
      push_found=1
      if [[ "$seg" =~ $force_re ]]; then push_force=1; fi
    elif [ "$gs_sub" = "commit" ]; then
      commit_found=1
    fi
    # 래퍼 판별: 앞의 VAR=값 을 건너뛴 첫 낱말이 래퍼이고 인자에 따옴표 문자열(Q)이 있으면 불투명.
    if [[ "$seg" == *Q* ]]; then
      seg_first=""
      set -f
      for tok in $seg; do
        case "$tok" in [A-Za-z_]*=*) continue ;; esac
        seg_first="${tok##*/}"; seg_first="${seg_first##*\\}"
        break
      done
      set +f
      seg_first="${seg_first%.[Ee][Xx][Ee]}"
      case "$seg_first" in
        bash|sh|zsh|dash|ksh|eval|pwsh|powershell|cmd|ssh) scan_opaque=1 ;;
      esac
    fi
  done <<EOF
$scan_text
EOF
  if [ "$scan_opaque" -eq 1 ] && [[ "$cmd" =~ $git_word_re ]]; then
    push_word_re='(^|[^[:alnum:]_-])push([^[:alnum:]_-]|$)'
    commit_word_re='(^|[^[:alnum:]_-])commit([^[:alnum:]_-]|$)'
    if [[ "$cmd" =~ $push_word_re ]]; then
      if [ "$push_found" -eq 0 ]; then opaque_push=1; fi
      push_found=1
      if [[ "$cmd" =~ $force_re ]]; then push_force=1; fi
    fi
    if [[ "$cmd" =~ $commit_word_re ]]; then commit_found=1; fi
  fi
fi
shopt -u nocasematch

# 0) gh pr merge 대상 PR 이 SRS(docs/ssot/) 를 바꿨는데 승인이 없으면 거부한다
#    (#49). 별도 훅 프로세스를 새로 두지 않고 이 훅에 얹는 이유는, 이미
#    Bash|PowerShell 을 지켜보는 훅이 있는데 같은 이벤트에 두 번째 훅
#    프로세스를 또 띄우면 같은 명령을 두 번 파싱하고 두 배로 느려지기
#    때문이다. git 명령이 아니므로 `git_subcommand` 대신 아래에서 따로
#    본다.
#
# gh 는 이 저장소의 GitHub 원격에서 판정 로직(checker.ssot_approval)을
# `uvx` 로 받아 부른다 — 훅이 검사 엔진을 얻는 방식(#12)과 같다. 판정
# 불가(네트워크 없음, gh 없음, uvx 없음, 예상 못한 종료코드)는 통과가
# 아니라 거부로 답한다(CLAUDE.md 원칙 7) — merge 를 막는 것이 이 훅의
# 목적이므로, 모른다는 것을 통과로 답하면 그 순간 보호가 사라진다.
#
# 명령에서 실제 `gh pr merge` 호출을 골라내는 일은 셸이 아니라 엔진의
# checker.merge_command 가 한다(#101). 예전에는 명령 전체를 공백으로 쪼개
# 훑어서, `;` 로 묶인 두 번째 merge 의 `-R` 이 첫 번째 PR 에 적용되고 이슈
# 본문(--body, heredoc)에 든 "gh pr merge" 글자도 merge 로 읽혔다. 이제는
# 따옴표·heredoc 본문을 명령으로 보지 않고 `;`·`&&`·`||`·`|`·개행으로 나눈
# 조각마다 자기 PR 번호와 -R 을 짝짓는다. 확실히 나누지 못하면(따옴표 불균형
# 등) 막고 "merge 는 한 명령에 하나씩" 이라고 안내한다.
#
# 한계: 변수로 감춘 명령(`x=merge; gh pr $x`)이나 큰따옴표 안의 `$(...)` 치환은
# 알아보지 못한다. 그 앞의 첫 관문인 아래 `pr merge` 부분 문자열 검사도
# 마찬가지다. 최종 방어선은 Actions 의 doc-guard 검사와 GitHub 화면이다.
#
# 엔진 판(#149): 플러그인 판(plugin.json version)과 같은 태그 v{version} 이다. 판 계산은
# engine_spec.py 한 곳이 하고 py 훅과 스킬도 같은 값을 쓴다. DOC_GUARD_ENGINE 이 있으면
# 그것이 우선이다. 모든 Bash 명령마다 uv 를 띄우지 않으려고, 엔진을 실제로 부르는 갈래
# (uvx 확인 직후)에서만 resolve_engine 을 부른다. 판을 못 정하면 main 으로 넘어가지 않고
# 거부한다(원칙 7).
engine=""
resolve_engine() {
  if [ -n "$engine" ]; then
    return 0
  fi
  if [ -n "${DOC_GUARD_ENGINE:-}" ]; then
    engine="$DOC_GUARD_ENGINE"
    return 0
  fi
  es_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 검사 엔진의 판을 정하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  es_rc=0
  engine="$(uv run --no-project python "$hook_dir/engine_spec.py" 2>"$es_err_file")" || es_rc=$?
  es_detail="$(tr -d '"\\`$\r' < "$es_err_file" 2>/dev/null | tr '\n' ' ')" || es_detail=""
  rm -f "$es_err_file"
  engine="$(printf '%s' "$engine" | tr -d '\r')"
  if [ "$es_rc" -ne 0 ] || [ -z "$engine" ]; then
    engine=""
    deny "검사 엔진의 판을 정하지 못했습니다(종료코드 $es_rc). 플러그인 설치가 깨졌거나 uv 를 실행하지 못한 것입니다. 검사 불능이므로 통과시키지 않습니다. 사유: $es_detail 다음: 🚨 직접 해 주세요: 플러그인을 다시 설치하거나 갱신하십시오. uv 가 없다면 PowerShell 에서 winget install --id astral-sh.uv -e 로 설치하십시오. 계속되면 이 메시지 전체를 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."
  fi
  # 태그 고정이면 그 태그가 아직 없을 수 있다는 단서를 재시도 안내에 덧붙인다.
  case "$engine" in
    *@v[0-9]*)
      next_retry="$next_retry 참고: 이 검사는 엔진 판 ${engine##*@} 을 받아 실행합니다. 그 판을 받을 수 없으면(저장소에 태그가 아직 없을 수 있음 - 플러그인 새 판이 병합된 직후에는 태그가 붙기까지 잠시 걸립니다) 같은 이유로 실패합니다."
      ;;
  esac
}

# merge 한 건을 검사한다. $1=저장소(-R, 없으면 빈 값), $2=PR 지정(번호·URL·브랜치,
# 없으면 빈 값). deny() 는 exit 하므로 여러 건 중 하나라도 걸리면 명령 전체가
# 거부된다.
check_one_merge() {
  repo="$1"
  prref="$2"
  # 3번째 인자가 auto 면 자동 병합 예약이다(#437). 서버가 기다려 주는 판정(검사·앞 PR·SRS 승인·위험도)은 건너뛰고
  # 사람 병합 경로만 본다.
  auto="${3:-}"

  # URL 형태(.../pull/123)면 번호와 저장소를 URL 에서 바로 뽑는다.
  case "$prref" in
    */pull/*)
      pr_number="${prref##*/pull/}"
      pr_number="${pr_number%%/*}"
      # 명령에서 온 값이 deny 문구에 들어가므로 " \ 백틱 $ 공백을 지운다.
      pr_number="$(printf '%s' "$pr_number" | tr -d '"\\`$ ')"
      if [ -z "$repo" ]; then
        repo="$(printf '%s' "$prref" | sed -n 's#^https\{0,1\}://github\.com/\([^/]*/[^/]*\)/pull/.*#\1#p')"
      fi
      ;;
    ''|*[!0-9]*)
      pr_number=""
      ;;
    *)
      pr_number="$prref"
      ;;
  esac

  if ! command -v gh >/dev/null 2>&1; then
    deny "gh 가 없어 이 PR 이 SRS(docs/ssot) 를 바꿨는지, 승인이 있는지 확인할 수 없습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. $next_install_gh"
  fi

  # 번호를 못 얻었으면(현재 브랜치나 브랜치 이름으로 지정한 경우) gh pr view
  # 로 같은 대상을 다시 물어 번호를 얻는다. gh pr view 는 gh pr merge 와
  # 같은 인자 형태(번호·URL·브랜치·빈 값=현재 브랜치)를 받아들인다.
  if [ -z "$pr_number" ]; then
    if [ -n "$prref" ] && [ -n "$repo" ]; then
      pr_number="$(gh pr view "$prref" -R "$repo" --json number -q .number 2>/dev/null)" || true
    elif [ -n "$prref" ]; then
      pr_number="$(gh pr view "$prref" --json number -q .number 2>/dev/null)" || true
    elif [ -n "$repo" ]; then
      pr_number="$(gh pr view -R "$repo" --json number -q .number 2>/dev/null)" || true
    else
      pr_number="$(gh pr view --json number -q .number 2>/dev/null)" || true
    fi
  fi

  if [ -z "$repo" ]; then
    repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" || true
  fi

  if [ -z "$repo" ] || [ -z "$pr_number" ]; then
    deny "gh pr merge 의 대상 PR 을 확인하지 못해 SRS 승인 여부를 판정할 수 없습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. 다음: Claude 가 PR 번호를 붙여(예: gh pr merge 123) 다시 실행하십시오. 그래도 안 되면 gh auth status 로 로그인 상태를 확인하고, 로그인 안 됨이면 사람이 gh auth login 을 실행하십시오."
  fi

  if [ "$auto" != auto ]; then
  # -1) 대상 PR 의 검사(status checks)가 실패했거나 아직 진행 중이면 거부한다(#120).
  #     무료 요금제는 빨간불이어도 Merge 버튼을 잠그지 못하므로, 적어도 Claude 의
  #     `gh pr merge` 는 여기서 막는다(사람의 웹 Merge 버튼은 범위 밖). 싼 gh 호출
  #     한 번이라 uvx 로 엔진을 받는 아래 검사들보다 먼저 두고, 빨간불 PR 이면 그
  #     사실을 먼저 알린다.
  #
  #     gh pr checks 는 검사가 실패하면 종료코드 1, 진행 중이면 8 을 내면서도
  #     --json 출력은 정상으로 낸다. 그래서 종료코드가 아니라 stdout 의 JSON 을
  #     읽는다. 검사가 하나도 없는 PR(CI 없는 저장소)은 stdout 이 비고 종료코드 1
  #     에 stderr 가 "no checks reported on the ... branch" 인 경우이며(gh 2.100
  #     에서 확인), 그때만 통과시킨다. 그 밖에 JSON 을 못 얻으면 통과가 아니라
  #     검사 불능으로 거부한다(CLAUDE.md 원칙 7).
  ck_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 의 검사 상태를 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  set +e
  ck_out="$(gh pr checks "$pr_number" -R "$repo" --json name,state,bucket,link,workflow,startedAt 2>"$ck_err_file")"
  ck_rc=$?
  set -e
  ck_err="$(cat "$ck_err_file" 2>/dev/null)" || ck_err=""
  rm -f "$ck_err_file"
  ck_out="$(printf '%s' "$ck_out" | tr -d '\r')"

  if [ -z "$ck_out" ] && printf '%s' "$ck_err" | grep -q 'no checks reported'; then
    : # 검사가 하나도 없는 PR(CI 없는 저장소). 막을 검사가 없으므로 통과시킨다.
  elif ! printf '%s' "$ck_out" | jq -e 'type == "array"' >/dev/null 2>&1; then
    ck_detail="$(printf '%s\n%s' "$ck_out" "$ck_err" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
    deny "PR #$pr_number 의 검사 상태를 확인하지 못해 merge 를 막습니다(종료코드 $ck_rc). 검사 불능이므로 통과시키지 않습니다. $next_retry 자세히: $ck_detail"
  else
    # 같은 워크플로의 같은 이름 검사가 여러 번 돈 PR(재실행, pull_request 와
    # pull_request_review 로 따로 돈 경우)은 옛 실패가 화면에 남는다. 그래서 (workflow,
    # name) 마다 가장 늦게 시작한 것만 본다. 진행 중은 아직 startedAt 이 비어 있을 수
    # 있으니 가장 최신으로 친다.
    # 건너뜀(skipping)은 같은 그룹에 다른 결과가 있으면 후보에서 뺀다 — 옛 실패를 가리면 안 된다. 시작 시각이 같거나 없으면 모두 남겨 예전처럼 판정한다.
    # `merge-order`(병합 순서 status)와 `pr-queue / …`(그것을 다는 워크플로 job)는 pr-queue 워크플로가
    # 남기는 것이다(#370). `pr-checks`(검사를 합친 job, #417)는 일부러 빼지 않는다 — job 실패는 검사 실패다.
    # 순서는 바로 아래 -1-1 검사가 정확한 메시지("먼저 #m")로 막으니 여기서 빼고,
    # 그대로 두면 순서 문제가 "검사 실패" 로 둔갑한다. job 은 다른 PR 의 실행에 취소돼 이 PR 에 취소 기록이
    # 남을 수 있어 같이 뺀다.
    ck_latest="$(printf '%s' "$ck_out" | jq -c '
      map(select(((.name // "") | split(" / ")[0]) as $g | $g != "merge-order" and $g != "pr-queue" and (.workflow // "") != "pr-queue"))
      | group_by([.workflow // "", .name])
      | map(
          . as $all
          | (map(select(.bucket != "skipping")) | if length > 0 then . else $all end) as $cand
          | ($cand | map(if .bucket == "pending" then "9999" else (.startedAt // "") end) | max) as $newest
          | $cand | map(select((if .bucket == "pending" then "9999" else (.startedAt // "") end) == $newest))
        )
      | add // []' 2>/dev/null | tr -d '\r')" || ck_latest=""
    if ! printf '%s' "$ck_latest" | jq -e 'type == "array"' >/dev/null 2>&1; then
      ck_latest="$ck_out"
    fi
    ck_fail_names="$(printf '%s' "$ck_latest" | jq -r '[.[] | select(.bucket == "fail" or .bucket == "cancel") | .name] | .[:5] | join(", ")' 2>/dev/null | tr -d '\r"\\`$')" || true
    ck_fail_total="$(printf '%s' "$ck_latest" | jq -r '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length' 2>/dev/null | tr -d '\r')" || true
    ck_fail_link="$(printf '%s' "$ck_latest" | jq -r '[.[] | select(.bucket == "fail" or .bucket == "cancel") | .link // empty] | .[0] // empty' 2>/dev/null | tr -d '\r"\\`$ ')" || true
    ck_wait_names="$(printf '%s' "$ck_latest" | jq -r '[.[] | select(.bucket != "pass" and .bucket != "skipping" and .bucket != "fail" and .bucket != "cancel") | .name] | .[:5] | join(", ")' 2>/dev/null | tr -d '\r"\\`$')" || true
    ck_wait_total="$(printf '%s' "$ck_latest" | jq -r '[.[] | select(.bucket != "pass" and .bucket != "skipping" and .bucket != "fail" and .bucket != "cancel")] | length' 2>/dev/null | tr -d '\r')" || true
    if [ "${ck_fail_total:-0}" -gt 0 ] 2>/dev/null; then
      if [ "$ck_fail_total" -gt 5 ]; then
        ck_fail_names="$ck_fail_names 등 ${ck_fail_total}개"
      fi
      deny "PR #$pr_number 의 검사가 실패해 merge 를 막습니다. 실패한 검사: $ck_fail_names 링크: $ck_fail_link 다음: Claude 가 실패한 검사의 로그(gh run view --log-failed 또는 위 링크)를 보고 원인을 고쳐 다시 올린 뒤 검사가 모두 통과하면 다시 merge 하십시오. 문서·코드 검사 실패라면 PR 코멘트에 파일별 원인과 고칠 방법이 있습니다."
    elif [ "${ck_wait_total:-0}" -gt 0 ] 2>/dev/null; then
      if [ "$ck_wait_total" -gt 5 ]; then
        ck_wait_names="$ck_wait_names 등 ${ck_wait_total}개"
      fi
      deny "PR #$pr_number 의 검사가 아직 끝나지 않았습니다($ck_wait_names). 끝나기 전에는 merge 하지 않습니다. 다음: gh pr checks $pr_number --watch 로 끝날 때까지 기다린 뒤 결과가 모두 통과이면 다시 merge 하십시오."
    fi
  fi

  fi

  if ! command -v uvx >/dev/null 2>&1; then
    deny "uvx 가 없어 SRS 승인 여부를 확인하지 못했습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. $next_install_uv"
  fi

  if [ "$auto" != auto ]; then
  # -1-1) 먼저 병합해야 하는 열린 PR 이 있으면 거부한다(#370). 앞 PR 은 base 브랜치가 그 PR 의
  #       브랜치이거나, 본문의 `먼저: #n` 줄, 같은 DEV 의 SRS→Spec→개발 순, 하네스 저장소의
  #       plugin.json version 순으로 정해진다(checker.pr_queue --pr). 같은 파일을 고친 PR 은
  #       경고일 뿐 막지 않는다. 엔진이 한 번 gh 로 열린 PR 을 읽는 값싼 검사이므로 승인·위험도
  #       검사(여러 번 읽음)보다 먼저 두었다. 순서를 정하지 못하면(순환, 읽기 실패, 엔진 실행
  #       실패) 통과가 아니라 거부다. 사람이 GitHub 화면에서 병합하는 것은 막지 못한다.
  pq_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 보다 먼저 병합할 PR 이 있는지 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  set +e
  pq_out="$(uvx --from "$engine" python -P -m checker.pr_queue --repo "$repo" --pr "$pr_number" --json 2>"$pq_err_file")"
  pq_rc=$?
  set -e
  pq_err="$(cat "$pq_err_file" 2>/dev/null)" || pq_err=""
  rm -f "$pq_err_file"
  pq_out="$(printf '%s' "$pq_out" | tr -d '\r')"

  pq_status=""
  if printf '%s' "$pq_out" | jq -e 'type == "object"' >/dev/null 2>&1; then
    pq_status="$(printf '%s' "$pq_out" | jq -r '.status // empty' 2>/dev/null | tr -d '\r')" || pq_status=""
  fi

  if [ "$pq_status" = ok ] && [ "$pq_rc" -eq 0 ]; then
    : # 먼저 병합할 열린 PR 이 없다. 통과시키고 나머지 검사를 계속한다.
  elif [ "$pq_status" = ok ] && [ "$pq_rc" -eq 1 ]; then
    # PR 은 번호만이 아니라 링크로 보인다(#386). 엔진이 준 url 이 없으면 저장소와 번호로 만든다.
    # 링크에 들어가는 저장소 이름($repo, 사용자 입력에서 옴)과 엔진 출력은 모두 tr 로 따옴표·역슬래시·백틱·달러를 지운 뒤
    # 메시지에 넣으므로 JSON 을 깨지 않는다.
    pq_repo="$(printf '%s' "$repo" | tr -d '\r"\\`$')"
    pq_list="$(printf '%s' "$pq_out" | jq -r --arg repo "$pq_repo" '[.before[] | "[#\(.number)](\(.url // ("https://github.com/" + $repo + "/pull/" + (.number | tostring)))) \(.title)" + (if (.reasons | length) > 0 then " - 이유: " + (.reasons | join("; ")) else "" end)] | join(" / ")' 2>/dev/null | tr -d '\r"\\`$')" || pq_list=""
    pq_first="$(printf '%s' "$pq_out" | jq -r --arg repo "$pq_repo" '.before[0] // empty | "[#\(.number)](\(.url // ("https://github.com/" + $repo + "/pull/" + (.number | tostring))))"' 2>/dev/null | tr -d '\r"\\`$')" || pq_first=""
    deny "[PR #$pr_number](https://github.com/$pq_repo/pull/$pr_number) 보다 먼저 병합해야 하는 PR 이 아직 열려 있어 merge 를 막습니다. 먼저 병합할 PR: $pq_list 다음: 먼저 ${pq_first:-앞 PR} 을 병합하십시오(/harness:prs 로 순서와 상태 확인). 순서가 틀렸다면 이 PR 본문의 '먼저:' 줄을 고치십시오."
  else
    pq_msg=""
    if [ -n "$pq_status" ]; then
      pq_msg="$(printf '%s' "$pq_out" | jq -r '.message // empty' 2>/dev/null | tr -d '\r"\\`$')" || pq_msg=""
    fi
    if [ -z "$pq_msg" ]; then
      pq_detail_raw="$pq_out"
      if [ -n "$pq_err" ]; then
        pq_detail_raw="$pq_detail_raw $pq_err"
      fi
      pq_msg="$(printf '%s' "$pq_detail_raw" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
    fi
    deny "PR #$pr_number 보다 먼저 병합할 PR 이 있는지 확인하지 못해 merge 를 막습니다(종료코드 $pq_rc). 확인되지 않는 상태로 통과시키지 않습니다. 사유: $pq_msg 다음: /harness:prs 로 PR 상태와 순서를 확인하십시오. 순환이면 PR 본문의 '먼저:' 줄을 고치십시오. $next_retry"
  fi

  # stdout 과 stderr 를 나눠 받는다(#63). uv 가 엔진을 캐시 없이 새로 빌드할 때
  # "Building doc-guard-checker ...", "Installed N packages ..." 같은 진행
  # 로그를 stderr 로 낸다. 예전에는 `2>&1` 로 합쳐 받아 그 로그가 JSON 앞뒤에
  # 섞여 들어왔고, 판정 자체는 정상(종료코드 0, touches_ssot: false)인데도
  # 아래 jq 해석이 실패해 "확인하지 못해 merge 를 막습니다" 로 잘못 거절했다.
  # 이제 JSON 해석은 stdout 만으로 하고, stderr 는 실패했을 때 사람에게 보여줄
  # "자세히" 로만 쓴다.
  ssot_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 의 SRS 승인 여부를 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  trap 'rm -f "$ssot_err_file"' EXIT

  set +e
  ssot_out="$(uvx --from "$engine" python -P -m checker.ssot_approval check-pr --repo "$repo" --pr "$pr_number" 2>"$ssot_err_file")"
  ssot_rc=$?
  set -e
  ssot_err="$(cat "$ssot_err_file" 2>/dev/null)" || ssot_err=""
  rm -f "$ssot_err_file"

  # uvx 가 판정 로직을 아예 못 받았거나(#12 와 같은 사정) 못 돌렸으면, 그
  # 출력은 checker.ssot_approval 이 약속한 JSON 이 아니라 uvx/python 이 낸
  # 원문 오류다. 그런 상태에서는 uvx 자신의 종료코드가 우연히 0 이나 1 과
  # 같아도 그것을 판정 결과로 읽지 않는다 — 판정 로직이 실행조차 못 됐다는
  # 뜻이기 때문이다.
  ssot_json_ok=0
  if printf '%s' "$ssot_out" | jq -e . >/dev/null 2>&1; then
    ssot_json_ok=1
  fi

  if [ "$ssot_json_ok" -eq 1 ] && [ "$ssot_rc" -eq 0 ]; then
    : # SRS 를 안 바꿨거나 이미 승인됐다. 통과시키고 나머지 검사를 계속한다.
  elif [ "$ssot_json_ok" -eq 1 ] && [ "$ssot_rc" -eq 1 ]; then
    reason="$(printf '%s' "$ssot_out" | jq -r '.reason // empty' 2>/dev/null)" || true
    # 승인은 했지만 그 뒤 새 커밋이 올라온 경우(#119)의 사유에는 이미 "다음:" 이
    # 들어 있다. 일반 안내를 또 붙여 "다음:" 이 겹치지 않게 한다.
    case "$reason" in
      *"다음:"*)
        deny "SRS(docs/ssot) 를 바꾼 PR #$pr_number 인데 현재 최신 커밋에 대한 승인자의 Approve 가 없어 merge 를 막습니다. 사유: $reason 그 뒤 다음: Approve 가 최신 커밋에 달리면 Claude 가 gh pr merge 를 다시 실행합니다."
        ;;
      *)
        deny "SRS(docs/ssot) 를 바꾼 PR #$pr_number 인데 작성자가 아닌 승인자의 Approve 가 없어 merge 를 막습니다. 사유: $reason 다음: 🚨 직접 해 주세요: .github/ssot-approvers 에서 이 PR 작성자에게 정해진 승인자(작성자 본인 제외)에게 이 PR 의 리뷰에서 Approve 를 요청하십시오. Approve 가 달린 뒤 Claude 가 gh pr merge 를 다시 실행합니다."
        ;;
    esac
  else
    # $ssot_out(stdout)과 $ssot_err(stderr)는 uvx/gh 가 낸 원문 오류일 수 있어
    # 큰따옴표·역슬래시가 섞여 있을 수 있다. deny() 가 그대로 JSON 에 끼워
    # 넣으므로 여기서 지운다. JSON 해석에는 쓰지 않고 사람이 읽을 "자세히"
    # 에만 둘 다 보여준다.
    detail_raw="$ssot_out"
    if [ -n "$ssot_err" ]; then
      if [ -n "$detail_raw" ]; then
        detail_raw="$detail_raw
$ssot_err"
      else
        detail_raw="$ssot_err"
      fi
    fi
    detail="$(printf '%s' "$detail_raw" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
    deny "PR #$pr_number 의 SRS 승인 여부를 확인하지 못해 merge 를 막습니다(종료코드 $ssot_rc). 확인되지 않는 상태로 통과시키지 않습니다. $next_retry 자세히: $detail"
  fi

  fi

  # 0-1) Plugin·엔진처럼 사람이 직접 merge 해야 하는 경로(.github/human-merge-paths)
  #      를 바꾼 PR 이면 거부한다(#104). Claude 세션은 소유자의 GitHub 계정으로
  #      동작해 GitHub 가 사람과 구분하지 못하므로, 여기서 Claude 의 `gh pr merge`
  #      만 막고 사람은 GitHub 화면의 Merge 버튼으로 병합한다. 위와 같은 이유로
  #      stdout/stderr 를 나눠 받고, 판정 불가는 통과가 아니라 거부다.
  hm_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 가 사람이 merge 해야 하는 경로를 바꿨는지 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  set +e
  hm_out="$(uvx --from "$engine" python -P -m checker.ssot_approval check-human-merge --repo "$repo" --pr "$pr_number" 2>"$hm_err_file")"
  hm_rc=$?
  set -e
  hm_err="$(cat "$hm_err_file" 2>/dev/null)" || hm_err=""
  rm -f "$hm_err_file"

  hm_json_ok=0
  if printf '%s' "$hm_out" | jq -e . >/dev/null 2>&1; then
    hm_json_ok=1
  fi

  if [ "$hm_json_ok" -eq 1 ] && [ "$hm_rc" -eq 0 ]; then
    : # 보호 경로를 안 바꿨다. 통과시키고 나머지 검사를 계속한다.
  elif [ "$hm_json_ok" -eq 1 ] && [ "$hm_rc" -eq 1 ]; then
    hm_paths="$(printf '%s' "$hm_out" | jq -r '(.paths // []) | .[:5] | join(", ")' 2>/dev/null | tr -d '\r"\\')" || true
    hm_total="$(printf '%s' "$hm_out" | jq -r '(.paths // []) | length' 2>/dev/null | tr -d '\r')" || true
    if [ "${hm_total:-0}" -gt 5 ] 2>/dev/null; then
      hm_paths="$hm_paths 등 ${hm_total}개"
    fi
    if [ "$auto" = auto ]; then
      deny "이 PR 은 사람이 직접 병합하는 경로($hm_paths)를 바꿔서 자동 병합을 걸 수 없어요. 다음: 사람이 GitHub 화면에서 병합하거나, 사람이 그 PR 에 자동 병합을 켜 주세요."
    fi
    deny "PR #$pr_number 은 사람이 직접 merge 해야 하는 경로($hm_paths)를 바꿨습니다. Claude 는 이 PR 을 merge 할 수 없습니다. 다음: 🚨 직접 해 주세요: 사용자에게 이 PR 의 GitHub 화면(PR 페이지 아래쪽)에서 Merge 버튼을 눌러 병합해 달라고 요청하십시오."
  else
    hm_detail_raw="$hm_out"
    if [ -n "$hm_err" ]; then
      if [ -n "$hm_detail_raw" ]; then
        hm_detail_raw="$hm_detail_raw
$hm_err"
      else
        hm_detail_raw="$hm_err"
      fi
    fi
    hm_detail="$(printf '%s' "$hm_detail_raw" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
    deny "PR #$pr_number 가 사람이 merge 해야 하는 경로를 바꿨는지 확인하지 못해 merge 를 막습니다(종료코드 $hm_rc). 확인되지 않는 상태로 통과시키지 않습니다. $next_retry 자세히: $hm_detail"
  fi

  if [ "$auto" != auto ]; then
  # 0-2) PR 위험도(크기·위험 경로·비밀값·다른 검사)가 높은데 최신 커밋에 대한 승인이 없으면
  #      거부한다(#102). 기준은 대상 저장소의 .github/risk-gate.yaml 이고 없으면 게이트가
  #      꺼진 것이라 통과(종료코드 0)다. 위와 같은 이유로 stdout/stderr 를 나눠 받고, 판정
  #      불가는 통과가 아니라 거부다. 엔진이 돌려주는 next 에는 이미 "다음:" 이 들어 있다.
  rg_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 의 위험도를 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  set +e
  rg_out="$(uvx --from "$engine" python -P -m checker.risk_gate check-pr --repo "$repo" --pr "$pr_number" 2>"$rg_err_file")"
  rg_rc=$?
  set -e
  rg_err="$(cat "$rg_err_file" 2>/dev/null)" || rg_err=""
  rm -f "$rg_err_file"

  rg_json_ok=0
  if printf '%s' "$rg_out" | jq -e . >/dev/null 2>&1; then
    rg_json_ok=1
  fi

  if [ "$rg_json_ok" -eq 1 ] && [ "$rg_rc" -eq 0 ]; then
    : # 게이트가 꺼져 있거나 위험하지 않거나 위험하지만 승인됐다. 통과시킨다.
  elif [ "$rg_json_ok" -eq 1 ] && [ "$rg_rc" -eq 1 ]; then
    rg_reasons="$(printf '%s' "$rg_out" | jq -r '(.reasons // []) | .[:5] | join(" / ")' 2>/dev/null | tr -d '\r"\\`$')" || true
    rg_total="$(printf '%s' "$rg_out" | jq -r '(.reasons // []) | length' 2>/dev/null | tr -d '\r')" || true
    if [ "${rg_total:-0}" -gt 5 ] 2>/dev/null; then
      rg_reasons="$rg_reasons 등 ${rg_total}개"
    fi
    next_risk="$(printf '%s' "$rg_out" | jq -r '.next // empty' 2>/dev/null | tr -d '\r"\\`$')" || true
    case "$next_risk" in
      *"다음:"*) : ;;
      *) next_risk="다음: 🚨 직접 해 주세요: .github/ssot-approvers 에서 이 PR 작성자에게 정해진 승인자(작성자 본인 제외)에게 최신 커밋을 보고 Approve 를 요청하십시오." ;;
    esac
    deny "PR #$pr_number 은 위험도가 높은데 최신 커밋에 대한 승인자의 Approve 가 없어 merge 를 막습니다. 이유: $rg_reasons $next_risk Approve 가 달리면 Claude 가 gh pr merge 를 다시 실행합니다."
  else
    rg_detail_raw="$rg_out"
    if [ -n "$rg_err" ]; then
      if [ -n "$rg_detail_raw" ]; then
        rg_detail_raw="$rg_detail_raw
$rg_err"
      else
        rg_detail_raw="$rg_err"
      fi
    fi
    rg_detail="$(printf '%s' "$rg_detail_raw" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
    deny "PR #$pr_number 의 위험도를 확인하지 못해 merge 를 막습니다(종료코드 $rg_rc). 검사 불능이므로 통과시키지 않습니다. $next_retry 자세히: $rg_detail"
  fi
  fi
}

# 0-0) 작성자가 지금 gh 로그인 계정과 다른 PR 을 바꾸는 gh pr 명령을 거부한다(#150).
#      대상은 merge·edit·close·reopen·comment·review·ready. 읽기(view·diff·checks·list·
#      status·checkout)는 건드리지 않는다. 다른 계정의 PR 은 읽기만 하고 내 작업이 주는
#      영향만 알리는 것이 규칙이다(governance.md). 무료 개인 계정이라 서버가 막지 못해
#      Claude 쪽에서 막는 보조 관문이다 — 사람이 웹에서 하는 일은 막지 못하고, 그것은
#      Actions(pr-tamper-alert)가 사후에 알린다.
#
#      명령 분해는 merge 와 같은 엔진 모듈(checker.merge_command --mutations)을 쓴다.
#      따옴표·heredoc 본문의 글자를 명령으로 읽지 않고 조각마다 자기 -R 과 PR 지정을 짝짓기
#      때문이다. 작성자는 gh pr view 로, 로그인 계정은 gh api user 로 얻어 대소문자 무시로
#      비교한다. 얻지 못하면 통과도 거부(작성자 다름)도 아닌 검사 불능으로 거부한다.
#      gh 호출은 timeout 이 있으면 30초로 끊는다. 이 검사는 아래 merge 검사보다 먼저 돈다.
gh_tcmd=()
command -v timeout >/dev/null 2>&1 && gh_tcmd=(timeout 30)

# 지금 gh 로그인 계정을 login_now 에 얻는다(소문자). 얻지 못하면 거부한다.
get_login_now() {
  if ! command -v gh >/dev/null 2>&1; then
    deny "gh 가 없어 PR 작성자와 지금 로그인 계정을 비교할 수 없습니다. 검사 불능이므로 통과시키지 않습니다. $next_install_gh"
  fi
  set +e
  login_now="$(${gh_tcmd[@]+"${gh_tcmd[@]}"} gh api user --jq .login 2>/dev/null)"
  login_rc=$?
  set -e
  login_now="$(printf '%s' "$login_now" | tr -d '\r"\\` $' | tr '[:upper:]' '[:lower:]')"
  if [ "$login_rc" -ne 0 ] || [ -z "$login_now" ]; then
    deny "지금 gh 로그인 계정을 확인하지 못해 PR 작성자와 비교할 수 없습니다(종료코드 $login_rc). 검사 불능이므로 통과시키지 않습니다. $next_retry"
  fi
}

# 지금 로그인 계정이 대상 저장소의 admin 인지 본다. $1=저장소(빈 값이면 현재 저장소).
# admin 이면 0, 아니면 1. 조회를 못 하면 통과도 거부(admin 아님)도 아닌 검사 불능으로 거부한다.
viewer_is_admin() {
  va_args=()
  [ -n "$1" ] && va_args+=("$1")
  set +e
  va_perm="$(${gh_tcmd[@]+"${gh_tcmd[@]}"} gh repo view ${va_args[@]+"${va_args[@]}"} --json viewerPermission --jq .viewerPermission 2>/dev/null)"
  va_rc=$?
  set -e
  va_perm="$(printf '%s' "$va_perm" | tr -d '\r"\\` $' | tr '[:lower:]' '[:upper:]')"
  if [ "$va_rc" -ne 0 ] || [ -z "$va_perm" ]; then
    deny "검사 불능: 다른 계정의 PR 인데 지금 계정의 저장소 권한(admin 여부)을 gh 로 확인하지 못했습니다(종료코드 $va_rc). 통과시키지 않습니다. $next_retry"
  fi
  [ "$va_perm" = "ADMIN" ]
}

# PR 한 건의 작성자를 확인한다. $1=하위 명령, $2=저장소(-R, 없으면 빈 값), $3=PR 지정(없으면 현재 브랜치).
check_pr_author() {
  ca_sub="$1"
  ca_repo="$2"
  ca_ref="$3"
  # URL 로 지정하면 gh 가 저장소를 URL 에서 읽으므로 -R 을 붙이지 않는다.
  # 권한 조회용 저장소는 URL 에서 뽑아 남긴다.
  ca_is_url=0
  case "$ca_ref" in
    */pull/*)
      ca_is_url=1
      ca_repo="$(printf '%s' "$ca_ref" | sed -n 's#^https\{0,1\}://github\.com/\([^/]*/[^/]*\)/pull/.*#\1#p')"
      ;;
  esac
  ca_args=()
  [ -n "$ca_ref" ] && ca_args+=("$ca_ref")
  [ -n "$ca_repo" ] && [ "$ca_is_url" -eq 0 ] && ca_args+=(-R "$ca_repo")
  set +e
  ca_author="$(${gh_tcmd[@]+"${gh_tcmd[@]}"} gh pr view ${ca_args[@]+"${ca_args[@]}"} --json author --jq .author.login 2>/dev/null)"
  ca_rc=$?
  set -e
  ca_author="$(printf '%s' "$ca_author" | tr -d '\r"\\` $')"
  if [ "$ca_rc" -ne 0 ] || [ -z "$ca_author" ]; then
    deny "gh pr $ca_sub 의 대상 PR 작성자를 확인하지 못했습니다(종료코드 $ca_rc). 검사 불능이므로 통과시키지 않습니다. 다음: Claude 가 PR 번호를 붙여(예: gh pr $ca_sub 123) 다시 실행하십시오. 그래도 안 되면 gh auth status 로 로그인 상태를 확인하고, 로그인 안 됨이면 사람이 gh auth login 을 실행하십시오."
  fi
  ca_author_lc="$(printf '%s' "$ca_author" | tr '[:upper:]' '[:lower:]')"
  # 작성자가 같으면 권한 조회를 하지 않는다(호출 줄이기). 다르면 admin 인지 본다.
  if [ "$ca_author_lc" != "$login_now" ] && ! viewer_is_admin "$ca_repo"; then
    deny "작성자 $ca_author 의 PR 이고 지금 gh 로그인 계정은 $login_now 입니다. admin 권한이 있는 계정만 남의 PR 을 고칠 수 있는데 이 계정은 admin 이 아닙니다. 다른 계정이 만든 PR 은 읽기만 하므로 gh pr $ca_sub 를 막습니다. 다음: 읽기(gh pr view, diff, checks)만 하고, 내 작업이 그 PR 에 주는 영향(충돌, 같은 파일, 검사 결과 변화)만 사용자에게 알리십시오. 병합, 수정, 닫기, 코멘트, 리뷰는 그 PR 작성자나 사용자가 직접 합니다."
  fi
}

pr_word_re='(^|[^[:alnum:]_-])pr([^[:alnum:]_-]|$)'
pr_sub_re='(^|[^[:alnum:]_-])(merge|edit|close|reopen|comment|review|ready)([^[:alnum:]_-]|$)'
if [[ "$cmd" =~ $pr_word_re ]] && [[ "$cmd" =~ $pr_sub_re ]]; then
  if ! command -v uvx >/dev/null 2>&1; then
    deny "uvx 가 없어 이 명령이 다른 계정 PR 을 바꾸는지 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. $next_install_uv"
  fi
  resolve_engine
  pm_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 이 명령의 대상 PR 을 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  set +e
  pm_out="$(printf '%s' "$cmd" | uvx --from "$engine" python -P -m checker.merge_command --mutations 2>"$pm_err_file")"
  pm_rc=$?
  set -e
  pm_err="$(cat "$pm_err_file" 2>/dev/null)" || pm_err=""
  rm -f "$pm_err_file"

  if ! printf '%s' "$pm_out" | jq -e . >/dev/null 2>&1; then
    pm_detail="$(printf '%s\n%s' "$pm_out" "$pm_err" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
    deny "이 명령이 PR 을 바꾸는 gh pr 명령인지 확인하지 못해 막습니다(종료코드 $pm_rc). 검사 불능이므로 통과시키지 않습니다. $next_retry 자세히: $pm_detail"
  fi
  if [ "$pm_rc" -eq 2 ] && printf '%s' "$pm_out" | jq -e 'has("error")' >/dev/null 2>&1; then
    pm_why="$(printf '%s' "$pm_out" | jq -r '.error // empty' 2>/dev/null | tr -d '\r"\\`$' | cut -c1-200)" || pm_why=""
    deny "명령을 믿을 만하게 해석하지 못해 대상 PR 과 작성자를 확인할 수 없습니다($pm_why). 검사 불능이므로 통과시키지 않습니다. 다음: Claude 가 gh pr 명령을 한 명령에 하나씩, 다른 명령과 묶지 말고, PR 번호를 붙이고 알려진 옵션만 써서 다시 실행하십시오."
  fi
  if [ "$pm_rc" -ne 0 ] || ! printf '%s' "$pm_out" | jq -e '.mutations | type == "array"' >/dev/null 2>&1; then
    deny "이 명령이 PR 을 바꾸는 gh pr 명령인지 확인하지 못해 막습니다(종료코드 $pm_rc). 검사 불능이므로 통과시키지 않습니다. 다음: Claude 가 gh pr 명령을 한 명령에 하나씩 다시 실행하십시오. $next_retry"
  fi

  # 한 줄에 한 건씩 "하위명령 저장소 PR지정". 빈 값은 "-" 자리표시자로 받아 되돌린다.
  pm_lines="$(printf '%s' "$pm_out" | jq -r '.mutations[] | [.sub, ((.repo // "") | if . == "" then "-" else . end), ((.prref // "") | if . == "" then "-" else . end)] | join(" ")' | tr -d '\r')"
  if [ -n "$pm_lines" ]; then
    get_login_now
    while IFS=' ' read -r pm_sub pm_repo pm_prref; do
      [ -z "$pm_sub" ] && continue
      [ "$pm_repo" = "-" ] && pm_repo=""
      [ "$pm_prref" = "-" ] && pm_prref=""
      check_pr_author "$pm_sub" "$pm_repo" "$pm_prref"
    done <<EOF
$pm_lines
EOF
  fi
fi

# 첫 관문: `pr merge` 글자가 명령에 없으면 merge 일 수 없으므로 엔진을 부르지
# 않는다. 일반 명령마다 uvx 를 띄우면 느려서 사람들이 훅을 끄게 된다.
case "$cmd" in
  *pr*merge*)
    if ! command -v uvx >/dev/null 2>&1; then
      deny "uvx 가 없어 이 명령이 gh pr merge 인지, SRS 승인이 있는지 확인하지 못했습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. $next_install_uv"
    fi
    resolve_engine
    mc_err_file="$(mktemp 2>/dev/null)" || {
      deny "임시 파일을 만들지 못해 이 명령이 gh pr merge 인지 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
    }
    set +e
    mc_out="$(printf '%s' "$cmd" | uvx --from "$engine" python -P -m checker.merge_command 2>"$mc_err_file")"
    mc_rc=$?
    set -e
    mc_err="$(cat "$mc_err_file" 2>/dev/null)" || mc_err=""
    rm -f "$mc_err_file"

    if ! printf '%s' "$mc_out" | jq -e . >/dev/null 2>&1; then
      mc_detail="$(printf '%s\n%s' "$mc_out" "$mc_err" | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
      deny "이 명령이 gh pr merge 인지 확인하지 못해 막습니다(종료코드 $mc_rc). 확인되지 않는 상태로 통과시키지 않습니다. $next_retry 자세히: $mc_detail"
    fi
    if [ "$mc_rc" -eq 2 ] && printf '%s' "$mc_out" | jq -e 'has("error")' >/dev/null 2>&1; then
      deny "명령을 셸 문법대로 믿을 만하게 나누지 못해 gh pr merge 가 있는지 확인할 수 없습니다. 다음: Claude 가 merge 를 한 명령에 하나씩, 다른 명령과 묶지 말고 다시 실행하십시오."
    fi
    if [ "$mc_rc" -ne 0 ] || ! printf '%s' "$mc_out" | jq -e '.merges | type == "array"' >/dev/null 2>&1; then
      deny "이 명령이 gh pr merge 인지 확인하지 못해 막습니다(종료코드 $mc_rc). 확인되지 않는 상태로 통과시키지 않습니다. 다음: Claude 가 merge 를 한 명령에 하나씩 다시 실행하십시오. $next_retry"
    fi

    # 한 줄에 한 건씩 "저장소 PR지정". 윈도우 jq 의 CRLF 는 벗긴다. 공백 구분
    # read 는 빈 앞칸을 삼켜 저장소 없음과 PR 지정 없음을 헷갈리므로, 빈 값은
    # "-" 자리표시자로 받아 되돌린다(저장소·PR 지정에 "-" 만 오는 일은 없다).
    mc_lines="$(printf '%s' "$mc_out" | jq -r '.merges[] | [((.repo // "") | if . == "" then "-" else . end), ((.prref // "") | if . == "" then "-" else . end), (if .admin == true then "admin" elif .auto == true then "auto" else "-" end)] | join(" ")' | tr -d '\r')"
    while IFS=' ' read -r mc_repo mc_prref mc_mode; do
      [ -z "$mc_repo" ] && continue
      [ "$mc_repo" = "-" ] && mc_repo=""
      [ "$mc_prref" = "-" ] && mc_prref=""
      # --admin 은 보호 규칙(필수 검사·승인)을 우회한다. 어떤 PR 에도 허용하지 않는다(#437).
      if [ "$mc_mode" = "admin" ]; then
        deny "gh pr merge --admin 은 보호 규칙과 필수 검사를 건너뛰는 병합이라 막습니다. 다음: --admin 을 빼고 실행하십시오. 검사나 승인이 모자라 못 합치는 거라면 그 사유를 해결하십시오(자동 병합 예약은 gh pr merge 번호 --auto --squash)."
      fi
      # --auto 는 병합을 예약만 한다. 필수 검사와 승인이 끝나야 GitHub 서버가 합치므로
      # 검사 진행 중·앞 PR 대기·SRS 승인·위험도 판정은 건너뛰고, 사람 병합 경로는 그대로 막는다(#437).
      # 남의 PR 금지는 위 0-0 관문이 이미 merge 에 적용했다.
      check_one_merge "$mc_repo" "$mc_prref" "$mc_mode"
    done <<EOF
$mc_lines
EOF
    ;;
esac

# 1) 되돌릴 수 없는 강제 푸시는 어떤 경우에도 거부한다. 선언 접두어보다 먼저
#    검사하는 이유는, 접두어가 이 동작까지 열어 주는 문이 되지 않게 하기
#    위해서다. 짧은 옵션은 -f 로도 -uf 로도 묶여 쓰이므로, 붙임표 하나로
#    시작하는 토큰 안에 f 가 있으면 강제로 본다. --force-with-lease 는 붙임표
#    둘로 시작하고 --force 뒤에 공백이 오지 않아 이 패턴에 걸리지 않는다.
#    push 조각마다 보므로(#264) `git status && git push -f` 도 걸린다.
if [ "$push_force" -eq 1 ]; then
  deny "git push --force 는 이 저장소에서 금지되어 있습니다. 다음: --force 를 빼고 /harness:deliver 를 실행하십시오. 리베이스로 이력이 바뀐 경우의 --force-with-lease 푸시도 /harness:deliver 가 수행합니다."
fi

# 2) main 에서의 커밋도 선언 접두어와 무관하게 거부한다. 브랜치 규칙은
#    /harness:deliver 의 절차가 아니라 이 저장소의 전제이기 때문이다.
if [ "$commit_found" -eq 1 ]; then
  branch="$(git symbolic-ref --short -q HEAD || echo 알수없음)"
  if [ "$branch" = "main" ]; then
    deny "main 브랜치에는 직접 커밋할 수 없습니다. 다음: /harness:start 를 실행해 이슈를 만들고 규칙에 맞는 브랜치로 옮긴 뒤 그 브랜치에서 다시 커밋하십시오."
  fi
fi

# 2-1) 커밋에 들어갈 staged 변경에서 비밀정보를 gitleaks 로 검사한다(#170). 푸시하는 순간
#      비밀값은 이미 GitHub 에 올라가므로(폐기·교체해야 한다) 커밋 전에 막는 보조 관문이다.
#      주 관문은 Actions 의 gitleaks 검사(#159)이고 같은 규칙(하네스 기본 설정 + SAP 규칙,
#      프로젝트 .gitleaks.toml)을 쓴다. Claude 의 git commit 에만 걸린다 — 사람이 터미널에서
#      직접 한 커밋은 이 훅을 거치지 않으므로 Actions 가 잡는다.
#
#      커밋일 때만 gitleaks 를 부른다(다른 명령마다 부르면 느려서 훅을 끄게 된다). `git add .
#      && git commit` 처럼 묶인 명령도 잡도록, 큰따옴표·작은따옴표 안과 heredoc 본문을 걷어낸
#      명령을 ; && || | 로 나눠 조각마다 하위 명령을 본다. 위의 sub 는 첫 git 명령만 본다.
#
#      건너뛰기: 이 훅 프로세스 자신의 환경 변수 HARNESS_SKIP_SECRET_SCAN=1 일 때만. 명령 문자열
#      안의 접두어(HARNESS_SKIP_SECRET_SCAN=1 git commit)는 이 훅의 환경이 아니라 무시한다.
#      사람만 켠다(governance.md). 건너뛰면 그 사실을 알림으로 남긴다.
#
#      검사 범위를 정직하게 하려고, staged 밖 변경이 커밋에 들어가는 형태(-a, --all, -i,
#      --include, -o, --only)는 막는다. -a 나 --include 는 working tree 의 내용을 커밋에 넣어
#      staged 만 보는 검사로는 범위를 알 수 없다(검사 불능). --amend 는 새로 들어가는 것이
#      staged 변경뿐이라 staged 검사로 충분하다(기존 커밋의 내용은 이미 지난 일이다).
#      한계: `git commit 파일명`(경로 지정)도 working tree 내용을 커밋하지만 따옴표 안 메시지와
#      구분해 안정적으로 알아내기 어려워 막지 못한다. 최종 방어선은 Actions 다.
skip_notice=""

# 훅이 정상으로 끝낼 때의 출구. 비밀정보 검사를 건너뛰었으면 그 알림을 함께 낸다.
finish_ok() {
  if [ -n "$skip_notice" ]; then
    printf '{"systemMessage":"%s","hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"%s"}}\n' "$skip_notice" "$skip_notice"
  fi
  exit 0
}

# gitleaks 실행 파일을 찾는다. 결과는 gl_bin. 찾는 차례: GITLEAKS_BIN(테스트·직접 지정),
# PATH, 그리고 winget 이 설치한 자리(ensure-tools.sh 의 locate_tool 과 같은 곳).
find_gitleaks() {
  gl_bin=""
  if [ -n "${GITLEAKS_BIN:-}" ]; then
    gl_bin="$(command -v "$GITLEAKS_BIN" 2>/dev/null || true)"
    return 0
  fi
  gl_bin="$(command -v gitleaks 2>/dev/null || true)"
  [ -n "$gl_bin" ] && return 0
  lad="${LOCALAPPDATA:-$HOME/AppData/Local}"
  if command -v cygpath >/dev/null 2>&1; then
    lad="$(cygpath -u "$lad" 2>/dev/null || printf '%s' "$lad")"
  else
    lad="$(printf '%s' "$lad" | tr '\\' '/')"
  fi
  for d in \
    "$lad/Microsoft/WinGet/Links" \
    "$lad"/Microsoft/WinGet/Packages/Gitleaks.Gitleaks_*; do
    if [ -f "$d/gitleaks.exe" ]; then
      gl_bin="$d/gitleaks.exe"
      return 0
    fi
  done
  return 0
}

# 이 훅은 명령 전체가 실행되기 전에 돈다. 같은 명령에서 commit 앞 조각이 인덱스를 바꾸면
# (git add 등) 훅 시점의 staged 는 커밋될 내용이 아니다. 그래서 commit 앞에 git 조각이 있으면
# 검사할 수 없다고 본다. 목록을 맞추지 않고 "어떤 git 하위 명령이든" 으로 단순하게 하되, 인덱스를
# 못 바꾸는 읽기 전용(status, diff, log, show, rev-parse)만 예외로 둔다.
commit_seg=""
gl_prior_git=""
# 조각 목록은 위 스캔(scan_segs, scan_subs)을 그대로 쓴다.
gl_i=0
while [ "$gl_i" -lt "$scan_n" ]; do
  seg="${scan_segs[$gl_i]}"
  gl_sub="${scan_subs[$gl_i]}"
  gl_i=$((gl_i + 1))
  if [ "$gl_sub" = "commit" ]; then
    commit_seg="$seg"
    break
  fi
  case "$gl_sub" in
    ''|status|diff|log|show|rev-parse) ;;
    *) gl_prior_git="$gl_sub" ;;
  esac
done

if [ -n "$commit_seg" ]; then
  if [ "${HARNESS_SKIP_SECRET_SCAN:-}" = "1" ]; then
    skip_notice="비밀정보 검사를 건너뜀: HARNESS_SKIP_SECRET_SCAN=1 이 켜져 있어 이 커밋의 gitleaks 검사를 하지 않았습니다. 이 커밋에 비밀값이 있는지 확인되지 않았습니다. 다음: 사람이 그 변수를 끈 뒤 Claude Code 를 새로 여십시오."
  elif gl_top="$(git rev-parse --show-toplevel 2>/dev/null)" && [ -n "$gl_top" ]; then
    # merge·rebase·cherry-pick 진행 중이면 staged 에 남이 쓴 내용이 섞여 이 검사의 대상이
    # 아니다. 기존 훅이 통과시키던 상황을 그대로 둔다.
    gl_busy=0
    for gp in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply; do
      if [ -e "$(git rev-parse --git-path "$gp" 2>/dev/null)" ]; then gl_busy=1; fi
    done

    if [ "$gl_busy" -eq 0 ]; then
      if [ -n "$gl_prior_git" ]; then
        deny "검사 불능: 같은 명령에서 git commit 앞에 git $gl_prior_git 가 먼저 실행되어, 훅이 검사하는 시점의 staged 가 실제로 커밋될 내용과 다를 수 있습니다. 검사하지 못한 상태로 통과시키지 않습니다. 다음: Claude 가 git add 를 먼저 따로 실행한 뒤 git commit 을 별도 명령으로 실행하십시오."
      fi
      # staged 밖 변경이 커밋에 들어가는 형태를 막는다.
      gl_scope_bad=0
      gl_after=0
      set -f
      for tok in $commit_seg; do
        tok="${tok#\"}"; tok="${tok%\"}"
        tok="${tok#\'}"; tok="${tok%\'}"
        if [ "$gl_after" -eq 0 ]; then
          [ "$tok" = "commit" ] && gl_after=1
          continue
        fi
        case "$tok" in
          --all|--include|--only) gl_scope_bad=1 ;;
          --*) : ;;
          -?*)
            # 묶인 짧은 옵션(-am). 값을 받는 글자(m F C c t S)를 만나면 나머지는 값이다.
            gl_rest="${tok#-}"
            while [ -n "$gl_rest" ]; do
              gl_ch="${gl_rest%"${gl_rest#?}"}"
              gl_rest="${gl_rest#?}"
              case "$gl_ch" in
                a|i|o) gl_scope_bad=1 ;;
                m|F|C|c|t|S) break ;;
              esac
            done
            ;;
        esac
      done
      set +f
      if [ "$gl_scope_bad" -eq 1 ]; then
        deny "검사 불능: git commit 에 -a, --all, -i, --include, -o, --only 가 있어 staged 밖의 변경까지 커밋에 들어갑니다. 비밀정보 검사는 staged 변경만 보므로 이 커밋의 범위를 검사할 수 없고, 검사하지 못한 상태로 통과시키지 않습니다. 다음: Claude 가 커밋할 파일을 git add 로 올린 뒤 -a 같은 옵션 없이 git commit 을 다시 실행하십시오."
      fi

      # staged 변경이 없으면 검사할 것이 없다(커밋 자체도 대개 실패한다).
      gl_staged=0
      git diff --cached --quiet >/dev/null 2>&1 || gl_staged=1
      if [ "$gl_staged" -eq 1 ]; then
        find_gitleaks
        if [ -z "$gl_bin" ]; then
          deny "검사 불능: gitleaks 가 없어 비밀정보 검사를 하지 못했습니다. 검사하지 못한 상태로 커밋을 통과시키지 않습니다. 다음: 🚨 직접 해 주세요: PowerShell 에서 winget install --id Gitleaks.Gitleaks -e 를 실행해 gitleaks 를 설치한 뒤 Claude Code 를 새로 여십시오(세션을 다시 시작하면 자동 설치도 다시 시도합니다)."
        fi

        gl_tmp="$(mktemp -d 2>/dev/null)" || deny "검사 불능: 임시 폴더를 만들지 못해 비밀정보 검사를 하지 못했습니다. 검사하지 못한 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
        mkdir -p "$gl_tmp/.harness-engine/checker/gitleaks"
        if ! cp "$hook_dir/gitleaks-harness.toml" "$gl_tmp/.harness-engine/checker/gitleaks/harness.toml" 2>/dev/null; then
          rm -rf "$gl_tmp"
          deny "검사 불능: 하네스 기본 gitleaks 설정(hooks/gitleaks-harness.toml)을 읽지 못해 비밀정보 검사를 하지 못했습니다. 검사하지 못한 상태로 통과시키지 않습니다. 다음: 🚨 직접 해 주세요: harness 플러그인을 다시 설치하거나 갱신하십시오. 계속되면 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."
        fi

        # 설정: 저장소의 .gitleaks.toml 이 있으면 그것, 없으면 하네스 기본 설정. 설정 안의
        # [extend] path 는 설정 파일 위치가 아니라 gitleaks 를 부른 현재 폴더 기준이다. 프로젝트
        # .gitleaks.toml 이 Actions 용 경로(.harness-engine/checker/gitleaks/harness.toml)로
        # 이어받아도 로컬에서 풀리도록, 그 경로에 플러그인 복사본을 둔 임시 폴더를 현재 폴더로
        # 하고 저장소는 경로 인자로 넘긴다.
        if [ -f "$gl_top/.gitleaks.toml" ]; then
          gl_cfg="$gl_top/.gitleaks.toml"
        else
          gl_cfg=".harness-engine/checker/gitleaks/harness.toml"
        fi

        gl_out_file="$gl_tmp/out.txt"
        gl_tcmd=()
        command -v timeout >/dev/null 2>&1 && gl_tcmd=(timeout 120)
        set +e
        ( cd "$gl_tmp" && ${gl_tcmd[@]+"${gl_tcmd[@]}"} "$gl_bin" git --pre-commit --staged --redact --exit-code 2 --no-banner --no-color -v -c "$gl_cfg" "$gl_top" ) >"$gl_out_file" 2>&1 </dev/null
        gl_rc=$?
        set -e
        # 로그의 색 코드(ESC)가 JSON 에 들어가면 안 되므로 지운다(--no-color 는 로그 줄엔 듣지 않는다).
        gl_out="$(sed -E 's/\x1b\[[0-9;]*[A-Za-z]//g' "$gl_out_file" 2>/dev/null | tr -d '\r')" || gl_out=""
        rm -rf "$gl_tmp"

        # gitleaks 는 저장소를 못 읽는 등의 오류도 종료코드 0 으로 끝낼 때가 있어 로그의 ERR 도
        # 본다. 값은 --redact 로 가려지고, 요약에는 규칙·파일·줄만 쓴다.
        if [ "$gl_rc" -eq 0 ] && printf '%s\n' "$gl_out" | grep -Eq '(^|[[:space:]])(ERR|FTL)([[:space:]]|$)'; then
          gl_rc=99
        fi

        case "$gl_rc" in
          0)
            : # 비밀값이 발견되지 않았다.
            ;;
          2)
            gl_summary="$(printf '%s\n' "$gl_out" | awk '
              /^RuleID:/ { r = $2 }
              /^File:/   { f = $0; sub(/^File:[ \t]*/, "", f) }
              /^Line:/   { n++; if (n <= 5) printf "%s%s %s:%s", (n > 1 ? ", " : ""), r, f, $2 }
              END { if (n > 5) printf " 등 %d건", n }' | tr -d '"\\`$')"
            deny "비밀값 발견: 커밋에 들어갈 staged 변경에서 비밀정보 모양이 발견되어 커밋을 막습니다(값은 가려서 표시하지 않습니다). 발견: $gl_summary 다음: Claude 가 해당 줄을 파일에서 빼고 git add 로 다시 올린 뒤 커밋하십시오. 진짜 비밀값이면 이미 노출된 것으로 보고 폐기하고 새로 발급해 교체해야 하므로 사람에게 알리십시오. 오탐이면 🚨 직접 해 주세요: 저장소의 .gitleaks.toml 의 [allowlist] 에 해당 경로나 정규식을 추가하십시오(Claude 가 스스로 추가하지 않습니다)."
            ;;
          *)
            if [ "$gl_rc" -eq 124 ]; then
              gl_detail="시간 초과(120초)"
            else
              gl_detail="$(printf '%s\n' "$gl_out" | grep -E 'FTL|ERR' | head -n 3 | tr -d '"\\`$' | tr '\n' ' ' | cut -c1-300)"
              [ -z "$gl_detail" ] && gl_detail="출력 없음"
            fi
            deny "검사 불능: gitleaks 가 오류로 끝나(종료코드 $gl_rc) 비밀정보 검사를 하지 못했습니다. 이것은 비밀값이 발견됐다는 뜻이 아니며, 검사하지 못한 상태로 통과시키지도 않습니다. 사유: $gl_detail 다음: gitleaks 가 동작하는지, 저장소의 .gitleaks.toml 이 올바른 TOML 이고 [extend] path 가 .harness-engine/checker/gitleaks/harness.toml 인지 확인하고 같은 커밋을 다시 시도하십시오. 계속되면 🚨 직접 해 주세요: 원인을 해결하십시오(급하면 HARNESS_SKIP_SECRET_SCAN=1 을 환경에 설정하고 Claude Code 를 새로 여십시오. 이 변수는 사람만 켜고 Claude 는 켜지 않습니다)."
            ;;
        esac
      fi
    fi
  fi
fi

# 2-1b) 공유 .claude/settings.json 의 enabledPlugins 에서 harness 가 빠지거나 꺼지는 변경을 막는다(#471).
#      claude plugin uninstall 이 묻지 않고 이 항목을 비운 일이 있어, 커밋되면 팀원 전체의 harness 가
#      꺼진다. 커밋은 staged 변경을, 푸시는 origin 기준 범위를 본다. 판정은 enabled_plugin_guard.py
#      (종료코드 0 통과, 1 거절, 2 검사 불능). 그 파일을 건드린 적이 없으면 python 을 부르지 않는다.
#      세션 cwd 가 저장소 하위 폴더여도 저장소 루트의 파일을 본다(:(top) 경로, 판정 쪽은 git -C 루트).
#      푸시는 HEAD 만 본다 — `git push origin 다른브랜치:대상` 처럼 HEAD 가 아닌 refspec 이면 그 refspec 의
#      내용은 보지 못한다(기존 푸시 대상 파싱은 도착 브랜치만 뽑는다).
#      HARNESS_SKIP_SECRET_SCAN 은 비밀정보 검사 전용이라 여기에는 듣지 않는다.
enabled_guard() {
  local mode="$1" what="$2" out rc
  set +e
  out="$(PYTHONIOENCODING=utf-8 uv run --no-project python "$hook_dir/enabled_plugin_guard.py" "$mode" 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 0 ] && return 0
  out="$(printf '%s' "$out" | tr -d '\r')"
  if [ "$rc" -ne 1 ] && [ "$rc" -ne 2 ]; then
    out="검사 불능: enabledPlugins 검사를 실행하지 못했습니다(종료코드 $rc). 검사하지 못한 상태로 통과시키지 않습니다. 사유: $out 다음: uv 가 있는지 확인하고 같은 명령을 다시 시도하십시오. $next_install_uv"
  fi
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' \
    "$(printf '%s' "$what 를 막습니다. $out" | jq -Rs .)"
  exit 0
}
if [ -n "$commit_seg" ] && git rev-parse --show-toplevel >/dev/null 2>&1; then
  if ! git diff --cached --quiet -- ':(top).claude/settings.json' >/dev/null 2>&1; then
    enabled_guard staged "커밋"
  fi
fi
if [ "$push_found" -eq 1 ] && [ -n "$(git log -1 --format=%H -- ':(top).claude/settings.json' 2>/dev/null || true)" ]; then
  enabled_guard push "푸시"
fi

# 2-2) 푸시 전에 080 에 쓴 ABAP 오브젝트가 모두 활성화됐는지 본다(#190). 선언
#      접두어(DELIVER=1)보다 먼저 검사한다 — 접두어가 이 관문을 여는 문이 되지
#      않게 하기 위해서다. 기록 파일도 실패 표식도 없으면(대부분의 푸시) python 을 부르지 않는다.
#      기록이 있는데 관문을 실행하지 못하면 통과가 아니라 검사 불능으로 거부한다.
#      관문 출력(여러 줄, 따옴표 포함 가능)은 deny() 에 끼우지 않고 jq 로 JSON 인코딩한다.
if [ "$push_found" -eq 1 ]; then
  act_git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null | tr -d '\r' || true)"
  if [ -n "$act_git_dir" ] && { [ -e "$act_git_dir/harness-adt-activation.json" ] || [ -e "$act_git_dir/harness-adt-activation.error" ]; }; then
    set +e
    act_out="$(PYTHONIOENCODING=utf-8 uv run --no-project python "$hook_dir/activation_gate.py" check "$(pwd)" 2>&1)"
    act_rc=$?
    set -e
    if [ "$act_rc" -ne 0 ]; then
      act_out="$(printf '%s' "$act_out" | tr -d '\r')"
      if [ "$act_rc" -ne 1 ]; then
        act_out="활성화 관문을 실행하지 못해(종료코드 $act_rc) 활성화 성공을 확인할 수 없습니다(검사 불능). 확인되지 않는 상태로 통과시키지 않습니다. 사유: $act_out 다음: uv 가 있는지 확인하고 같은 명령을 다시 시도하십시오. $next_install_uv"
      fi
      printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' \
        "$(printf '%s' "푸시를 막습니다. $act_out" | jq -Rs .)"
      exit 0
    fi
  fi
fi

# 2-3) 작성자가 지금 gh 로그인 계정과 다른 PR 의 브랜치로 가는 푸시를 거부한다(#150).
#      DELIVER=1 로 통과할 푸시에만 건다(선언 없는 푸시는 아래 4) 에서 어차피 거부된다).
#      푸시 대상은 refspec 의 도착 쪽(없으면 HEAD 의 현재 브랜치)이고, 그 브랜치에 열린
#      PR 이 없으면 통과한다. 대상 브랜치나 gh 조회를 확정하지 못하면 검사 불능으로 거부한다.
#      -R 이 푸시엔 없으므로 현재 저장소 기준이다. --head 는 브랜치 이름만 맞추므로 포크의
#      같은 이름 브랜치 PR 도 걸릴 수 있다(보수적인 쪽).
#      조각마다 push 를 찾으므로 앞에 다른 git 명령이 붙어도 본다. 최종 방어선은 Actions 의
#      사후 알림이다.
check_push_authors() {
  pa_branches=()
  pa_unresolved=""
  pa_i=0
  while [ "$pa_i" -lt "$scan_n" ]; do
    pa_seg="${scan_segs[$pa_i]}"
    pa_sub="${scan_subs[$pa_i]}"
    pa_i=$((pa_i + 1))
    [ "$pa_sub" = "push" ] || continue
    pa_after=0
    pa_skip=0
    pa_pos=()
    set -f
    for tok in $pa_seg; do
      tok="${tok#\"}"; tok="${tok%\"}"
      tok="${tok#\'}"; tok="${tok%\'}"
      if [ "$pa_after" -eq 0 ]; then
        [ "$tok" = "push" ] && pa_after=1
        continue
      fi
      if [ "$pa_skip" -eq 1 ]; then pa_skip=0; continue; fi
      case "$tok" in
        --repo|-o|--push-option|--receive-pack|--exec) pa_skip=1 ;;
        --all|--mirror) pa_unresolved="--all/--mirror 로 모든 브랜치를 한꺼번에 푸시" ;;
        -*) : ;;
        *) pa_pos+=("$tok") ;;
      esac
    done
    set +f
    # 첫 위치 인자는 원격 이름이고 나머지가 refspec 이다. refspec 이 없으면 현재 브랜치.
    pa_specs=()
    if [ "${#pa_pos[@]}" -gt 1 ]; then pa_specs=("${pa_pos[@]:1}"); fi
    if [ "${#pa_specs[@]}" -eq 0 ]; then pa_specs=("HEAD"); fi
    for spec in "${pa_specs[@]}"; do
      spec="${spec#+}"
      dst="${spec##*:}"
      dst="${dst#refs/heads/}"
      case "$dst" in
        refs/*) continue ;; # 태그 등 브랜치가 아닌 대상
        Q|'') pa_unresolved="푸시 대상을 읽을 수 없는 refspec 이 있음"; continue ;;
        HEAD)
          dst="$(git symbolic-ref --short -q HEAD 2>/dev/null | tr -d '\r' || true)"
          if [ -z "$dst" ]; then pa_unresolved="HEAD 가 브랜치가 아님(detached)"; continue; fi
          ;;
      esac
      pa_branches+=("$dst")
    done
  done

  if [ -n "$pa_unresolved" ]; then
    deny "검사 불능: 푸시할 브랜치를 확정하지 못했습니다($pa_unresolved). 그 브랜치에 다른 계정이 만든 PR 이 있는지 확인할 수 없어 통과시키지 않습니다. 다음: Claude 가 브랜치 이름을 적어(예: git push -u origin 브랜치이름) 한 브랜치씩 다시 푸시하십시오."
  fi
  [ "${#pa_branches[@]}" -eq 0 ] && return 0

  get_login_now
  for br in "${pa_branches[@]}"; do
    # 명령에서 온 값이 deny 문구에 들어가므로 " \ 백틱 $ 를 지운 사본을 문구에 쓴다.
    br_safe="$(printf '%s' "$br" | tr -d '"\\`$')"
    set +e
    pa_authors="$(${gh_tcmd[@]+"${gh_tcmd[@]}"} gh pr list --head "$br" --state open --json author --jq '.[].author.login' 2>/dev/null)"
    pa_rc=$?
    set -e
    if [ "$pa_rc" -ne 0 ]; then
      deny "검사 불능: 브랜치 $br_safe 에 열린 PR 이 있는지 gh 로 확인하지 못했습니다(종료코드 $pa_rc). 다른 계정의 PR 인지 알 수 없어 통과시키지 않습니다. $next_retry"
    fi
    pa_authors="$(printf '%s' "$pa_authors" | tr -d '\r"\\`$')"
    while IFS= read -r pa_author; do
      pa_author="$(printf '%s' "$pa_author" | tr -d ' ')"
      [ -z "$pa_author" ] && continue
      pa_author_lc="$(printf '%s' "$pa_author" | tr '[:upper:]' '[:lower:]')"
      if [ "$pa_author_lc" != "$login_now" ] && ! viewer_is_admin ""; then
        deny "브랜치 $br_safe 에는 작성자 $pa_author 의 열린 PR 이 있고 지금 gh 로그인 계정은 $login_now 입니다. admin 권한이 있는 계정만 남의 PR 을 고칠 수 있는데 이 계정은 admin 이 아닙니다. 다른 계정이 만든 PR 의 브랜치로는 푸시하지 않습니다. 다음: 푸시하지 말고, 내 작업이 그 PR 에 주는 영향(충돌, 같은 파일, 검사 결과 변화)만 사용자에게 알리십시오. 내 작업은 새 브랜치에서 이어 가십시오."
      fi
    done <<EOF
$pa_authors
EOF
  done
}

# 3) /harness:deliver 스킬이 절차를 따르고 있다는 선언이면 여기서 통과시킨다.
#    위의 두 검사를 지난 뒤라 강제 푸시와 main 커밋은 이미 걸러져 있다.
#    선언은 낱말 DELIVER=1 로 시작할 때만 인정한다(DELIVER=10, DELIVER=1foo 는 아니다). 선언이
#    명령 맨 앞에 있으면 그 명령 전체(묶인 뒤쪽 푸시 포함)에 적용된다.
#
#    따옴표를 해석할 수 없어(래퍼 안, 닫히지 않은 따옴표) 푸시 여부나 푸시 대상을 확정하지 못하면
#    선언이 있어도 통과시키지 않는다(원칙 7).
if [ "$opaque_push" -eq 1 ]; then
  deny "검사 불능: 따옴표를 해석할 수 없어 푸시 여부를 판정하지 못했습니다. 명령에 따옴표 문자열을 다시 실행하는 부분(bash -c, eval, ssh 등)이나 닫히지 않은 따옴표가 있고 git 과 push 낱말이 함께 있습니다. 푸시일 수 있어 통과시키지 않습니다. 다음: Claude 가 푸시를 따옴표나 래퍼 없이 별도 명령으로 풀어 다시 실행하십시오. 푸시는 /harness:deliver 가 수행하고, 그 절차를 따르는 중이면 명령 앞에 DELIVER=1 을 붙이십시오."
fi
if [[ "$cmd" =~ ^DELIVER=1[[:space:]] ]]; then
  # 첫 git 하위 명령이 push 가 아니어도(DELIVER=1 git status && git push ...) 조각마다
  # push 를 찾아 본다. push 조각이 없으면 gh 를 부르지 않는다.
  check_push_authors
  finish_ok
fi

# 4) 스킬을 거치지 않은 푸시를 거부한다.
if [ "$push_found" -eq 1 ]; then
  deny "푸시는 /harness:deliver 스킬이 수행합니다. /harness:deliver 는 커밋과 fetch 와 rebase 와 푸시와 PR 생성을 한 번에 처리합니다. 다음: /harness:deliver 를 실행하십시오. 이미 그 스킬 절차를 따르는 중이라면 명령 앞에 DELIVER=1 을 붙여 다시 실행하십시오."
fi

finish_ok
