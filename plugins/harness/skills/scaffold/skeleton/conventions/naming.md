# 이름 규칙 (SAP S/4HANA Public Cloud & BTP)

블루어드 사내 표준 — SAP S/4HANA Public Cloud & BTP Naming Guide v1.2 를
정리했다.

사내 기본값이다. 고객사 표준이 정해지면 이 파일을 고친다. 공통 개발 규칙과
부딪히면 이 파일이 이긴다(CR-004 제외).

객체·파일·변수 이름을 지을 때는 이 파일을 먼저 읽는다. 아래에서 `Z` 는 운영
이관 대상, `Y` 는 개발 시스템에만 두는 도구·유틸리티를 뜻한다(`Y`/`Z` 구분은
Common 의 Package 절 참조). 이름에 쓰는 영역 코드는 다음 절의 표를 따른다.
`<회사약어>` 는 이 표준을 쓰는 회사의 약어 자리표시다.

## 1. Common

### 1.1 영역(모듈) 코드

| 영역 | 코드 | 영역 | 코드 | 영역 | 코드 |
|---|---|---|---|---|---|
| 영업 | SD | 설비 | PM | 재무회계 | FI |
| 물류 | LE | 인사 | HR | 관리회계 | CO |
| 생산 | PP | 사양관리 | VC | 자금 | TR |
| 구매 | MM | 기준 정보 | MD | 기획 | IM |
| 공통 | CM | 거버넌스 | GV | BTP | BTP |
| 펨뱅킹 | FB | 내부통제 | iFLOW | | |

### 1.2 CTS (Transport 설명)

형식: `[영역코드]설명_YYYY-MM-DD HH:MM`

| 위치 | 용도 | 설명 |
|---|---|---|
| 1, 4 | 구분자 | `[` `]` |
| 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| 5~N | 설명 | Transport 목적 및 대상을 설명 |
| N+1~ | 일자 및 시간 | Transport 일시 (`_YYYY-MM-DD HH:MM`) |

예시: `[MM]자재 마스터 리포트_2025-05-12 13:05`

### 1.3 Package

형식: `Z` + 영역 코드 + Optional (예: `ZMM`)

| 위치 | 용도 | 설명 |
|---|---|---|
| 1 | CBO 구분 | `Y`: 개발 시스템에만 두는 도구·유틸리티 / `Z`: 운영(PRD) 이관 대상 Application program |
| 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| 4~30 | Optional | SAP 표준 모듈이 아닌 3rd-Party 솔루션 등 의미 있는 명칭을 적어야 할 때 |

- 최대 30자리.
- Super Package 위치: `ZCUSTOM_DEVELOPMET` (원문 표기 그대로).

## 2. RAP (S/4HANA Cloud Public Edition)

모든 이름의 1번째 자리(`Y`/`Z`)와 2~3번째 자리(영역 코드)는 Common 과 같다.

### 2.1 ABAP Dictionary

| 객체 | 이름 형식 | 길이 제한 | 예시 |
|---|---|---|---|
| Domain | `Z` + `D` + `_` + Text | 30 | `ZD_WERKS`, `ZD_ZMALLTYPE` |
| Data Element | `Z` + `E` + `_` + Text | 30 | `ZE_WERKS`, `ZE_ZMALLID` |
| Structure | `Z` + 영역코드 + `_S_` + Text | 30 | `ZSD_S_Customer` |
| Database Table | `Z` + 영역코드 + 유형 + 일련번호 3자리 + 테이블 번호 + Optional | 16 | `ZSDA0010`, `ZSDA1010_Header`, `ZSDD0010`, `ZSDD1010_Header` |

Domain · Data Element 세부 규칙.

| 구분 | 위치 | 설명 |
|---|---|---|
| Domain | 4~30 Text | Domain 이름. 필드명을 주로 사용. Data Type 은 필드의 기술적인 속성(필드의 타입, 길이) |
| Data Element | 4~30 Text | 의미적인 정보를 가지는 명칭. 테이블, 프로그램 내 변수 타입, 화면 필드 선언 등에 쓴다 |
| 공통 | - | 가능하면 존재하는 SAP data element 를 사용한다. table field name 에 공백과 특수문자는 사용하지 않는다 |

Structure 세부.

