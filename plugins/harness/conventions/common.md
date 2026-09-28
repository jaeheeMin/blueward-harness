# 공통 개발 규칙

이 문서는 harness Plugin 에 실려, 어느 Project Repository 에서나 똑같이
지키는 개발 규칙을 담는다. 프로젝트마다 다른 규칙 — 이름 접두어(Z, Y 등),
SAP naming rule 같은 것 — 은 여기 두지 않고 그 저장소 `conventions/` 에
둔다.

두 규칙이 부딪히면 프로젝트 `conventions/` 가 이긴다. 다만 **CR-004(비밀
정보)만은 어떤 프로젝트 Convention 으로도 뒤집지 못한다.**

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
조인의 `<별칭>~*`). `COUNT( * )` 는 통과한다. CDS 는 필드 목록 와일드카드 문법이
불확실해 이번에는 넣지 않았다. 정말 예외라면 같은 줄이나 바로 위 줄에
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

**기계 검사**: 문서로만.

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
`CATCH SYSTEM-EXCEPTIONS ... .` 는 `ENDCATCH.` 까지) 뒤에 다음
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
