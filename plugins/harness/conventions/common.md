# 공통 개발 규칙

이 문서는 harness Plugin 에 실려, 어느 Project Repository 에서나 똑같이
지키는 개발 규칙을 담는다. 프로젝트마다 다른 규칙 — 이름 접두어(Z, Y 등),
SAP naming rule 같은 것 — 은 여기 두지 않고 그 저장소 `conventions/` 에
둔다.

두 규칙이 부딪히면 프로젝트 `conventions/` 가 이긴다. 다만 **CR-004(비밀
정보)만은 어떤 프로젝트 Convention 으로도 뒤집지 못한다.**

## 기본 대상과 ATC 와의 관계

기본 대상은 **S/4HANA Cloud Public Edition 의 ABAP Cloud**(Developer
Extensibility)다. 예시와 판단은 ABAP Cloud 에서 쓸 수 있는 문법을 기준으로
하고, classic ABAP 은 검사기가 함께 받아 줄 뿐 기준으로 삼지 않는다.

SAP 에는 자체 검사 도구 ATC(ABAP Test Cockpit)가 있고, 하네스는 그것을
대신하지 않는다. 둘은 보는 것과 자리가 다르다.

| | 하네스 기계 검사 | ATC |
|---|---|---|
| 자리 | 저장 전(Hook), PR(Actions) | SAP 테넌트 안(ADT 실행, 운송 release) |
| 보는 것 | 아래 CR 규칙 | SAP 가 정한 check variant |

