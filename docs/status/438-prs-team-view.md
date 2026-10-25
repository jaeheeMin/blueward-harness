# #438 `/harness:prs` 에 팀원별 진행·막힘·오류 현황 보기 (2026-10-25)

어드민이 팀원 각자의 진행·막힘·오류를 판단하려면 PR 목록이 아니라 사람별 묶음이 필요하다. `checker.pr_queue --team` 을 더했다. 0.10.110.

## 결정

- **옵션 이름 `--team`**. 기존 옵션은 범위(`--mine`/`--all`)와 출력 모양(`--json`/`--verbose`)이다. 팀 보기는 범위가 항상 저장소 전체라 `--all --by-person` 처럼 두 개를 겹치지 않고 한 옵션으로 했다. `--all` 은 붙여도 무시되고, `--mine`·`--pr` 과는 쓸 수 없다(parser 오류). 보조: `--days N`(병합 최근 일수, 기본 7), `--stale-days N`(열린 PR 정체 기준, 기본 3). 담당 이슈 14일은 고정.
- **코드는 `checker/pr_team.py` 새 모듈**. `pr_queue.py` 는 이미 1200줄이라 옵션과 분기만 더했다. 열린 PR 의 상태·병합 순서는 `pr_queue.compute` 를 그대로 재사용(새로 계산하지 않음).
- **호출 수**: 모두 GraphQL 로 묶는다. 열린 PR 시각 1회, 병합 PR 검색 1회, 열린 이슈 100개씩(최대 5쪽), 실패 사유는 검사가 막힌 PR 만 15개씩 1회. 원장은 디렉터리 1회 + 파일마다 1회(프로그램 수에 비례, PR 수 아님). 전체 시간 제한 150초를 넘기면 남은 읽기는 "시간 제한" 확인 불능이다(gh 한 번은 기존 30초 제한).
- **실패 사유는 check run 의 annotations 첫 메시지 > title > summary 첫 줄**. 공통 원인 키(public-cloud 실제 실행 뒤 고침): 사유가 **구체적**이면 문구만으로 묶고 해당 검사 이름은 `checks[]` 목록으로 붙인다(결제 실패 문구가 ai-review·doc-guard·gitleaks·ops-guard 로 갈려 같은 PR 목록이 네 번 반복됐다). **흔한 문구**는 (검사 이름, 사유)로 묶는다. 흔한 문구 = `exit code N` 을 포함하거나 20자 미만(예 "Failure" — 어느 검사에서나 나와 상관없는 PR 을 묶는다. 20자는 실제 구체적 문구가 이보다 길고 "Process completed with exit code 1." 류가 짧은 쪽이라 잡은 값). 사유 문구가 없으면(`no_text`) 묶지 않는다. 사유는 전체 문구로 보이며 300자를 넘으면 문장 끝(없으면 단어 끝)에서 자르고 `…`.
- **막힘은 PR 당 한 줄·한 항목**: `blocked[]` 항목 = `{pr,title,url,author,reasons:[…]}`. 검사 실패·충돌·승인 대기·앞 PR 대기는 같은 줄에 ` · ` 로 잇는다(`[#347] 검사 실패: 공통 원인 ① (ai-review·doc-guard·gitleaks·ops-guard) · 앞 [#346] 병합 대기`). 요약 표의 "막힌 PR" 은 PR 수다.
- **사유를 읽는 PR 은 상태가 검사 실패·검사 시작 전·병합 막힘·검사 불안정인 것**. 이유: `classify` 는 `pr-checks` 같은 합친 job 의 실패를 검사 실패로 세지 않아(단계가 따로 보고) Actions 결제 실패처럼 job 이 시작되지 못한 경우 상태가 "병합 막힘" 등으로 나온다. 사유는 그 job 의 annotation 에 있으므로 여기서는 순서 표시(`merge-order`·`pr-queue`)·알림·승인 게이트만 빼고 실패한 검사를 센다.
- **"움직임 없음" = 사람이 마지막으로 손댄 때**(public-cloud 에서 봇이 모든 PR 의 `updatedAt` 을 한꺼번에 올려 정체가 전부 사라지는 것을 보고 `updatedAt` 을 버렸다). PR: 마지막 커밋 · 열린 때 · 사람(봇 제외)의 마지막 코멘트 · 리뷰 · 리뷰 코멘트 중 가장 늦은 것. 이슈: 사람의 마지막 코멘트, 없으면 생성 시각. 모두 기존 GraphQL 묶음(PR 100개 1회, 이슈 100개씩)에 필드만 더해 읽는다. 기준일을 **초과**할 때만 정체이고 정확히 같으면 아직 아니다. 봇 = `__typename` Bot, `[bot]` 접미사, `github-actions`·`dependabot`(GraphQL 은 봇 login 에서 `[bot]` 을 떼어 주는 경우가 있어 이름도 본다. `claude`·`copilot` 은 같은 이름의 사람 계정을 잘못 뺄 수 있어 목록에서 뺐다 — 그런 봇은 `__typename`·`[bot]` 으로 잡힌다. 이 저장소 워크플로의 코멘트는 모두 GITHUB_TOKEN 의 github-actions 가 남기고 public-cloud 코멘트 작성자도 github-actions 와 사람뿐이었다).
- **판정 불능**: 읽은 활동 중 가장 늦은 것이 기준일 안이면 정체 아님이 확실하다. 기준일을 넘었는데 ① 최근 20개 코멘트·리뷰가 전부 봇이고 그 앞에 더 있거나(사람 댓글이 앞에 있을 수 있음), ② 커밋 시각이 없거나, ③ 리뷰 스레드가 창(최근 10개) 밖에도 있으면(보이는 사람 활동이 있어도 더 새로운 답글을 놓쳤을 수 있다) `stale.unknown_prs`/`unknown_issues` 와 `unknown[]` 로 올린다. `updatedAt` 으로 대신하지 않는다.
- **원장**: 저장소 기본 브랜치(`repos/{repo}` 의 `default_branch`, 하드코딩 main 아님)의 `audit/ledger/*.md` `## 개발 건` 표(`ID`·`내용`·`담당`·`상태`·`마지막 PR`). 기본 브랜치를 읽은 뒤 디렉터리가 없으면(404) `ledger.status` = `none`("원장 없음", 확인 불능 아님). 기본 브랜치 조회 실패(원장 위치를 알 수 없음), 디렉터리 읽기 실패, 파일 읽기 실패, `## 개발 건` 절·표·`상태` 열 없음은 `unknown`. 개발 건의 사람 배정은 `담당` 칸(`@` 허용, 대소문자 무시)이 있으면 그 사람 칸을 만들어 배정하고(이번 기간 활동이 없어도), 비었을 때만 마지막 PR 의 작성자(이번에 읽은 열린·병합 PR 안에서), 둘 다 못 정하면 `ledger.unowned`.
- **봇 계정**(`[bot]`·Bot 형)은 팀원에서 뺀다.
- **원칙 7**: 읽지 못한 칸은 값이 `null` 이고 `unknown[]` 에 사유가 있다(빈 목록이 아니다). 열린 PR 목록 자체를 못 읽으면 기존처럼 "PR 상태 확인 불능" 종료코드 2.

