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
- **Claude 에게 도구를 주지 않는다**(`--tools ""` + `--disallowedTools` 로 한 번 더). `claude --help` 의 `--tools` 설명: `Use "" to disable all tools, "default" to use the default set`. 모델은 프롬프트에 실린 diff(바뀐 줄과 앞뒤 `-U40` 줄)만 보고 저장소 파일을 읽지 못한다. `--allowedTools`·`--settings`(Read 거부 목록)는 넘기지 않는다 — 허용할 도구가 없고, 거부 목록은 아래 시험처럼 저장소 밖 경로를 못 막았다. 묶음당 턴은 3(구조화 출력 한 번과 재시도 정도). `--permission-prompts none`, `--strict-mcp-config`, `--setting-sources ""`, `--no-session-persistence`.
- 정책 유지: AI 리뷰를 못 돌리면(검사 불능·일부만 봄) 통과로 보지 않고 승인이 필요하다(원칙 7). 마커, status 문자열, risk-gate 가 읽는 job id `ai-review` 는 그대로다.
- `id-token: write` 는 더 이상 필요 없다. 재사용 워크플로와 스캐폴드 예시에서 뺐다. public-cloud 의 호출 워크플로에 남아 있어도 동작에는 영향이 없다(그 저장소는 고치지 않았다).
- PR 코멘트: 제외 파일은 "AI 리뷰 대상 아님 - 코드가 아닌 파일 N개" 한 줄(예시 3개), partial 사유는 묶음 상한과 묶음 실패로 나눠 적는다.

## 주의

- 구독 OAuth 토큰은 `claude setup-token` 을 실행한 사람의 구독에 묶인다. 사용량도 그 구독에서 나간다. 이 점은 액션을 쓰던 때와 같은 조건이다. 여러 사람이 쓰는 저장소는 토큰을 만든 사람의 한도에 걸릴 수 있으니, 공용이면 API 키 쓰기를 검토한다(지금 워크플로는 API 키를 비워 구독 토큰만 쓰므로 API 키로 바꾸려면 워크플로를 고쳐야 한다).
- **프롬프트 인젝션으로 토큰이 새는 길(검토에서 나온 심각한 위험).** PR 의 diff 는 비신뢰 입력이다. 거기에 심은 지시를 따라 Claude 가 `Read` 로 `/proc/self/environ`(`CLAUDE_CODE_OAUTH_TOKEN`)이나 `.git/config`(체크아웃이 남긴 `GITHUB_TOKEN` extraheader)를 읽고, 지적 문장(`summary`)에 실으면 PR 코멘트로 새어 나간다. 겹겹이 막았다.
  1. 두 checkout 모두 `persist-credentials: false` — `.git/config` 에 토큰이 남지 않는다.
  2. ~~읽기 거부 목록~~ → **도구 제거.** 처음엔 `--tools Read,Glob,Grep` + `--settings` 의 `permissions.deny`(`/proc`·`/etc`·`.git`·`~/.ssh` 등)로 막으려 했다. 직접 시험에서 이 방식은 저장소 밖 파일을 막지 못했다.

     | 시험한 경로 | 거부 목록 방식의 결과 |
     |---|---|
     | (a) `.git/config` | 막힘 |
     | (b) `../outside-secret.txt` (저장소 밖 상대 경로) | **읽힘** |
     | (c) `C:/Windows/win.ini` (저장소 밖 절대 경로) | **읽힘** |
     | (d) `~/.ssh/known_hosts` | 막힘으로 보였으나 파일이 없어 거부와 없음을 구분하지 못함 |
     | (e) 저장소 안 파일 | 읽힘(정상) |

     도구 제거 뒤 같은 경로로 재시험한 결과는 모두 응답에 안 실렸다(통과). 이때 `max-turns 3` 에서 `num_turns` 가 6 으로 나왔지만 `structured_output` 은 정상이었다. json-schema 재시도가 턴 상한 밖에서 도는 것으로 보인다(추정, 확인은 못 함).

     그래서 도구를 아예 주지 않기로 했다(위 결정). 거부 목록과 `--allowedTools` 는 지웠다.
  3. `--scrub-config` 로 리뷰 전에 체크아웃의 `.claude/`, `.mcp.json`, `CLAUDE.md`, `.claude.json` 을 지운다(`--setting-sources ""` 가 안 먹어도 PR 이 심은 훅·MCP·지시가 없게). 로컬에선 기본 꺼짐이다.
  4. 자식 프로세스 환경 변수는 허용 목록(PATH, HOME, LANG/LC_*, TMPDIR 류, `CLAUDE_CODE_OAUTH_TOKEN`, `DISABLE_UPDATES`, Windows 로컬용 최소 몇 개)만 넘긴다. `GITHUB_TOKEN`·`ACTIONS_*`·`RUNNER_*` 는 빠진다.
  5. 마지막 관문: 결과를 쓰기 전에 지적 문장과 실패 사유에 (a) env 의 `CLAUDE_CODE_OAUTH_TOKEN`·`GITHUB_TOKEN` 실제 값(8자 이상) (b) 토큰 모양(기존 `risk_gate.SECRET_PATTERNS` + `sk-ant-`·`gh*_`·`github_pat_`·`Authorization: basic`·긴 base64)이 있으면 `ai-review.json` 을 쓰지 않고 검사 불능("결과에 비밀값으로 보이는 문자열")으로 끝낸다. 값은 어디에도 출력하지 않는다. 비교용 `GITHUB_TOKEN` 은 리뷰 단계 env 로 넘기지만 자식 환경에는 안 넘어간다.
  - **남는 위험:** 구독 토큰은 같은 프로세스 환경에 남는다(claude 가 인증에 써야 하므로). 2)~5) 로 읽기·유출 길을 막았을 뿐이다. 거부 경로 목록이 빠진 경로를 읽는 우회, 토큰을 인코딩해 싣는 우회(base64 패턴은 40자 이상만 본다)는 이론상 남는다. 토큰이 새어 나갔다고 의심되면 `claude setup-token` 으로 새로 만들어 시크릿을 바꾼다.