080 개발 테넌트(2026-09-28 실측)의 시스템 variant 는
`ABAP_CLOUD_DEVELOPMENT_DEFAULT` 였다. 실제 Z 클래스 다섯 개에 돌려 보니
`SELECT *`, `FIELDS *`, 반복문 안 `SELECT` 자리에서 finding 이 나오지
않았다 — CR-002, CR-003 은 ATC 와 겹치지 않는다. 빈 CATCH 는 실물 사례가
없어 확인하지 못했다. 같은 실측에서 priority 1·2 finding 은 운송을 막고
(`blockPriority`), priority 3 은 막지 않았다(`allowTransports`). 운송
release 때 ATC 를 자동으로 돌릴지와 막는 기준은 테넌트 관리자 설정이다
(ABAP Development Tools User Guide, "Working with ATC During Transport
Release").

## CR-001 이름에 한글을 쓰지 않는다

변수, 함수, 클래스, 객체, 필드 같은 이름에는 한글을 쓰지 않는다. 주석과
문자열은 괜찮다.

**왜**: 한글 이름은 전송 시스템과 여러 편집기에서 인코딩이 깨지기 쉽고,
팀 밖 개발자가 검색과 자동완성으로 찾지 못한다.

**나쁜 예 (ABAP)**
```abap
DATA 주문번호 TYPE vbeln.
```

**좋은 예 (ABAP)**
```abap
DATA lv_order_no TYPE vbeln. " 주문번호
```

**기계 검사**: 코드 저장 시(훅)와 PR 검사(Actions)에서 막는다. ABAP, JS/TS, CDS,
BDEF(동작 정의)를 본다. 정말 예외라면 같은 줄이나 바로 위 줄에 `harness:allow
CR-001 <이유>` 를 주석으로 남긴다 — 이유 없이는 예외로 인정하지 않는다.

## CR-002 반복문 안에서 DB 를 조회하지 않는다

LOOP, DO, WHILE 같은 반복문(JS 라면 for, while) 안에서 SELECT 를 부르지
않는다. 한 번에 모아 조회한다 — ABAP 은 FOR ALL ENTRIES, JOIN, 범위 조건
IN 을 쓰고, ABAP Cloud 에서는 가능하면 CDS view 로 JOIN 한다.

**왜**: 반복 횟수만큼 DB 왕복이 늘어나, 건수가 커지면 응답 시간이 선형이
아니라 감당할 수 없이 늘어난다.

**나쁜 예 (ABAP)**
```abap
LOOP AT lt_order INTO ls_order.
  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.
ENDLOOP.
```

**좋은 예 (ABAP)**
```abap
SELECT * FROM vbak INTO TABLE lt_vbak
  FOR ALL ENTRIES IN lt_order WHERE vbeln = lt_order-vbeln.
```

**좋은 예 (ABAP Cloud, CDS)**: `define view entity Z_I_Order as select from
vbak inner join vbap on vbak.vbeln = vbap.vbeln`

**기계 검사**: 코드 저장 시(훅)와 PR 검사(Actions)에서 막는다. ABAP 은 LOOP/DO/WHILE
과 SELECT...ENDSELECT 의 중첩을 세고, JS/TS(CAP) 는 `for`/`while`/`.forEach`/`.map`
안의 `SELECT.from` 류 호출을 잡는다(휴리스틱). 정말 예외라면 `harness:allow CR-002
<이유>` 주석을 남긴다 — 이유 없이는 예외로 인정하지 않는다.

## CR-003 SELECT * 대신 필요한 필드만 조회한다

**왜**: 필요 없는 컬럼까지 읽으면 네트워크와 메모리를 낭비하고, 테이블에
필드가 늘어날 때 호출부가 말없이 더 무거워진다.

**나쁜 예 (ABAP)**
```abap
SELECT * FROM vbak INTO TABLE lt_vbak WHERE vbeln IN lt_vbeln.
```

**좋은 예 (ABAP)**
```abap
SELECT vbeln, erdat, kunnr FROM vbak INTO TABLE lt_vbak WHERE vbeln IN lt_vbeln.
```

**기계 검사**: 코드 저장 시(훅)와 PR 검사(Actions)에서 막는다. ABAP 만 본다(옛
문법 `SELECT [SINGLE] [DISTINCT] * FROM`, 새 문법 `SELECT FROM ... FIELDS *`,
조인의 `<별칭>~*`). `COUNT( * )` 는 통과한다. CDS view entity 는 `SELECT *` 자체를
지원하지 않아 SAP 가 활성화 단계에서 막으므로 따로 검사하지 않는다. 정말 예외라면 같은 줄이나 바로 위 줄에
`harness:allow CR-003 <이유>` 를 주석으로 남긴다 — 이유 없이는 예외로 인정하지
않는다.

## CR-004 비밀정보를 소스나 저장소에 두지 않는다

비밀번호, 토큰, 접속 정보(Credential)를 소스 코드나 저장소 어디에도 두지
않는다. 환경별 URL 처럼 비밀이 아닌 값은 `env/` 에 둬도 되지만, 거기에도
Credential 은 넣지 않는다.

**왜**: 저장소는 git 이력을 남긴다. 한 번 커밋되면 나중에 지워도 이력에
남고, Private 저장소라도 팀원이 늘수록 노출 범위가 넓어진다.

**나쁜 예 (ABAP)**
```abap
DATA lv_password TYPE string VALUE 'P@ssw0rd123'.
```

**좋은 예 (ABAP)**
```abap
" Secure Login Library 나 Destination Service 로 런타임에 받는다
DATA lv_password TYPE string.
lv_password = get_password_from_destination( ).
```

**기계 검사**: 문서로만.

## CR-005 표준 객체를 직접 수정하지 않는다

표준(SAP 제공) 객체를 직접 고치지 않고, 공개된 확장 지점(Released API,
Cloud BAdI, 사용자 로직 등)만 쓴다. 프라이빗 프로젝트에서 다르게 정했으면
그 사실을 프로젝트 `conventions/` 에 적는다.

**왜**: 표준 객체를 고치면 업그레이드나 패치마다 충돌하고, 클린 코어
원칙에서 벗어난다.

**나쁜 예 (ABAP)**: 표준 클래스나 프로그램의 소스를 직접 열어 로직을
덧붙인다.

**좋은 예 (ABAP Cloud)**: Cloud BAdI 구현 클래스에서 정해진 확장 지점만
구현한다.

**기계 검사**: 하네스는 검사하지 않는다. Public Cloud 에서는 플랫폼이 막는다
— ABAP Cloud 는 같은 software component 의 오브젝트나 released API 만 쓰거나
확장할 수 있다("Both language versions only allow access to repository
objects of the same software component or repository object released with
the required release contracts", SAP 공식 PDF "ABAP Cloud: Background
Concepts and Overview", help.sap.com). Private Cloud·온프레미스처럼 classic
ABAP 을 함께 쓰는 프로젝트에서는 리뷰로 본다.

## CR-006 하드코딩한 값은 설정이나 상수로 뺀다

회사 코드, 플랜트, 사용자 ID 같은 값을 소스에 직접 박지 않고 설정
(Customizing, 환경변수)이나 상수로 뺀다.

**왜**: 값이 바뀌거나 다른 회사코드에 적용할 때마다 소스를 뒤져 고쳐야
하고, 한 곳이라도 빠뜨리면 조용히 틀린 채로 넘어간다.

**나쁜 예 (ABAP)**
```abap
IF iv_bukrs = '1000'.
```

**좋은 예 (ABAP)**
```abap
IF iv_bukrs = gc_company_code_kr.
```

**기계 검사**: 문서로만.

## CR-007 오류를 조용히 삼키지 않는다

예외나 오류를 잡았으면 기록(로그)하거나 사용자에게 알린다. 잡기만 하고
아무 것도 하지 않는 빈 CATCH 는 두지 않는다.

**왜**: 조용히 삼킨 오류는 실패가 일어난 그 자리에서 사라져, 훨씬 뒤에
엉뚱한 곳에서 원인 모를 증상으로 나타난다.

**나쁜 예 (ABAP)**
```abap
TRY.
    lo_service->call( ).
  CATCH cx_root.
ENDTRY.
```

**좋은 예 (ABAP)**
```abap
TRY.
    lo_service->call( ).
  CATCH cx_root INTO lx_error.
    MESSAGE lx_error->get_text( ) TYPE 'E'.
ENDTRY.
```

**기계 검사**: 코드 저장 시(훅)와 PR 검사(Actions)에서 막는다. ABAP, JS/TS 를
본다. "완전히 빈" CATCH 만 잡는다 — ABAP 은 `CATCH ... .` (옛 문법
`CATCH SYSTEM-EXCEPTIONS ... .` 는 `ENDCATCH.` 까지 — ABAP Cloud 에는 이
문법이 없어 classic ABAP 에서만 해당한다) 뒤에 다음
CATCH/CLEANUP/ENDTRY(또는 ENDCATCH)까지 문장이 하나도 없으면(주석만 있어도
같다) 위반이고, JS/TS 는 `catch {}`/`catch (e) {}` 와 `.catch(() => {})`/
`.catch(function(){})` 처럼 처리 콜백이 빈 프로미스 형태를 잡는다. 예외를
잡아 로그만 남기고 재던지지 않는 것처럼 "완전히 비어 있지는 않은" 경우는
모양만으로 판정할 수 없어 사람 리뷰의 몫으로 남긴다. 정말 예외라면 같은 줄이나
바로 위 줄에 `harness:allow CR-007 <이유>` 를 주석으로 남긴다 — 이유 없이는
예외로 인정하지 않는다.

## CR-008 이름 접두어와 네이밍 규칙은 프로젝트 conventions 에 둔다

Z, Y 같은 이름 접두어와 그 프로젝트만의 네이밍 규칙은 공통 규칙이 아니라
각 Project Repository 의 `conventions/` 에 둔다.

**왜**: 접두어는 고객사·프로젝트마다 다르게 정해진다. 여기 공통 규칙에
두면 프로젝트마다 예외를 적어야 해서 오히려 헷갈린다.

**나쁜 예**: 이 문서(common.md)에 "접두어는 Z 로 통일한다" 처럼 특정
프로젝트의 규칙을 적는다.

**좋은 예**: 프로젝트 `conventions/naming.md` 에 "커스텀 필드는 ZZ, 커스텀
오브젝트는 Z 로 시작한다" 를 적는다.

**기계 검사**: 문서로만.

## CR-009 데이터를 바꾸는 앱은 권한을 검사한다

생성·변경·삭제·전기·액션처럼 데이터를 바꾸는 RAP 앱은 behavior pool 에서
권한을 실제로 검사한다. BDEF 의 `authorization master ( global | instance )`
가 가리키는 권한 메서드(`FOR GLOBAL AUTHORIZATION`, `FOR INSTANCE
AUTHORIZATION`)가 모든 요청에 `if_abap_behv=>auth-allowed` 만 돌려주면 앱
사용 권한이 있는 사람은 누구나 모든 데이터를 바꿀 수 있다. 검사 방식과 이유는
Spec 의 `## 권한` 절에 적는다.

**왜**: 앱 사용 권한(IAM App)은 앱을 열 수 있느냐만 정한다. 어느 플랜트의
재고를 전기해도 되는지 같은 데이터 단위 권한은 behavior pool 이 검사해야 한다.
SAP 가이드의 전부 허용 예시는 권한 객체가 아직 없을 때 쓰는 시뮬레이션이며
운영에서 쓰지 말라고 안내한다. 검사 없이 배포하면 의도하지 않은 사람이 재고·
전표를 바꿀 수 있다.

**나쁜 예 (ABAP)**
```abap
METHOD get_global_authorizations.
  result-%create = if_abap_behv=>auth-allowed.
  result-%update = if_abap_behv=>auth-allowed.
ENDMETHOD.
```

**좋은 예 (ABAP)** — 구조는 SAP RAP 가이드(Implementing Global/Instance
Authorization)를 따른다. 권한 객체 이름(`ZPP_PLANT`)은 예시다.
```abap
METHOD get_global_authorizations.
  IF requested_authorizations-%create = if_abap_behv=>mk-on.
    AUTHORITY-CHECK OBJECT 'ZPP_PLANT' ID 'ACTVT' FIELD '01'.
    result-%create = COND #( WHEN sy-subrc = 0
                             THEN if_abap_behv=>auth-allowed
                             ELSE if_abap_behv=>auth-unauthorized ).
  ENDIF.
ENDMETHOD.
```
플랜트처럼 데이터 값에 따라 달라지는 권한은 `instance` 권한 메서드에서 인스턴스의
필드 값으로 `ID 'WERKS' FIELD ...` 를 검사한다(create 와 static action 은
instance 권한을 쓸 수 없다). 권한을 다른 곳(표준 BO, CDS 접근 제어(DCL))에
위임한 것이면 `harness:allow CR-009 <이유>` 로 그 사실과 근거를 남긴다.

**기계 검사**: 경고만 한다(`level: warn` — 코드 저장과 PR 검사를 막지는 않는다. 훅은
저장 때 경고를 알려 주고 PR 코멘트에 "경고" 로 나온다). ABAP 소스에서 `FOR GLOBAL
AUTHORIZATION` 또는 `FOR INSTANCE AUTHORIZATION` 메서드(`METHODS:` 콜론 체인 선언 포함)의
구현이 (a) `auth-allowed` 만 대입하고(`auth-unauthorized` 가 없다) 그 **클래스 구현**
(`CLASS ... IMPLEMENTATION` ~ `ENDCLASS`) 안에 `AUTHORITY-CHECK` 가 없거나, (b) 본문이
비었거나 주석뿐이면(비어 있을 때 실제로 무엇을 허용하는지 확인하지 못했으므로
"권한 메서드가 비어 있음 — 확인 필요") 경고한다. 권한 확인을 같은 클래스의 다른 메서드로
빼도 AUTHORITY-CHECK 가 그 클래스에 있으면 경고하지 않는다(주석·문자열 속은 세지 않는다).
못 잡는 것과 한계: 메서드 정의가 다른 파일(`locals_def`)에 있는 경우, 검사는 있지만
틀린 권한 객체·필드를 쓴 경우는 못 잡는다. AUTHORITY-CHECK 가 같은 파일의 다른(헬퍼) 클래스나
다른 파일에 있으면 경고가 나온다 — 오탐이니 `harness:allow` 로 남긴다. 또 위험 판정(risk-gate)이
바꾼 `.abap` 파일에 이 경고가 있으면 "쓰기 앱인데 권한 검사 없음" 사유로 승인을 요구한다. 의도한
것이면 `METHOD <이름>.` 구현 줄이나 바로 위 줄에 `harness:allow CR-009 <이유와 결정자>` 를 남긴다 —
이유 없이는 예외로 인정하지 않는다.
