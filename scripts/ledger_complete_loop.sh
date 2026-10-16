#!/usr/bin/env bash
# ledger-complete.yml 의 재시도 루프(#346). Project Repository 작업 트리(main 을 checkout 한 곳)에서 부른다.
#
# 시도마다 origin/main 으로 맞추고 → apply → 원장이 바뀌면 커밋 → push 한다. push 가 밀리면(그 사이 main 이
# 움직임) 다음 시도에서 다시 받아 처음부터 한다. apply 가 종료 2(판정 불능)이거나 출력을 못 읽으면 되풀이하지
# 않고 실패로 멈춘다(파일은 바꾸지 않았다). 이 스크립트는 항상 0 으로 끝나고 결과는 outcome 으로 알린다.
#
# 입력(환경변수)
#   REPO         owner/repo (필수)
#   SHA          push 로 들어온 마지막 커밋 (필수)
#   BEFORE       push 직전의 main 커밋. 0 이 아니고 히스토리에 있으면 BEFORE..SHA 의 모든 커밋을 처리한다
#   ATTEMPTS     최대 시도 수 (기본 5)
#   RETRY_SLEEP_MAX  시도 사이 랜덤 대기 상한 초 (기본 5, 0 이면 대기 없음)
#   APPLY_CMD    apply 를 부르는 명령 (기본: 엔진 checkout 의 ledger_complete.py)
# 출력: reason.txt(사유), $GITHUB_OUTPUT 의 outcome=done|failed
set -u

REPO="${REPO:?REPO 가 필요하다}"
SHA="${SHA:?SHA 가 필요하다}"
BEFORE="${BEFORE:-}"
ATTEMPTS="${ATTEMPTS:-5}"
RETRY_SLEEP_MAX="${RETRY_SLEEP_MAX:-5}"
APPLY_CMD="${APPLY_CMD:-uv run --project .harness-engine python .harness-engine/scripts/ledger_complete.py}"

git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"

# 처리할 커밋: push 에 커밋이 여럿이면 오래된 것부터 전부, 아니면 SHA 하나.
shas="$SHA"
if [ -n "$BEFORE" ] && ! [[ "$BEFORE" =~ ^0+$ ]] && git cat-file -e "${BEFORE}^{commit}" 2>/dev/null; then
  range="$(git rev-list --reverse "${BEFORE}..${SHA}" 2>/dev/null)"
  [ -n "$range" ] && shas="$range"
fi
sha_args=()
for s in $shas; do sha_args+=(--sha "$s"); done

outcome=failed
reason="알 수 없는 이유로 끝나지 못했다."
for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "::group::시도 $attempt"
  if [ "$attempt" -gt 1 ] && [ "$RETRY_SLEEP_MAX" -gt 0 ]; then
    sleep $((RANDOM % RETRY_SLEEP_MAX + 1))
  fi
  if ! git fetch origin main || ! git reset --hard origin/main; then
    reason="origin/main 을 받지 못했다(시도 $attempt)."
    echo "::endgroup::"
    continue
  fi
  # shellcheck disable=SC2086
  $APPLY_CMD apply --repo "$REPO" "${sha_args[@]}" --root . > result.json 2> error.txt
  code=$?
  cat error.txt >&2 || true
  cat result.json || true
  status="$(jq -r '.status // empty' result.json 2>/dev/null)"
  if [ "$code" != "0" ]; then
    # 2 는 판정 불능이다. 파일을 바꾸지 않았으니 되풀이해도 같으므로 멈춘다.
    reason="$(jq -r '.reason // empty' result.json 2>/dev/null)"
    [ -z "$reason" ] && reason="ledger_complete.py 가 종료코드 $code 로 끝났다: $(head -c 500 error.txt)"
    echo "::endgroup::"
    break
  fi
  if [ -z "$status" ]; then
    # 종료 0 인데 출력을 못 읽으면 "바꿀 것 없음" 으로 넘기지 않는다(검사 불능).
    reason="ledger_complete.py 의 출력에서 status 를 읽지 못했다: $(head -c 300 result.json | tr '\n' ' ')"
    echo "::endgroup::"
    break
  fi
  if [ "$status" != "changed" ]; then
    outcome=done
    echo "원장을 바꿀 것이 없다: $(jq -r '.reason' result.json)"
    echo "::endgroup::"
    break
  fi
  refs="$(jq -r '.prs | map("#\(.)") | join(", ")' result.json 2>/dev/null)"
  if [ -z "$refs" ]; then
    reason="ledger_complete.py 의 출력에서 처리한 PR 번호를 읽지 못했다."
    echo "::endgroup::"
    break
  fi
  git add audit/ledger
  if ! git commit -m "docs: 진행 원장 완료 표시" -m "Refs $refs"; then
    reason="원장 변경을 커밋하지 못했다."
    echo "::endgroup::"
    break
  fi
  if git push origin HEAD:main 2> push-error.txt; then
    outcome=done
    echo "원장을 완료로 표시해 push 했다: $(jq -r '.changed | join(", ")' result.json)"
    echo "::endgroup::"
    break
  fi
  cat push-error.txt >&2
  reason="push 가 ${attempt}번 실패했다: $(head -c 300 push-error.txt | tr '\n' ' ')"
  # main 이 앞서 나가 밀린 경우만 다시 시도한다. 권한 거부·훅 거부(remote rejected) 등은 되풀이해도 같다.
  if ! grep -qE 'non-fast-forward|fetch first|^ ! \[rejected\]' push-error.txt; then
    reason="push 가 거부됐다(다시 시도해도 같다): $(head -c 300 push-error.txt | tr '\n' ' ')"
    echo "::endgroup::"
    break
  fi
  echo "::endgroup::"
done

printf '%s' "$reason" > reason.txt
echo "outcome=$outcome"
[ -n "${GITHUB_OUTPUT:-}" ] && echo "outcome=$outcome" >> "$GITHUB_OUTPUT"
exit 0