- 마지막 관문이 쓰는 비밀값 패턴(`checker.risk_gate`, yaml 등을 불러온다)은 `run` 시작 때 먼저 불러온다. 못 불러오면 claude 를 부르기 전에 검사 불능(종료코드 2)이다. 예상 못 한 예외도 `main` 이 검사 불능(2)과 사유 파일(예외 종류만)로 남기고 트레이스백은 stderr 에만 낸다.
- 묶음 기록(`batches`)에 `num_turns` 와 `permission_denials`(도구 이름과 대상 경로·패턴만, 내용은 싣지 않음)를 남긴다. 결과 JSON 에서 도구 호출 횟수를 얻는 필드는 확인하지 못해 싣지 않았다. 거부 기록은 인젝션 시도를 알아보는 단서다.
- 묶음마다 모델을 따로 부르므로 큰 PR 은 호출 수가 는다(최대 `max-batches` 번). 비용·턴은 `ai-review.json` 의 `batches` 에 묶음별로 남는다.
- 설치 스크립트(`claude.ai/install.sh`)는 러너에서 내려받아 실행한다. 판을 입력으로 고정하고 설치 뒤 판을 확인하지만 스크립트 자체를 검증하지는 않는다.

## 확인하지 못한 것

- 실제 `claude -p` 호출은 이 작업에서 돌리지 않았다(별도로 확인). 특히 `--setting-sources ""`(빈 값)와 `--permission-prompts none` 이 이 판(2.1.310)에서 의도대로 동작하는지, `structured_output` 키 이름은 실제 실행으로 확인해야 한다. 테스트는 가짜 실행기로 명령 구성과 결과 처리만 본다.
- 러너에서의 설치(`install.sh`)와 `PATH` 설정은 Actions 에서 돌려 보기 전엔 확인하지 못했다.

## 남은 일

- 막힌 9개 PR 의 ai-review 재실행은 사용자 확인 뒤에 한다.
- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
- public-cloud 호출 워크플로의 `id-token: write` 제거는 그쪽 저장소에서 따로(영향 없음).

## 추가 결정 (도구 제거 이후)

- **문맥 줄 40(`-U40`).** 도구가 없으니 앞뒤 문맥은 diff 에 실린 만큼이 전부다. 최근 8개 커밋 범위(39개 파일)로 `--dry-run` 을 비교하면 글자 수가 288,029(-U20) → 327,864(-U40)로 약 14% 늘지만 묶음은 6개로 같다. `batch-chars` 60000 은 그대로 둔다(묶음이 늘어 `max-batches` 8 에 가까워지면 올리는 것을 검토).
- **serious 기준.** `PROMPT_HEAD` 의 `[무엇을 지적하나]` 첫 줄에 예시를 넣었다: 데이터를 바꾸는 동작의 권한 검사 누락, 권한 검사가 실패해도 통과시키는 처리(fail-open), 정확성 버그, 보안 취약점, 데이터 손실. 권한 검사 누락은 공통 규칙 CR-009("데이터를 바꾸는 앱은 권한을 검사한다")와 맞춘 것이다. CR-009 는 ABAP 소스를 정적으로 보는 경고(`warn`)이고, AI 리뷰는 같은 원칙을 언어와 관계없이 serious 로 본다.
- 프롬프트에서 "Read/Grep/Glob 으로 읽어도 된다" 를 지우고 "주어진 diff 만으로 판단한다. 보이지 않는 코드에 대해 추측하지 않는다" 로 바꿨다.
- 겹 방어는 그대로다: `--scrub-config`, 환경 변수 허용 목록, `persist-credentials: false`, 결과 쓰기 전 `scan_leaks`.
- 실제 실행 확인: `--tools ""` 로 도구가 없는 상태에서 파일 내용이 응답에 실리지 않았다. 턴 수는 위 시험처럼 상한(3)보다 크게 보고될 수 있다.
- **누출 검사 오탐(#347·#350).** `scan_leaks` 의 "40자 이상 대소문자·숫자 base64" 패턴이 `src/ui5/zppu0010/webapp/ext/QueuedRefresh.js` 같은 긴 경로를 걸어 UI5 가 든 PR 이 모두 검사 불능이 됐다. 고친 것: (1) 지적의 `file` 필드는 토큰 모양 패턴에서 빼고 env 토큰 실제 값 일치만 본다, (2) base64 패턴의 매치가 경로·식별자 모양이면 제외한다 — 슬래시 없는 매치는 통째로 낱말(camelCase, 대문자 약어, 끝 숫자)이어야 하고, 슬래시가 있으면 조각마다 낱말 모양이거나 8자 이하여야 한다. 진짜 base64 토큰에도 `/` 가 들어갈 수 있어 문자 클래스에서 `/` 를 빼지 않았다. 숫자가 낱말 사이에 끼는 무작위 문자열은 계속 걸린다.
- 프롬프트에 점검 항목을 추가했다: 데이터를 바꾸는 동작(생성·변경·삭제·전기·액션)이 diff 에 있으면 권한 검사가 있는지와 권한 검사가 실패했을 때(결과 행 없음, 실패 테이블, `sy-subrc` 가 0 이 아님) 막는지를 확인하고, 없거나 막지 않으면 serious 다.
