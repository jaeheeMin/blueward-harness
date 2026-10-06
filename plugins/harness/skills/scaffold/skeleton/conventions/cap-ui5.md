# CAP · SAPUI5 개발 표준

블루어드 사내 표준 — CAP·SAPUI5 개발표준 정의서 v1.0 을 정리했다.

사내 기본값이다. 고객사 표준이 정해지면 이 파일을 고친다. 공통 개발 규칙과
부딪히면 이 파일이 이긴다(CR-004 제외).

CAP 프로젝트(BTP Side-by-Side Extension)와 그 안의 SAPUI5 앱에 적용한다.
CAP 프로젝트가 아니면 별도 개발 표준 문서를 만들어 적용한다. 프로젝트 상황에
따라 고쳐야 하면 이 문서를 기준으로 프로젝트 개발 표준을 만든다. 원문에 있던
코드 예시·화면 그림은 옮기지 않았다.

`<회사약어>` 는 이 표준을 쓰는 회사의 약어, `<프로젝트 접두어>` 는 프로젝트가
정하는 접두어 자리표시다.

## 1. 개요

- 목적: CAP Project 의 표준을 세워 적용해 개발한 코드의 일관성과 목표 시스템의
  품질 수준을 높인다.
- Backend Service(OData Service)와 Front App(UI)은 SAP BTP 의 통합개발환경
  BAS(Business Application Studio)로 개발한다. 원칙은 BAS 사용이다.

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
- DB Deployer Project 구성: `db/schema.cds`(Domain 정의), `db/undeploy.json`
  (Undeploy(Domain) 정의), `mta.yaml`(Application Deploy Descriptor). DB Deployer 가
  더 필요하면 기존 entity-deployer 를 참고해 만든다.

## 4. 이름 규칙

### 4.1 Project · Folder · CDS

| 대상 | 형식 | 표기법 | 예시 |
|---|---|---|---|
| Project Folder | `<프로젝트 접두어>` + [단어][단어]... | Upper CamelCase | `<프로젝트 접두어>CustomerManagement`, `<프로젝트 접두어>OrderManagement` |
| UI5 App Folder | [단어][단어]... + `App` | Lower CamelCase | `customerManagementApp`, `orderManagementApp` |
| Project name | Project folder name 과 같게. 임의 변경 불허 | - | - |
| Domain 파일 | `schema.cds`. 임의 변경 불허 | Lower case | - |
| Namespace (Domain) | `<회사약어>`. 임의 수정 불허 | - | - |
| Context | [단어] | Lower Case | `common`, `expense`, `financial` |
| Entity (Domain) | [단어]_[단어]_... | Lower Case | `Customers`, `Expense`, `Orders` (원문 예시 그대로) |
| Service Definition 파일 | `service.cds`. 임의 변경 불허 | Lower case | - |
| service | [단어][단어]... + `Service` | Upper CamelCase | `orderService`, `vanderService`, `deliveryService` (원문 예시 그대로) |
| entity (Service) | [단어][단어][단어]... | Upper CamelCase | `Books`, `Authors`, `Orders` |
| action | [단어][단어][단어] | Lower CamelCase | `addCustomer`, `createOrder` |
| function | [단어][단어][단어] | Lower CamelCase | `getStock`, `sum` |
| Service Implementation 파일 | Service Definition 과 같은 이름에 확장자만 `.js` | - | - |

- Domain CDS 는 업무 영역 구분이 필요하면 `context` 구문을 쓴다. 전체 30자를 넘지
  않게 구성한다.
- Domain CDS 로 만들어지는 DB Object 의 이름은 Namespace, Context, Entity name 을
  조합하므로 전체 길이를 고려해 명명한다.
- Service Definition 은 용도별로 서비스를 나눠야 하면 `service` 구문으로 나눈다.
- action 은 데이터 처리(CUD) 기능을 제공할 때, function 은 데이터 조회(R) 기능을
  제공할 때 쓰기를 권장한다.
