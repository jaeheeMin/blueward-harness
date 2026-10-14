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
  Class, AMDP Class, CDS Table Function, Message Class, IAM App, Business
  Catalog, Launchpad App Descriptor Item 중 하나(앞의 13종과 IAM App·Business
  Catalog 는 `conventions/naming.md` 의 표기, Launchpad App Descriptor Item 은
  ADT 가 앱 디스크립터에 쓰는 이름)
- 이름: 영문자로 시작하는 객체 이름(예: `ZSD_UI_CUSTOMER`, 대소문자 무관).
  네임스페이스는 `/DMO/I_TRAVEL` 처럼 쓴다. 참조만 하는 SAP 표준 객체도 같다.
  공백·하이픈·한글은 쓸 수 없다. 이름을 모르면 추측으로 채우지 않는다
- 작업: 생성, 수정, 참조 중 하나

| 종류 | 이름 | 작업 | 비고 |
|---|---|---|---|
|  |  |  |  |

## Launchpad 노출

이 개발 건을 Launchpad 타일로 띄우면 타일마다 한 행씩 표로 적는다. 개발 단계에서 앱
디스크립터(`Launchpad App Descriptor Item`)를 만들 때 이 표를 그대로 읽는다. Launchpad 에
띄우지 않는 개발이면 이 절을 지워도 된다. 값을 모르면 추측하거나 "미정" 으로 두지 말고
사람에게 물어 채운다.

- 타일 제목·부제·아이콘(`sap-icon://…`): 타일에 보이는 글자와 그림
- 시맨틱 오브젝트: 영문자로 시작하고 영문자·숫자를 쓴다(밑줄도 허용, 예: `AnalyticQuery`)
- 액션: 소문자로 시작하는 동사나 짧은 구, 공백 없음(예: `display`, `preview`).
  영문자·숫자·밑줄만 쓴다
- 파라미터: 이동할 때 넘기는 값(예: `query=ZMM_C_STOCKLEDGERQUERY`). 없으면 비워 둔다
- 카탈로그: 타일이 들어갈 Business Catalog 이름(예: `ZMM_BC_AUTO1`)
- 배치: 어느 페이지·영역에 놓는지(예: `MM AUTO1 페이지 · 재고원장 보고서 영역`)
- 근거: SAP Help "Editing Launchpad App Descriptor Items" (검색 요약으로만 확인, 전문 미확인 —
  첫 실제 Spec 에서 대조)

| 타일 제목 | 부제 | 아이콘 | 시맨틱 오브젝트 | 액션 | 파라미터 | 카탈로그 | 배치 |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

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
