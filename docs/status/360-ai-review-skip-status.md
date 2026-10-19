# #360 위험한 PR 에도 AI 리뷰를 돌리고, 건너뜀·취소를 성공처럼 보이지 않게 (2026-10-19)

## 문제

public-cloud 의 위험 PR(#235 5619줄, #241)은 `risk_gate.py precheck-pr` 가 종료코드 3(이미 위험)을 내 AI 리뷰를 건너뛰었는데, `ai-review` 검사는 success(초록)로 보였다. risk-gate 는 cancelled run 까지 "AI 리뷰 검사가 실패함(심각한 지적 또는 검사 불능)" 으로 뭉뚱그려 적었다. 결국 아무도 보지 않은 채 main 에 들어갔다. 검사를 못 한 것을 통과로 뭉갠 것이다(CLAUDE.md 원칙 7).

## 결정 (사용자, B안)

위험한 PR 에도 AI 리뷰를 돌린다. 모든 PR 에 ai-review 가 돈다. 위험 PR 은 AI 리뷰에 더해 승인자 Approve 도 필요하다(승인 판정은 그대로).

## 설계 결정

**큰 PR 처리.** 프롬프트가 Claude 에게 우선순위(위험 경로 → 로직 변경 → 나머지)를 주고, 다 못 보면 결과 JSON 에 `"coverage": "partial"` 과 `"unreviewed": [파일들]` 을 쓰게 한다. 일부만 봤고 심각한 지적이 없으면 상태 `partial` 로 job 을 실패(exit 1)시키고 코멘트에 "일부만 봄 - 못 본 파일 N개: …" 를 적는다. 심각한 지적이 있으면 그대로 `fail`(못 본 파일 수도 같이 적는다). 조용히 통과시키지 않는다.
- `coverage`·`unreviewed` 키가 없으면 "다 봄" 으로 읽는다(옛 형식 호환). 이유: 이미 도는 프롬프트·테스트가 쓰던 형식이고, 키 없음을 형식 오류로 보면 모델이 키를 빼먹는 것만으로 검사 불능이 돼 오히려 잡음이 늘어난다. 값이 있는데 틀리면(coverage 가 full/partial 이 아니거나 unreviewed 가 문자열 목록이 아님) 형식 오류=검사 불능이다. `coverage: full` 인데 `unreviewed` 가 비어 있지 않으면 모순이라 못 본 쪽을 믿어 partial 로 본다.
- Claude 단계에 `timeout-minutes: 15`(job 20분보다 짧게). job timeout 이 먼저 오면 `always()` 단계가 돌지 못해 코멘트 없이 cancelled 로 끝난다. step timeout 이면 outcome 이 failure 라 결과 정리가 "검사 불능(시간 초과일 수 있음)" 을 코멘트로 남긴다. (job timeout 이면 `always()` 단계가 돌지 못할 수 있어 코멘트를 남기지 못한다 — risk-gate 가 cancelled·timed_out 으로 구분해 적는다.)
- 취소된 run 이 코멘트를 덮어쓰지 않게 "PR 코멘트 갱신" 의 조건을 `always() && …` 에서 `!cancelled() && …` 로 바꿨다. `always()` 는 concurrency 취소 때도 단계를 돌릴 수 있어(실제로 돌았는지 Actions 에서 확인하지는 못했다), 낡은 run 의 "검사 불능" 이 새 run 의 코멘트를 덮을 위험이 있었다. 결과 정리·판정 단계는 파일과 종료코드만 다뤄 부작용이 없으므로 `always()` 그대로다.

**코멘트 표식.** ai-review 코멘트 끝에 `<!-- ai-review-result {"sha","status","serious","findings"(serious 만 최대 5),"unreviewed"} -->` 를 붙인다(기존 `<!-- ai-review -->` 유지). status 는 pass|fail|partial|unavailable|skip|secret(비밀값 의심, 아래 예외). JSON 은 `ensure_ascii` 로 쓰고 `-->` 를 `-->` 로 이스케이프해 HTML 주석이 일찍 닫히지 않는다. job 요약에는 표식을 싣지 않는다. 위험 PR 이면 코멘트 맨 위에 "위험 PR - 승인자 Approve 도 필요합니다: 사유" 한 줄(precheck 의 `risky`·`reasons` 를 쓴다).

**risk-gate 가 결과를 구분(`ai_review_reasons`).** 최신 run(`filter=latest`)의 결론별:
- success → 통과. 단 같은 head sha 의 표식이 pass 가 아니면(partial·fail·unavailable·skip) 보수적으로 사유를 올린다("검사 결론은 success 였으나 결과 코멘트가 다름"). 정상 흐름에서는 일어나지 않는 모순이라, 둘 중 어느 쪽이 맞는지 모르는 채 통과로 가리는 것보다 승인자가 보게 한다. 표식이 없거나 sha 가 다르거나 pass 면 통과(표식을 믿어 통과를 뒤집지는 않고, 코멘트는 누구나 쓸 수 있으므로 사유를 더하는 쪽으로만 쓴다).
- failure → 같은 sha 의 표식: fail 은 "AI 리뷰 심각한 지적 N건: file:line 요약; …"(최대 3건, 요약 100자에서 자름), partial 은 "AI 리뷰가 일부만 봄(못 본 파일 N개) — 승인자가 나머지를 확인", unavailable 은 "AI 리뷰 검사 불능 — …". 표식이 없거나 sha 가 다르거나 JSON 이 깨졌으면 예전 일반 문구.
- cancelled / timed_out → "…취소돼 검사하지 못함 — ai-review 를 다시 실행" / "…시간 초과로 검사하지 못함 — 다시 실행".
- skipped·neutral → "AI 리뷰가 돌지 않음(결론 skipped) — 검사하지 못함". ai_review 가 켜진 저장소에서 안 돈 것이므로 통과가 아니다.
- 그 밖 → 결론 이름을 넣은 검사 불능.
- 다른 검사(`checks_reasons`)의 `_run_state` 는 바꾸지 않았다(cancelled=fail, skipped·neutral=pass 그대로).
- 코멘트는 `GET /repos/{r}/issues/{pr}/comments`(`get_all`)로 필요할 때만(failure·success 결론일 때) 한 번 읽는다. **조회가 실패하면**(권한 없음 등 어떤 예외든) 판정 불능으로 만들지 않고 "표식 없음" 과 같게 일반 문구로 둔다. 이유: 표식은 사유를 자세히 하는 보조 정보이고, check 결론 자체는 이미 알고 있어 위험 판정은 그대로 나온다. 코멘트를 못 읽었다는 사실은 사유 문구 차이로만 드러난다(일반 문구는 코멘트를 확인하라고 안내한다).
- `build_next` 의 ai-review 안내를 일부만 봄·검사 불능·취소·시간 초과·돌지 않음까지 포함하게 고쳤다.
- 위험 PR 에서 심각한 지적은 위 failure 경로로 risk-gate 사유에 붙는다(승인자가 사유에서 바로 본다).

**코멘트 신뢰(검토 반영).** 누구나 PR 에 코멘트를 쓸 수 있으므로 표식은 `user.type == "Bot"` 이고 `login == "github-actions[bot]"` 인 코멘트에서만 읽는다(type 만으론 아무 GitHub App 이나 통과해 둘 다 본다. 워크플로가 `github.token` 으로 쓰므로 정상 코멘트는 이 계정이다). 워크플로의 기존 코멘트 찾기도 같은 조건이다. 한 코멘트에 표식 모양이 여럿이면 마지막 것을 쓴다(진짜는 맨 끝). 워크플로 `clean()` 은 `<!--`·`-->` 를 깨 보이는 본문에 주석이 못 들어가게 한다. 사유에 넣는 표식의 `file`(200자)·`summary`(100자)는 길이를 자르고 `@` 멘션을 무력화한다. 코멘트 목록은 `github.paginate(..., per_page: 100)` 로 모두 읽는다.

**partial 은 AI 의 자기 신고(한계).** `coverage` 가 full 인지는 AI 가 스스로 적은 값이라 검증할 수 없다. 크기 기준을 넘은 PR 인데 AI 가 full 이라 하면 상태·판정은 그대로 두고 코멘트에 "AI 가 전체를 봤다고 스스로 적었습니다(검증 안 됨)" 한 줄을 붙인다. 크기 위험 구분을 위해 `precheck-pr` 출력에 사유를 낸 기준 이름 `criteria`(size·paths·secret)를 추가했다(사유 문자열을 파싱하지 않는다).

**권한(permissions).** risk-gate caller 는 `pull-requests: write` 를 이미 받는다(PR 코멘트를 만들고 고친다). 이슈 코멘트 목록 조회(`issues/{n}/comments`)는 pull-requests read 로 되므로 caller 권한을 바꿀 필요가 없다고 본다. 실제 public-cloud 에서 돌려 본 것은 아니다(확인 못 함) — 안 되면 위 "조회 실패" 경로로 일반 문구가 나올 뿐 판정은 깨지지 않는다.

**설정 키 그대로.** `risk-gate.yaml` 키를 바꾸지 않았다. public-cloud 는 caller(`ai-review.yml`·`risk-gate.yml`)나 `risk-gate.yaml` 을 바꿀 필요가 없다. `@stable` 로 재사용 워크플로와 엔진을 받으므로 0.10.86 이 stable 이 되면 따라온다. 옛 판의 `precheck-pr` 는 위험 PR 에 3을 냈지만 새 워크플로는 새 엔진과 함께 받으므로 어긋나지 않는다.

**precheck.** 종료코드 3 은 설정 없음·`ai_review: false` 에만 쓰고, 4 는 비밀값이 보인 PR(아래 예외)에만 쓴다. 그 밖에 위험하면 0 이고 `risky`·`reasons` 는 출력에 남는다. `size`·`paths`·`secret` 만 평가하는 것은 그대로(`checks`·`ai_review` 는 교착 방지로 뺀다).

**`skip` 은 여전히 성공.** 설정 없음·꺼짐뿐이고 그때 risk-gate 의 `ai_review` 기준도 평가되지 않는다(둘 다 base 의 같은 설정을 읽는다). 그래서 이 skip 은 "검사를 못 함" 이 아니라 "검사 대상이 아님" 이다.

## 예외: 비밀값이 보이는 PR 은 리뷰를 돌리지 않는다 (사용자, A안)

위험한 PR 도 리뷰하되, **새로 들어온 줄에 비밀값 패턴(`SECRET_PATTERNS`)이 실제로 보인 PR 만** AI 리뷰를 돌리지 않는다. 이유: 진짜 키·토큰이 들어 있는 diff 가 외부 API(Claude)로 나가지 않게 하기 위해서다. 돌리지 않는 대신 통과로 보이지 않게 `ai-review` 를 실패(빨간불)시키고 "검사 불능 - 비밀값으로 보이는 문자열이 있어 AI 에 보내지 않음(<패턴 이름들>), 승인자가 직접 확인" 이라고 밝힌다. **값**은 어디에도 남지 않는다(`secret_reasons` 의 사유는 패턴 이름과 `파일:줄` 만 담는다). 위치(파일:줄)는 risk-gate 사유처럼 precheck JSON 의 `reasons` 로 job 로그(`cat precheck.json`)에 남는다(승인자가 위치를 알아야 하므로 그대로 둔다). ai-review 코멘트·표식에는 패턴 이름만 적는다.

- **`unscanned`(변경이 너무 커서 비밀값 검사를 못 한 파일)는 이 예외에 넣지 않았다.** 큰 PR 이 이번 이슈의 핵심이라 계속 리뷰해야 한다. 검사를 못 한 것은 "비밀값이 보였다" 가 아니다. 그래서 `precheck_pr` 출력에 `secret_found`(bool)·`secret_patterns`(이름 목록)를 두고, `_crit_secret` 의 사유와 별도로 `secret_pattern_names(added_lines(...))` 로 계산한다(`secret_scan: false` 면 항상 false).
- **한계: 너무 커서 patch 가 없는 파일(unscanned)은 비밀값 검사를 못 했으므로 그 안의 비밀값은 AI 리뷰로 나갈 수 있다.** 검사하지 못한 것을 "비밀값 없음" 으로 보지 않지만, 보내지 않을 근거도 없어 계속 리뷰하기로 한 대가다.
- **새 워크플로 + 옛 엔진.** 종료코드 0 인데 precheck JSON 에 `secret_found` 키가 없으면(`engine-ref` 가 옛 판) 사전 판정 단계가 `exit-code` 출력을 2(판정 불능)로 바꿔 Claude 단계를 돌리지 않고 "검사 불능 — 엔진이 비밀값 확인 결과를 내지 않음" 으로 실패시킨다. 비밀값 확인 없이 diff 가 나가는 것을 막기 위해서다.
- **구분 방법: 새 종료코드 4(`EXIT_SECRET`)를 골랐다.** `secret_found` 필드만 두고 0 을 유지하면 옛 워크플로가 필드를 모른 채 리뷰를 돌려 비밀값 diff 가 AI 로 나간다. 종료코드 4 는 옛 워크플로가 "0 도 3 도 아님 = 판정 불능" 으로 읽어 토큰·Claude 단계를 건너뛰고 검사 불능으로 실패하므로 실패 쪽으로 안전하다(재사용 워크플로와 엔진은 둘 다 `@stable`/`engine-ref: stable` 이라 같은 태그로 같이 움직이지만, 어긋나도 안전하다). 필드(`secret_found`, `secret_patterns`)도 함께 둬 새 워크플로가 이름을 읽고 테스트가 구분을 본다.
- **상태 이름: `secret` 을 새로 뒀다.** `unavailable` 재사용도 가능했지만 표식 status 만으로 risk-gate 가 사유를 "비밀값 의심이라 AI 리뷰를 돌리지 않음(diff 를 외부 AI 에 보내지 않기 위해) — 승인자가 직접 확인" 으로 적을 수 있고, 시크릿 토큰 누락·Claude 실패 같은 "서비스를 못 돌림" 과 "의도적으로 안 보냄" 이 갈린다. 옛 risk-gate 엔진이 `secret` 표식을 만나면 `_marker_reason` 이 None 이라 일반 문구로 간다(판정은 그대로 실패).
- 워크플로: `pre` 단계 종료코드가 4 이면 `token`/`PR head`/`claude` 단계는 `exit-code == '0'` 조건이라 돌지 않는다. 결과 정리가 `secret` 상태로 코멘트를 만들고(skip 과 달리 코멘트를 만든다), 판정 단계가 `exit 1`.
- 코멘트는 이 경우 "위험 PR" 줄을 덧붙이지 않는다(사유 줄에 파일:줄이 들어 있어 퍼뜨리지 않으려는 뜻).

## 길잡이에 빠졌던 것 보충

`docs/guide/harness-guide.html` 에 앞선 수정이 반영 안 된 두 가지를 더했다: 리뷰 결과는 `github-actions` 봇 코멘트만 읽는다, 큰 PR 에서 AI 의 "전체를 봤다(coverage full)" 는 자기 신고라 확인되지 않는다.

## 바뀐 파일

- `checker/risk_gate.py` — `precheck_pr`/`cmd_precheck_pr`(위험해도 0), `ai_review_reasons`·`parse_ai_review_marker`·`_marker_reason`, `Context.load_comments`, `fetch_pr_comments`, `build_next`, docstring.
- `.github/workflows/ai-review.yml` — 프롬프트(우선순위·coverage), step timeout, 결과 정리(partial·표식·위험 안내), 판정.
- `checker/tests/test_ai_review_workflow.py`, `checker/tests/test_risk_gate.py` — 아래 테스트.
- 문서: `plugins/harness/rules/governance.md`, `plugins/harness/README.md`, `README.md`, `plugins/harness/skills/scaffold/SKILL.md`, 스캐폴드 skeleton 주석(`dot-github/risk-gate.yaml`, `dot-github/workflows/ai-review.yml`), `docs/guide/harness-guide.html`(판 표기 0.10.86 포함).
- `plugins/harness/.claude-plugin/plugin.json` — version 0.10.86.

## 테스트

- skip=success 를 못박은 `test_최종_판정은_통과와_건너뜀만_성공이다` 를 partial 포함으로 고치고, precheck 의 "위험이면 3" 테스트를 "위험이어도 리뷰는 돌린다(0)" 로 고쳤다.
- 추가: 위험 PR 도 코멘트에 위험 안내, partial(심각 없음→partial, 심각 있음→fail), coverage 키 없음=pass, full+unreviewed 모순=partial, coverage·unreviewed 형식 오류=검사 불능, 표식 sha·status·최대 5개·`-->` 이스케이프, step timeout < job timeout, risk-gate 결론별 사유(failure+표식 fail/partial/unavailable, 표식 없음·sha 불일치·깨진 JSON, 코멘트 조회 실패, cancelled·timed_out·skipped·neutral·그 밖, success+표식 불일치/일치/낡음), `_run_state` 불변, `decide_pr` 통합.

## 남은 일

- 병합 뒤 길잡이를 아티팩트에 다시 올린다(`docs/guide/README.md`).
- 이 변경이 stable 이 되면 public-cloud 에서 위험 PR 로 실제로 도는지(코멘트 조회 권한 포함) 한 번 확인한다.
