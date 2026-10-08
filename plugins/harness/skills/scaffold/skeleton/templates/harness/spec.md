# DEV-000 <제목>

이 파일 하나가 개발 건 하나의 Spec 이다. 개발자는 이 문서만 보고 개발할 수
있어야 한다. 새 개발 건마다 `docs/spec/DEV-xxx-<요약>.md` 로 새 파일을
만들고, 같은 DEV 번호로 `audit/ledger/` 의 진행 원장에 등록한다.

## 근거 요구사항

이 Spec 이 구현하는 REQ 번호와 `docs/ssot/SRS.md` 링크를 적는다. 예:
REQ-012, REQ-014 ([SRS](../ssot/SRS.md))

## 개요

무엇을 왜 만드는지 한두 문단으로 적는다.

## 상세 설계

개발자가 그대로 구현할 수 있을 만큼 구체적으로 적는다. 아직 정해지지 않은
것은 추측으로 채우지 않고 "미정" 이라고 남긴다.

## 완료 조건

이 개발 건이 끝났다고 볼 수 있는 조건을 적는다.

## 참조

Convention 과 Template 은 본문에 옮겨 적지 않고 링크만 적는다. 공통 개발
규칙(harness Plugin 의 `conventions/common.md`)과 이 저장소 `conventions/`
를 함께 링크한다. 예:
[공통 개발 규칙](https://github.com/jaeheeMin/blueward-harness/blob/main/plugins/harness/conventions/common.md),
`conventions/naming.md`, `templates/`.

## 변경 이력

| 날짜 | 내용 | 변경 기록 링크 |
|---|---|---|
|  |  |  |

SRS 나 설계가 바뀌어 이 Spec 을 고칠 때마다 한 행씩 남긴다.
