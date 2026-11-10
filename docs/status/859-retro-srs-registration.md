# #859 SRS 없이 끝난 개발의 요구사항 사후 등록 경로 (2026-11-10)

## 배경

public-cloud DEV-010(이슈 #340)·DEV-011(이슈 #366)은 SRS 요구사항(REQ) 없이 개발이 끝났다. #845(v0.10.241)부터 REQ 없는 Spec 은 `spec-ready` 위반이라 담당자가 REQ-010·011 을 사후 등록해야 한다. 가능은 했지만 스킬에 안내가 없어 정확한 말을 해야만 맞는 경로를 탔다.

- `reserve` 로 가면 새 번호(REQ-015 이상)가 나와 RICEFW ID(DEV-010)와 어긋난다(`pairing` 의 `ricefw_mismatch`).
- "기존 개발의 일부" 를 고르면 없는 REQ 의 범위를 넓히려 든다.
- 원장 `완료` 인 DEV 의 Spec 을 쓰면 deliver 가 `리뷰` 로 되돌리거나 되돌릴지 물었다.

## 바꾼 것

- `plugins/harness/skills/srs/SKILL.md`: description 에 "DEV-010 사후 등록" 트리거, "SRS 를 거치지 않고 끝난 개발의 사후 등록" 절 추가(`list` 의 `req` 키 없는 DEV 가 후보 → 그 `[DEV-xxx]` 이슈를 `claim --issue N` → 같은 번호 REQ, 다음 단계 `개발`, RICEFW ID 같은 번호, Status 는 실제 상태, 원장·Spec 은 건드리지 않음). 이 경우 "기존 개발과의 관계" 질문은 건너뛴다. 질문이 나와도 "새 개발" 답은 그대로 통한다.
- `plugins/harness/skills/spec/SKILL.md`·`start/SKILL.md`·`deliver/SKILL.md`: 원장 `완료` 인 DEV 의 Spec 작성·수정은 상태를 바꾸지 않고(`진행`·`리뷰` 로 바꾸지도, 되돌릴지 묻지도 않고) Spec 칸만 채운다.
- `docs/guide/harness-guide.html`(SRS 만들기·Spec 만들기 탭), `console/whats_new.json`, plugin.json 0.10.249.
- `checker/tests/test_pairing.py`: 사후 등록 시나리오(REQ-010 이 RICEFW DEV-010, 원장 `완료`, Spec 있음)에서 pairing 위반·경고가 없는 시험.

## 코드가 아니라 문서인 이유

deliver 의 원장 갱신은 스크립트가 아니라 스킬 문서의 절차이고(`audit/ledger/` 를 Claude 가 고친다), `완료` 를 뒤로 돌리는 코드는 없다. 엔진의 `ledger_stale`·`ledger_complete` 는 대표 이슈를 닫는 PR 의 행이 `완료` 인지만 보고 `완료` 를 되돌리는 쪽은 검사하지 않는다.

## 이미 안내된 방법과의 호환

담당자에게 메일로 안내한 순서(이슈 번호로 `claim --issue 340`, REQ-010 작성, 다음 단계 개발, RICEFW ID DEV-010, Status Done, 관계 질문에 "새 개발", 원장 상태를 물으면 "아니오(완료 유지)")는 그대로 통한다. claim 경로와 관계 질문은 없애지 않았다.

## 남은 일

DEV-010·011 의 실제 등록은 public-cloud 담당자가 한다(이 저장소 밖).