| 위치 | 용도 | 설명 |
|---|---|---|
| 1 | CBO 구분 | Y / Z |
| 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| 4 | 구분자 | `_` |
| 5 | 유형 | `S`: Structure 의 약어 |
| 6 | 구분자 | `_` |
| 7~N | Text | 사용자 정의(의미 있는 내용) Structure 이름 |

Database Table 세부.

| 위치 | 용도 | 설명 |
|---|---|---|
| 1 | CBO 구분 | Y / Z |
| 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| 4 | 유형 | `A`: Active Data, 실제 데이터 저장용 테이블 / `D`: Draft Data, 드래프트 데이터 저장용 테이블 |
| 5~7 | 일련번호 | 3자리 Serial 숫자 |
| 8 | 테이블 번호 | `0`: 메인 테이블 / `1`~`9`: 메인 테이블에 대한 Sub-Table 또는 연관된 파생·추가 테이블 |
| 9~16 | Optional | `_` 를 Prefix 로 붙인 뒤 사용자 정의(의미 있는 내용) 테이블 이름 |

- Database Table Name 은 최대 16자리. 원문 본문은 16자리로 적었는데 v1.2 의 개정 요약은 15자리로 바꿨다고 적어 서로 어긋난다. 프로젝트에서 확인해 이 파일을 고친다.
- 예시: Active Data(`A`) `ZSDA0010` 또는 `ZSDA1010_Header`, Draft Data(`D`) `ZSDD0010` 또는 `ZSDD1010_Header`.

### 2.2 CDS View

형식: `Z` + 영역코드 + `_` + View 유형 + `_` + Text + (`_` + Suffix, 생략 가능)

| 위치 | 용도 | 설명 |
|---|---|---|
| 1 | CBO 구분 | Y / Z |
| 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| 4 | 구분자 | `_` |
| 5 | 유형 | View 유형: R, I, C, A, X, E, F, D |
| 6 | 구분자 | `_` |
| 7~N | Text | 사용자 정의(의미 있는 내용) CDS View 이름 |
| N+1 | 구분자 | `_`, 생략 가능 |
| N+2~30 | Suffix | View 유형(Suffix): Query(Qry, Q), Cube(C), Text(Txt, T), TP, VH/StdVH |

- CDS View Name 은 최대 30자리.
- Behavior 정의, Metadata Extension 은 관련 CDS Entity 와 같은 이름을 쓴다.

View 유형(5번째 자리).

| 유형 | View 분류 | 설명 | 예시 |
|---|---|---|---|
| R | 기본 인터페이스 뷰 (Reusable/Basic Interface View) | 다른 뷰나 소비 뷰에서 재사용 가능한 핵심 데이터 뷰. 비즈니스 개체(Entity)의 기본 정보를 제공 | `ZMM_R_Materials` |
| I | 복합 인터페이스 뷰 (Composite Interface View) | 여러 기본 인터페이스 뷰(R)를 조합해 비즈니스 컨텍스트에 맞게 구성한 뷰 | `ZMM_I_Purchasing` |
| C | 소비/프로젝션 뷰 (Consumption/Projection View) | UI 또는 RAP OData 서비스 등 최종 소비를 위한 뷰. 앱과 직접 연결 | `ZSD_C_SalesConsumption` |
| A | 원격 API 뷰 (Remote API View) | 외부 시스템과 통신하기 위해 API 형태로 제공되는 뷰. 외부 노출 가능 | `ZHR_A_Employee_API` |
| X | 뷰 확장 (View Extension) | 기존 CDS 뷰에 필드를 추가하거나 기능을 확장할 때 사용 | `ZMM_X_PurchaseOrder_EXT` |
| E | 확장 포함 뷰 (Extension Include View) | 다른 뷰에 포함될 수 있는 구조 확장용 뷰. 모듈화에 유리 | `ZSD_E_SalesOrderInclude` |
| F | 유도 함수 (Derivation Function) | 계산 또는 파생 로직을 구현한 함수성 뷰(예: 세금 계산) | `ZFI_F_FinanceTaxCalc` |
| D | 추상 엔티티 (Abstract Entity) | 실제 테이블과 연결되지 않은 개념적·논리적 엔티티. RAP Entity 모델 등에서 사용 | `ZMM_D_LogisticsEntity` |

Suffix.