- **계정 형식**: `GITHUB_LOGIN` 은 밑줄도 허용한다(Enterprise Managed Users 의 `name_shortcode`).
- **팀 별칭 파일** `.github/harness-team.yaml`(기본 브랜치): 원장 `담당` 칸의 실명을 GitHub 아이디로 잇는다. 규칙은 코드가 아니라 Project Repository 데이터이고, 원장 줄을 직접 고치면 그 줄을 고치는 열린 PR 이 모두 충돌하기 때문이다. 위치를 `.github/` 로 한 이유: 저장소에 이미 `.github/ssot-approvers`·`.github/human-merge-paths` 같은 사람·경로 데이터 파일이 있고 엔진이 같은 방식(기본 브랜치의 contents API)으로 읽는다. 형식은 `별칭:` 아래 `이름: 아이디`(이름 대소문자 무시, 값의 `@` 허용). 404 = 별칭 없음(경고 없음), 읽기 실패·YAML 오류·`별칭` 매핑 아님 = warnings 에 넣고 별칭 없이 계속, 값이 GitHub 아이디 형식이 아니면 그 별칭만 경고 후 미적용, 대소문자만 다른 중복 이름은 경고 후 먼저 나온 것을 쓴다. 404 가 아닌 읽기 실패(`GhError`)는 warnings 에 더해 `unknown[]` 의 "팀 별칭 파일" 로도 올린다(형식 오류·값 오류는 경고만). 원장 담당에만 적용한다(이슈 담당자는 이미 GitHub 아이디라서). 적용 결과는 JSON `aliases_applied[]`(`name`,`login`,`items`)와 텍스트 맨 끝 한 줄.

