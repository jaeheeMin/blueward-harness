#!/usr/bin/env bash
# gitleaks 로 비밀정보(CR-004)를 검사하고 결과를 세 갈래로 가른다(#159).
#
#   종료 0  clean  비밀값이 없다.
#   종료 1  leak   비밀값이 발견됐다(위반). 값은 --redact 로 가려서 출력한다.
#   종료 1  error  검사를 하지 못했다(검사 불능). 통과도 위반도 아니다(CLAUDE.md 원칙 7).
#
# 종료 코드는 둘 다 1 이라, 구분은 메시지와 GITHUB_OUTPUT 의 `result=clean|leak|error` 로 한다.
# gitleaks 는 유출 때도 오류(fatal) 때도 기본 종료코드가 1 이라 서로 못 가르므로, 유출에만
# `--exit-code 2` 를 지정해 2 는 유출, 0 은 통과, 그 밖(1, 126, 127 등)은 검사 불능으로 본다.
#
# gitleaks 는 존재하지 않는 커밋 범위나 git 저장소가 아닌 폴더에도 "0 commits scanned" 로 종료코드 0 을
# 내므로, 검사 범위와 저장소를 이 스크립트가 먼저 확인한다(그대로 두면 아무것도 보지 않고 통과한다).
#
# 환경 변수
#   EVENT_NAME   pull_request(_*) 또는 push (GitHub 의 github.event_name)
#   BASE_SHA     pull_request: base 커밋. push: 이 push 이전의 main 커밋(github.event.before)
#   HEAD_SHA     검사할 마지막 커밋
#   GITLEAKS_BIN gitleaks 실행 파일(기본 gitleaks)
#   HARNESS_GITLEAKS_CONFIG  하네스 기본 설정(기본 .harness-engine/checker/gitleaks/harness.toml)
#   REPORT_PATH  JSON 리포트 경로(기본 gitleaks-report.json). 값이 가려진 것만 쓴다.
#
# 설정: 저장소 꼭대기의 .gitleaks.toml 이 있으면 그것, 없으면 하네스 기본 설정이다. 단 PR 은 PR 이 낸 head 의
# 파일이 아니라 base 커밋의 .gitleaks.toml 을 쓴다(임시 파일로 꺼내 --config 로 넘긴다) — PR 이 같은 PR 안에서
# 자기 allowlist 로 자기 비밀값을 통과시키지 못하게 하기 위해서다. 그 변경은 병합 뒤부터 적용되며, PR 이 파일을
# 바꿨으면 경고한다. base 에 파일이 없으면 하네스 기본 설정이다. push 는 체크아웃된 파일을 쓴다.
# 설정을 읽다 실패하면(파일 없음이 아닌 오류) 검사 불능이다.
#
# 저장소 꼭대기(현재 폴더)에서 부른다. 설정의 [extend] path 는 현재 폴더 기준이다.

set -u

GITLEAKS_BIN="${GITLEAKS_BIN:-gitleaks}"
HARNESS_CONFIG="${HARNESS_GITLEAKS_CONFIG:-.harness-engine/checker/gitleaks/harness.toml}"
REPORT_PATH="${REPORT_PATH:-gitleaks-report.json}"
EVENT_NAME="${EVENT_NAME:-}"
BASE_SHA="${BASE_SHA:-}"
HEAD_SHA="${HEAD_SHA:-}"
ZERO_SHA="0000000000000000000000000000000000000000"

emit() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "result=$1" >> "$GITHUB_OUTPUT"
  fi
}

fail_error() {
  echo "::error title=gitleaks 검사 불능::$1 이것은 비밀값이 발견됐다는 뜻이 아니다. 검사를 하지 못했으므로 통과로 보지 않는다."
  emit error
  exit 1
}

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  fail_error "현재 폴더가 git 저장소가 아니다."
fi

# 설정 고르기(위 머리 설명 참고). 결과는 변수 config 에 둔다.
config=""
tree_entry() { git ls-tree "$1" -- .gitleaks.toml; }  # 파일이 없으면 성공하되 출력이 비어 있다.