- Service Implementation(.js)은 Custom Logic 이 필요한 경우에만 선언한다.

### 4.2 UI5 Application

공통:

- 특별한 경우를 빼고 최대 15자를 넘지 않게 한다.
- 형식에 구분자가 있거나 표기법이 지정된 경우를 빼고는 Lower CamelCase 로 쓴다.
- 단어를 쓰거나 상세를 적을 때는 의미를 짐작할 수 있게 짓는다.

| 대상 | 형식 | 표기법 | 예시 |
|---|---|---|---|
| Control ID | [View 이름]-[Control 약어]-[상세] | View 이름·Control 약어는 Lower Case, 상세는 Lower CamelCase | `main-tbl-list`, `detail-mi-email`, `detail-cbx-used`, `detail-btn-excelDownload` |
| Constant | `CONST_` + [단어] + `_` + [단어] | Upper Case | `CONST_MAX_COUNT`, `CONST_LIMIT` |
| Variable | [Datatype Prefix][단어][단어] | Upper CamelCase | `sId`, `oUserInfo`, `iCount`, `aRow`, `dToday`, `fRate`, `bEanbled`, `rDate`, `vVariant` (원문 예시 그대로) |
| Event handler | `on` + [Control 약어] + [Event Name] | 약어, Event 명은 Upper CamelCase | `onBtnSavePress`, `onTblCellClick`, `onItemSelected` |
| Function | `_` + [동사][단어][단어] | 동사, 단어는 Lower CamelCase | `_searchUserList`, `_calcAmount`, `_getAccessToken` |
| Parameter | Variable 과 같게 적용 | - | - |

- Controller 에서 직접 접근할 필요가 없는 Control 에는 id 를 짓지 않는다.

Control 약어.

| Control | 약어 | Control | 약어 |
|---|---|---|---|
| `sap.ui.table.Table` | `tbl` | `sap.m.MaskInput` | `mi` |
| `sap.m.Button` | `btn` | `sap.m.DatePicker` | `dp` |
| `sap.m.Toolbar` | `tbar` | `sap.m.CheckBox` | `cbx` |
| `sap.m.Panel` | `pnl` | `sap.m.VBox` | `vbx` |
| `sap.m.Label` | `lbl` | `sap.m.HBox` | `hbx` |
| `sap.m.Input` | `inp` | `sap.m.RadioButton` | `rb` |

Variable Datatype Prefix.

| Type | Prefix | Type | Prefix |
|---|---|---|---|
| String | `s` | Date | `d` |
| Object | `o` | Float | `F` (원문 표기. 예시는 소문자 `fRate`) |
| Integer | `i` | Boolean | `b` |
| Map | `m` | Regular Expression | `r` |
| Array | `a` | Variant types | `v` |

### 4.3 다국어 Properties

- Key 는 `[AppID].[Type].[key]` 로 구성한다. key 는 카멜 표기법으로 쓰고, 값에 해당
  언어 텍스트를 적는다.

| Type | 예 |
|---|---|
| Title | `main.title.empDetailInfo=임직원상세정보` |
| Label | `main.label.empNm=직원이름` |
| Text | `main.text.summCont=요약정보를 다음과 같이 기술합니다……….` |
| Button | `detail.button.uploadFiles=파일업로드` |
| Message | `detail.message.requiredTitle=제목을 입력하세요.` |
| argument 전달 | `detail.message.procResult={0}건 중 {1}건이 완료처리 되었습니다.` |

## 5. 코드 작성 규칙

### 5.1 기본

- Class 밖에 전역변수를 만들지 않는다(만들면 제거할 방법이 없다).
- 동적 Control 을 만들 때 ID 작성은 피해, 멤버 변수로 참조되는 것을 막는다.
- 해당 Controller 에서만 쓰는 private 변수·함수의 이름은 underscore(`_`)로 시작한다.
  예: `this._bFinalized`, `this._reRenderTable()`
