---
name: cts
description: CTS(Change and Transport System) 관리대장(Configuration·CBO)에 요청 건이나 Error 내역을 더하고, 트랜스포트에서 읽은 값으로 요청 표를 채우고, 고객 양식 xlsx 로 산출할 때 쓴다. 사용자가 "CTS 관리대장에 추가해줘", "CTS 요청 기록해줘", "트랜스포트에서 채워줘", "Error 내역 추가", "관리대장 엑셀로 뽑아줘" 라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 트랜스포트 요청을 만들거나 릴리스하거나 지우는 일(쓰기 도구)은 이 스킬이 하지 않는다. 읽기 전용 조회로 채우기만 한다. 개발 Spec 이나 사용자 매뉴얼이면 spec·manual 스킬로.
---

# /harness:cts

`docs/CTS관리대장/` 의 CTS 관리대장 작업본(md)에 요청 건을 한 행씩 더하고, 고객 양식 xlsx 로 산출하는 입구다. 관리대장은
**종류마다**(Configuration, CBO) 작업본 파일 하나이고, 계속 쌓이는 대장이라 판(버전)을 올려 가며 새 xlsx 를 낸다. 양식은
Project Repository 의 `templates/` 에 있고 양식 지도는 `templates/forms/CTS_관리대장_*.yaml` 이다. 시트·표·열 이름은 항상
지도에서 읽는다 — 이 스킬에 양식 고유 글자를 지어 적지 않는다. `<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에
표시되는 경로다.

값은 사람이 알려 준 것과, 읽기 전용 ADT MCP 로 읽은 트랜스포트 정보(아래 "트랜스포트에서 채우기",
[#563](https://github.com/jaeheeMin/blueward-harness/issues/563))만 받아 적는다. 오픈단계·모둘·주요변경 같은 사람만 아는 값은
지어내지 않고 묻거나 비워 둔다.

`git rev-parse --show-toplevel` 로 Project Repository 루트를 확인한다.

## 작업본 형식

위치와 이름: `docs/CTS관리대장/CTS관리대장_<종류>.md` (예: `docs/CTS관리대장/CTS관리대장_Configuration.md`). 폴더와 이름은 지도
`산출` 의 폴더·파일명(`CTS관리대장_<종류>_v{버전}.xlsx`)에서 `_v{버전}` 만 뺀 것이라, 산출 xlsx 와 같은 폴더에 나란히 놓인다.
파일명 규칙은 `rules/cts.yaml` 이 강제한다.

```markdown
# CTS 관리대장 Configuration

버전: 0.1

## 양식 항목

### CTS_관리대장_Configuration · Config. CTS

#### Config. CTS

| 오픈단계 | NO | 요청일 | 모둘 | CTS 유형 | Target System | Request NO | Description | 주요변경 및 특이사항 | 요청자 | 처리일자 | 처리시간 | 처리자 | 처리결과 | 승인 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <값> | 1 | 2026-11-02 | <값> | <값> | <값> | <값> | <값> | <값> | <값> | | | | | |

### CTS_관리대장_Configuration · Error 내역

#### Error 내역

| 오픈단계 | NO | 요청일 | 모둘 | CTS 유형 | Client 종속여부 | Target System | Target Client | Request NO | Description | Error 내용 | 요청자 | 조치사항 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
```

(위 열 이름과 시트 이름은 **지도에서 읽은 것**이다. 지도가 바뀌면 지도의 이름을 따른다. `<값>` 자리는 실제 값으로 채운다.)

- **머리.** 첫 `##` 앞의 `버전: 0.1` 줄이 산출 파일명의 버전(`v0.1`)이 된다. 처음은 0.1, 올릴 때 0.1 씩이다. 줄이 없거나
  `x.y` 모양이 아니면 산출이 파일명을 만들지 못해 거부한다.
- **`## 양식 항목`.** `### <양식> · <시트>` 소절마다 `#### <표 이름>` 아래 표 하나다. 표의 열 이름은 지도 `열` 키와 같아야 한다 —
  양식 머리글의 오타(`모둘`)도 받은 그대로 쓴다. 지도에 없는 시트·표·열은 쓰지 않는다. 저장할 때(훅)와 PR(doc-guard
  `form_columns`)이 "양식 밖" 으로 거절하고 산출도 멈춘다. 지도에 있는 열이 표에서 빠지는 것은 허용이다(빈칸으로 산출된다).
