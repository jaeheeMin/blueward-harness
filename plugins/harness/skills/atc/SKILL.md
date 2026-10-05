---
name: atc
description: SAP ATC(ABAP Test Cockpit) 지적을 돌려 보고 처리 순서에 따라 고친다. 사용자가 "ATC 돌려줘", "ATC 지적 고쳐줘", "ATC 결과 정리해줘", "운송 막는 지적 없애줘" 라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 하네스 코드 규칙(CR-001~) 위반이나 문서 검사 결과를 고치는 말이면 이 스킬 없이 해당 지적을 직접 고치고, 커밋·푸시·PR 이면 deliver 스킬로, 새 작업의 이슈·브랜치면 start 스킬로.
compatibility: SAP ADT MCP 서버(.mcp.json)와 Project Repository 의 env/adt-tiers.yaml 이 필요하다. 이 플러그인 저장소처럼 env/adt-tiers.yaml 이 없는 곳에서는 쓰지 않는다.
---

# /harness:atc

SAP 테넌트에서 ATC 를 돌려 지적(finding)을 모으고, 고칠 수 있는 것과 사람이
정해야 하는 것을 나눠 처리하는 스킬이다. "고쳐 줘" 라고만 맡기면 근거 없이
`"#EC` 로 덮거나, 동작이 바뀌는 수정을 묻지 않고 하거나, 다시 돌려 보지 않고
끝낼 수 있어서 순서를 정해 둔다. 커밋·푸시·PR 은 하지 않는다 — `/harness:deliver`
의 몫이다. `<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는
경로다.

## 쓰는 MCP 도구

도구 이름은 `mcp__<서버>__<도구>` 이고, 인자는 설치된 MCP 서버(`mcp-abap-abap-adt-api`)
정의를 따른다.

| 도구 | 인자 | 돌려주는 것 |
|---|---|---|
| `atcCheckVariant` | `variant`(variant 이름) | 글자 하나 — worklist ID |
| `createAtcRun` | `variant`(**위 ID**, 이름이 아니다), `mainUrl`(대상 오브젝트 또는 패키지 ADT URL), `maxResults`(선택, 기본 100) | `id`, `timestamp`, `infos` — `infos` 의 `FINDING_STATS` 가 priority 1·2·3 건수다(예: `"0,2,0"`) |
| `atcWorklists` | `runResultId`(위 `id`), `timestamp`(`createAtcRun` 이 준 값)·`usedObjectSet`(선택), `includeExempted`(선택) | `objects[]` — 오브젝트마다 `findings[]`(`priority`, `checkId`, `checkTitle`, `messageId`, `messageTitle`, `location`, `quickfixInfo`). `location` 은 소스 URL 과 `range` 인데 의미 있는 것은 **줄 번호뿐**이다(080 실측: `column` 0, start·end 같음) |
| `getObjectSource` | `objectSourceUrl`, `startLine`·`maxLines`(선택) | 소스 |
| `syntaxCheckCode` | `url`(필수), `code`(선택, 없으면 이번 세션에 읽거나 쓴 소스) | 문법 오류·경고 |
| `lock` / `setObjectSource` / `unLock` | `objectUrl` → `objectSourceUrl`·`source`·`lockHandle`(·`transport`) → `objectUrl`·`lockHandle` | 쓰기. 쓰기 허용 서버에서만 |
| `atcExemptProposal` / `atcRequestExemption` | `markerId` / `proposal` | 5단계 참고 |

결과는 모두 `{status, result}` 모양의 JSON 글자로 온다. 도구 이름이 위와 다르거나
인자를 거절하면 짐작해서 바꿔 부르지 말고 멈추고 사람에게 알린다.

## 절차

0. **Project Repository 확인.** 저장소 꼭대기에 `env/adt-tiers.yaml` 이 없으면
   **멈추고** "이 저장소에는 env/adt-tiers.yaml 이 없어 SAP 테넌트 보호가 걸려 있지
   않다. SAP 를 부르는 일은 SAP 서버 표를 가진 Project Repository 세션에서 한다" 고
   알린다. 이 하네스 저장소 같은 곳에서 SAP 도구를 부르지 않는다. 파일이 있으면
   읽어 서버 이름과 `writes_allowed` 를 파악해 둔다.
1. **대상과 서버 확인.** 사용자에게 다음을 확인한다. 정해지지 않은 것은 짐작하지
   않고 묻는다.
   - 대상: 오브젝트 하나 또는 패키지. 가장 좁은 범위로 시작한다. 대상의 ADT URL
     (`mainUrl`)을 `searchObject` 나 `objectStructure` 로 확인한다. 패키지는 담긴
     오브젝트 목록을 먼저 보여 주고 범위를 확인받는다. 패키지 실행은 오래 걸린다
     (080 실측: 패키지 하나에 120초를 넘겨 MCP 가 백그라운드 작업으로 넘겼다) —
     시작 전에 사용자에게 알리고, 결과가 올 때까지 기다린다.
   - 서버: 어느 MCP 서버(테넌트)에서 돌릴지. ATC **실행**은 어느 서버든 할 수
     있다. 소스 **수정**은 `env/adt-tiers.yaml` 에서 `writes_allowed: true` 인
     서버에서만 한다 — 아니면 4단계까지(분류와 보고)만 하고 수정은 하지 않는다.
   - variant 이름: 서버 항목의 선택 키 `atc_variant` 에서 읽는다(예:
     `servers.<서버>.atc_variant: ABAP_CLOUD_DEVELOPMENT_DEFAULT`). 키가 없으면
     **사용자에게 이름을 묻는다** — 추측하거나 다른 프로젝트의 값을 가져다 쓰지
     않는다.
2. **실행과 수집.** `atcCheckVariant`(variant 이름) → 돌려받은 ID 를
   `createAtcRun` 의 `variant` 에 → 돌려받은 `id` 를 `atcWorklists` 의 `runResultId`
   에 넣어 finding 을 모은다. worklist ID 와 `id` 가 같은 값으로 올 수 있다(080
   실측) — 같아도 이상한 것이 아니니 각각 정해진 자리에 넘긴다.
   - worklist 를 읽기 전에 `createAtcRun` 의 `infos` 에서 `FINDING_STATS`(priority
     1·2·3 건수)를 먼저 본다. 합계가 `maxResults` 이상이면 worklist 가 잘린다 —
     `maxResults` 를 합계보다 크게 다시 돌리거나, 대상을 좁히자고 사용자에게
     묻는다. 잘린 결과로 "전부" 라고 말하지 않는다.
   - 도구가 오류를 내거나, ID 가 비었거나, `id` 가 없거나, worklist 를 읽지
     못하면 **"검사 불능"** 이라고 보고하고 멈춘다. 통과나 "지적 없음" 으로 말하지
     않는다. 세션 만료는 `ADT session expired`·401 뿐 아니라 **400** 으로도 나타난다
     (080 실측: `atcCheckVariant`·`searchObject` 가 400) — 400 이 나오면 세션 만료부터
     의심하고, 그 서버에 로그인하는 프로젝트의 스킬(예: 테넌트 로그인 스킬)을
     안내한다.
   - `FINDING_STATS` 가 `0,0,0` 이고 `objects` 가 비었고 오류도 없을 때만 "지적 0건"
     이라고 하되, 어느 서버·대상·variant 로 돌렸는지를 함께 적는다.
3. **표로 보여 주기.** finding 을 체크 종류(`checkTitle`)와 `priority` 별로 묶어
   개수와 대표 위치(오브젝트·줄 번호)를 표로 보여 준다. 다음 사실을 표 아래에 적는다.
   - priority 1·2 지적은 운송 release 를 막고(`blockPriority`), priority 3 은
     막지 않는다(`allowTransports`) — 080 개발 테넌트 실측(#85)이고, release 때
     ATC 를 돌릴지와 막는 기준은 테넌트 관리자 설정이다.
   - priority 가 곧 Clean Core 등급(A~D)은 아니다. 둘의 공식 대응표는 없으므로
     등급으로 환산하지 않고 ATC 가 낸 priority 를 그대로 쓴다.
4. **3단계 분류.** 각 finding 을 소스(`getObjectSource`)와 대조해 셋 중 하나에 넣고,
   표에 분류와 이유 한 줄을 적는다. **애매하면 "확인 후" 로 한다.**
   - **자동**: 동작이 바뀌지 않는 기계적 수정. 예: 쓰이지 않는 변수 선언 삭제,
     `CREATE OBJECT` 를 `NEW` 로, `READ TABLE` + `sy-subrc` 를 `line_exists( )` 로,
     체인 선언(`DATA: a, b.`)을 풀기. 자동이라도 묶음(배치) 단위로 무엇을 바꿀지 보여 주고 사용자 확인을
     받은 뒤 적용한다 — 말없이 적용하지 않는다.
   - **확인 후**: 동작·성능·의미가 바뀔 수 있는 수정. 예: 반복문 안 조회를 밖으로
     빼기, `SELECT` 필드 목록 바꾸기, 예외 처리 흐름 바꾸기, 매개변수 방식
     (`EXPORTING` → `RETURNING`) 바꾸기, 상수 추출. 무엇이 어떻게 바뀌는지와 영향을
     보여 주고 **사용자가 승인한 뒤에만** 고친다.
   - **수동**: 설계 변경이나 released API 대체가 필요한 것. 예: 릴리스되지 않은
     테이블·함수 모듈을 released CDS 뷰·클래스로 바꾸기(컬럼·인터페이스가 달라진다),
     권한 검사 구조 추가, 인터페이스 변경. 고치지 않고 목록과 이유만 보고한다.
5. **`"#EC` 와 exemption.** `"#EC …` pseudo-comment 로 지적을 끄거나 ATC exemption 을
   요청하는 것은 지적이 이 맥락에서 **왜 틀렸는지** 근거를 **사용자가 승인**했을
   때만 한다. 근거 없이 끄는 것은 수정이 아니다. 쓰면 근거를 같은 줄 주석이나 PR
   본문에 남긴다. `atcRequestExemption` 은 사람이 승인하는 절차를 여는 도구라
   Claude 가 단독으로 제출하지 않는다 — 필요하면 `atcExemptProposal`(`markerId`)로
   제안서까지만 만들어 보여 주고 제출은 사람이 하게 한다.