- ID 는 unique 하게 쓴다(Copy & Paste 때 주의).
- jQuery selection 은 쓰지 않도록 하되, 쓸 때는 `jQuery("#<someId>")` 가 아니라
  `jQuery(document.getElementById(sId))` 를 쓴다.
- logging 은 `console.log()` 대신 `sap.base.Log` 의 info/debug/warning/error/fatal 을
  쓴다.

### 5.2 들여쓰기 · 빈 줄 · formatting

- 1 Tab 은 4칸으로 설정한다.
- Control 이 같은 레벨이면 Tab 개수를 같게 하고, 하위 레벨이면 1 Tab 더 들여쓴다.
- Control 의 Attribute 가 많으면 줄을 바꾼 뒤 같은 Tab 개수를 적용한다.
- Control 간 구분을 위한 빈 줄은 하나까지 허용하고 그 이상은 두지 않는다.
- 모든 구문 뒤의 세미콜론을 생략하지 않는다.
- 소괄호 앞에는 space 를 두지 않는다.
- `if/else/for/while/do/switch/try/catch/finally`, 중괄호, 연산자, 콤마 뒤에는
  space 를 둔다.
- `function/for/if-else/switch` 와 중괄호 시작은 같은 줄에 둔다.
- 값 비교는 `===`, `!==` 를 쓴다. 고의로 피하는 경우는 예외다.

### 5.3 주석

- 주석에 중요정보(ID, Password, 사번, 접속정보)를 남기지 않는다.
- XML: 주석은 `<!-- Comments -->` 형태로, 하이픈 두 개와 주석 사이에 space 를 한 칸씩
  둔다. View, Fragment, Block 최상단에 화면 설명을 한 줄로 적는다. View 코드의 시작
  주석과 종료 주석을 둔다.
- JS: `/*** Comments ***/` 형태로, 주석과 space 를 한 칸씩 둔다. Controller 최상단에
  헤더 주석으로 요약 정보를 적고, Controller 함수 위에 함수 정보를 적는다.
  getter method 는 기능 설명, `@param {type} paramName 내용`, `@return {namespace} 내용`,
  setter method 는 기능 설명, `@param {type} paramName 내용`.
- Properties: 다국어 관련 주석 형태가 따로 있다(원문 그림이라 옮기지 못했다).

## 6. 프로그램 요소 작성 규칙

### 6.1 기본

- MVC(Model-View-Controller) 패턴으로 개발하기 위해 표준 Project 구조를 지킨다.
- Controller 를 만들 때 `BaseController.js` 를 extend 해 공통 함수를 쓸 수 있게 한다.
- 공통 Library 의 함수를 최대한 써서 코드 작성 패턴을 정형화한다. 예: Model(Model,
  ODataModel 처리), Nav(navigation 처리), Formatter(Data format 처리).
- Custom Controller 는 UI5 범위를 벗어난 새 기능을 구현할 때 쓴다.
- 초기화, instance 필드 기술 등은 생성자 function 으로 처리한다. 예: `this._bReady = false;`
- Label, Text, Message 는 다국어 처리가 원칙이다.

### 6.2 View

App 유형.

| 유형 | 설명 |
|---|---|
| WorkList Type | 사용자가 처리할 항목 모음이 표시되며, 보통 목록 항목의 세부 정보를 검토하고 조치를 수행하는 형태 |
| Master/Detail Type | 유연한 Column layout type 으로 Single Page 에 여러 화면 칼럼을 표시한다. Master 화면에서 여러 Detail 화면으로 navigation 하며, 일반적인 페이지별 navigation 보다 화면 간 이동이 빠르고 유연하다 |

화면 코딩.

- Aggregation 이 없는 XML Element 를 닫을 때는 Close Tag 대신 `/` 를 쓰고, `/` 앞에
  공백을 두지 않는다. 예: `<Button id="main-btn-save" text="{i18n>main.btn.save}" press="onBtnSavePress"/>`
