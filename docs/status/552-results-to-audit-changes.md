# #552 개발 결과 기록을 Spec 대신 audit/changes 에 (2026-10-31)

## 배경

risk-gate 는 `docs/spec/` 아래 파일이 바뀌면 승인자 Approve 를 요구한다. 개발이 끝난 뒤 "실제로 이렇게 만들었다" 를 Spec 에 몇 줄 적는 개발 PR 도 승인을 기다렸다. 같은 내용은 `audit/changes/`(위험 경로 아님)에도 적고 있었다.

## 바꾼 것

지시문만 바꿨다. 엔진·섞임 판정 로직은 그대로다. Plugin version 0.10.141.

- 원칙: Spec 은 설계가 바뀔 때만 고친다(고치면 지금처럼 승인 대상). 개발 결과(080 반영 확인, 시험 결과, 구현하며 확정된 사항, 변경 이력의 "구현 결과 반영" 줄)는 `audit/changes/YYYYMMDD-<요약>.md` 에 종류 `구현 결과` 로만 적는다.
- Spec 에 남기는 예외: `## 사용 객체`(`checker/overlap.py` 가 읽음. 객체가 바뀌면 설계 변경이라 Spec 을 고치고 승인), `## 양식 항목` 의 변경이력(Title·Cover) 표(개발사양서 xlsx 산출 필수. 산출 PR 에서만 고침).
- "같은 DEV 의 Spec 을 같이 고치는 것은 섞임이 아니다" 는 유지하고, 결과 기록은 audit/changes 에 적는다는 점과 Spec 을 고치면 승인이 필요하다는 점을 덧붙였다.
- 고친 곳: `skills/spec/SKILL.md`, `skills/deliver/SKILL.md`, `skills/start/SKILL.md`, `rules/commit-and-pr.md`, `rules/governance.md`, scaffold skeleton(`templates/harness/spec.md`, `templates/harness/audit-change.md`, `audit/README.md`), `docs/guide/harness-guide.html`.

## 확인한 것

- skeleton 의 `rules/audit-changes.yaml` 은 파일명과 필수 절만 검사하고 `종류` 값은 검사하지 않아 규칙은 바꾸지 않았다.
- 시험은 스킬·규칙·skeleton·길잡이를 읽는 파일만 돌렸다(전체는 CI).

## 남긴 것

- 나중에 다시 볼 대안: Spec 은 처음 생길 때만 승인(엔진에서 `docs/spec/` 새 파일 추가만 승인 사유로 보고 수정은 제외). 개발 뒤 수정도 승인 없이 들어가지만 설계 큰 변경도 승인을 건너뛴다. 이번엔 하지 않았고 이 이슈를 마친 뒤 다시 본다.
- 이미 만들어진 Project Repository(public-cloud 등)의 `templates/harness/audit-change.md`·`spec.md`·`audit/README.md` 에는 `구현 결과` 안내가 자동으로 닿지 않으니 따로 맞춰야 한다(검사는 종류 값을 보지 않아 깨지지 않는다).
- version 근거: main 이 0.10.139, 열린 #550 이 0.10.140 을 쓰므로 이 PR 은 0.10.141 이다. #550 다음에 병합한다.
- 병합 뒤 길잡이 아티팩트에 다시 올려야 한다.