| Suffix | View 유형 | 설명 | 예시 |
|---|---|---|---|
| Query, Qry, Q | 분석용 쿼리 뷰 (Analytical query view) | 분석 또는 리포트를 위한 계산 중심의 쿼리 뷰 | `ZMM_C_PurchaseOrderQuery` 또는 `ZMM_C_PurchaseOrder_Q` |
| Cube, C | 분석 큐브 뷰 (Analytical cube view) | 다양한 차원에서 집계 데이터를 제공하는 다차원 큐브 뷰 | `ZSD_C_SalesDataCube` 또는 `ZSD_C_SalesData_C` |
| Text, Txt, T | 언어 의존 텍스트 제공 뷰 (Language-dependent text provider) | 다국어 UI 에 텍스트를 제공하는 뷰 | `ZMM_I_MaterialText` 또는 `ZMM_I_Material_T` |
| TP | 트랜잭션 처리 뷰 (Transactional processing view) | 입력·처리 중심의 트랜잭션 데이터를 다루는 뷰 | `ZFI_C_FinanceJourEntriesTP` 또는 `ZFI_C_FinanceJourEntries_TP` |
| VH/StdVH | 값 도움말 뷰 ((Standard) Value help view) | UI 필드 선택에 필요한 값 목록을 제공 | `ZMM_I_MaterialsVH` 또는 `ZMM_I_Materials_VH` |

### 2.3 CDS Field

| 규칙 | 설명 | 예시 |
|---|---|---|
| 일관성 및 약어 사용 지양 (Uniformity and Avoidance of Ambiguity) | 필드 이름은 전체 단어로 구성하고, 같은 개념에는 같은 명칭을 사용 | `SalesOrderNumber` (O) / `SlsOrdNo` (X) |
| CamelCase 로 가독성 향상 (Legibility by Using Camel Case) | 단어마다 첫 글자를 대문자로 써 이름을 직관적으로 표현 | `CustomerName`, `DeliveryDate` |
| 약어 사용 회피 (Avoidance of Abbreviations) | 약어보다 의미가 분명한 전체 단어를 써 오해를 막는다 | `MaterialDescription` (O) / `MatDesc` (X) |

Field Naming Structure(네이밍 요소).

| 네이밍 요소 | 설명 | 예시 |
|---|---|---|
| 객체 (Object) | 사물 또는 개념의 클래스(유형)를 정의 | `SalesOrder` |
| 속성 (Property) | 객체 인스턴스 간에 공유되는 특성 | `Confirmation` |
| 표현형 (Representation) | 해당 속성이 나타내는 데이터 형식 또는 표현 | `Date` |

Field Naming Representation Term(표현 용어).

| 표현 용어 | 설명 | 예시 |
|---|---|---|
| 식별자 (Identifier) | 인스턴스를 식별하는 값 | `BankAccount`, `BankAccountUUID` |
| 코드 (Code) | 미리 정의된 값들의 범위 안에서 선택되는 값 | `CorrespondenceLanguage`, `TransactionCurrency` |
| 표시자 (Indicator) | 참/거짓(boolean) 값 | `OrderIsReleased` |
| 금액 (Amount) | 특정 시점의 금액 | `TaxAmount` |
| 날짜 (Date) | 달력 날짜 | `GoodsArrivalDate` |
| 시간 (Time) | 특정 시각 | `ShiftDay`, `EndTime` |
| 날짜와 시간 (Date and Time) | 날짜와 시간을 모두 포함하는 값 | `CreationDateTime` |
| 수량 (Quantity) | 셀 수 있거나 측정 가능한 양 | `InspectedProductQuantity` |
| 텍스트 (Text) | 텍스트 정보 | `GoodsLocationText` |
| 기간 (Duration) | 두 시점 사이의 기간 | `ServiceWorkDuration` |

### 2.4 Business Services

| 객체 | 이름 형식 | 길이 제한 | 예시 |
|---|---|---|---|
| Service Definition | `Z` + 영역코드 + `_` + 서비스 유형(`UI`/`API`) + `_` + Text | 40 | `ZSD_UI_CUSTOMER`, `ZSD_API_CUSTOMER` |
| Service Binding | `Z` + 영역코드 + `_` + 서비스 유형(`UI`/`API`/`OB`) + `_` + Text + `_` + Suffix | 30 | `ZSD_UI_CUSTOMER_V2`, `ZSD_UI_CUSTOMER_V4`, `ZSD_API_CUSTOMER_V2`, `ZSD_API_CUSTOMER_V4` |

