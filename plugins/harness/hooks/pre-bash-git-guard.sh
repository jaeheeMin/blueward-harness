#!/usr/bin/env bash
set -euo pipefail

input="$(cat)"

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
next_install_uv="다음: 사람이 할 일 - PowerShell 에서 winget install --id astral-sh.uv -e 를 실행해 uv 를 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오."
next_install_gh="다음: 사람이 할 일 - PowerShell 에서 winget install --id GitHub.cli -e 로 GitHub CLI 를 설치하고 gh auth login 으로 로그인한 뒤 Claude Code 를 새 터미널에서 다시 여십시오."
next_retry="다음: 네트워크를 확인하고 잠시 뒤 같은 명령을 다시 시도하십시오. gh auth status 가 로그인 안 됨을 보이면 사람이 gh auth login 을 실행해야 합니다. 계속되면 이 메시지 전체를 붙여 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오."

if ! command -v jq >/dev/null 2>&1; then
  # 판단할 수 없을 때 통과시키지 않는다. 통과시키면 정확히 이 상황에서
  # 보호가 사라진다. 다만 검사 대상이 git 명령이나 `gh pr merge` 이므로
  # 그 밖의 명령은 막지 않는다. `gh pr merge` 도 여기 넣은 이유는 아래
  # PRD 승인 검사가 이 훅 안에서 jq 로 결과를 읽기 때문이다(#49).
  case "$input" in
    *git*|*"pr merge"*)
      deny "jq 가 없어 git/gh 명령을 검사하지 못했습니다. 검사할 수 없는 상태로 통과시키지 않습니다. 다음: 사람이 할 일 - PowerShell 에서 winget install --id jqlang.jq -e 를 실행해 jq 를 설치한 뒤 Claude Code 를 새 터미널에서 다시 여십시오(macOS 는 brew install jq)."
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
  set -f
  found=0
  skip_next=0
  for tok in $1; do
    # 셸이 벗겨 줄 따옴표가 문자열에는 남아 있으므로 여기서 벗긴다.
    tok="${tok#\"}"; tok="${tok%\"}"
    tok="${tok#\'}"; tok="${tok%\'}"
    if [ "$skip_next" -eq 1 ]; then skip_next=0; continue; fi
    if [ "$found" -eq 0 ]; then
      # Windows 는 `git.exe` 로 부르고 경로 구분자로 `\` 를 쓴다. `/` 와 `\`
      # 양쪽 기준으로 마지막 경로 성분을 떼어 내고, 대소문자와 `.exe` 확장자
      # 차이를 없앤 뒤에 git 인지 비교한다. bash 3.2 호환을 위해 `${var,,}`
      # 대신 tr 을 쓴다.
      base="${tok##*/}"
      base="${base##*\\}"
      base="$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')"
      case "$base" in
        *.exe) base="${base%.exe}" ;;
      esac
      case "$base" in
        git) found=1 ;;
      esac
      continue
    fi
    case "$tok" in
      -C|-c) skip_next=1 ;;
      -*) : ;;
      *) set +f; printf '%s' "$tok"; return 0 ;;
    esac
  done
  set +f
  return 0
}

sub="$(git_subcommand "$cmd")"

# 0) gh pr merge 대상 PR 이 PRD(docs/ssot/) 를 바꿨는데 승인이 없으면 거부한다
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
engine="${DOC_GUARD_ENGINE:-git+https://github.com/jaeheeMin/blueward-harness@main}"