- **한 표는 한 시트다.** Configuration 은 `Config. CTS` 와 `Error 내역`, CBO 는 `CBO CTS` 와 `Error 내역` 시트다. 작업본에는 그
  종류의 양식 소절만 쓴다. 다른 종류의 시트 이름이나 다른 양식(예: Configuration 작업본 안의 `CTS_관리대장_CBO`)을 쓰면 규칙
  (`파일명_양식`)이 양식 밖으로 거절한다 — 그대로 산출하면 그 행들이 조용히 빠지기 때문이다.
- **열 값.** `NO` 는 숫자(표마다 1부터), `요청일`·`처리일자` 는 `YYYY-MM-DD`(엑셀 날짜 칸으로 들어간다), 나머지는 글자다.
  날짜 칸에 `11/2` 처럼 다른 모양을 쓰면 산출이 `type: date-text` 경고(종료코드 3)를 낸다. `NO` 가 숫자인지는 어느 검사도 보지
  않는다(양식 칸이 일반 서식이라 엔진이 숫자 칸인지 모른다) — 표마다 1부터 이어 쓰는 것을 이 스킬이 지킨다.
  셀 안 줄바꿈은 `<br>`, 값에 `|` 가 있으면 `\|` 로 쓴다.
- 행 수가 양식에 서식이 있는 줄(Configuration 38, CBO 45, Error 9줄, 지도 주석)을 넘으면 산출이 마지막 줄의 서식을 새 행에 복제한다.
  넘겼으면 엑셀로 열어 서식이 이어지는지 사람이 본다.

## 0단계: 브랜치 확인

작업본을 쓰기 전에, 지금 브랜치가 이번 CTS 관리대장 작업에 맞는지 확인한다. 확인은 `<이 스킬의 base directory>/../start/SKILL.md`
의 "다른 스킬이 부르는 브랜치 확인" 을 그대로 따른다 — 미커밋 변경, main 이면 start 절차, 다른 작업 브랜치면 같은 일인지
판단·질문, 판정 불능이 거기 있다. start 를 따로 부르라고 하지 않는다. 이 스킬에서 정하는 것은 아래뿐이다.

- **이번 작업 설명**은 "CTS 관리대장 — `<종류>` 요청 추가" 한 줄이다. 종류를 받은 뒤에 브랜치를 비교한다(그 전에는 읽기만 하고
  파일을 쓰지 않는다).
- **같은 일의 판단 기준.** 브랜치 이슈 제목·본문이 같은 종류의 CTS 관리대장 작업이면 같은 일이다. 아니면 묻는다.
- **main 이면 번호 없는 작업 이슈를 만든다.** start 절차를 `docs` 작업으로 수행한다 — 제목은 `CTS 관리대장 — <종류> <요약>`, 브랜치는
  `docs/{이슈번호}-…`. DEV 번호는 받지 않는다(관리대장은 개발 건이 아니다).

## 요청 건 더하기

1. **종류를 정한다.** `templates/forms/CTS_관리대장_*.yaml` 를 읽어 `양식`·`설명` 을 보여 주고 고르게 한다(지도가 하나면 그것으로
   확인만 한다). 사용자가 말했으면 묻지 않는다.
   - 지도 폴더가 없거나 CTS 관리대장 지도가 하나도 없으면 **멈추고** 지도가 없다고 알린다. 지도를 이 스킬이 추측해 만들지 않는다.
     양식 지도는 Project Repository 에서 먼저 만들어 병합돼야 한다(`<이 스킬의 base directory>/../spec/form-map.md`).
   - 읽지 못한 지도(파싱 오류, 필수 키 없음)가 있으면 목록에서 조용히 빼지 않고 어느 파일이 왜 안 읽히는지 알리고 멈춘다.
   - `rules/cts.yaml`·`rules/cts-output.yaml`·`templates/harness/cts.md` 가 없으면 아래 "규칙 설치" 로 안내한다.
2. **작업본을 읽는다.** `docs/CTS관리대장/CTS관리대장_<종류>.md` 가 있으면 읽는다(표의 마지막 `NO`, 머리의 `버전:`을 알아야 한다).
   없으면 새 대장이다 — 아래 3 에서 지도의 시트·표·열 이름으로 위 형식대로 만들고 `버전: 0.1` 로 시작한다.
