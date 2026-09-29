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

if ! command -v jq >/dev/null 2>&1; then
  # 판단할 수 없을 때 통과시키지 않는다. 통과시키면 정확히 이 상황에서
  # 보호가 사라진다. 다만 검사 대상이 git 명령이나 `gh pr merge` 이므로
  # 그 밖의 명령은 막지 않는다. `gh pr merge` 도 여기 넣은 이유는 아래
  # PRD 승인 검사가 이 훅 안에서 jq 로 결과를 읽기 때문이다(#49).
  case "$input" in
    *git*|*"pr merge"*)
      deny "jq 가 없어 git/gh 명령을 검사하지 못했습니다. 검사할 수 없는 상태로 통과시키지 않습니다. jq 를 설치한 뒤 다시 시도하십시오."
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
  deny "훅이 입력을 해석하지 못해 이 명령을 검사할 수 없었습니다. 검사할 수 없는 상태로 통과시키지 않습니다. 저장소 관리자에게 알리십시오."
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
gh_is_pr_merge() {
  set -f
  stage=0  # 0: gh 를 못 찾음, 1: gh 뒤 pr 을 기다림, 2: pr 뒤 merge 를 기다림
  for tok in $1; do
    tok="${tok#\"}"; tok="${tok%\"}"
    tok="${tok#\'}"; tok="${tok%\'}"
    if [ "$stage" -eq 0 ]; then
      base="${tok##*/}"
      base="${base##*\\}"
      base="$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')"
      case "$base" in *.exe) base="${base%.exe}" ;; esac
      case "$base" in gh) stage=1 ;; esac
      continue
    fi
    case "$tok" in
      -*) continue ;;
    esac
    if [ "$stage" -eq 1 ]; then
      if [ "$tok" = "pr" ]; then stage=2; else set +f; return 1; fi
      continue
    fi
    set +f
    [ "$tok" = "merge" ]
    return $?
  done
  set +f
  return 1
}