- Control 의 Icon Property 는 `sap-icon://` 를 뺀 값으로 설정한다(원문 표기).
  올바른 예 `<Button Icon="sap-icon://accept"/>`, 잘못된 예 `<Button Icon="accept"/>`
  (원문 예시가 서로 이어지지 않는다. 확인이 필요하다).

### 6.3 Controller

- 3개 이상의 수식(Expression)을 이어 쓰지 않고 나눠 적어 가독성을 높인다.
- Naked 함수를 되도록 인수(Parameter)로 쓰지 않고 밖으로 분리해 호출한다.
- `__getFoo()` 나 `_bar` 처럼 하나 또는 두 개의 `_` 로 시작하는 SAPUI5 의 메소드·Attribute 를
  쓰지 않는다. private 으로 보호되는 대상이라 SAPUI5 Core Lib. 가 갱신될 때 이름이나
  내부 코드가 바뀌어 App 오류가 날 수 있다.
- OData 에서 CRUD 처리용 Primary Key 는 문자열로 직접 만들지 않고 `createKey` 함수를
  쓴다.

공통 Library.

| 파일 | 역할 |
|---|---|
| `/lib/Base.js` | manifest 설정정보 적용, control selector 등 공통 function 정의. 모든 Controller 가 extend 하는 BaseController |
| `/lib/Model.js` | JSONModel, ODataModel 생성·통신 처리 function |
| `/lib/Nav.js` | 화면 간 navigation 기능을 정형화한 function |
| `/lib/Formatter.js` | Data format 변경, display 관련 function |
| `/lib/Validator.js` | form data validation 체크 function |

process flow & lifecycle.

| 함수 | 설명 |
|---|---|
| `onInit` | Controller 가 실행될 때 한 번만 호출. 이벤트 핸들러 바인딩, 데이터 초기화, View 가 렌더링되기 전 View 수정을 할 수 있다 |
| `onRounterMatched` | Router 에서 `attachPatternMatched` 로 정의한 함수. 파라미터 정보를 받는다(원문 표기 그대로) |
| `onBeforeRendering` | 최초 `onInit` 호출 뒤, 이후 View 가 다시 렌더링되기 전에 항상 호출. View 에 다시 들어올 때 수행할 처리를 적용한다 |
| `onAfterRendering` | View 가 렌더링된 직후 실행. 렌더링이 끝난 View 를 다뤄야 할 때 실행한다 |
| `onExit` | 프로그램 종료 시 한 번만 실행. 리소스를 반환한다 |

### 6.4 다국어 적용

- XML View: `{i18n>key}` 로 쓴다. argument 를 넘길 때는 i18n properties 에 argument
  문자(`{0}`)를 지정하고, Controller 에서 `sap.base.strings.formatMessage` 를 import 해
  private 함수 `formatMessage` 로 등록하고, View 에서 parts/formatter 로 표현한다.
  예: `{parts: [i18n path, arg context path], formatter: '.formatMessage'}`
- Controller: ResourceBundle 객체를 만든 뒤 key 로 text 를 가져온다. argument 를 넘기는
  방법도 있다.

### 6.5 메시지 처리

OData 통신 결과 메시지.

- CRUD OData 통신의 성공/실패 여부와 기타 조건 이상에 대한 메시지는 SAP side 에서
  전달된 메시지를 표현한다. 예: 성공적으로 처리되었습니다. / 저장되었습니다. / 수정되었습니다.

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
  "~세요.", "~주시오." 같은 비종결 언어와 특수문자는 쓰지 않는다.
- Input Control 의 validation 체크 메시지(필수입력, 자릿수, 입력 Type, min/max Number)는
  value 의 binding property 와 MessageManager 로 표현한다.
- Validation 메시지, UI control 의 처리 완료/실패 메시지 등은 MessageToast 로 표현한다.
  예: 적용할 설비를 선택해 주십시오. / 다운로드 할 데이터가 없습니다.