서비스 유형(5~6(7)번째 자리).

| 값 | 의미 | 쓰는 곳 |
|---|---|---|
| UI | Fiori App 과 연결되는 UI 용 서비스 정의 | Definition, Binding |
| API | 외부 연동용 OData API 용 서비스 정의 | Definition, Binding |
| OB | Outbound Service 용 서비스 정의 | Binding 만 |

Service Binding Suffix.

| Suffix | 의미 |
|---|---|
| V2 | OData V2 형식 |
| V4 | OData V4 형식 |
| REST | Outbound Service 형식 |

- Service Definition 의 Text 는 8~40자리, Service Binding 의 Text 는 8~N자리이고 `_` + Suffix 가 (N+2)~30자리.
- 원문 예시 표기: Definition `UI: ZSD_UI_CUSTOMER`, `Web API: ZSD_API_CUSTOMER`. Binding `UI + OData V2: ZSD_UI_CUSTOMER_V2` 등.

### 2.5 Source Code Objects

| Prefix | 구분 | 설명 | 예시 |
|---|---|---|---|
| `ZBP_` | Behavior Pool | RAP 의 Behavior 정의를 구현하는 ABAP 클래스의 접두어 | `ZBP_SD_CUSTOMER` |
| `LHC_` | Handler Class | RAP 의 행동 처리 로직을 구현하는 Local Handler Class | `LHC_ZSD_CUSTOMER` |
| `LSC_` | Saver Class | RAP 의 저장 로직을 담당하는 Saver Class | `LSC_ZSD_CUSTOMER` |

- Association 은 `_CamelCase` 로 쓰는 것을 권장한다. 예: `_toSalesOrder`, `_toBusinessPartner`.
- Behavior Definition 을 만든 뒤 Behavior Extension Class 를 만들면 위 Prefix 가 자동으로 붙는다.

### 2.6 Message

| 객체 | 이름 형식 | 길이 제한 | 예시 |
|---|---|---|---|
| Message Class | `Z` + 영역코드 | 20 | `ZMM` |
| Message Number | 001~999 (Custom 메시지 번호) | - | `900` |

- 표준 SAP Error Message 이외에 추가하는 Message 는 SAP message 에 추가될 때 900 으로 시작해서 추가될 수 있다.

### 2.7 ABAP Class · AMDP Class · CDS Table Function

| 객체 | 이름 형식 | 길이 제한 | 예시 |
|---|---|---|---|
| ABAP Class | `Z` + `CL` + `_` + Text | 30 | `ZCL_SalesOrderUpdate` |
| AMDP Class | `Z` + `CL` + `_` + `AMDP` + `_` + Text | 30 | `ZCL_AMDP_SalesOrderUpdate` |
| CDS Table Function | `Z` + 영역코드 + `_` + `TF` + `_` + Text | 30 | `ZFI_TF_JournalEntry` |

세부(원문 위치 번호 그대로).

| 객체 | 위치 | 용도 | 설명 |
|---|---|---|---|
| ABAP Class | 1 | CBO 구분 | Y / Z |
| | 2~3 | 영역 코드 | "Class" (원문 표기. 예시는 `CL`) |
| | 4 | 구분자 | `_` |
| | 5~30 | Text | 사용자 정의(의미 있는 내용) Class 이름 |
| AMDP Class | 1 | CBO 구분 | Y / Z |
| | 2~3 | 영역 코드 | "Class" (원문 표기. 예시는 `CL`) |
| | 4 | 구분자 | `_` |
| | 5~8 | 서비스 유형 | `AMDP`: ABAP Managed Database Procedure |
| | 9 | 구분자 | `_` |
| | 10~N | Text | 사용자 정의(의미 있는 내용) AMDP Class 이름 |
| CDS Table Function | 1 | CBO 구분 | Y / Z |
| | 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| | 4 | 구분자 | `_` |
| | 5~6 | 서비스 유형 | `TF`: Table Function |
| | 7 | 구분자 | `_` |
| | 9~N | Text | 사용자 정의(의미 있는 내용) 이름 |

## 3. KeyUser Objects (S/4HANA Cloud Public Edition)