6. **수정과 재실행.** 승인된 묶음만 고친다. 고치기 전 소스(`getObjectSource`)를
   그대로 보관해 두고, 되돌릴 때 그 소스를 다시 쓴다. 쓰기 허용 서버에서 `lock` →
   `setObjectSource`(`lockHandle`) → `unLock` 으로 쓴다. 쓰기 가드가 거절하면
   우회하지 않고 사유를 보고한다. 쓴 뒤 `syntaxCheckCode`(`url`)로 문법을 확인하고,
   오류가 있으면 되돌린다. 그다음 **같은 서버·같은 variant·같은 대상**으로 2단계를
   다시 돌려 전후 개수를 표로 보고한다.

   | 구분 | 이전 | 이후 | 증감 |
   |---|---|---|---|
   | priority 1 | | | |
   | priority 2 | | | |
   | priority 3 이하 | | | |

   새로 생긴 지적이 있으면 그 수정을 되돌리고 이유를 적는다. 재실행이 검사 불능이면
   "줄었다" 고 말하지 않고 검사 불능으로 보고한다. 활성화(`activateObjects` 등)는
   이 스킬 범위가 아니다 — 필요하면 사용자에게 알린다. ATC 가 활성화 전(inactive)
   소스를 보는지는 아직 실측하지 않았다. 고쳤는데 재실행 결과가 그대로면 "고쳐지지
   않았다" 고 단정하지 말고, 활성화 전이라 반영되지 않았을 수 있다고 함께 보고한다.
7. **마무리.** 공통 개발 규칙(`<이 스킬의 base directory>/../../conventions/common.md`
   의 CR-001~)과 겹치는 지적이 있으면(예: ATC 지적이 CR-007 빈 CATCH 와 같은 것)
   메모해 보고에 적는다. 같은 일을 두 번 하지 않도록 어느 쪽 지적이 먼저 걸렸는지만
   적고 규칙 문서는 고치지 않는다. 소스는 SAP 테넌트에 쓴 상태이지 저장소 변경이
   아니다 — 저장소에 남길 변경(문서·메모)이 있으면 커밋·PR 은 `/harness:deliver` 로
   한다.

## 하지 않는 것

- 검사 불능을 통과나 "0건" 으로 말하는 것
- variant 이름을 추측하거나 하드코딩하는 것
- 근거와 사용자 승인 없이 `"#EC` 를 넣거나 exemption 을 요청하는 것
- `writes_allowed: true` 가 아닌 서버에 소스를 쓰는 것, 쓰기 가드를 우회하는 것
- 분류가 애매한 수정을 "자동" 으로 처리하는 것
- priority 를 Clean Core 등급으로 환산하는 것