3. **요청 건 항목을 묻는다.** 지도 첫 시트 표(`Config. CTS`/`CBO CTS`)의 열을 하나씩 확인한다. 열 이름은 지도에서 읽은 대로 보인다.
   - `NO` 는 묻지 않는다. 그 표의 가장 큰 `NO` + 1 이다(비었으면 1).
   - `요청일` 은 사용자가 준 날짜를 `YYYY-MM-DD` 로 적는다. "오늘" 이라고 하면 오늘 날짜다. 말하지 않았으면 묻는다.
   - `오픈단계`·`모둘`·`CTS 유형`·`Target System`(CBO 는 `Client 종속여부`·`Target Client` 도)·`Request NO`·`Description`·
     `주요변경 및 특이사항`·`요청자` 는 사용자에게서만 받는다(트랜스포트에서 읽어 채우는 열은 아래 "트랜스포트에서 채우기" 가 맡는다).
     **트랜스포트 번호(`Request NO`)와 대상 시스템은 지어내지 않는다.**
     모르면 비워 두고 그렇다고 알리거나 사용자에게 되묻는다. 형식이 정해진 값(예: `CTS 유형`)은 기존 행의 쓰는 방식을 따르고,
     기존 행이 없으면 양식 머리글의 메모(IMG/PGM, S/F 설명)가 있다고 알리고 묻는다.
   - `처리일자`·`처리시간`·`처리자`·`처리결과`·`승인` 은 처리하는 사람이 나중에 채우는 칸이다. 사용자가 알려 줄 때만 적고, 아니면
     빈칸으로 둔다. 처리 결과를 알려 주면 새 행을 만들지 않고 **그 요청의 행**(`Request NO` 로 찾는다)을 고친다.
   - 한 번에 요청 여러 건을 받으면 한 행씩 더한다.
4. **Error 내역을 더한다.** 사용자가 CTS 처리 중 난 Error 를 알려 주면 `Error 내역` 표에 행을 더한다. `NO` 는 이 표의 마지막 `NO` + 1
   (표마다 따로 센다. 고객사가 다르게 센다고 하면 따른다). `Request NO`·`Description` 은 어느 요청 건의 Error 인지 알려 달라고 하고,
   위 요청 표의 같은 건에서 가져오거나 사용자가 준 값을 쓴다. `Error 내용`·`조치사항` 은 사용자의 말을 요약하지 않고 그대로 적는다.
5. 저장 전에 doc-guard 훅(`pre_write_guard.py`)이 `rules/cts.yaml` 로 파일 이름·필수 절·양식 밖 열을 검사한다. 막히면 사유대로
   고친다. 훅이 죽어 검사를 못 한 경우는 통과나 위반이 아니라 검사를 못 했다고 알린다. 훅이 막으면 우회하지 않고 사유를 알린다.

## 트랜스포트에서 채우기

사용자가 "트랜스포트에서 채워줘", "내 트랜스포트 관리대장에 넣어줘" 라고 하면 SAP 의 트랜스포트 요청을 읽어 요청 표에 행으로 더한다.
**읽기만 한다.** 엔진은 MCP 를 부르지 못하니, 이 스킬이 읽고 JSON 으로 저장하면 엔진 명령이 작업본으로 옮긴다. 작업본이 없으면 먼저
위 "요청 건 더하기" 1~2 로 종류를 정하고 작업본을 만든다(0단계 브랜치 확인 포함). `Request NO` 가 이미 있는 행은 건드리지 않는다.

1. **읽을 서버와 사용자.** 읽을 테넌트·클라이언트는 `env/adt-tiers.yaml` 의 `servers` 기준이다(서버 이름 → 호스트·클라이언트·티어).
   커스터마이징 요청은 커스터마이징 테넌트(예: `abap-adt-z5u`, 클라이언트 100), 워크벤치 요청은 개발 테넌트(`abap-adt-z5u-dev`,
   080)에서 읽는 것이 보통이다. 어느 서버에서 읽을지, 어느 SAP 사용자(트랜스포트 소유자)의 것을 읽을지는 사용자에게 확인한다 — 모르면
   지어내지 않는다. 그 파일이 없으면 멈추고 알린다.