- 확인 요청은 MessageBox 로 표현한다. 예: 저장하시겠습니까?
- MaskInput Control 로 입력 내용을 안내할 수 있다.
- Input 의 Value Helper 처럼 입력 안내가 필요하면 placeholder 속성으로 문구를 안내한다.

## 7. Secure 코딩

행정기관 및 공공기관 정보시스템 구축·운영지침(행정안전부 고시 제 2018-21 호)에 따라
소스코드 전체에 소프트웨어 보안 취약점이 없도록 하며, 행정안전부의 「소프트웨어
개발보안 가이드」와 「소프트웨어 보안약점 진단 가이드」를 지킨다.

| 단계 | 구분 | 항목 | 적용 방안 |
|---|---|---|---|
| 설계(보안 설계 기준) | 입력 데이터 검증 및 표현 | HTTP 프로토콜 유효성 검증 | 자동 연결할 외부 사이트의 URL 과 도메인은 화이트 리스트로 관리하고, 사용자 입력값을 자동 연결할 사이트 주소로 쓰면 그 값이 화이트 리스트에 있는지 확인한다 |
| 구현(보안 약점 제거 기준) | 입력 데이터 검증 및 표현 | 크로스사이트 스크립트 | XSS 필터를 적용해 script 태그 문자 등 위험 문자를 입력받으면 문자참조(HTML entity)로 걸러내고, 서버에서 브라우저로 보낼 때 문자를 인코딩한다. 예: `<script>` → `&lt;script&gt;` |
| 구현 | 입력 데이터 검증 및 표현 | 위험한 형식 파일 업로드 | 업로드 때 확장자를 확인해 허용된 형식의 파일만 올라가게 한다 |
| 구현 | 입력 데이터 검증 및 표현 | HTTP 응답분할 | Http Response Header 에 들어가는 CR(%0D), LF(%0A)를 제거하거나 치환하는 입력값 검증으로 헤더 분할을 막는다 |
| 구현 | 보안기능 | 하드코드된 암호화 키 | 암호키를 소스코드에 하드코딩해 쓰지 않도록, 암호키는 암호화해 안전한 별도 위치에 저장한 뒤 쓴다 |
| 구현 | 보안기능 | 사용자 하드디스크에 저장되는 쿠키를 통한 정보 노출 | 쿠키 만료시간을 최소로 설정하고, 영속적 쿠키(Max-Age)에 사용자 권한 등급, 인증정보 등 중요정보를 넣지 않는다 |
| 구현 | 보안기능 | 주석문 안에 포함된 시스템 주요정보 | 주석문에 ID, Password, 사번 등을 적지 않고, 개발이 끝나면 개발에 쓴 중요정보를 확실히 지운다 |

## naming.md 와 다르게 정한 곳

같은 대상을 `naming.md` 와 이 파일이 다르게 정한 곳이다. 원문 두 문서가 서로 맞춰져
있지 않다. 어느 쪽을 따를지 프로젝트에서 정해 두 파일을 고친다.

| 대상 | `naming.md` | 이 파일 |
|---|---|---|
| Control ID | `deliveryFromDate`, `goodsNameInput` 처럼 Lower Camel Case | `main-tbl-list` 처럼 `[View]-[Control 약어]-[상세]` |
| Constant | `MAX_LENGTH` | `CONST_MAX_COUNT` (`CONST_` 접두어) |
| Variable 접두어 | `s i d b o fn` | `s o i m a d F b r v` |
| Event handler | `onNewItemPress` | `onBtnSavePress` (Control 약어 포함) |
| Internal function | `fnGetToken` | `_searchUserList` |
| Service 파일 | `OrderManagement-service.cds` 형태 | `service.cds` 로 고정 |
| Entity/Element 표기 | Domain·Service 모두 Entity 는 Upper, Element 는 Lower Camel Case | Domain Entity 는 Lower Case, Service entity 는 Upper CamelCase |
| Namespace | `<회사약어>.<모듈코드>` | `<회사약어>` |
