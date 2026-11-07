# #718 — SRS 다음 단계 `표준` 추가, 설정·표준 건은 SRS Status 로 진행 관리

사용자 결정(2026-11-05): 다음 단계를 개발 / 설정 / 표준 / 미정 넷으로. 개발이 아닌 건(설정·표준)은 진행 원장이 아니라 SRS 의 Status 칸(New → Planned → In Process → Done, On Hold/Dropped/Duplicate)으로 진행 관리한다. 원장은 개발 건만. 원장이 있든 없든 같은 동작.

## 바뀐 곳
- 엔진 `checker/pairing.py`: `NEXT_STEPS` 에 `표준`, `NON_DEV_STEPS`(설정·표준·미정)는 RICEFW ID 빈칸(`ricefw_not_empty`). `no_ledger_config` 경고 제거(설정·표준 건은 원장 줄이 없는 게 정상). `non_dev_numbers()` 추가(SRS 글에서 설정·표준 REQ 번호).
- 엔진 `checker/spec_ready.py`: base SRS 의 `다음 단계` 가 설정·표준인 DEV/REQ 도 설정 건(개발 아님)으로 본다. 원장 Spec 칸 `설정` 도 계속 인정. SRS 가 base 에 없거나 열이 없으면 원장 판정만 남고, 읽다 실패하면 검사 불능.
- 콘솔 서버 `devready.py`: `is_setup` = SRS 다음 단계 설정·표준 또는 옛 원장 Spec 칸 `설정`. 응답에 `standard`(표준 건 수)와 항목별 `standard` 추가. 원장이 없어도 `docs/ssot/SRS.md` 가 있으면 읽는다(전엔 `no`).
- `workflow.json`: `branches` 에 `표준`(flow `standard`), `standard` 갈래 추가, `config` 갈래의 원장 단계를 SRS Status 단계로, quote 를 바뀐 SKILL 문장에 맞춤.
- 스킬: `srs`(다음 단계 표에 `표준`, "설정·표준 요구사항" 절을 Status 로), `spec`, `start`("설정·표준 건" 절, `next_step` 로 판정; `reserve_number.py` 는 이미 `next_step` 을 내보내 코드 변경 없음).
- 템플릿: scaffold `SRS.md`(넷), `audit-ledger.md`(설정·표준은 원장에 올리지 않음). `rules/ssot.yaml`·`rules/README.md` 는 `다음 단계` 열 이름만 말해 바꿀 문장이 없었다.
- 문서: `checker/README.md`, `checker/export.py` 주석, `spec/form-map.md`, `docs/guide/harness-guide.html`(다음 단계 표·SRS 흐름·start·spec-ready·용어집), `docs/design/web-console.md`.
- `plugin.json` 0.10.194, `whats_new.json` 0.10.194.

## 호환 결정과 이유
- 원장 Spec 칸 `설정` 은 읽기만 계속 인정한다(spec_ready 의 config 판정, devready, pairing 의 `spec_cell_config` 경고, 링크 검사 제외). 이유: public-cloud 원장엔 `설정` 행이 0개지만 다른 Project Repository 는 확인하지 못했다. 새로 `설정` 줄을 쓰라는 안내만 없앴다.
- SRS 판정이 먼저, 원장은 보조. 둘이 어긋나면(SRS 개발, 원장 `설정`) pairing 은 기존처럼 경고만 낸다.
- Status 값 목록(New/Planned/In Process/Done/On Hold/Dropped/Duplicate) 검사는 넣지 않았다. 이유: Backlog 양식 Status 가 고객사 양식의 드롭다운이라 값이 다를 수 있고(옛 `유효`·`변경됨`·`폐기`), 이미 `form_columns` 와 export 가 양식 허용 값으로 대조한다. 엔진이 따로 막으면 기존 데이터가 깨진다.
- `pairing` 은 `audit/ledger/` 가 없으면 건너뛴다(기존 동작). 그래서 원장 없는 저장소에서는 `표준` 값 검사(`next_step_invalid`)가 안 돈다. 원장 없는 저장소의 다음 단계 값 검사는 따로 이슈감.

## #598
이슈의 "표준 기능" 은 이번 `표준` 다음 단계로 흡수한다. `교육` 등 다른 값은 범위 밖.

## 열어 둔 것
- 설정·표준 건도 작업 이슈 제목은 `[DEV-xxx]` 번호를 그대로 쓴다(REQ 와 같은 번호). 원장 줄은 안 만든다. 이슈 제목 표기를 `[REQ-xxx]` 로 바꿀지는 정하지 않았다.
- Status `In Process` 는 작업 브랜치의 SRS 에 쓰므로 병합 전에는 main 에 안 보인다.
- `ledger-ready` 검사(대표 이슈 Closes 시 원장 `완료`)와 deliver 는 원장 줄이 없는 설정·표준 건에서 통과(원장 줄 없음)로 가는지 별도 확인 필요.

## 콘솔 화면 남은 일(다른 PR 이 static 을 고치는 중이라 이번엔 안 건드림)
- `flow-logic.js:372` "설정 건 N개" 표시: 표준 건도 `standard` 로 구분해 "표준 건 N개".
- `app.js` 새 작업 종류 버튼 '설정하기' 옆에 표준 기능 종류 추가, `standard` 갈래로 시작.
- 설정·표준 건 진행을 SRS Status(`In Process`/`Done`) 로 보이기.

## 메인 세션 리뷰 (2026-11-06)

- 구현은 "SRS 가 먼저, 원장 `설정` 은 보조" 라고 했지만 `spec_ready` 는 원장 `설정` 과 SRS 설정·표준을 합집합으로 봤고 `devready` 도 같았다. 원장에 설정으로 적었다가 SRS 에서 개발로 바꾼 건이 개발 PR 에서 "설정 건" 으로 막히고 콘솔에서도 설정 건으로 셌다.
- 고침: SRS 가 그 번호를 `개발` 로 정했으면 옛 원장 `설정` 은 무시한다(`spec_ready._srs_step_numbers`, `devready` 의 `step != 개발` 조건). 시험 `test_SRS_가_개발로_바꾼_건은_옛_원장_설정이어도_설정으로_막지_않는다`, `test_dev_ready_srs_dev_overrides_old_ledger_setup` 추가. 엔진 시험 파일 5개 167 통과.