2. **읽기 도구만 쓴다.** 먼저 `mcp__<서버>__userTransports`(`user`, `targets: true`)를 부른다. 080 실측(2026-11-03)에서 이것은
   workbench·customizing 모두 빈 배열이었으니, **비면** `transportConfigurations` 응답의 `configurations[0].link` 를
   `transportsByConfig`(`configUri`=그 link, `targets: true`)에 넣어 읽는다. 설정(`configurations`)이 **여러 개면 전부** 읽어 설정마다 응답을
   따로 저장한다(엔진이 합치고 같은 요청 번호는 한 번만 쓴다). 읽은 설정이 몇 개인지, 설정마다 요청이 몇 건이었는지 사용자에게 알린다.
   `transportConfigurations` 가 비었거나 `link` 가 없으면 멈추고 알린다. 응답 모양은 `transports.{workbench|customizing}[]`(대상 묶음, `tm:name`·`tm:desc`) → `modifiable[]`·`released[]`(요청:
   `tm:number`·`tm:owner`·`tm:desc`·`tm:target`·`tm:lastchanged_timestamp`) → `tasks[]`(요청 아래 task, 행이 아니다)다. **`createTransport`·
   `transportRelease`·`transportDelete`·`transportSetOwner`·`transportAddUser` 같은 쓰기 도구는 부르지 않는다**(`env/adt-tiers.yaml` 의
   `write_tools`, 읽기 전용 서버에서는 가드도 막는다). 가드·훅이 막으면 우회하지 말고 사유를 알린다.
3. **응답을 그대로 저장한다.** 저장소 밖 임시 폴더(예: 세션 scratchpad)의 `adt.json` 에 응답 JSON 을 **고치지 않고** 쓴다 — 저장소 안에 두지
   않는다. 변환은 엔진(`--adt`)이 한다: `category` 는 최상위 키(`workbench`/`customizing`), `tasks` 는 행으로 만들지 않고, 기본은 `modifiable`
   만 넣는다(릴리스된 요청까지 넣으려면 `--include-released`). 응답 모양이 기대와 다르면 엔진이 검사 불능(종료 2)으로 멈춘다.
   - **요청일은 ADT 응답에 없다.** 있는 것은 마지막 변경 시각(`tm:lastchanged_timestamp`, 14자리 `YYYYMMDDhhmmss`)뿐이고 요청을 만든 날짜가
     아니다. 그래서 기본은 `요청일` 을 **비운다**(사람이 적는다). 매핑 `요청일_출처: lastchanged` 로 고른 경우만 마지막 변경일을 쓴다.
   - `Target System` 은 요청의 `tm:target` 이고 비어 있으면(로컬 변경 요청) 빈칸이다.
   - 읽지 못한 트랜스포트(상세 조회 오류·401 등)가 있으면 `adt.json` 대신 중간 JSON 형식(엔진 머리 설명)을 직접 만들어 `unread` 에
     `{"number","reason"}` 을 넣고 `--adt` 를 빼서 부른다 — 빼면 조용히 빠진다. 사용자 소유 요청이 없는 빈 응답은 "읽을 것이 없다" 로 알린다.
4. **엔진을 부른다.** 먼저 `--check`, 문제없으면 `--check` 를 빼고 다시.

   ```bash
   e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "채우기 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
   uvx --from "$e" \
     python -P -m checker.cts_fill --root "$(git rev-parse --show-toplevel)" --transports "<adt.json 경로>" [--transports "<다른 설정 응답 경로>"] --adt \
     --spec "docs/CTS관리대장/CTS관리대장_<종류>.md" [--spec "docs/CTS관리대장/CTS관리대장_<다른 종류>.md"] --check
   ```

   매핑은 Project Repository 의 `templates/harness/cts-fill.yaml` 이다(없으면 아래 "규칙 설치"). 트랜스포트의 `category` 가 어느 작업본으로
   갈지도 그 매핑이 정한다(`customizing` → Configuration, `workbench` → CBO). 이미 있는 행의 **빈 칸**만 채우려면 `--fill-empty` 를 더한다.
   엔진은 새 행의 `NO`(표의 마지막 숫자 + 1)·`Request NO`·`Description`·`요청자`(소유자)·`Target System`·`CTS 유형`(IMG/PGM)만
   채우고(`요청일` 은 위 매핑 설정일 때만), 오픈단계·모둘·주요변경 및 특이사항·Client 종속여부·Target Client·처리 칸은 비운다.
