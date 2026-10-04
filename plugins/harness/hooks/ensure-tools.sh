#!/usr/bin/env bash
# 세션 시작 때 harness Hook 이 쓰는 도구(uv, jq, gh, gitleaks)가 있는지 보고, Windows 에서
# 없으면 winget 으로 설치한다(#116). session-start-sync.sh 가 부른다.
#
# - 결과는 stdout 으로 한 줄씩 낸다. 다 있으면 아무것도 내지 않는다.
# - jq 를 쓰지 않는다(jq 자체를 설치하는 스크립트라서).
# - 어떤 경우에도 0 으로 끝난다. 이 스크립트가 세션 시작을 막아선 안 된다.
# - 설치했다고 말하기 전에 실행 파일이 실제로 생겼는지 확인한다.
# - 같은 실패를 세션마다 되풀이하지 않도록 실패를 기록하고 24시간 건너뛴다.
#
# 환경 변수
#   HARNESS_NO_AUTO_INSTALL=1  설치하지 않고 안내만 한다
#   HARNESS_FAKE_UNAME         (테스트용) uname -s 결과를 대신한다
#   HARNESS_TOOLS_BUDGET       (기본 300) 이 스크립트 전체가 설치에 쓸 수 있는 초. 넘기면 남은
#                              설치를 건너뛰고 다음 세션에 다시 시도하라고 알린다(#131)
#   HARNESS_INSTALL_TIMEOUT    (기본 90) winget 한 번이 기다릴 수 있는 초
#   CLAUDE_PLUGIN_DATA         실패 기록을 둘 폴더(기본 $HOME/.claude/harness)

set +e

RETRY_SECONDS=86400
INSTALL_TIMEOUT="${HARNESS_INSTALL_TIMEOUT:-90}"
# 훅 전체 제한(600초) 안에서 동기화와 경고 전달이 돌 수 있게 설치에 쓰는 시간을 묶는다(#131).
# 최악: 설치 상한 300초 + gh auth status 15초 = 315초.
TOOLS_BUDGET="${HARNESS_TOOLS_BUDGET:-300}"
AUTH_TIMEOUT=15
case "$INSTALL_TIMEOUT" in '' | *[!0-9]*) INSTALL_TIMEOUT=90 ;; esac
case "$TOOLS_BUDGET" in '' | *[!0-9]*) TOOLS_BUDGET=300 ;; esac

# 이 스크립트는 예기치 않은 상태에서도 Hook 을 죽이지 않는다.
uname_s="${HARNESS_FAKE_UNAME:-$(uname -s 2>/dev/null || echo unknown)}"
case "$uname_s" in
  MINGW* | MSYS* | CYGWIN*) is_windows=1 ;;
  *) is_windows=0 ;;
esac

to_unix_path() {
  local p="$1"
  [ -z "$p" ] && return 0
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$p" 2>/dev/null || printf '%s' "$p"
  else
    printf '%s' "$p" | tr '\\' '/'
  fi
}

local_app_data="$(to_unix_path "${LOCALAPPDATA:-$HOME/AppData/Local}")"
# HARNESS_PROGRAMFILES 는 테스트용: Windows 에서는 PROGRAMFILES 를 덮어쓸 수 없다.
program_files="$(to_unix_path "${HARNESS_PROGRAMFILES:-${PROGRAMFILES:-C:/Program Files}}")"
state_dir="$(to_unix_path "${CLAUDE_PLUGIN_DATA:-$HOME/.claude/harness}")"
state_file="$state_dir/tool-install-failures"

have_timeout=0
if command -v timeout >/dev/null 2>&1; then
  have_timeout=1
fi

# 남은 설치 시간(초). SECONDS 는 이 셸이 시작한 뒤 흐른 초다.
budget_left() {
  echo "$((TOOLS_BUDGET - SECONDS))"
}
budget_hit=0

winget_bin=""
if [ "$is_windows" = "1" ]; then
  if command -v winget >/dev/null 2>&1; then
    winget_bin="winget"
  elif command -v winget.exe >/dev/null 2>&1; then
    winget_bin="winget.exe"
  elif [ -f "$local_app_data/Microsoft/WindowsApps/winget.exe" ]; then
    winget_bin="$local_app_data/Microsoft/WindowsApps/winget.exe"
  elif [ -f "$local_app_data/Microsoft/WindowsApps/winget" ]; then
    winget_bin="$local_app_data/Microsoft/WindowsApps/winget"
  fi
