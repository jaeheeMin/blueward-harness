# #751 — Launchpad 시맨틱 오브젝트·액션 규칙을 SAP 문서와 실제 값에 맞추기

## 무엇을 왜
- `conventions/naming.md` 5.4 절이 Action 을 Upper Camel Case(`List`)로 쓰라고 해서, 규칙대로 쓰면 Spec 검사(액션은 소문자 시작)가 거절했다. 소문자로 시작하는 camelCase(`list`, `display`, `detail`)로 고쳤다.
- spec 스킬에 "앱 디스크립터를 쓸 때 SAPUI5 App ID(SAP 필수값)를 묻고 추측하지 않는다" 를 더했다. 표 열은 늘리지 않았다(옛 Spec 이 깨진다).
- 시맨틱 오브젝트의 밑줄은 **허용을 유지**했다. 처음에는 SAP 문서(영문자·숫자만)에 맞춰 밑줄을 거절하려 했다. 그런데 public-cloud 의 실제 앱 두 개가 밑줄을 쓰고 실제로 열린다(DEV-003 `ZMM_StockLedger`, DEV-008 배포 자동 생성 디스크립터의 `ZPP_AUTO1_PRODUCT_STATUS`). 실제 값을 거절하는 쪽이 더 나빠서, 사용자 결정(2026-11-07)으로 넓게 두고 근거를 `rules/spec.yaml` 주석에 남겼다. 새로 지을 때는 영문자·숫자만 쓰라고 naming.md 와 spec 스킬에 적었다.
- 길잡이 Spec 설명(`docs/guide/harness-guide.html`)도 같은 내용으로 고쳤다.

## SAP 문서 근거
Editing Launchpad App Descriptor Items(https://help.sap.com/docs/abap-cloud/abap-development-tools-user-guide/editing-launchpad-app-descriptor-items), 2026-11-07 전문 확인.
- Semantic Object: "The following characters are allowed: uppercase letters [A-Z], lowercase letters [a-z], numbers [0-9]. The first character must be an uppercase or lowercase letter." (Mandatory)
- Action: "choose a verb or a short phrase starting with lower case and without blanks". 허용 문자는 영문자·숫자·밑줄이다. (Mandatory)
- SAPUI5 App ID: Mandatory

**테넌트에서 확인(2026-11-07, 100 `abap-adt-z5u`, 읽기 전용 `getObjectSource`).** 앱 디스크립터 `ZPP_AUTO1_010_UI5R` 소스에 `"semanticObject":"ZPP_AUTO1_PRODUCT_STATUS"` 가 있다. 이 디스크립터는 배포로 자동 생성된 `_UI5R` 이고 `appId` 는 `zppauto1010` 이다. 밑줄 든 시맨틱 오브젝트가 실제 SAP 에 존재한다는 뜻이다. DEV-003 의 `ZMM_StockLedger` 는 Spec 기록(100 에서 `ZMM_StockLedger-display` 로 열림)으로만 확인했다. 문서 규칙이 ADT 에서 손으로 만들 때의 입력 규칙이고 배포 자동 생성 경로는 다르다는 해석은 추측이다.

## 시험
`checker/tests/test_md_table.py`
- 밑줄 시맨틱 오브젝트 통과: 기존 시험을 유지했다.
- 새 시험: `SalesOrder1` + `display` 통과, 액션 `_x` 위반.

Plugin version 0.10.200.