Key User Extensibility 객체는 모두 예약어 `YY1_` 로 시작한다. `YY1_` 는
Key User Extensibility 식별 예약어이며 삭제할 수 없다.

| 객체 | 이름 형식 | 길이 제한(예약어 포함) | 예시 |
|---|---|---|---|
| Custom CDS View · Analytical Query | `YY1_` + 영역코드 + `_` + Text + `_` + 시나리오 코드 + 버전 | 26 | `YY1_MM_Materials_VH`, `YY1_MM_Materials_VH_1` |
| Custom Field | `YY1_` + Text | 22 | `YY1_ProjectName` |
| Custom Business Object | `YY1_` + Text | 26 | `YY1_BonusPlan` |
| Custom Logic | `YY1_` + Text | 30 | `YY1_SendEmail`, `YY1_PROJECT_VALIDATION` |
| Outbound Service (Custom Business Object 용) | `YY1_` + `OB` + `_` + Text + `_REST` | 30 | `YY1_OB_SalesOrder_REST`, `YY1_OB_PROJECT_VALIDATION_REST` |
| Communication Scenario ID (Custom Business Object 용) | `YY1_` + `CS` + `_` + Text | 30 | `YY1_CS_SalesOrder`, `YY1_CS_PROJECT_VALIDATION` |

세부.

| 객체 | 위치 | 용도 | 설명 |
|---|---|---|---|
| Custom CDS View · Analytical Query | 1~4 | 예약어 | `YY1_` |
| | 5~6 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| | 7 | 구분자 | `_` |
| | 8~N | Text | 사용자 정의(의미 있는 내용) CDS View 이름 |
| | N+1 | 구분자 | `_` |
| | (N+2)~(N+3) | 시나리오 코드 | AC, VH, DE, AD, EA, SC(생략) |
| | (N+4)~(N+5) | Version | 생략: 최초 CDS View / `_1`~: 최초 CDS View 의 변경 사항을 반영한 버전 순번 |
| Custom Field | 5~N | Text | 사용자 정의(의미 있는 내용) Field 명 |
| Custom Business Object | 5~N | Text | 사용자 정의(의미 있는 내용) Business Object 명 |
| Custom Logic | 5~N | Text | 사용자 정의(의미 있는 내용) Logic 명 또는 Extension Point 의 BAdI 명 |
| Outbound Service | 5~6 | 영역 코드 | `OB` (Outbound Service, 원문 표기) |
| | 7 | 구분자 | `_` |
| | 8~25 | Text | 사용자 정의(의미 있는 내용) Service 명 |
| | 26~30 | Suffix | `_REST` (예약어, 삭제 불가) |
| Communication Scenario ID | 5~6 | 영역 코드 | `CS` (Communication Scenario, 원문 표기) |
| | 7 | 구분자 | `_` |
| | 8~30 | Text | 사용자 정의(의미 있는 내용) Logic 명 또는 업무명 |

View 시나리오 코드.

| 코드 | View 시나리오 | 설명 | 예시 |
|---|---|---|---|
| AC | 분석용 집계 데이터 (Analytical cube) | 다차원 분석을 위한 집계 데이터 제공 뷰(Query 에서 주로 사용) | `YY1_SD_SalesOverview_AC` |
| VH | 값 선택 (F4 도움말) (Value Help) | F4 도움말 제공용 뷰(입력 필드의 값 선택 목록 제공) | `YY1_MM_Materials_VH` |
| DE | 외부 시스템 데이터 추출 (Data Extraction) | 외부 시스템이나 BW 로 데이터를 추출하기 위한 뷰 | `YY1_MM_InvoiceExport_DE` |
| AD | 분석 기준 정보(차원) (Analytical Dimension) | 분석 큐브(AC)에 연결될 차원 정보 제공(차트 기준 정보 등) | `YY1_SD_CustomerInfo_AD` |
| EA | API 제공 목적 (External API) | 외부 시스템에 API 형태로 제공되는 뷰(OData/API 로 노출 목적) | `YY1_HR_EmployeeDetail_EA` |
| SC, 생략 | SAP 제공 표준 뷰 (Standard CDS View) | SAP 에서 제공하는 표준 CDS 뷰(수정 불가, 재사용용 참고) | `YY1_MM_PurchaseItems` |

