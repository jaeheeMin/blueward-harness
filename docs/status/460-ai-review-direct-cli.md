# #460 ai-review 를 Claude CLI 직접 호출 + 묶음 리뷰로 바꾸기 (2026-10-26)

## 문제

2026-10-25 public-cloud 에서 PR 검사를 다시 돌렸을 때 큰 PR 에서 ai-review 가 막혔다. 결과 파일이 안 만들어진 검사 불능이 5개 PR, "일부만 봄" 이 4개 PR 이었다. 둘 다 그 PR 의 코드 문제가 아니라 AI 리뷰를 돌리지 못한 것이다.

## 원인

| | 내용 | 근거 |
|---|---|---|
| A | `anthropics/claude-code-action@v1` 은 OIDC 로 Anthropic 서버에서 앱 토큰을 받는다. 서버가 워크플로 파일이 기본 브랜치와 같은지 보고, 다르면 거절한다. 액션은 "Skipping action due to workflow validation" 로 조용히 건너뛰어 결과 파일이 안 만들어진다. 스택 PR 이 옛 호출 워크플로를 가져 걸렸다 | 재현, 액션 로그 |
| B | 모델이 `git diff`·Read 로 무엇을 읽을지 스스로 고르고, coverage 도 스스로 적는다. 다 봤는지가 모델의 자기 신고라 믿을 수 없다 | 아래 재현 표 |

#347 을 로컬에서 같은 프롬프트로 두 번 재현했다. 출력 한도 문제는 아니었다.

| 회차 | 모델이 적은 coverage | 실제 |
|---|---|---|
| 1 | partial | 16개 파일을 못 봄 |
| 2 | full | "다 안 봤다" 고 말하고도 full 로 적음 |

## 공식 문서

- CI 에서 `CLAUDE_CODE_OAUTH_TOKEN` 으로 CLI 실행: https://code.claude.com/docs/en/authentication.md. `ANTHROPIC_API_KEY` 가 있으면 `-p` 에서 그게 우선이라 비운다. `--bare` 는 이 토큰을 읽지 않아 쓰지 않는다.
- 판 고정 설치(`curl -fsSL https://claude.ai/install.sh | bash -s <version>`)와 자동 갱신 끄기 `DISABLE_UPDATES`: https://code.claude.com/docs/en/setup.md
- `--json-schema` + `--output-format json` → 결과 JSON 의 `structured_output`: https://code.claude.com/docs/en/cli-reference.md
- stdin 프롬프트 10MB 까지: https://code.claude.com/docs/en/headless.md

## 결정

- 액션을 쓰지 않고 워크플로가 Claude CLI(`claude -p`)를 직접 부른다. 판은 `claude-code-version` 입력으로 고정하고 설치 뒤 `claude --version` 으로 확인한다.
- 리뷰는 엔진 모듈 `checker/ai_review.py` 가 한다(워크플로와 로컬 시험이 같은 코드, 진입점 `scripts/ai_review.py`).
- 리뷰 대상은 **코드 파일만**이다. `*.md`, `docs/` 아래, 오피스·PDF·이미지, 바이너리는 `excluded`(대상 아님, 못 본 것이 아니므로 partial 로 세지 않는다). 삭제만 된 파일은 `deleted`. 규칙은 `EXCLUDED_PREFIXES`·`EXCLUDED_EXTENSIONS` 표 하나다.
- 파일별 diff(`-U20`)를 `batch-chars`(기본 60000) 이하 묶음으로 나눠 묶음마다 `claude -p` 를 한 번 부른다. 큰 파일은 hunk 단위로 쪼개고, 혼자 상한을 넘는 hunk 는 그 hunk 만의 묶음(`oversize`)으로 둔다. `max-batches`(기본 8)를 넘는 묶음의 파일은 리뷰하지 않고 `unreviewed`(사유 "묶음 상한").
- **다 봤는지는 워크플로(엔진)가 판정한다.** 대상 파일 전부가 성공한 묶음에 들어 있으면 full, 아니면 partial. 모델에게 coverage 를 묻지 않고, 프롬프트의 "큰 변경 우선순위"·coverage 지시도 없앴다. 이전의 "AI 가 전체를 봤다고 스스로 적었습니다(검증 안 됨)" 안내도 없앴다.
- 묶음 성공 = 종료코드 0, 결과 JSON 이 오류가 아님, `structured_output` 이 스키마에 맞음. 실패한 묶음의 파일은 `unreviewed`(사유: 종료코드, 시간 초과, 형식 오류). 묶음 밖 파일의 지적은 버리지 않고 `outside_batch` 로 표시한다.
- 성공한 묶음이 하나도 없으면 `ai-review.json` 을 쓰지 않고 `ai-review-unavailable.json`(사유)을 남긴 채 종료코드 2. 결과 정리 단계가 검사 불능으로 읽고 사유를 코멘트에 적는다. 대상 코드가 0개면 full + 지적 없음 + `no_code_to_review`.
- 묶음당 timeout 300초, 전체 780초(워크플로 단계 timeout 15분보다 짧게). 전체 시간이 모자라면 남은 묶음은 못 본 것으로 적는다.
- 허용 도구는 `Read,Glob,Grep` 뿐이고 `--permission-prompts none` 으로 그 밖의 요청은 거절한다. `--strict-mcp-config`, `--setting-sources ""`, `--no-session-persistence`.
- 정책 유지: AI 리뷰를 못 돌리면(검사 불능·일부만 봄) 통과로 보지 않고 승인이 필요하다(원칙 7). 마커, status 문자열, risk-gate 가 읽는 job id `ai-review` 는 그대로다.
- `id-token: write` 는 더 이상 필요 없다. 재사용 워크플로와 스캐폴드 예시에서 뺐다. public-cloud 의 호출 워크플로에 남아 있어도 동작에는 영향이 없다(그 저장소는 고치지 않았다).
- PR 코멘트: 제외 파일은 "AI 리뷰 대상 아님 - 코드가 아닌 파일 N개" 한 줄(예시 3개), partial 사유는 묶음 상한과 묶음 실패로 나눠 적는다.

