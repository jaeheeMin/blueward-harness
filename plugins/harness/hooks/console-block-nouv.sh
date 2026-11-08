#!/usr/bin/env bash
# uv 가 없어 검사 훅을 실행하지 못했을 때(hooks.json 의 폴백) 그 사실을 웹 콘솔에 알린다(#765).
#
# console_block.py 는 uv 로 python 을 띄우는데 지금은 uv 가 없는 경우라 쓸 수 없다. 그래서 bash 의 /dev/tcp 로
# 같은 주소(127.0.0.1:<HARNESS_CONSOLE_PORT 또는 4873>/hooks/blocked)에 같은 본문을 보낸다.
# "검사하지 못했다" 사유라 콘솔은 ? 확인 못 함 카드로 그린다(막힘이 아니다. CLAUDE.md 7번).
#
# 사용: printf '%s' "$훅_입력_JSON" | bash console-block-nouv.sh <훅 이름> <사유>
# 보고는 부가 기능이다. 콘솔이 없거나 실패해도 아무것도 출력하지 않고 종료코드 0 으로 끝난다.
# 사유 문자열에는 큰따옴표와 역슬래시를 쓰지 않는다(JSON 에 그대로 끼운다).

hook="${1:-}"
reason="${2:-}"
input="$(head -c 4194304 2>/dev/null)" || input=""
[ -n "$hook" ] && [ -n "$reason" ] || exit 0

# 훅 입력 JSON 에서 문자열 값을 이스케이프된 채로 뽑는다(jq 가 없을 수 있다). 없으면 빈 문자열.
field() {
  printf '%s' "$input" | tr -d '\r\n' | sed -nE 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\1/p' | head -n1
}

session_id="$(field session_id)"
[ -n "$session_id" ] || exit 0  # 어느 세션인지 모르면 보낼 곳이 없다

body="{\"hook_event_name\":\"HarnessBlocked\",\"hook\":\"${hook}\",\"reason\":\"${reason}\",\"session_id\":\"${session_id}\""
for key in tool_use_id tool_name cwd; do
  value="$(field "$key")"
  [ -n "$value" ] && body="${body},\"${key}\":\"${value}\""
done
body="${body}}"

port="${HARNESS_CONSOLE_PORT:-4873}"
case "$port" in '' | *[!0-9]*) port=4873 ;; esac

send() {
  local len line
  len="$(printf '%s' "$body" | LC_ALL=C wc -c | tr -d ' \r')"  # 바이트 수
  exec 3<>"/dev/tcp/127.0.0.1/${port}" || return 0
  printf 'POST /hooks/blocked HTTP/1.1\r\nHost: 127.0.0.1:%s\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\n\r\n%s' \
    "$port" "$len" "$body" >&3 || return 0
  IFS= read -r -t 2 line <&3 || true  # 응답을 받아야 서버가 본문을 처리하기 전에 연결을 끊지 않는다
  exec 3>&- 3<&-
  return 0
}

if timeout --version >/dev/null 2>&1; then  # Windows 기본 timeout.exe 가 잡히면 --version 이 실패한다 — 그땐 제한 없이 보낸다
  export body port
  timeout 6 bash -c "$(declare -f send); send" >/dev/null 2>&1 || true
else
  (send) >/dev/null 2>&1 || true
fi
exit 0