## 4. Communication configuration (S/4HANA Cloud Public Edition)

| 객체 | 이름 형식 | 길이 제한 | 예시 |
|---|---|---|---|
| Communication System · User | `ZCOM_` + 통신 대상 시스템 약어(3자리) + Optional(`_` + 의미 있는 내용) | - | `ZCOM_EAI`, `ZCOM_FBS`, `ZCOM_BTP_RPA` |
| Custom Communication Scenario | `Z` + 영역코드 + `_` + `CS` + `_` + Text | 30 | `ZSD_CS_SalesOrderManage` |
| Communication Arrangement | `Z` + 영역코드 + `_` + `CA` + `_` + Text | 30 | `ZSD_CA_SalesOrderManage` |

- Communication System 과 User 는 같은 이름으로 관리한다.
- Communication System · User 위치: 1~5 `ZCOM_`(Communication 식별 예약어), 6~8 통신 대상 시스템 약어(3자리), 9~N Optional(`_` 를 Prefix 로 붙인 뒤 사용자 정의 이름).
- Custom Communication Scenario 위치: 1 CBO 구분, 2~3 영역 코드, 4 `_`, 5~6 `CS`, 7 `_`, 8~30 사용자 정의 통신 시나리오 이름.
- Communication Arrangement 위치: 1 CBO 구분, 2~3 영역 코드, 4 `_`, 5~6 `CA`, 7 `_`, 8~30 Text. 표준 Communication Scenario 를 쓰면(예: `SAP_COM_0100`) `COM_0100` + Optional(`_` + 의미 있는 내용), 직접 만든 Communication Scenario 면 사용자 정의 통신 시나리오 이름.
- 원문은 Communication Scenario·Arrangement 의 길이 제한을 둘 다 "Communication Scenario ID 는 최대 30자리" 로 적었다.

## 5. SAPUI5

### 5.1 Namespace

형식: `kr.co.<회사약어>.<시스템 구분>`

| 구분 | 값 |
|---|---|
| 국가 코드 | `kr` |
| 기관 코드 | `co` |
| 회사 약어 | `<회사약어>` |
| 시스템 구분 | `erp`: S/4HANA Cloud Public 에 배포되는 App / `btp`: BTP 에 배포되는 App |

구분자는 `.` 이다.

### 5.2 Module name · Project name

| 위치 | 용도 | 설명 |
|---|---|---|
| 1 | CBO 구분 | Y / Z |
| 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| 4 | 유형 | `U`: SAP UI5 |
| 5~7 | 일련번호 | 3자리 Serial 숫자 |
| 8 | 테이블 번호 | `0`: 메인 테이블 / `1`~`9`: 메인 테이블에 대한 Sub-Table 또는 연관된 파생·추가 테이블 |

- 예시: `zdfu0010`
- BSP ABAP Repository 는 최대 15자리.
- 단, 표준 프로그램 Adaptation 또는 Extension 을 하는 경우는 예외.

### 5.3 파일 · 코드 이름

| 대상 | 이름 형식 | 표기법 | 예시 |
|---|---|---|---|
| View 파일명 | `text` + `.view.xml` (text: View 의 용도를 쉽게 알 수 있는 단어를 조합) | - | `CustomerList.view.xml`, `OrderList.view.xml`, `OrderDetail.view.xml` |
| Fragment 파일명 | `text1` + `text2` + `.fragment.xml` (text1: Fragment 의 용도를 뜻하는 단어 조합, text2: Fragment 를 대표하는 Control name) | Upper Camel Case | `SearchDialog.fragment.xml`, `AdditionalTable.fragment.xml` |
| Controller 파일명 | `text` + `.controller.js` (text: View 의 text 와 같게) | - | `CustomerList.controller.js`, `OrderList.controller.js`, `OrderDetail.controller.js` |
| Control id | `text1` + `text2` (text1: 컨트롤의 용도를 쉽게 알 수 있는 단어 조합, text2: `Button`, `Input`, `ComboBox` 등) | Lower Camel Case | `deliveryFromDate`, `goodsNameInput`, `deleteRowButton` |
| Event handler | `on` + `text2` + `text3` (text2: 기능을 쉽게 알 수 있는 단어 조합, text3: Control 의 event name) | Upper Camel Case | `onNewItemPress`, `onSelectedRowDeletePress` |
| Internal function | `fn` + `text2` (text2: 기능을 쉽게 알 수 있는 단어 조합) | Upper Camel Case | `fnGetToken`, `fnSendRequest`, `fnParsingResponse` |
| i18n key | `text1` + `text2` + `text3` (text1: View 의 text 와 같게, text2: Control 의 ID, text3: 텍스트가 보여질 Attribute 명칭) | Upper Camel Case | `MainNameLableText`, `MainTableAmountText` |
| Constant | 상수의 용도를 알 수 있는 단어. 둘 이상이면 `_` 로 조합 | - | `MAX_LENGTH`, `SUCCESS`, `FAIL` |
| Variable | 데이터 타입 접두어 + `text2` (text2: 용도를 쉽게 알 수 있는 단어 조합) | Lower Camel Case | `iTotalCount`, `dTaxRate`, `oParameter` |