fi

winget_id() {
  case "$1" in
    uv) echo "astral-sh.uv" ;;
    jq) echo "jqlang.jq" ;;
    gh) echo "GitHub.cli" ;;
    gitleaks) echo "Gitleaks.Gitleaks" ;;
  esac
}

# 결과: found_where = path(이 세션 PATH 에 있음) | elsewhere(설치돼 있으나 PATH 밖) | none
#       found_bin   = 실행할 수 있는 경로
locate_tool() {
  local tool="$1" id d
  id="$(winget_id "$tool")"
  found_where="none"
  found_bin=""
  if command -v "$tool" >/dev/null 2>&1; then
    found_where="path"
    found_bin="$tool"
    return 0
  fi
  for d in \
    "$local_app_data/Microsoft/WinGet/Links" \
    "$local_app_data"/Microsoft/WinGet/Packages/"${id}"_* \
    "$program_files/GitHub CLI"; do
    if [ -f "$d/$tool.exe" ]; then
      found_where="elsewhere"
      found_bin="$d/$tool.exe"
      return 0
    fi
  done
  return 0
}

recent_failure() {
  local tool="$1" t ts now
  [ -f "$state_file" ] || return 1
  now="$(date +%s 2>/dev/null || echo 0)"
  while read -r t ts; do
    ts="$(printf '%s' "$ts" | tr -d '')"
    # 숫자가 아니면 건너뛴다. 산술식에 넣으면 스크립트 전체가 죽는다.
    case "$ts" in '' | *[!0-9]*) continue ;; esac
    if [ "$t" = "$tool" ] && [ "$((now - ts))" -lt "$RETRY_SECONDS" ]; then
      return 0
    fi
  done < "$state_file"
  return 1
}

clear_failure() {
  local tool="$1"
  [ -f "$state_file" ] || return 0
  grep -v "^$tool " "$state_file" > "$state_file.tmp" 2>/dev/null
  mv -f "$state_file.tmp" "$state_file" 2>/dev/null
  return 0
}

record_failure() {
  local tool="$1"
  mkdir -p "$state_dir" 2>/dev/null || return 0
  clear_failure "$tool"
  printf '%s %s\n' "$tool" "$(date +%s 2>/dev/null || echo 0)" >> "$state_file" 2>/dev/null
  return 0
}

winget_try() {
  # 인자: 도구 id, 추가 옵션...
  local id="$1" limit left
  shift
  limit="$INSTALL_TIMEOUT"
  left="$(budget_left)"
  # 전체 상한이 한 번의 대기보다 적게 남았으면 그만큼만 기다린다. 이때 시간 초과는
  # 설치가 실패한 것이 아니라 상한에 걸린 것이므로 실패 기록에 넣지 않는다.
  budget_hit=0
  if [ "$left" -lt "$limit" ]; then
    limit="$left"
    budget_hit=1
  fi
  [ "$limit" -lt 1 ] && limit=1
  local -a tcmd=()
  [ "$have_timeout" = "1" ] && tcmd=(timeout "$limit")
  "${tcmd[@]}" "$winget_bin" install --id "$id" -e --silent \
    --accept-package-agreements --accept-source-agreements --disable-interactivity \
    "$@" < /dev/null > /dev/null 2>&1
}

manual_cmd() {
  echo "PowerShell 에서 winget install --id $(winget_id "$1") -e"
}

say() {
  printf '%s\n' "$1"
}

missing_for_brew=""
gh_bin=""