# merge 한 건을 검사한다. $1=저장소(-R, 없으면 빈 값), $2=PR 지정(번호·URL·브랜치,
# 없으면 빈 값). deny() 는 exit 하므로 여러 건 중 하나라도 걸리면 명령 전체가
# 거부된다.
check_one_merge() {
  repo="$1"
  prref="$2"

  # URL 형태(.../pull/123)면 번호와 저장소를 URL 에서 바로 뽑는다.
  case "$prref" in
    */pull/*)
      pr_number="${prref##*/pull/}"
      pr_number="${pr_number%%/*}"
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
    deny "gh 가 없어 이 PR 이 PRD(docs/ssot) 를 바꿨는지, 승인이 있는지 확인할 수 없습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. $next_install_gh"
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
    deny "gh pr merge 의 대상 PR 을 확인하지 못해 PRD 승인 여부를 판정할 수 없습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. 다음: Claude 가 PR 번호를 붙여(예: gh pr merge 123) 다시 실행하십시오. 그래도 안 되면 gh auth status 로 로그인 상태를 확인하고, 로그인 안 됨이면 사람이 gh auth login 을 실행하십시오."
  fi

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
  ck_out="$(gh pr checks "$pr_number" -R "$repo" --json name,state,bucket,link 2>"$ck_err_file")"
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
    ck_fail_names="$(printf '%s' "$ck_out" | jq -r '[.[] | select(.bucket == "fail" or .bucket == "cancel") | .name] | .[:5] | join(", ")' 2>/dev/null | tr -d '\r"\\`$')" || true
    ck_fail_total="$(printf '%s' "$ck_out" | jq -r '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length' 2>/dev/null | tr -d '\r')" || true
    ck_fail_link="$(printf '%s' "$ck_out" | jq -r '[.[] | select(.bucket == "fail" or .bucket == "cancel") | .link // empty] | .[0] // empty' 2>/dev/null | tr -d '\r"\\`$ ')" || true
    ck_wait_names="$(printf '%s' "$ck_out" | jq -r '[.[] | select(.bucket != "pass" and .bucket != "skipping" and .bucket != "fail" and .bucket != "cancel") | .name] | .[:5] | join(", ")' 2>/dev/null | tr -d '\r"\\`$')" || true
    ck_wait_total="$(printf '%s' "$ck_out" | jq -r '[.[] | select(.bucket != "pass" and .bucket != "skipping" and .bucket != "fail" and .bucket != "cancel")] | length' 2>/dev/null | tr -d '\r')" || true
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

  if ! command -v uvx >/dev/null 2>&1; then
    deny "uvx 가 없어 PRD 승인 여부를 확인하지 못했습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. $next_install_uv"
  fi

  # stdout 과 stderr 를 나눠 받는다(#63). uv 가 엔진을 캐시 없이 새로 빌드할 때
  # "Building doc-guard-checker ...", "Installed N packages ..." 같은 진행
  # 로그를 stderr 로 낸다. 예전에는 `2>&1` 로 합쳐 받아 그 로그가 JSON 앞뒤에
  # 섞여 들어왔고, 판정 자체는 정상(종료코드 0, touches_ssot: false)인데도
  # 아래 jq 해석이 실패해 "확인하지 못해 merge 를 막습니다" 로 잘못 거절했다.
  # 이제 JSON 해석은 stdout 만으로 하고, stderr 는 실패했을 때 사람에게 보여줄
  # "자세히" 로만 쓴다.
  ssot_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 의 PRD 승인 여부를 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
  }
  trap 'rm -f "$ssot_err_file"' EXIT

  set +e
  ssot_out="$(uvx --from "$engine" python -m checker.ssot_approval check-pr --repo "$repo" --pr "$pr_number" 2>"$ssot_err_file")"
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
    : # PRD 를 안 바꿨거나 이미 승인됐다. 통과시키고 나머지 검사를 계속한다.
  elif [ "$ssot_json_ok" -eq 1 ] && [ "$ssot_rc" -eq 1 ]; then
    reason="$(printf '%s' "$ssot_out" | jq -r '.reason // empty' 2>/dev/null)" || true
    deny "PRD(docs/ssot) 를 바꾼 PR #$pr_number 인데 작성자가 아닌 승인자의 Approve 가 없어 merge 를 막습니다. 사유: $reason 다음: 사람이 할 일 - .github/ssot-approvers 에 적힌 승인자(PR 작성자가 아닌 사람)에게 이 PR 의 리뷰에서 Approve 를 요청하십시오. Approve 가 달린 뒤 Claude 가 gh pr merge 를 다시 실행합니다."
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
    detail="$(printf '%s' "$detail_raw" | tr -d '"\\' | tr '\n' ' ' | cut -c1-300)"
    deny "PR #$pr_number 의 PRD 승인 여부를 확인하지 못해 merge 를 막습니다(종료코드 $ssot_rc). 확인되지 않는 상태로 통과시키지 않습니다. $next_retry 자세히: $detail"
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
  hm_out="$(uvx --from "$engine" python -m checker.ssot_approval check-human-merge --repo "$repo" --pr "$pr_number" 2>"$hm_err_file")"
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
    deny "PR #$pr_number 은 사람이 직접 merge 해야 하는 경로($hm_paths)를 바꿨습니다. Claude 는 이 PR 을 merge 할 수 없습니다. 다음: 사람이 할 일 - 사용자에게 이 PR 의 GitHub 화면(PR 페이지 아래쪽)에서 Merge 버튼을 눌러 병합해 달라고 요청하십시오."
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
    hm_detail="$(printf '%s' "$hm_detail_raw" | tr -d '"\\' | tr '\n' ' ' | cut -c1-300)"
    deny "PR #$pr_number 가 사람이 merge 해야 하는 경로를 바꿨는지 확인하지 못해 merge 를 막습니다(종료코드 $hm_rc). 확인되지 않는 상태로 통과시키지 않습니다. $next_retry 자세히: $hm_detail"
  fi
}

# 첫 관문: `pr merge` 글자가 명령에 없으면 merge 일 수 없으므로 엔진을 부르지
# 않는다. 일반 명령마다 uvx 를 띄우면 느려서 사람들이 훅을 끄게 된다.
case "$cmd" in
  *"pr merge"*)
    if ! command -v uvx >/dev/null 2>&1; then
      deny "uvx 가 없어 이 명령이 gh pr merge 인지, PRD 승인이 있는지 확인하지 못했습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다. $next_install_uv"
    fi
    mc_err_file="$(mktemp 2>/dev/null)" || {
      deny "임시 파일을 만들지 못해 이 명령이 gh pr merge 인지 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오. 계속되면 사람이 TEMP 폴더의 빈 공간과 쓰기 권한을 확인하십시오."
    }
    set +e
    mc_out="$(printf '%s' "$cmd" | uvx --from "$engine" python -m checker.merge_command 2>"$mc_err_file")"
    mc_rc=$?
    set -e
    mc_err="$(cat "$mc_err_file" 2>/dev/null)" || mc_err=""
    rm -f "$mc_err_file"

    if ! printf '%s' "$mc_out" | jq -e . >/dev/null 2>&1; then
      mc_detail="$(printf '%s\n%s' "$mc_out" "$mc_err" | tr -d '"\\' | tr '\n' ' ' | cut -c1-300)"
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
    mc_lines="$(printf '%s' "$mc_out" | jq -r '.merges[] | [((.repo // "") | if . == "" then "-" else . end), ((.prref // "") | if . == "" then "-" else . end)] | join(" ")' | tr -d '\r')"
    while IFS=' ' read -r mc_repo mc_prref; do
      [ -z "$mc_repo" ] && continue
      [ "$mc_repo" = "-" ] && mc_repo=""
      [ "$mc_prref" = "-" ] && mc_prref=""
      check_one_merge "$mc_repo" "$mc_prref"
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
if [ "$sub" = "push" ] && [[ "$cmd" =~ (^|[[:space:]])(-[a-zA-Z]*f[a-zA-Z]*|--force)([[:space:]]|$) ]]; then
  deny "git push --force 는 이 저장소에서 금지되어 있습니다. 다음: --force 를 빼고 /harness:deliver 를 실행하십시오. 리베이스로 이력이 바뀐 경우의 --force-with-lease 푸시도 /harness:deliver 가 수행합니다."
fi

# 2) main 에서의 커밋도 선언 접두어와 무관하게 거부한다. 브랜치 규칙은
#    /harness:deliver 의 절차가 아니라 이 저장소의 전제이기 때문이다.
if [ "$sub" = "commit" ]; then
  branch="$(git symbolic-ref --short -q HEAD || echo 알수없음)"
  if [ "$branch" = "main" ]; then
    deny "main 브랜치에는 직접 커밋할 수 없습니다. 다음: /harness:start 를 실행해 이슈를 만들고 규칙에 맞는 브랜치로 옮긴 뒤 그 브랜치에서 다시 커밋하십시오."
  fi
fi

# 3) /harness:deliver 스킬이 절차를 따르고 있다는 선언이면 여기서 통과시킨다.
#    위의 두 검사를 지난 뒤라 강제 푸시와 main 커밋은 이미 걸러져 있다.
case "$cmd" in
  DELIVER=1*)
    exit 0
    ;;
esac

# 4) 스킬을 거치지 않은 푸시를 거부한다.
if [ "$sub" = "push" ]; then
  deny "푸시는 /harness:deliver 스킬이 수행합니다. /harness:deliver 는 커밋과 fetch 와 rebase 와 푸시와 PR 생성을 한 번에 처리합니다. 다음: /harness:deliver 를 실행하십시오. 이미 그 스킬 절차를 따르는 중이라면 명령 앞에 DELIVER=1 을 붙여 다시 실행하십시오."
fi

exit 0