## JSON 키

SKILL.md 의 "팀원별 현황" 표에 있다. 최상위: `status`, `repo`, `generated_at`, `days`, `stale_days`, `issue_stale_days`, `common_causes`, `people`, `unassigned_issues`, `ledger`, `unknown`, `warnings`.

## 바꾼 파일

- `checker/pr_team.py`(새), `checker/pr_queue.py`(`--team`·`--days`·`--stale-days`), `checker/tests/test_pr_team.py`(새)
- `plugins/harness/skills/prs/SKILL.md`, `docs/guide/harness-guide.html`("내 PR 확인하기" 탭, 레일 판 표기 0.10.110 · 2026-10-25), `plugins/harness/.claude-plugin/plugin.json`(0.10.110)

- **열린 PR 시각**은 `gh pr list --limit 100` 과 같은 집합(생성 최신순 100개)을 읽는다. 목록에 있는데 시각이 없는 PR 은 정체 아님이 아니라 `stale.unknown_prs` 와 `unknown[]` 의 "PR 시각(정체 판정 불능)" 으로 올린다. 100개 뒤에 더 있으면 경고.
- **검사 50개 초과**: 검사 목록이 한 쪽(50개)을 넘는 PR 은 쪽을 넘겨 최대 250개까지 읽고, 그래도 남으면 `checks_truncated` 와 "검사가 250개를 넘어 일부를 읽지 못함" 으로 구분해 표시한다(사유 없음과 다르다).

## 한계

- 이슈는 라벨·담당자 변경 같은 이벤트를 읽지 않는다(이슈마다 타임라인 조회가 필요해 호출이 이슈 수에 비례). 사람이 라벨만 만진 이슈는 정체로 남을 수 있다. 리뷰 코멘트는 스레드 최근 10개의 마지막 코멘트와 `reviews`(답글도 리뷰로 기록됨)로 읽는다. 코멘트·리뷰는 PR·이슈마다 최근 20개만 읽는다.
- 병합 PR 은 100개(`sort:updated-desc` 로 최근 갱신순), 열린 이슈는 500개(갱신 최신순 5쪽), 열린 PR 은 `PR_LIMIT`(100)에서 잘리고 `truncated` 와 주의를 낸다. 이슈는 최신순이라 **오래된 것부터 잘리므로** 정체 판정이 정상으로 보이지 않게 "오래 머문 이슈" 칸을 "확인 불능(부분)" 으로 표시한다. 병합 수는 "n+ (부분)" 이다.
- 새 판이 병합돼 태그가 붙기 전에는 훅·`uvx` 로 받는 엔진에 `--team` 이 없다.
- 개인 정기 보고용 코워크 지시문 갱신은 저장소 밖 일이라 이 PR 에 없다(JSON 키는 위 표).