- Controller Lifecycle method 는 기존 명칭을 유지한다(Event handler 예외).
- 원문의 i18n key 예시 표기: 자리 구분자는 `.` (N+1, M+1 위치)이나 예시에는 `.` 이 없다.

변수 접두어(데이터 타입).

| 타입 | 접두어 | 설명 | 예시 |
|---|---|---|---|
| String | `s` | String 값 | `sName`, `sMessage` |
| 정수형 | `i` | 정수형 값 | `iCost`, `iTotal` |
| 실수형 | `d` | 실수형 값 | `dAmount`, `dTaxRate` |
| Boolean | `b` | 참/거짓 값 | `bIsReady`, `bDone` |
| 객체 | `o` | 객체 유형 | `oObject`, `oButton` |
| 함수 | `fn` | 함수 유형 | `fnCallback`, `fnSuccess` |

### 5.4 SemanticObject · Action

| 대상 | 규칙 | 표기법 | 예시 |
|---|---|---|---|
| SemanticObject name | Module name 의 text 와 같게 명명. 일관성을 지키고 약어 사용을 피한다 | Upper Camel Case | `SalesOrderList`, `MaterialList` |
| Action name | 어떤 View 를 가리키는지 쉽게 짐작할 수 있는 단어를 조합. 일관성을 지키고 약어 사용을 피한다 | Upper Camel Case | `List`, `Display`, `Detail` |

- SemanticObject 와 Action 을 이은 예시: `OrderManagement-List`, `Finance-Detail`.

## 6. NodeJS (CAP CDS)

| 대상 | 이름 형식 | 표기법 | 예시 |
|---|---|---|---|
| CDS Domain - Model 파일명 | `schema` + `.` + `cds` | - | `schema.cds` |
| CDS Domain - Namespace | `<회사약어>` + `.` + 모듈 코드(`fi`, `co`, `mm`, `pp`, `sd` 등) | - | `<회사약어>.fi`, `<회사약어>.mm`, `<회사약어>.sd` |
| CDS Domain - Entity name | 용도를 쉽게 알 수 있는 단어 조합. 같은 개념에는 같은 명칭. 약어 사용 지양 | Upper Camel Case | `SalesOrderList`, `MaterialList` |
| CDS Domain - Element name | 용도를 쉽게 알 수 있는 단어 조합. 같은 개념에는 같은 명칭. 약어 사용 지양 | Lower Camel Case | `deliveryDate`, `orderDate` |
| CDS Service - Definitions 파일명 | `text` + `_` + `service` + `.` + `cds` (text: 서비스의 기능을 명확히 표현하는 단어를 조합) | Upper Camel Case 를 조합 | 원문 예시 `OrderProcess-service.cds`, `MaterialManagement-service.cds` |
| CDS Service - Implementation 파일명 | `text` + `-` + `service` + `.` + `js` (text: Service definitions name 과 같게) | - | `OrderManagement-service.js`, `MaterialManagement-service.js` |
| CDS Service - Entity name | 전체 단어로 이름을 구성. 같은 개념에는 같은 명칭 | Upper Camel Case | `SalesOrderList`, `MaterialList` |
| CDS Service - Element name | 전체 단어로 이름을 구성. 같은 개념에는 같은 명칭 | Lower Camel Case | `deliveryDate`, `orderDate` |
| CDS Service - Action & Function | `prefix` + `text` (prefix: 대표 기능을 동사로, text: 로직을 설명할 수 있는 단어 조합) | prefix 는 lower case, text 는 Upper Camel Case | `getOrderList`, `createCostomerInformation`, `UpdateOrderItem` (원문 예시 그대로) |
| CDS Service - Additional Library | `text` + `.` + `js` (용도에 맞게 이름을 만든다) | - | `Helper.js`, `Utils.js` |
| CDS - Constant name | 상수의 용도를 알 수 있는 단어. 둘 이상이면 `_` 로 조합 | - | `MAX_LENGTH`, `SUCCESS`, `FAIL` |
| CDS - Variable name | 데이터 타입 접두어 + `text2` (text2: 용도를 쉽게 알 수 있는 단어 조합) | Lower Camel Case | `iTotalCount`, `dTaxRate`, `oParameter` |