if gh_is_pr_merge "$cmd"; then
  repo=""
  prref=""
  after_merge=0
  expect=""
  set -f
  for tok in $cmd; do
    tok="${tok#\"}"; tok="${tok%\"}"
    tok="${tok#\'}"; tok="${tok%\'}"
    if [ -n "$expect" ]; then
      case "$expect" in repo) repo="$tok" ;; esac
      expect=""
      continue
    fi
    if [ "$after_merge" -eq 0 ]; then
      case "$tok" in merge) after_merge=1 ;; esac
      continue
    fi
    case "$tok" in
      -R|--repo) expect=repo ;;
      --repo=*) repo="${tok#--repo=}" ;;
      -R=*) repo="${tok#-R=}" ;;
      -*) : ;;
      *) [ -z "$prref" ] && prref="$tok" ;;
    esac
  done
  set +f

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
    deny "gh 가 없어 이 PR 이 PRD(docs/ssot) 를 바꿨는지, 승인이 있는지 확인할 수 없습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다."
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
    deny "gh pr merge 의 대상 PR 을 확인하지 못해 PRD 승인 여부를 판정할 수 없습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다."
  fi

  engine="${DOC_GUARD_ENGINE:-git+https://github.com/jaeheeMin/blueward-harness@main}"
  if ! command -v uvx >/dev/null 2>&1; then
    deny "uvx 가 없어 PRD 승인 여부를 확인하지 못했습니다. 확인되지 않는 상태로 merge 를 허용하지 않습니다."
  fi

  # stdout 과 stderr 를 나눠 받는다(#63). uv 가 엔진을 캐시 없이 새로 빌드할 때
  # "Building doc-guard-checker ...", "Installed N packages ..." 같은 진행
  # 로그를 stderr 로 낸다. 예전에는 `2>&1` 로 합쳐 받아 그 로그가 JSON 앞뒤에
  # 섞여 들어왔고, 판정 자체는 정상(종료코드 0, touches_ssot: false)인데도
  # 아래 jq 해석이 실패해 "확인하지 못해 merge 를 막습니다" 로 잘못 거절했다.
  # 이제 JSON 해석은 stdout 만으로 하고, stderr 는 실패했을 때 사람에게 보여줄
  # "자세히" 로만 쓴다.
  ssot_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 의 PRD 승인 여부를 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다."
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
    deny "PRD(docs/ssot) 를 바꾼 PR #$pr_number 인데 작성자가 아닌 승인자의 Approve 가 없어 merge 를 막습니다. 사유: $reason"
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
    deny "PR #$pr_number 의 PRD 승인 여부를 확인하지 못해 merge 를 막습니다(종료코드 $ssot_rc). 확인되지 않는 상태로 통과시키지 않습니다. 자세히: $detail"
  fi

  # 0-1) Plugin·엔진처럼 사람이 직접 merge 해야 하는 경로(.github/human-merge-paths)
  #      를 바꾼 PR 이면 거부한다(#104). Claude 세션은 소유자의 GitHub 계정으로
  #      동작해 GitHub 가 사람과 구분하지 못하므로, 여기서 Claude 의 `gh pr merge`
  #      만 막고 사람은 GitHub 화면의 Merge 버튼으로 병합한다. 위와 같은 이유로
  #      stdout/stderr 를 나눠 받고, 판정 불가는 통과가 아니라 거부다.
  hm_err_file="$(mktemp 2>/dev/null)" || {
    deny "임시 파일을 만들지 못해 PR #$pr_number 가 사람이 merge 해야 하는 경로를 바꿨는지 확인하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다."
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
    deny "PR #$pr_number 은 사람이 직접 merge 해야 하는 경로($hm_paths)를 바꿨습니다. Claude 는 이 PR 을 merge 할 수 없습니다. 사용자에게 GitHub 화면에서 Merge 버튼으로 병합해 달라고 요청하십시오."
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
    deny "PR #$pr_number 가 사람이 merge 해야 하는 경로를 바꿨는지 확인하지 못해 merge 를 막습니다(종료코드 $hm_rc). 확인되지 않는 상태로 통과시키지 않습니다. 자세히: $hm_detail"
  fi
fi

# 1) 되돌릴 수 없는 강제 푸시는 어떤 경우에도 거부한다. 선언 접두어보다 먼저
#    검사하는 이유는, 접두어가 이 동작까지 열어 주는 문이 되지 않게 하기
#    위해서다. 짧은 옵션은 -f 로도 -uf 로도 묶여 쓰이므로, 붙임표 하나로
#    시작하는 토큰 안에 f 가 있으면 강제로 본다. --force-with-lease 는 붙임표
#    둘로 시작하고 --force 뒤에 공백이 오지 않아 이 패턴에 걸리지 않는다.
if [ "$sub" = "push" ] && [[ "$cmd" =~ (^|[[:space:]])(-[a-zA-Z]*f[a-zA-Z]*|--force)([[:space:]]|$) ]]; then
  deny "git push --force 는 이 저장소에서 금지되어 있습니다. 리베이스로 이력이 바뀐 경우에는 --force-with-lease 를 쓰고, 그 절차는 /harness:deliver 가 수행합니다."
fi

# 2) main 에서의 커밋도 선언 접두어와 무관하게 거부한다. 브랜치 규칙은
#    /harness:deliver 의 절차가 아니라 이 저장소의 전제이기 때문이다.
if [ "$sub" = "commit" ]; then
  branch="$(git symbolic-ref --short -q HEAD || echo 알수없음)"
  if [ "$branch" = "main" ]; then
    deny "main 브랜치에는 직접 커밋할 수 없습니다. /harness:start 를 실행해 이슈를 만들고 규칙에 맞는 브랜치에서 작업하십시오."
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
  deny "푸시는 /harness:deliver 스킬이 수행합니다. /harness:deliver 는 커밋과 fetch 와 rebase 와 푸시와 PR 생성을 한 번에 처리합니다. 스킬 절차를 따르는 중이라면 명령 앞에 DELIVER=1 을 붙이십시오."
fi

exit 0