## 주의

- 구독 OAuth 토큰은 `claude setup-token` 을 실행한 사람의 구독에 묶인다. 사용량도 그 구독에서 나간다. 이 점은 액션을 쓰던 때와 같은 조건이다. 여러 사람이 쓰는 저장소는 토큰을 만든 사람의 한도에 걸릴 수 있으니, 공용이면 API 키 쓰기를 검토한다(지금 워크플로는 API 키를 비워 구독 토큰만 쓰므로 API 키로 바꾸려면 워크플로를 고쳐야 한다).
- **프롬프트 인젝션으로 토큰이 새는 길(검토에서 나온 심각한 위험).** PR 의 diff 는 비신뢰 입력이다. 거기에 심은 지시를 따라 Claude 가 `Read` 로 `/proc/self/environ`(`CLAUDE_CODE_OAUTH_TOKEN`)이나 `.git/config`(체크아웃이 남긴 `GITHUB_TOKEN` extraheader)를 읽고, 지적 문장(`summary`)에 실으면 PR 코멘트로 새어 나간다. 겹겹이 막았다.
  1. 두 checkout 모두 `persist-credentials: false` — `.git/config` 에 토큰이 남지 않는다.
  2. `--tools Read,Glob,Grep` 으로 도구 자체를 읽기 셋으로 줄이고(Bash·Write 없음), `--settings` 의 `permissions.deny` 로 `/proc`·`/sys`·`/etc`·`.git`·`_temp`·`~/.ssh`·`~/.claude*` 등 읽기를 거부한다(경로 문법은 permissions 문서의 gitignore 식, `//` 절대 경로, `~/` 홈). 홈 전체는 러너 작업 폴더가 홈 아래라 막지 않는다.
  3. `--scrub-config` 로 리뷰 전에 체크아웃의 `.claude/`, `.mcp.json`, `CLAUDE.md`, `.claude.json` 을 지운다(`--setting-sources ""` 가 안 먹어도 PR 이 심은 훅·MCP·지시가 없게). 로컬에선 기본 꺼짐이다.
  4. 자식 프로세스 환경 변수는 허용 목록(PATH, HOME, LANG/LC_*, TMPDIR 류, `CLAUDE_CODE_OAUTH_TOKEN`, `DISABLE_UPDATES`, Windows 로컬용 최소 몇 개)만 넘긴다. `GITHUB_TOKEN`·`ACTIONS_*`·`RUNNER_*` 는 빠진다.
  5. 마지막 관문: 결과를 쓰기 전에 지적 문장과 실패 사유에 (a) env 의 `CLAUDE_CODE_OAUTH_TOKEN`·`GITHUB_TOKEN` 실제 값(8자 이상) (b) 토큰 모양(기존 `risk_gate.SECRET_PATTERNS` + `sk-ant-`·`gh*_`·`github_pat_`·`Authorization: basic`·긴 base64)이 있으면 `ai-review.json` 을 쓰지 않고 검사 불능("결과에 비밀값으로 보이는 문자열")으로 끝낸다. 값은 어디에도 출력하지 않는다. 비교용 `GITHUB_TOKEN` 은 리뷰 단계 env 로 넘기지만 자식 환경에는 안 넘어간다.
  - **남는 위험:** 구독 토큰은 같은 프로세스 환경에 남는다(claude 가 인증에 써야 하므로). 2)~5) 로 읽기·유출 길을 막았을 뿐이다. 거부 경로 목록이 빠진 경로를 읽는 우회, 토큰을 인코딩해 싣는 우회(base64 패턴은 40자 이상만 본다)는 이론상 남는다. 토큰이 새어 나갔다고 의심되면 `claude setup-token` 으로 새로 만들어 시크릿을 바꾼다.
- 묶음마다 모델을 따로 부르므로 큰 PR 은 호출 수가 는다(최대 `max-batches` 번). 비용·턴은 `ai-review.json` 의 `batches` 에 묶음별로 남는다.
- 설치 스크립트(`claude.ai/install.sh`)는 러너에서 내려받아 실행한다. 판을 입력으로 고정하고 설치 뒤 판을 확인하지만 스크립트 자체를 검증하지는 않는다.

## 확인하지 못한 것

- 실제 `claude -p` 호출은 이 작업에서 돌리지 않았다(별도로 확인). 특히 `--setting-sources ""`(빈 값)와 `--permission-prompts none` 이 이 판(2.1.310)에서 의도대로 동작하는지, `structured_output` 키 이름은 실제 실행으로 확인해야 한다. 테스트는 가짜 실행기로 명령 구성과 결과 처리만 본다.
- 러너에서의 설치(`install.sh`)와 `PATH` 설정은 Actions 에서 돌려 보기 전엔 확인하지 못했다.

## 남은 일

- 막힌 9개 PR 의 ai-review 재실행은 사용자 확인 뒤에 한다.
- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
- public-cloud 호출 워크플로의 `id-token: write` 제거는 그쪽 저장소에서 따로(영향 없음).
