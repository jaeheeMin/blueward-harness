# CAP · SAPUI5 개발 표준

블루어드 사내 표준 — CAP·SAPUI5 개발표준 정의서 v1.0 을 정리하고, SAP 공식 문서에
맞춰 고쳤다(2026-11-14).

사내 기본값이다. 고객사 표준이 정해지면 이 파일을 고친다. 공통 개발 규칙과
부딪히면 이 파일이 이긴다(CR-004 제외).

CAP 프로젝트(BTP Side-by-Side Extension)와 그 안의 SAPUI5 앱에 적용한다.
CAP 프로젝트가 아니면 별도 개발 표준 문서를 만들어 적용한다. 프로젝트 상황에
따라 고쳐야 하면 이 문서를 기준으로 프로젝트 개발 표준을 만든다. 원문에 있던
코드 예시·화면 그림은 옮기지 않았다.

`<회사약어>` 는 이 표준을 쓰는 회사의 약어, `<프로젝트 접두어>` 는 프로젝트가
정하는 접두어 자리표시다.

## 0. 읽는 법

### 0.1 근거 표시

규칙은 다음 순서로 근거를 잡았다. ① SAP 공식 앱 개발 문서(SAPUI5 SDK, CAP 문서,
Fiori Design Guidelines) ② SAP 공식 지침·도구(openui5 `guidelines.md` 의 "strong
recommendation", Fiori tools eslint 규칙) ③ public-cloud 실제 코드 ④ 사내 정의서.
각 규칙 옆에 `(SAP 공식: <문서명>)` 또는 `(사내 규칙)` 을 적었다. 문서 이름의 URL 은
맨 끝 "근거" 절에 있다.

### 0.2 기계 검사 세기

규칙 옆 표시는 PR 과 저장 직전 훅에서 어떻게 검사되는지를 뜻한다. 이름은 새로 만든 객체만, 코드는
PR 에서 추가·변경된 줄만 본다.

| 표시 | 뜻 |
|---|---|
| `[막기]` | 위반이면 검사가 실패한다. console.* 사용, `==`/`!=` 사용, Control ID 의 하이픈, 화면 XML 에 한글 직접 쓰기 |
| `[경고]` | 기계로 판정할 수 있어 경고만 낸다. 병합은 막지 않는다 |
| `[리뷰]` | 지금은 사람이 리뷰에서 본다(맥락이 필요하거나 아직 기계 검사를 만들지 않았다) |

검사는 프로젝트에 `conventions/cap-ui5.yaml` 이 있을 때 켜진다(예시는 하네스의
`conventions/cap-ui5.example.yaml`). 파일이 없으면 검사하지 않고, 있는데 못 읽으면
검사 불능이다. 규칙별 심각도와 예외 경로는 그 파일에서 바꾼다.

| 규칙 id | 검사 | 기본 |
|---|---|---|
| UI5-001 | `console.*` 호출 | 막기 |
| UI5-002 | `==` / `!=` | 막기 |
| UI5-003 | Control ID 의 하이픈 | 막기 |
| UI5-004 | 화면 XML 속성에 한글 직접 쓰기 | 막기 |
| UI5-101 | `icon` 속성이 `sap-icon://`·URL 이 아님 | 경고 |
| UI5-102 | 자기 닫힘 `/>` 앞 공백 | 경고 |
| UI5-103 | DOM 직접 접근(`document.getElementById` 등) | 경고 |
| UI5-104 | UI5 private(`_` 로 시작) 멤버 사용 | 경고 |
| UI5-105 | 들여쓰기에 공백 사용 | 경고 |
| UI5-106 | 지역변수 이름 접두어 | 경고 |
| UI5-108 | i18n 키 형식 `[화면].[Type].[key]` | 경고 |
| UI5-109 | i18n 문구 윗줄 텍스트 종류 주석 | 경고 |
| UI5-110 | i18n 한글 메시지 `~세요.`·`~주시오.` 끝맺음 | 경고 |

## 1. 개요

- 목적: CAP Project 의 표준을 세워 적용해 개발한 코드의 일관성과 목표 시스템의
  품질 수준을 높인다. `[리뷰]` (사내 규칙)
- Backend Service(OData Service)와 Front App(UI)은 SAP BTP 의 통합개발환경
  BAS(Business Application Studio)로 개발한다. 원칙은 BAS 사용이다. `[리뷰]` (사내 규칙)

### 1.1 프로그램 항목별 언어

| 구분 | 세부 항목 | 표준 언어 |
|---|---|---|
| Backend Service | 소스 주석 | 한글/영문 |
| Backend Service | 메시지 | 다국어(한글 기본) |
| Front App | 소스 주석 | 한글/영문 |
| Front App | 화면(Title, Label 등) 항목 | 다국어(한글 기본) |
| Front App | 메시지 | 다국어(한글 기본) |

## 2. 형상관리

- 소스코드는 GitHub 로 관리한다.
- Repository 는 용도로 나눈다.

| 용도 | 담는 것 |
|---|---|
| CAP(Side-by-Side Extension) Project 저장소 | CAP Project 로 개발한 소스코드 |
| RAP(Developer Extension) Project 저장소 | RAP Project 로 개발한 소스코드 |

- 단일 Repository 안에 CAP Project 를 여럿 둔다. 개별 CAP Project 는 독립된 폴더에
  만드는 것이 기본이다.
- 같은 Repository 의 CAP Project 가 공통으로 참조해야 하는 DB Deployer 를 뺀,
  다른 CAP Project 끼리의 상호 참조는 원칙적으로 금지한다.
- 최상위 폴더에는 개별 CAP Project 를 담는 폴더, `.gitignore`, `README.md` 외의
  폴더·파일을 추가하지 않는다.
- SAP Integration Suite, SAP Build Process Automation 에서 만든 코드는 형상관리
  대상에서 제외한다.

(이 절은 모두 사내 규칙, `[리뷰]`)

## 3. CAP Project 구조

| 경로 | 내용 |
|---|---|
| `app/` | UI5 App 을 두는 최상위 경로. UI5 App 은 개별 폴더로 구성 |
| `db/` | 프로젝트에서 공통으로 쓰는 정의(Domain CDS) 파일 |
| `srv/` | Service Definition & Implementation 파일 |

- Project 의 용도에 따라 폴더(`app`, `db`, `srv`) 삭제는 허용한다. 같은 목적의
  프로그램을 여러 Project 로 나누는 것은 금지한다.
- HDI Container 로 Database Schema 를 만들어 쓴다. HDI Container Instance 는
  Repository 에 있는 container-deployer Project 로 이미 만들어져 있으므로, 그
  Project 를 이용한 추가 작업은 금지한다.
- DB Deployer Project 구성: `db/schema.cds`(Domain 정의 기본 예시), `db/undeploy.json`
  (Undeploy(Domain) 정의), `mta.yaml`(Application Deploy Descriptor). DB Deployer 가
  더 필요하면 기존 entity-deployer 를 참고해 만든다.

(이 절은 모두 사내 규칙, `[리뷰]`)

## 4. 이름 규칙

### 4.1 Project · Folder · CDS

| 대상 | 형식 | 표기법 | 예시 | 근거 · 검사 |
|---|---|---|---|---|
| Project Folder | `<프로젝트 접두어>` + [단어][단어]... | Upper CamelCase | `<프로젝트 접두어>CustomerManagement`, `<프로젝트 접두어>OrderManagement` | 사내 규칙 `[리뷰]` |
| UI5 App Folder (CAP 프로젝트 `app/` 안) | [단어][단어]... + `App` | Lower CamelCase | `customerManagementApp`, `orderManagementApp` (원문 예시는 `<프로젝트 접두어>CustomerManagement`; 형식에 맞춰 바꾼 예시) | 사내 규칙 `[리뷰]` |
| UI5 App Folder (ABAP 에 배포하는 앱, `src/ui5/`) | `naming.md` 5.2 형식(`z` + 영역 + `u` + 번호) | - | `zppu0010` | 사내 규칙 `[리뷰]` |
| Project name | Project folder name 과 같게. 임의 변경 불허 | - | - | 사내 규칙 `[리뷰]` |
| Domain 파일 | 기본 예시는 `schema.cds` | Lower case | - | 사내 규칙 `[리뷰]` |
| Namespace (Domain) | `<회사약어>` 또는 `<회사약어>.<모듈>` 둘 다 허용. 임의 수정 불허 | - | - | 사내 규칙 `[리뷰]`. 참고: CAP 은 조직 이름처럼 바뀔 수 있는 말을 namespace 에 쓰지 말라고 한다(SAP 공식: CAP Domain Modeling) |
| Context | [단어] | Lower Case | `common`, `expense`, `financial` | 사내 규칙 `[리뷰]` |
| Entity (Domain) | 대문자로 시작하는 복수형 | Upper CamelCase | `Customers`, `Orders` | SAP 공식: CAP Domain Modeling `[리뷰]` |
| element (Domain) | 소문자로 시작 | Lower CamelCase | `deliveryDate`, `orderDate` | SAP 공식: CAP Domain Modeling `[리뷰]` |
| type (Domain) | 단수형 | Upper CamelCase | `Address` | SAP 공식: CAP Domain Modeling `[리뷰]` |
| Service Definition 파일 | 서비스별 이름 `<이름>-service.cds` | - | `OrderManagement-service.cds` | SAP 공식: CAP Core Services(예 `cat-service.cds`) `[리뷰]` |
| Service Implementation 파일 | Service Definition 과 같은 이름에 확장자만 `.js` | - | `OrderManagement-service.js` | SAP 공식: CAP Core Services `[리뷰]` |
| service | [단어][단어]... + `Service` | Upper CamelCase | `OrderService`, `DeliveryService` | SAP 공식: CAP Core Services(`service CatalogService`) `[리뷰]` |
| entity (Service) | [단어][단어][단어]... | Upper CamelCase | `Books`, `Authors`, `Orders` | SAP 공식: CAP Domain Modeling `[리뷰]` |
| action | [단어][단어][단어] | Lower CamelCase | `addCustomer`, `createOrder`, `cancelOrder` | 사내 규칙(CAP 공식 예시 `cancelOrder` 와 같다) `[리뷰]` |
| function | [단어][단어][단어] | Lower CamelCase | `getStock`, `sum`, `countOrders` | 사내 규칙(CAP 공식 예시 `countOrders` 와 같다) `[리뷰]` |

- Domain CDS 는 업무 영역 구분이 필요하면 `context` 구문을 쓴다. 이름은 전체 30자를
  넘지 않게 구성한다. HANA 식별자 한도는 127자(SAP 공식)이고, 30자는 사내 규칙이다.
  `[리뷰]` (사내 규칙)
- Domain CDS 로 만들어지는 DB Object 의 이름은 Namespace, Context, Entity name 을
  조합하므로 전체 길이를 고려해 명명한다. `[리뷰]` (사내 규칙)
- Service Definition 은 용도별로 서비스를 나눠야 하면 `service` 구문으로 나눈다.
  `schema.cds` 한 개와 서비스별 `<이름>-service.cds` 를 두는 것이 기본 구성이다.
  `[리뷰]` (SAP 공식: CAP Core Services)
- action 은 데이터 처리(CUD) 기능을 제공할 때, function 은 데이터 조회(R) 기능을
  제공할 때 쓰기를 권장한다. `[리뷰]` (사내 규칙)
- Service Implementation(.js)은 Custom Logic 이 필요한 경우에만 선언한다. `[리뷰]`
  (사내 규칙)

### 4.2 UI5 Application

공통:

- 특별한 경우를 빼고 최대 15자를 넘지 않게 한다. `[리뷰]` (사내 규칙)
- 형식에 구분자가 있거나 표기법이 지정된 경우를 빼고는 Lower CamelCase 로 쓴다.
  `[리뷰]` (사내 규칙)
- 단어를 쓰거나 상세를 적을 때는 의미를 짐작할 수 있게 짓는다. `[리뷰]` (사내 규칙)

| 대상 | 형식 | 표기법 | 예시 | 근거 · 검사 |
|---|---|---|---|---|
| Control ID | 하이픈 없는 lowerCamel. 뜻이 보이게 짓는다. Control 약어는 넣어도 빼도 된다 | Lower CamelCase | `goodsNameInput`, `listBtnSearch`, `mainTblList`, `detailMiEmail` | SAP 공식: SAPUI5 ID Handling(하이픈은 UI5 가 붙이는 구분자라 쓰지 않는다). 하이픈 `[막기]`, 나머지 `[리뷰]` |
| Constant | 대문자와 밑줄. `CONST_` 접두어를 붙인 형태와 붙이지 않은 형태 둘 다 허용 | Upper Case | `CONST_MAX_COUNT`, `CONST_LIMIT`, `MAX_LENGTH`, `SUCCESS` | 사내 규칙 `[리뷰]` |
| Variable | [Datatype Prefix][단어][단어] | 접두어 뒤 대문자로 이어 쓰는 camelCase | `sId`, `oUserInfo`, `iCount`, `aRow`, `dToday`, `fRate`, `bEnabled`, `rDate`, `vVariant` | SAP 공식: openui5 guidelines.md(강한 권장) `[경고]` |
| Event handler | `on` 으로 시작. Control 약어를 넣은 `on` + [Control 약어] + [Event Name] 과 약어 없는 `on` + [기능] + [Event Name] 둘 다 허용 | `on` 뒤는 Upper CamelCase | `onBtnSavePress`, `onNewItemPress`, `onTblCellClick`, `onItemSelected` | 사내 규칙 `[리뷰]` |
| 내부(private) 함수 | `_` 로 시작 하나 + [동사][단어][단어] | 동사, 단어는 Lower CamelCase | `_searchUserList`, `_calcAmount`, `_getAccessToken` | SAP 공식: openui5 guidelines.md(private 은 `_`) `[리뷰]` |
| Parameter | Variable 과 같게 적용 | - | - | 사내 규칙 `[리뷰]` |

- 고정(stable) ID 를 다는 것이 기본이다. 뷰와 Fragment 에서 만드는 Control 에는 뜻이
  보이는 ID 를 붙인다. `[리뷰]` (SAP 공식: SAPUI5 Use Stable IDs)
- ID 는 unique 하게 쓴다(Copy & Paste 때 주의). `[리뷰]` (SAP 공식: SAPUI5 ID Handling)

Control 약어(쓸 때 참고. 약어는 넣어도 빼도 된다. 사내 규칙).

| Control | 약어 | Control | 약어 |
|---|---|---|---|
| `sap.ui.table.Table` | `tbl` | `sap.m.MaskInput` | `mi` |
| `sap.m.Button` | `btn` | `sap.m.DatePicker` | `dp` |
| `sap.m.Toolbar` | `tbar` | `sap.m.CheckBox` | `cbx` |
| `sap.m.Panel` | `pnl` | `sap.m.VBox` | `vbx` |
| `sap.m.Label` | `lbl` | `sap.m.HBox` | `hbx` |
| `sap.m.Input` | `inp` | `sap.m.RadioButton` | `rb` |

Variable Datatype Prefix (SAP 공식: openui5 guidelines.md. 강한 권장이지 의무는 아니다).

| Type | Prefix | Type | Prefix |
|---|---|---|---|
| String | `s` | Boolean | `b` |
| Object | `o` | Regular Expression | `r` |
| jQuery object | `$` | Function | `fn` |
| Integer | `i` | Variant types | `v` |
| Map / associative array | `m` | Promise | `p` |
| Array | `a` | Date | `d` |
| Float | `f` (소문자) | | |

- `fn` 은 함수를 담는 변수의 접두어다(내부 함수의 이름 규칙이 아니다). 내부 함수는
  위 표의 `_` 로 시작하는 규칙을 따른다.

### 4.3 다국어 Properties

- Key 는 `[화면].[Type].[key]` 로 구성한다. 화면은 화면(View) 이름이다. Type 은
  title·label·text·button·message·column·dialog 등이다. key 는 카멜 표기법으로
  쓰고, 값에 해당 언어 텍스트를 적는다. `[경고]` (사내 규칙)

| Type | 예 |
|---|---|
| Title | `main.title.empDetailInfo=임직원상세정보` |
| Label | `main.label.empNm=직원이름` |
| Text | `main.text.summCont=요약정보를 다음과 같이 기술합니다……….` |
| Button | `detail.button.uploadFiles=파일업로드` |
| Message | `detail.message.requiredTitle=제목을 입력하십시오.` |
| argument 전달 | `detail.message.procResult={0}건 중 {1}건이 완료처리 되었습니다.` |

- 문구마다 윗줄에 텍스트 종류 주석을 단다. 형식은 `#<종류>[,<길이>][:<번역자 메모>]`
  이다. `[경고]` (SAP 공식: openui5 translationfiles.md)

| 종류 | 뜻 | 종류 | 뜻 |
|---|---|---|---|
| `#XBUT` | 버튼 | `#XTIT` | 제목 |
| `#XFLD` | 라벨 | `#XMSG` | 메시지 |
| `#XTOL` | 툴팁 | | |

  예:

```
#XBUT,20: 저장 버튼
detail.button.save=저장
#XMSG
detail.message.requiredTitle=제목을 입력하십시오.
```

## 5. 코드 작성 규칙

### 5.1 기본

- 전역변수를 만들지 않는다. 모듈(`sap.ui.define`)로 감싼다. `[리뷰]` (SAP 공식: openui5
  guidelines.md, Fiori tools eslint `sap-no-global-variable`)
- 동적 Control 을 만들 때는 Controller 의 `createId()` 로 ID 를 만든다. `[리뷰]`
  (SAP 공식: SAPUI5 ID Handling)
- 해당 Controller 에서만 쓰는 private 변수·함수의 이름은 underscore(`_`)로 시작한다.
  예: `this._bFinalized`, `this._reRenderTable()` `[리뷰]` (SAP 공식: openui5 guidelines.md)
- DOM 을 직접 다루지 않는다(`document.getElementById` 등). Control 은 `this.byId()` 등
  UI5 API 로 가져온다. 꼭 DOM 이 필요하면 jQuery 선택자를 쓰고, ID 에 특수문자가 있을
  수 있으면 `jQuery(window.document.getElementById(sId))` 로 감싼다. `[경고]` (SAP 공식:
  Fiori tools eslint `sap-no-dom-access`, openui5 guidelines.md)
- logging 은 `console.log()` 대신 `sap.base.Log` 의 info/debug/warning/error/fatal 을
  쓴다. `[막기]` (SAP 공식: Fiori tools eslint `sap-no-console-log`)

### 5.2 들여쓰기 · 빈 줄 · formatting

- 들여쓰기는 탭 문자로 한다. 칸 수는 정하지 않으며, 파일 안의 기존 방식이 다르면 그
  방식을 따른다. `[경고]` (SAP 공식: openui5 guidelines.md)
- Control 이 같은 레벨이면 Tab 개수를 같게 하고, 하위 레벨이면 1 Tab 더 들여쓴다.
  `[리뷰]` (사내 규칙)
- Control 의 Attribute 가 많으면 줄을 바꾼 뒤 같은 Tab 개수를 적용한다. `[리뷰]` (사내 규칙)
- Control 간 구분을 위한 빈 줄은 하나까지 허용하고 그 이상은 두지 않는다. `[리뷰]` (사내 규칙)
- 모든 구문 뒤의 세미콜론을 생략하지 않는다. `[리뷰]` (SAP 공식: openui5 guidelines.md)
- 소괄호 앞에는 space 를 두지 않는다. `[리뷰]` (SAP 공식: openui5 guidelines.md)
- `if/else/for/while/do/switch/try/catch/finally` 뒤, 중괄호와 연산자 앞뒤, 콤마 뒤에는
  space 를 둔다. `[리뷰]` (SAP 공식: openui5 guidelines.md)
- `function/for/if-else/switch` 와 중괄호 시작은 같은 줄에 둔다. `[리뷰]` (SAP 공식:
  openui5 guidelines.md)
- 값 비교는 `===`, `!==` 를 쓴다. `[막기]` (SAP 공식: openui5 guidelines.md, Fiori tools
  eslint `eqeqeq`)

### 5.3 주석

- 주석에 중요정보(ID, Password, 사번, 접속정보)를 남기지 않는다. `[리뷰]` (사내 규칙)
- XML: 주석은 `<!-- Comments -->` 형태로, 하이픈 두 개와 주석 사이에 space 를 한 칸씩
  둔다. View, Fragment, Block 최상단에 화면 설명을 한 줄로 적는다. View 코드의 시작
  주석과 종료 주석을 둔다. `[리뷰]` (사내 규칙)
- JS: `/*** Comments ***/` 형태로, 주석과 space 를 한 칸씩 둔다. Controller 최상단에
  헤더 주석으로 요약 정보를 적고, Controller 함수 위에 함수 정보를 적는다.
  getter method 는 기능 설명, `@param {type} paramName 내용`, `@return {namespace} 내용`,
  setter method 는 기능 설명, `@param {type} paramName 내용`. `[리뷰]` (사내 규칙)
- Properties: 문구 윗줄에 텍스트 종류 주석을 단다(4.3 참조).

## 6. 프로그램 요소 작성 규칙

### 6.1 기본

- MVC(Model-View-Controller) 패턴으로 개발하기 위해 표준 Project 구조를 지킨다. `[리뷰]` (사내 규칙)
- Controller 를 만들 때 `BaseController.js` 를 extend 해 공통 함수를 쓸 수 있게 한다.
  `[리뷰]` (사내 규칙)
- 공통 Library 의 함수를 최대한 써서 코드 작성 패턴을 정형화한다. 예: Model(Model,
  ODataModel 처리), Nav(navigation 처리), Formatter(Data format 처리). `[리뷰]` (사내 규칙)
- Custom Controller 는 UI5 범위를 벗어난 새 기능을 구현할 때 쓴다. `[리뷰]` (사내 규칙)
- 초기화, instance 필드 기술 등은 생성자 function 으로 처리한다. 예: `this._bReady = false;`
  `[리뷰]` (사내 규칙)
- Label, Text, Message 는 다국어 처리가 원칙이다. 화면 XML 에 한글을 직접 쓰지 않고
  `{i18n>key}` 로 쓴다. `[막기]` (SAP 공식: openui5 guidelines.md "all texts visible in
  the UI must be translatable", Fiori tools eslint `sap-not-localized`)

### 6.2 View

App 유형.

| 유형 | 설명 |
|---|---|
| WorkList Type | 사용자가 처리할 항목 모음이 표시되며, 보통 목록 항목의 세부 정보를 검토하고 조치를 수행하는 형태 |
| Master/Detail Type | 유연한 Column layout type 으로 Single Page 에 여러 화면 칼럼을 표시한다. Master 화면에서 여러 Detail 화면으로 navigation 하며, 일반적인 페이지별 navigation 보다 화면 간 이동이 빠르고 유연하다 |

화면 코딩.

- Aggregation 이 없는 XML Element 를 닫을 때는 Close Tag 대신 `/` 를 쓰고, `/` 앞에
  공백을 두지 않는다. 예: `<Button id="mainBtnSave" text="{i18n>main.button.save}" press="onBtnSavePress"/>`
  `[경고]` (사내 규칙)
- Control 의 icon 속성(소문자 `icon`)은 `sap-icon://` 를 붙여 쓴다. 예
  `<Button icon="sap-icon://accept"/>`. 그림 파일의 URL 도 넣을 수 있다. `[경고]`
  (SAP 공식: SAPUI5 Step 18 Icons, `sap.m.Button` icon 속성 설명)

### 6.3 Controller

- 3개 이상의 수식(Expression)을 이어 쓰지 않고 나눠 적어 가독성을 높인다. `[리뷰]` (사내 규칙)
- Naked 함수를 되도록 인수(Parameter)로 쓰지 않고 밖으로 분리해 호출한다. `[리뷰]` (사내 규칙)
- `__getFoo()` 나 `_bar` 처럼 하나 또는 두 개의 `_` 로 시작하는 SAPUI5 의 메소드·Attribute 를
  쓰지 않는다. private 으로 보호되는 대상이라 SAPUI5 Core Lib. 가 갱신될 때 이름이나
  내부 코드가 바뀌어 App 오류가 날 수 있다. `[경고]` (SAP 공식: openui5 guidelines.md,
  Fiori tools eslint `sap-ui5-no-private-prop`. 내 private 도 `_` 로 시작해 기계가
  완전히 구분하지 못하므로 막지 않고 경고만 한다. `this`·`that`·`self` 의 멤버와 그 파일
  안에서 정의한 이름은 경고하지 않는다)
- OData 에서 CRUD 처리용 Primary Key 문자열을 손으로 만들지 않는다. V4 모델(우리
  앱 전부)은 `getKeyPredicate`/`requestKeyPredicate`(1.107.0 부터)나 binding context 를
  쓴다. `createKey` 는 V2 모델 전용이다. `[리뷰]` (SAP 공식: `sap.ui.model.odata.v4.ODataModel`
  API)

공통 Library.

| 파일 | 역할 |
|---|---|
| `/lib/Base.js` | manifest 설정정보 적용, control selector 등 공통 function 정의. 모든 Controller 가 extend 하는 BaseController |
| `/lib/Model.js` | JSONModel, ODataModel 생성·통신 처리 function |
| `/lib/Nav.js` | 화면 간 navigation 기능을 정형화한 function |
| `/lib/Formatter.js` | Data format 변경, display 관련 function |
| `/lib/Validator.js` | form data validation 체크 function |

(공통 Library 는 사내 규칙)

process flow & lifecycle (SAP 공식: SAPUI5 Controller).

| 함수 | 설명 |
|---|---|
| `onInit` | Controller 가 실행될 때 한 번만 호출. 이벤트 핸들러 바인딩, 데이터 초기화, View 가 렌더링되기 전 View 수정을 할 수 있다 |
| `onRouteMatched` | 관례 이름(UI5 생명주기 훅이 아니다). Router 의 `attachPatternMatched`/`attachRouteMatched` 로 붙인다. 파라미터 정보를 받는다 |
| `onBeforeRendering` | 최초 `onInit` 호출 뒤, 이후 View 가 다시 렌더링되기 전에 항상 호출. View 에 다시 들어올 때 수행할 처리를 적용한다 |
| `onAfterRendering` | View 가 렌더링된 직후 실행. 렌더링이 끝난 View 를 다뤄야 할 때 실행한다 |
| `onExit` | 뷰가 없어질 때(destroy) 호출. 리소스를 반환한다 |

### 6.4 다국어 적용

- XML View: `{i18n>key}` 로 쓴다. argument 를 넘길 때는 i18n properties 에 argument
  문자(`{0}`)를 지정하고, Controller 에서 `sap.base.strings.formatMessage` 를 import 해
  private 함수 `formatMessage` 로 등록하고, View 에서 parts/formatter 로 표현한다.
  예: `{parts: [i18n path, arg context path], formatter: '.formatMessage'}`
- Controller: ResourceBundle 객체를 만든 뒤 key 로 text 를 가져온다. argument 를 넘기는
  방법도 있다.

(이 절은 사내 규칙, `[리뷰]`)

### 6.5 메시지 처리

OData 통신 결과 메시지.

- CRUD OData 통신의 성공/실패 여부와 기타 조건 이상에 대한 메시지는 SAP side 에서
  전달된 메시지를 표현한다. 예: 성공적으로 처리되었습니다. / 저장되었습니다. / 수정되었습니다.
  `[리뷰]` (사내 규칙)

Http Status Code 참고.

| 구분 | Code | Text | 원인 |
|---|---|---|---|
| Success | 200 | OK | 요청 성공(Get method) |
| Success | 201 | OK | 요청 성공(Post method) |
| Success | 203 | OK | 요청 성공(Post method) |
| Success | 204 | OK | 요청 성공(Delete method) |
| Client errors | 400 | Bad Request | 잘못된 구문이나 URI 로 인한 구문분석 실패 |
| Client errors | 401 | Unauthorized | 인증이 필요하지만 인증 전송이 안 됨 |
| Client errors | 403 | Forbidden | Entity 에 접근할 권한이 없는 사용자 |
| Client errors | 404 | Record Not Found | 요청된 쿼리에 대한 결과가 없음(no rows) |
| Client errors | 405 | Method Not Allowed | 해당 record 에 쓸 수 없는 요청 |
| Client errors | 406 | Not Acceptable | 받아들일 수 없음 |
| Server errors | 500 | Internal Server Error | SAP Server Side error |
| Server errors | 501 | Not Implemented | 미구현 상태 |
| Server errors | 502 | Bad Gateway | Gateway 문제 |
| Server errors | 503 | Service Unavailable | 서비스 불가 상태 |

UI side 메시지.

- 메시지 내용은 "~바랍니다.", "~십시오.", "~하시겠습니까?" 같은 존칭 종결어로 끝내고,
  "~세요.", "~주시오." 같은 비종결 언어와 특수문자는 쓰지 않는다. `[경고]` (사내 규칙)
- Input Control 의 validation 체크 메시지(필수입력, 자릿수, 입력 Type, min/max Number)는
  value 의 binding property 와 MessageManager 로 입력칸 상태에 표현한다. `[리뷰]`
  (사내 규칙)
- MessageToast 는 성공·완료 알림에만 쓴다. 예: 저장되었습니다. 오류·경고·필수입력
  검증 메시지는 MessageToast 로 띄우지 않고 MessageBox 또는 입력칸 상태(MessageManager)로
  표현한다. 예: 적용할 설비를 선택해 주십시오. / 다운로드 할 데이터가 없습니다.
  `[리뷰]` (SAP 공식: Fiori Design Guidelines Message Toast, "Don't use the toast to:
  Display an error or warning message")
- 확인 요청은 MessageBox 로 표현한다. 예: 저장하시겠습니까? `[리뷰]` (사내 규칙)
- MaskInput Control 로 입력 내용을 안내할 수 있다. `[리뷰]` (사내 규칙)
- Input 의 Value Helper 처럼 입력 안내가 필요하면 placeholder 속성으로 문구를 안내한다.
  `[리뷰]` (사내 규칙)

## 7. Secure 코딩

행정기관 및 공공기관 정보시스템 구축·운영지침(행정안전부 고시 제 2018-21 호)에 따라
소스코드 전체에 소프트웨어 보안 취약점이 없도록 하며, 행정안전부의 「소프트웨어
개발보안 가이드」와 「소프트웨어 보안약점 진단 가이드」를 지킨다. 아래 항목은 모두
`[리뷰]` 이다.

| 단계 | 구분 | 항목 | 적용 방안 |
|---|---|---|---|
| 설계(보안 설계 기준) | 입력 데이터 검증 및 표현 | HTTP 프로토콜 유효성 검증 | 자동 연결할 외부 사이트의 URL 과 도메인은 화이트 리스트로 관리하고, 사용자 입력값을 자동 연결할 사이트 주소로 쓰면 그 값이 화이트 리스트에 있는지 확인한다 (사내 규칙) |
| 구현(보안 약점 제거 기준) | 입력 데이터 검증 및 표현 | 크로스사이트 스크립트 | 컨트롤이 출력 인코딩을 하므로 입력값을 미리 HTML entity 로 바꾸지 않는다. HTML 을 직접 만들 때만 `sap/base/security/encodeXML` 로 인코딩한다 (SAP 공식: SAPUI5 Cross-Site Scripting) |
| 구현 | 입력 데이터 검증 및 표현 | 위험한 형식 파일 업로드 | 업로드 때 확장자를 확인해 허용된 형식의 파일만 올라가게 하고, 저장하기 전에 VSI(Virus Scan Interface) 검사를 거친다 (SAP 공식: Fiori tools eslint `sap-no-upload`) |
| 구현 | 입력 데이터 검증 및 표현 | HTTP 응답분할 | Http Response Header 에 들어가는 CR(%0D), LF(%0A)를 제거하거나 치환하는 입력값 검증으로 헤더 분할을 막는다 (사내 규칙) |
| 구현 | 보안기능 | 하드코드된 암호화 키 | 암호키를 소스코드에 하드코딩해 쓰지 않도록, 암호키는 암호화해 안전한 별도 위치에 저장한 뒤 쓴다 (사내 규칙) |
| 구현 | 보안기능 | 사용자 하드디스크에 저장되는 쿠키를 통한 정보 노출 | 쿠키 만료시간을 최소로 설정하고, 영속적 쿠키(Max-Age)에 사용자 권한 등급, 인증정보 등 중요정보를 넣지 않는다 (사내 규칙) |
| 구현 | 보안기능 | 주석문 안에 포함된 시스템 주요정보 | 주석문에 ID, Password, 사번 등을 적지 않고, 개발이 끝나면 개발에 쓴 중요정보를 확실히 지운다 (사내 규칙) |
| 구현 | 보안기능 | 로컬 스토리지에 저장된 정보 노출 | 로컬 스토리지에 사용자·업무 데이터를 저장하지 않는다 (SAP 공식: SAPUI5 Secure Programming Aspects, Fiori tools eslint `sap-no-localstorage`) |
| 구현 | 보안기능 | 클라이언트에 저장된 로그온 정보 | 클라이언트(브라우저)에 로그온 정보를 저장하지 않는다 (SAP 공식: SAPUI5 Secure Programming Aspects) |

## 정리한 결과 (`naming.md` 와 맞춘 곳)

같은 대상을 `naming.md` 와 이 파일이 다르게 정했던 곳을 2026-11-14 에 정리했다.
Variable 접두어의 `d` 는 CAP 표준 쪽이 Date, Naming Guide 쪽이 실수형이라 뜻이
충돌했는데, 공식(`d` = Date, `f` = float)에 맞춰 정리했다.

| 항목 | 결정 | 근거 |
|---|---|---|
| Control ID | 하이픈 없는 lowerCamel. 두 문서 모두 같은 규칙 | SAP 공식: SAPUI5 ID Handling |
| Constant | `CONST_MAX_COUNT` · `MAX_LENGTH` 둘 다 허용 | 사내 규칙 |
| Variable 접두어 | 공식 표(`s o $ i m a d f b r fn v p`)로 통일. `d` = Date, `f` = float | SAP 공식: openui5 guidelines.md |
| Event handler | `on` 으로 시작하면 허용(`onBtnSavePress`, `onNewItemPress` 둘 다) | 사내 규칙 |
| Internal function | `_` 로 시작 하나. `fn` 은 함수를 담는 변수의 접두어 | SAP 공식: openui5 guidelines.md |
| Service 파일 | `<이름>-service.cds`, 구현은 같은 이름 `.js`. `schema.cds` 는 기본 예시 | SAP 공식: CAP Core Services |
| Entity/Element 표기 | Domain·Service 모두 Entity 는 Upper CamelCase(Domain 은 복수형), element 는 Lower CamelCase | SAP 공식: CAP Domain Modeling |
| Namespace | `<회사약어>` · `<회사약어>.<모듈>` 둘 다 허용 | 사내 규칙 |
| UI5 앱 폴더 | ABAP 배포 앱(`src/ui5/`)은 `naming.md` 5.2 형식, lowerCamel + `App` 은 CAP `app/` 안 앱만 | 사내 규칙 |
| i18n key | 두 문서 모두 `[화면].[Type].[key]` | 사내 규칙 |

## 근거

- SAPUI5 ID Handling: https://github.com/SAP/openui5-docs/blob/main/docs/05_Developing_Apps/id-handling-in-openui5-the-complete-guide-f51dbb7.md
- SAPUI5 Use Stable IDs: https://github.com/SAP/openui5-docs/blob/main/docs/03_Get-Started/use-stable-ids-79e910e.md
- SAPUI5 Step 18 Icons: https://github.com/SAP/openui5-docs/blob/main/docs/03_Get-Started/step-18-icons-776f735.md
- SAPUI5 Controller: https://github.com/SAP/openui5-docs/blob/main/docs/04_Essentials/controller-121b8e6.md
- SAPUI5 Secure Programming Aspects: https://github.com/SAP/openui5-docs/blob/main/docs/05_Developing_Apps/secure-programming-aspects-91f3c40.md
- SAPUI5 Cross-Site Scripting: https://github.com/SAP/openui5-docs/blob/main/docs/05_Developing_Apps/cross-site-scripting-91f0bd3.md
- openui5 guidelines.md: https://github.com/SAP/openui5/blob/master/docs/guidelines.md
- openui5 translationfiles.md: https://github.com/SAP/openui5/blob/master/docs/guidelines/translationfiles.md
- `sap.ui.model.odata.v4.ODataModel` (`getKeyPredicate`, 1.107.0 부터): openui5 저장소의 `src/sap/ui/model/odata/v4/ODataModel.js`
- CAP Domain Modeling: https://github.com/capire/docs/blob/main/guides/domain/index.md
- CAP Core Services: https://github.com/capire/docs/blob/main/node.js/core-services.md
- Fiori Design Guidelines Message Toast: https://www.sap.com/design-system/fiori-design-web/v1-154/ui-elements/message-toast
- Fiori tools eslint 규칙(`sap-no-dom-access`, `sap-no-console-log`, `sap-no-upload`, `sap-no-localstorage`): SAP/open-ux-tools 저장소 `packages/eslint-plugin-fiori-tools/docs/rules/`
- SAP HANA Cloud 식별자 한도(127자): https://help.sap.com/docs/HANA_CLOUD_DATABASE/c1d3f60099654ecfb3fe36ac93c121bb/209f5020751910148fd8fe88aa4d79d9.html
