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

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

# 종료 코드 0 으로 끝나는 훅의 표준 오류는 디버그 로그로만 가고 사용자 화면에
# 닿지 않는다. 그래서 세션이 끝난 뒤에도 남아야 하는 경고는 화면과 인수인계
# 파일 양쪽에 적는다. 다음 세션의 시작 훅이 이 파일을 읽어 반드시 전한다.
# 경로를 `.git` 으로 적지 않고 물어보는 이유는, 연결된 워크트리에서는 `.git` 이
# 디렉터리가 아니라 파일이어서 그 아래에 쓸 수 없기 때문이다. 파일 이름에
# 저장소 이름을 넣는 이유는, 이 훅이 harness 플러그인으로 여러 저장소에
# 설치되므로 특정 저장소 이름을 하드코딩하지 않기 위해서다.
repo_name="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$resolved_dir")")"
CARRYOVER="$(git rev-parse --git-dir)/${repo_name}-unfinished"

warn() {
  printf '%s\n' "$1"
  printf '%s\n' "$1" >> "$CARRYOVER"
}

# 변경이 없으면 jq 유무와 무관하게 조용히 끝난다. jq 유무 검사를 이 앞에
# 두면 변경이 없어도 매번 경고가 나가 버린다.
# /harness:deliver 가 스테이징에서 빼는 것(.superpowers/, *handoff*.md)은 여기서도
# 세지 않는다(#59). 세면 인계 메모 하나만 남아도 deliver 로 없앨 수 없는
# 경고가 매번 뜬다. 한글 경로는 porcelain 이 따옴표로 감싸므로 따옴표도 허용한다.
# --untracked-files=all 로 파일 단위로 본다. 기본값은 추적 안 된 폴더를 `?? docs/`
# 한 줄로 접어, 그 안에 인계 메모만 있어도 걸러 내지 못한다.
changed="$(git status --porcelain --untracked-files=all | grep -Ev '^.. "?((.*/)?\.superpowers/|.*handoff.*\.md"?$)' || true)"
if [ -z "$changed" ]; then
  exit 0
fi

branch="$(git symbolic-ref --short -q HEAD || echo 알수없음)"

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
