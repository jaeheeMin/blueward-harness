# DEV-000 <제목>

이 파일 하나가 개발 건 하나의 Spec 이다. 개발자는 이 문서만 보고 개발할 수
있어야 한다. 새 개발 건마다 `docs/spec/DEV-xxx-<요약>.md` 로 새 파일을
만들고, 같은 DEV 번호로 `audit/ledger/` 의 진행 원장에 등록한다.

## 근거 요구사항

이 Spec 이 구현하는 REQ 번호 하나와 `docs/ssot/SRS.md` 링크를 적는다. Spec 의
DEV 번호는 이 REQ 의 번호와 같다(REQ-012 → DEV-012). 예:
REQ-012 ([SRS](../ssot/SRS.md))

## 개요

무엇을 왜 만드는지 한두 문단으로 적는다.

## 상세 설계

개발자가 그대로 구현할 수 있을 만큼 구체적으로 적는다. 아직 정해지지 않은
것은 추측으로 채우지 않고 "미정" 이라고 남긴다.

## 사용 객체

이 개발 건이 만들거나 고치거나 읽기만 하는 SAP 객체를 표로 적는다. 다른 개발 건과
같은 객체를 겹쳐 쓰는지 기계가 읽어 비교하므로 형식을 지킨다. 쓰는 객체가 없으면
표를 비워 둔다.

- 종류: Domain, Data Element, Structure, Database Table, CDS View, Metadata
  Extension, Behavior Definition, Service Definition, Service Binding, ABAP
  Class, AMDP Class, CDS Table Function, Message Class 중 하나
  (`conventions/naming.md` 의 표기)
- 이름: 영문자로 시작하는 객체 이름(예: `ZSD_UI_CUSTOMER`, 대소문자 무관).
  네임스페이스는 `/DMO/I_TRAVEL` 처럼 쓴다. 참조만 하는 SAP 표준 객체도 같다.
  공백·하이픈·한글은 쓸 수 없다. 이름을 모르면 추측으로 채우지 않는다
- 작업: 생성, 수정, 참조 중 하나

| 종류 | 이름 | 작업 | 비고 |
|---|---|---|---|
|  |  |  |  |

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