- Service Definitions 파일명의 구분자는 원문 표(위치 N+1)에 `_` 로 적혀 있고 예시는 `-` 이다. Implementation 쪽은 표·예시 모두 `-` 이다. 원문 그대로 옮겼다.
- CDS 변수 타입 접두어는 5.3 의 변수 접두어 표와 같다(`s`, `i`, `d`, `b`, `o`, `fn`).

## 7. Fiori Launchpad & Work Zone

| 객체 | 이름 형식 | 길이 제한 | 예시 |
|---|---|---|---|
| IAM App | `Z` + 영역코드 + `_` + `IAM` + `_` + Text + Suffix | 30 | `ZFI_IAM_CUSTOM`, `ZFI_IAM_CUSTOM_EXT`, `ZFI_IAM_SALESORDER_UI5A` |
| Business Role | `Z` + 영역코드 + `_` + `BR` + `_` + Text | 40 | `ZFI_BR_CUSTOM` |
| Business Catalog | `Z` + 영역코드 + `_` + `BC` + `_` + Text | 30 | `ZBC_PP_SCHEDULING` (원문 예시 그대로) |
| Launchpad Space ID | `Z` + 영역코드 + `_` + `SP` + `_` + Text | 35 | `ZPP_SP_Scheduling` |
| Launchpad Page ID | `Z` + 영역코드 + `_` + `PG` + `_` + Text | 35 | `ZPP_PG_Scheduling` |

세부.

| 객체 | 위치 | 용도 | 설명 |
|---|---|---|---|
| IAM App | 1 | CBO 구분 | Y / Z |
| | 2~3 | 영역 코드 | FI, CO, MM, PP, SD 등 |
| | 4, 8 | 구분자 | `_` |
| | 5~7 | 서비스 유형 | `IAM`: Cloud Identity and Access Management, 업무 중심의 역할 부여 |
| | 8~25 | Text | 사용자 정의(의미 있는 내용) 역할 목적 |
| | N~30 | Suffix | `_EXT`: External App(삭제 불가) / `_MBC`: Business Configuration App(삭제 불가) / `_UI5A`: UI Adaptation App(삭제 불가) |
| Business Role | 4, 7 | 구분자 | `_` |
| | 5~6 | 서비스 유형 | `BR`: Business Role, 업무 중심의 역할 부여 |
| | 8~ | Text | 사용자 정의(의미 있는 내용) 권한 이름, 역할 목적 |
| Business Catalog | 4, 7 | 구분자 | `_` |
| | 5~6 | 서비스 유형 | `BC`: Business Catalog, 실제 사용자 역할에 따라 제공되는 비즈니스 프로세스 단위 카탈로그 |
| | 8~ | Text | Business Process 이름: 실제 사용자 활동. 예: Approval, Scheduling, Tracking |
| Launchpad Space ID | 4, 7 | 구분자 | `_` |
| | 5~6 | 서비스 유형 | `SP`: Space, Fiori Launchpad 상단 탭(스페이스)에 해당. 비즈니스 프로세스 단위로 구성 |
| | 8~ | Text | Business Process 이름(위와 같음) |
| Launchpad Page ID | 4, 7 | 구분자 | `_` |
| | 5~6 | 서비스 유형 | `PG`: Page, Space 안에 포함되는 하위 페이지 구성. 앱 타일이 배치됨 |
| | 8~ | Text | Business Process 이름(위와 같음) |

모든 객체의 1번째 자리는 CBO 구분(`Y`/`Z`), 2~3번째 자리는 영역 코드이다.