choose_config() {
  local base_entry head_entry tmp_dir
  if [ "$EVENT_NAME" = "pull_request" ] || [ "$EVENT_NAME" = "pull_request_target" ]; then
    base_entry="$(tree_entry "$BASE_SHA")" || fail_error "base 커밋($BASE_SHA)의 .gitleaks.toml 을 확인할 수 없다."
    head_entry="$(tree_entry "$HEAD_SHA")" || fail_error "head 커밋($HEAD_SHA)의 .gitleaks.toml 을 확인할 수 없다."
    if [ "$base_entry" != "$head_entry" ]; then
      echo "::warning title=gitleaks 설정 변경::이 PR 의 .gitleaks.toml 변경은 병합 뒤부터 적용된다. 이 PR 의 검사는 base 의 설정으로 한다."
    fi
    if [ -n "$base_entry" ]; then
      tmp_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
      config="$(mktemp "$tmp_dir/gitleaks-base-XXXXXX.toml")" || fail_error "임시 설정 파일을 만들 수 없다."
      git show "$BASE_SHA:.gitleaks.toml" > "$config" || fail_error "base 커밋의 .gitleaks.toml 을 읽을 수 없다."
      echo "설정: base($BASE_SHA)의 .gitleaks.toml (하네스 규칙을 유지하려면 [extend] path = \"$HARNESS_CONFIG\")"
      return
    fi
  elif [ -f .gitleaks.toml ]; then
    config=".gitleaks.toml"
    echo "설정: 저장소의 .gitleaks.toml (하네스 규칙을 유지하려면 [extend] path = \"$HARNESS_CONFIG\")"
    return
  fi
  if [ -f "$HARNESS_CONFIG" ]; then
    config="$HARNESS_CONFIG"
    echo "설정: 하네스 기본 설정 ($HARNESS_CONFIG)"
  else
    fail_error "하네스 기본 설정 파일이 없다($HARNESS_CONFIG)."
  fi
}

# 검사 범위.
commit_exists() { git cat-file -e "$1^{commit}" 2> /dev/null; }

if [ -z "$HEAD_SHA" ] || ! commit_exists "$HEAD_SHA"; then
  fail_error "검사할 마지막 커밋($HEAD_SHA)을 찾을 수 없다. 체크아웃이 전체 이력(fetch-depth: 0)이 아닐 수 있다."
fi

case "$EVENT_NAME" in
  pull_request | pull_request_target)
    if [ -z "$BASE_SHA" ] || ! commit_exists "$BASE_SHA"; then
      fail_error "PR 의 base 커밋($BASE_SHA)을 찾을 수 없다."
    fi
    log_opts="$BASE_SHA..$HEAD_SHA"
    scope="PR 커밋 범위 $log_opts"
    ;;
  push)
    if [ -z "$BASE_SHA" ] || [ "$BASE_SHA" = "$ZERO_SHA" ]; then
      # 브랜치가 처음 생긴 push: 그 이력 전체가 이번 push 다.
      log_opts="$HEAD_SHA"
      scope="새 브랜치의 전체 이력($HEAD_SHA)"
    elif commit_exists "$BASE_SHA"; then
      log_opts="$BASE_SHA..$HEAD_SHA"
      scope="push 커밋 범위 $log_opts"
    else
      # 강제 push 등으로 이전 커밋이 사라졌다. 범위를 알 수 없어 마지막 커밋 하나만 본다.
      log_opts="-1 $HEAD_SHA"
      scope="마지막 커밋 하나($HEAD_SHA) — push 이전 커밋($BASE_SHA)이 없어 범위를 줄였다"
      echo "::warning title=gitleaks 검사 범위 축소::push 이전 커밋을 찾을 수 없어 마지막 커밋 하나만 검사한다."
    fi
    ;;
  *)
    fail_error "지원하지 않는 이벤트($EVENT_NAME)다. pull_request 와 push 만 검사한다."
    ;;
esac

# shellcheck disable=SC2086  # log_opts 는 의도적으로 단어 분리한다("-1 <sha>").
commit_count="$(git rev-list --count $log_opts 2> /dev/null)" \
  || fail_error "검사 범위($log_opts)의 커밋 수를 셀 수 없다."
if [ "$commit_count" = "0" ]; then
  echo "검사 범위($scope)에 커밋이 없어 검사할 것이 없다."
  emit clean
  exit 0
fi
echo "검사 범위: $scope ($commit_count 커밋)"

choose_config

"$GITLEAKS_BIN" git \
  --config "$config" \
  --log-opts "$log_opts" \
  --redact \
  --verbose \
  --no-color \
  --no-banner \
  --exit-code 2 \
  --report-format json \
  --report-path "$REPORT_PATH" \
  .
code=$?

case "$code" in
  0)
    echo "통과: 비밀값이 발견되지 않았다."
    emit clean
    exit 0
    ;;
  2)
    echo "::error title=gitleaks 유출 발견::커밋에서 비밀값 모양이 발견됐다(값은 가려서 출력). 파일·줄·규칙은 위 출력과 리포트에 있다. 진짜 비밀이면 폐기·교체하고 이력에서 지운다. 오탐이면 저장소의 .gitleaks.toml [allowlist] 에 올린다."
    emit leak
    exit 1
    ;;
  *)
    fail_error "gitleaks 가 오류로 끝났다(종료코드 $code). 설정 파일($config)이나 바이너리를 확인한다."
    ;;
esac