5. **종료코드.** stdout 은 JSON 한 줄이다.
   - `0` — 정상(`--check` 포함). `results` 의 `added`(더한 행)·`filled`·`kept`(이미 있어 건드리지 않은 건)를 알린다.
   - `2` — 검사 불능. JSON·매핑·작업본을 읽지 못했거나 값 형식이 다르거나 `unread` 에 읽지 못한 트랜스포트가 있거나, 매핑의 열이 작업본
     머리글에 없거나(지도·매핑 오류), 인자가 틀렸다(이것도 JSON 한 줄로 나온다). **아무 파일도 쓰지 않았다.**
     `problems` 를 그대로 보이고 통과로도 위반으로도 취급하지 않는다. 읽지 못한 트랜스포트는 다시 읽어 JSON 을 고친 뒤 돈다.
   - `3` — 경고(`warnings`). `read` 는 변환된 요청 수다. **3 이어도 라우팅된 작업본은 이미 반영됐다**(`written`).
     `type: no-transports` — 읽은 요청이 0건이다. 읽을 요청이 없거나 읽기 경로가 틀린 것이니 `userTransports` 가 비면 `transportsByConfig`
     로 읽었는지 확인하고, "채웠다" 고 말하지 않는다. `type: unrouted` — 채울 작업본이 없는 종류의 트랜스포트가 있어 그 건은 채우지
     못했다. 그 종류의 작업본도 `--spec` 으로 주고 다시 돈다.
6. **채운 뒤 사람이 확인한다.** 비어 있는 요청일·오픈단계·모둘·주요변경 및 특이사항(CBO 는 Client 종속여부·Target Client 도)은 사람이 알려 주는 대로 채운다.
   `CTS 유형` 은 매핑의 값(IMG/PGM)이라 고객사 쓰는 방식과 맞는지 본다. 이어서 위 "산출" 로 `--check`.

## 버전 올리기

이 대장은 계속 쌓이고, 한 번 main 에 병합된 같은 이름의 xlsx 는 엔진이 덮어쓰지도 지우지도 않는다(거부 사유 "main 에 이미 있는 판이다").
행을 더하거나 값을 고쳐 새 xlsx 를 내려면 판을 올려야 한다.

1. `git fetch origin` 으로 `origin/main` 을 최신으로 맞춘다. 엔진은 fetch 하지 않는다.
2. 지금 `버전:` 의 파일(`CTS관리대장_<종류>_v<버전>.xlsx`)이 `origin/main` 에 있는지 본다:
   `git -c core.quotepath=false ls-tree --name-only origin/main docs/CTS관리대장/` 의 목록에서 찾는다(`core.quotepath=false` 가
   없으면 한글 이름이 `\352…` 로 나와 못 찾는다). 헷갈리면 그냥 산출한다 — main 에 있는 판이면 엔진이 "main 에 이미 있는 판이다" 로
   거부하니, 그때 버전을 올린다.
   - **있다** — 작업본 머리의 `버전:` 을 0.1 올린다(`0.1` → `0.2`; 큰 변경이면 사용자에게 묻는다). 산출하면 새 파일이 생기고
     **이전 판 xlsx 는 그대로 남는다.** 이전 판 파일을 이 스킬이 지우거나 고치지 않는다.
   - **없다** — 이 브랜치에서 만든(병합 전) 판이다. 버전을 올리지 않아도 같은 버전으로 다시 산출되고, 결과 JSON 에 `replaced: true` 가 붙는다.
   - 목록을 읽지 못하면(git 없음, `origin/main` 못 읽음) 판단하지 못한 것이다. 통과로 넘기지 않고 그렇다고 알린 뒤 fetch 를 다시 한다.
3. 작업본 md 는 하나이고 판마다 따로 두지 않는다. 판의 기록은 git 이력과 남아 있는 이전 판 xlsx 다.

## 산출

작업본이 채워지고 사용자가 xlsx 를 원하면("관리대장 엑셀로 뽑아줘") 먼저 `--check` 로 확인한 뒤 산출한다. `--check` 는 파일을 쓰지 않는다.

```bash
e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "산출 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
uvx --from "$e" \
  python -P -m checker.export --spec "docs/CTS관리대장/CTS관리대장_<종류>.md" --form "CTS_관리대장_<종류>" --root "$(git rev-parse --show-toplevel)" --check
```

