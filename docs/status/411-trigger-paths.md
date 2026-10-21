# #411 PR 내용과 무관하게 매번 도는 검사의 트리거 줄이기 (2026-10-21)

## 배경

public-cloud 의 Actions 분이 job 개수로 과금된다(몇 초짜리 job 도 1분). PR 푸시마다 도는 run 가운데 PR 내용과 무관하게 매번 도는 것을 트리거에서 줄였다. 판정 로직은 바꾸지 않았다. 재사용 워크플로(`.github/workflows/`)와 scaffold caller(`skeleton/dot-github/workflows/`) 양쪽을 고쳤다.

## 결정

1. **ssot-approval**: caller 의 `pull_request` 에 `paths: ['docs/ssot/**']`. `pull_request_review`·`push` 는 그대로(리뷰 이벤트는 paths 를 못 건다). SRS 를 안 바꾼 PR 에는 검사가 뜨지 않는데, 다른 검사(pr-queue 의 `GATE_GROUPS`, risk-gate 의 `EXCLUDED_CHECK_GROUPS`)는 이 검사가 실패했을 때만 승인 대기로 분류하고 있어야 한다고 요구하지 않으므로 없는 것으로 지나간다.
2. **doc-guard**: 검사 범위를 먼저 읽었다. `scripts/check_changed.py` 는 (a) `rules/*.yaml` 의 관할 glob 에 맞는 문서(skeleton 은 `docs/ssot`, `docs/spec`, `audit/changes`, `audit/ledger`), (b) `checker/code_checks.yaml` 이 아는 확장자(`.abap .js .ts .mjs .cjs .cds .asbdef`)의 코드를 **폴더와 무관하게** CR-001~ 로 검사한다, (c) 번호 짝·객체 겹침은 `docs/ssot`·`docs/spec`·`audit/ledger`, 판 번호 겹침은 `_v<판>.xlsx/.docx/.pptx` 를 본다. 그래서 paths 는 `docs/**`, `templates/**`, `rules/**`, `audit/**`, 코드 확장자 `**/*.<ext>` 7개, `**/*_v*.{xlsx,docx,pptx}` 로 했다. 코드 규칙 때문에 `src/**` 대신 확장자로 골랐다(코드가 `src/` 밖에 있어도 덮고, 이미지 같은 비검사 파일은 뺀다). 코드 파일이 바뀐 PR 에서는 여전히 돌아 절감이 줄어든다. 문서·코드 어느 쪽도 안 바꾼 PR(설정·이미지·README 등)만 안 돈다.
   - **push main 은 남겼다.** "실패하면 이슈 열기" 단계는 직접 push 만이 아니라, 무료 비공개 저장소라 branch protection 을 못 걸어 **PR 검사가 빨간 채로 병합된 경우**를 잡는 유일한 안전망이다(#95). 대신 PR 과 같은 `paths` 를 push 에도 걸어 문서·코드가 바뀐 병합에서만 돈다.
   - 새 시험 `test_trigger_paths.py` 가 paths 가 `code_checks.yaml` 의 확장자와 skeleton 규칙 관할을 덮는지 본다. 확장자나 관할이 늘면 시험이 먼저 깨진다.
3. **gitleaks**: 그대로(모든 PR·main push 에 필요).
4. **ai-review**: caller 의 `pull_request` 에 `paths: ['src/**']`. 엔진: `.github/risk-gate.yaml` 에 새 키 `ai_review_paths`(문자열 목록, 기본 `[]` = 모든 PR 이 대상). 목록이 비어 있지 않은데 PR 의 바뀐 파일 가운데 그 접두어 아래가 하나도 없으면 `ai_review` 기준이 대기 없이 통과하고(`risk_gate.ai_review_target`), `precheck-pr` 은 `enabled: false` 와 사유로 종료코드 3 을 낸다. 접두어 매칭은 `high_risk_paths` 와 같아서 `src/` 가 caller 의 `src/**` 와 같은 뜻이다. 모르는 키 오류는 유지하고 `ai_review_paths` 는 문자열 목록 검증을 한다. 위험 사유(크기·경로·비밀값)는 대상 여부와 무관하게 그대로다. scaffold 의 `risk-gate.yaml` 값은 `[src/]`. 길잡이·governance.md·README·scaffold SKILL.md 의 "모든 PR" 문구를 "코드(`src/`)를 바꾼 PR" 로 고쳤다.
5. **pr-queue**: `types` 에서 `edited`, `converted_to_draft` 제거(재사용 워크플로 머리 주석 예시, scaffold caller, 이 저장소 자신의 `pr-queue-self.yml`, 시험). 본문 `먼저:` 줄을 고쳐도 코멘트는 다음 PR·리뷰·main 이벤트까지 낡는다고 워크플로 머리 주석·governance.md·길잡이에 적었다.
6. **concurrency**: `ssot-approval.yml` 의 `check` job(PR·리뷰 전용)에 `ssot-approval-<PR 번호>` / `cancel-in-progress: true`. `doc-guard.yml`·`gitleaks.yml` 은 PR 과 main push 를 한 job 이 받으므로 group 을 `<이름>-${{ github.event.pull_request.number || github.sha }}`, `cancel-in-progress` 를 `${{ github.event_name == 'pull_request' }}` 로 둬 push 는 sha 로 겹치지 않고 취소되지 않는다. ssot-approval 의 `after-merge`(push)에는 넣지 않았다. ssot-approval 은 리뷰 이벤트도 같은 group 이라 새 리뷰가 진행 중인 PR 실행을 취소하는데, 리뷰 쪽 실행이 최신 판정이므로 옳고, 그 실행이 취소됐던 옛 실행을 다시 돌리는 기존 단계와도 충돌하지 않는다.
7. **시험**: `test_trigger_paths.py`(caller paths, concurrency, ai-review 두 설정의 일치), `test_risk_gate.py`(대상 아님 통과, 목록 비면 전과 같음, 모르는 키·잘못된 값 오류 유지, precheck), `test_pr_queue_workflow.py`·`test_scaffold.py` 를 맞췄다.

## 알려진 한계

- doc-guard 의 paths 는 caller 쪽에 복사본이라, 고객사가 `rules/` 에 `docs/`·`audit/` 밖을 관할하는 규칙을 더하면 그 caller 의 paths 도 직접 고쳐야 한다(caller 주석에 적었다).
- 이 변경을 public-cloud caller 에 적용하는 것은 그쪽 PR 로 한다(이 이슈 병합 뒤, 길잡이 갱신 이슈와 함께).