for tool in uv jq gh gitleaks; do
  id="$(winget_id "$tool")"
  locate_tool "$tool"

  case "$found_where" in
    path)
      ;;
    elsewhere)
      say "$tool 는 설치돼 있지만 이 세션이 아직 못 찾습니다. 다음: Claude Code 를 새로 여십시오."
      ;;
    none)
      if [ "$is_windows" != "1" ]; then
        missing_for_brew="$missing_for_brew $tool"
      elif [ -z "$winget_bin" ]; then
        say "$tool 가 없고 winget 도 찾지 못해 자동으로 설치하지 못했습니다. 다음: 사람이 할 일 - $(manual_cmd "$tool") 로 설치한 뒤 Claude Code 를 새로 여십시오(winget 이 없으면 Microsoft Store 의 '앱 설치 관리자' 를 먼저 설치)."
      elif [ "${HARNESS_NO_AUTO_INSTALL:-}" = "1" ]; then
        say "$tool 가 없습니다. HARNESS_NO_AUTO_INSTALL=1 이라 자동으로 설치하지 않았습니다. 다음: 사람이 할 일 - $(manual_cmd "$tool") 로 설치한 뒤 Claude Code 를 새로 여십시오."
      elif recent_failure "$tool"; then
        say "$tool 가 없습니다. 최근에 자동 설치가 실패해 24시간 동안 다시 시도하지 않습니다. 다음: 사람이 할 일 - $(manual_cmd "$tool") 로 설치한 뒤 Claude Code 를 새로 여십시오."
      elif [ "$(budget_left)" -le 0 ]; then
        say "$tool 가 없지만 도구 설치에 쓸 시간(${TOOLS_BUDGET}초)을 넘겨 설치하지 않았습니다. 다음: 다음 세션을 열면 자동으로 다시 시도합니다. 급하면 사람이 할 일 - $(manual_cmd "$tool") 로 설치한 뒤 Claude Code 를 새로 여십시오."
      else
        ok=0
        over=0
        if [ "$tool" = "gh" ]; then
          winget_try "$id"
          rc=$?
          locate_tool "$tool"
          [ "$found_where" != "none" ] && ok=1
        else
          winget_try "$id" --scope user
          rc=$?
          locate_tool "$tool"
          if [ "$found_where" != "none" ]; then
            ok=1
          elif [ "$rc" = "124" ] && [ "$budget_hit" = "1" ]; then
            over=1
          elif [ "$(budget_left)" -le 0 ]; then
            over=1
          else
            winget_try "$id"
            rc=$?
            locate_tool "$tool"
            [ "$found_where" != "none" ] && ok=1
          fi
        fi
        if [ "$ok" = "1" ]; then
          clear_failure "$tool"
          if [ "$found_where" = "path" ]; then
            say "$tool 가 없어 winget 으로 설치했습니다."
          else
            say "$tool 가 없어 winget 으로 설치했습니다. 다음: 이 세션은 새 프로그램을 아직 못 찾으니 Claude Code 를 새로 여십시오."
          fi
        elif [ "$over" = "1" ] || { [ "$rc" = "124" ] && [ "$budget_hit" = "1" ]; }; then
          # 상한에 걸린 것은 실패가 아니라 미완료다. 기록하지 않아 다음 세션에 바로 다시 시도한다.
          say "$tool 설치가 도구 설치 시간 상한(${TOOLS_BUDGET}초)에 걸려 끝나지 않았습니다. 설치됐는지 판단하지 못했습니다. 다음: 다음 세션을 열면 자동으로 다시 시도합니다. 급하면 사람이 할 일 - $(manual_cmd "$tool") 로 설치한 뒤 Claude Code 를 새로 여십시오."
        else
          record_failure "$tool"
          if [ "$rc" = "124" ]; then
            reason="시간 초과"
          else
            reason="winget 종료 코드 $rc, 실행 파일이 생기지 않음"
          fi
          say "$tool 를 winget 으로 설치하지 못했습니다($reason). 권한이나 회사 정책에 막혔을 수 있습니다. 다음: 사람이 할 일 - $(manual_cmd "$tool") 를 직접 실행한 뒤 Claude Code 를 새로 여십시오. 24시간 동안은 자동 설치를 다시 시도하지 않습니다."
        fi
      fi
      ;;
  esac

  if [ "$tool" = "gh" ]; then
    locate_tool gh
    gh_bin="$found_bin"
  fi
done

if [ -n "$missing_for_brew" ]; then
  say "이 컴퓨터는 Windows 가 아니라 자동으로 설치하지 않습니다. 없는 도구:$missing_for_brew. 다음: 사람이 할 일 - 터미널에서 brew install$missing_for_brew 를 실행한 뒤 Claude Code 를 새로 여십시오."
fi

if [ -n "$gh_bin" ]; then
  tcmd=()
  [ "$have_timeout" = "1" ] && tcmd=(timeout "$AUTH_TIMEOUT")
  if ! "${tcmd[@]}" "$gh_bin" auth status < /dev/null > /dev/null 2>&1; then
    say "gh 에 GitHub 로그인이 되어 있지 않습니다. 다음: 사람이 할 일 - gh auth login 을 실행해 GitHub 에 로그인하십시오."
  fi
fi

exit 0