`--check` 가 거부 없이 끝나면 `--check` 를 빼고 같은 명령을 다시 돈다. 엔진 판·`uvx`·PowerShell 호출 방법·stdout JSON 한 줄·`산출 불능`
처리는 `<이 스킬의 base directory>/../spec/SKILL.md` "양식 파일 산출" 과 같다(`@main` 이나 다른 판으로 대신 받지 않는다). 산출 xlsx 는 지도
`산출.폴더` 인 `docs/CTS관리대장/` 에 `CTS관리대장_<종류>_v<버전>.xlsx` 로 생긴다. 한 번에 한 종류만 산출한다(`--form` 으로 고른다).

종료코드:

- `0` `status: ok` — `files` 의 경로를 알린다. 엑셀로 한 번 열어 머리글·서식이 양식대로인지, 방금 더한 행의 날짜·번호 칸이 맞는지
  확인하라고 권한다. 이 확인은 사람 몫이다. `warnings` 가 있으면 항목별로 그대로 보여 준다.
- `3` `status: warning` — 파일은 만들었다. `warnings` 를 그대로 보여 주고, `type: dropdown-unchecked`·`leftover-review` 는 검사를 못 한 것이라
  통과가 아니니 그렇다고 알린다. `type: date-text` 는 날짜 칸에 날짜가 아닌 값이 들어간 것이라 작업본을 `YYYY-MM-DD` 로 고쳐 다시 산출한다.
- `1` `status: rejected` — 파일을 만들지 않았다. `problems` 의 시트·항목·사유를 그대로 보이고 작업본을 고친 뒤 다시 돈다. 같은 이름
  파일이 main 에 있어 거부된 것이면 위 "버전 올리기". 사유가 "main 에 있는 판인지 판단하지 못해" 이면 검사 불능이니 fetch 한 뒤 다시 한다.
- `2` `status: error` — 작업본·지도·템플릿을 읽지 못했거나 작업본이 지도에 없는 시트·표·열을 가리킨다(양식 밖 항목을 모두 모아 알린다).
  산출하지 못했다고 알리고 작업본을 지도의 이름으로 고친다.
- stdout 이 JSON 으로 읽히지 않으면(uvx 실패, 엔진 못 받음) "산출 불능" 이다. 거부로도 통과로도 취급하지 않는다.

**검사는 이 스킬이 하지 않는다.** 산출한 xlsx 의 파일 이름은 PR 을 열 때 Actions(doc-guard)가 `rules/cts-output.yaml` 로 맡는다. 산출 성공은
doc-guard 통과가 아니다. 파일 이름 패턴(`CTS관리대장_(Configuration|CBO)_v\d+\.\d+\.xlsx`)은 지도 `산출.파일명` 을 읽어 만든 것이 아니라 사본이라,
"첫 판은 0.1", "0.1 씩 올림" 은 어느 검사도 강제하지 않는다. 사람이 챙기고, 양식이 바뀌어 파일명 모양이 바뀌면 패턴도 직접 고친다.

## 규칙 설치

Project Repository 에 CTS 관리대장 검사 규칙이 없으면 이 스킬 폴더의 파일을 복사한다(이 PR 은 `rules/`·`templates/` 를 바꾸므로 승인자
Approve 가 필요하다고 알린다. 엔진은 `rules/` 만 읽는다). 마지막 줄의 `cts-fill.yaml` 은 "트랜스포트에서 채우기" 를 쓸 때만 필요하다.

| 이 스킬 폴더 | Project Repository |
|---|---|
| `cts.yaml` | `rules/cts.yaml` (작업본: 파일명·필수 절·양식 밖 열) |
| `cts-output.yaml` | `rules/cts-output.yaml` (산출 xlsx 파일명 패턴) |
| `cts-template.md` | `templates/harness/cts.md` (필수 절의 기준) |
| `cts-fill.yaml` | `templates/harness/cts-fill.yaml` (트랜스포트 → 작업본 열 매핑·종류 분기·CTS 유형 값) |

작업본의 관할은 `docs/CTS관리대장/*.md`, 산출물의 관할은 `docs/CTS관리대장/*.xlsx` 다. 종류(Configuration·CBO)가 늘면 두 규칙 파일의
파일명 패턴에 새 종류를 더한다.
