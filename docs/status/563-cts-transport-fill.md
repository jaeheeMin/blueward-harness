# #563 CTS 관리대장 트랜스포트 자동 채우기 (2026-11-03)

## 배경

#577 에서 `/harness:cts` 가 사람이 알려 준 값만 작업본에 적었다. 보류가 풀렸다(사용자 결정 2026-11-03): CTS 관리대장은 트랜스포트를 관리하는 문서라 public-cloud #57(Z5U ZLOCAL 이관 여부)과 상관없이 진행한다. 이 작업은 읽기 전용 ADT MCP 로 읽은 트랜스포트를 작업본 요청 표 행으로 옮긴다.

## 바꾼 것

- `checker/cts_fill.py`: `python -P -m checker.cts_fill --spec <작업본>… --transports <json> [--map] [--root] [--fill-empty] [--check]`. 엔진은 MCP 를 부르지 않고 스킬이 저장한 JSON 만 읽는다. 새 요청은 행으로 더하고(`NO` 는 표의 마지막 숫자 + 1, 요청일·번호순 정렬), `Request NO` 가 이미 있는 행은 건드리지 않는다(`--fill-empty` 면 빈 칸만 채운다). 작업본은 임시 파일 → `os.replace` 로 원자적으로 쓰고 CRLF·LF 를 그대로 둔다.
- `plugins/harness/skills/cts/cts-fill.yaml`: 매핑 사본(Project Repository 의 `templates/harness/cts-fill.yaml`). 트랜스포트 `category` → 작업본 종류(`customizing` → Configuration, `workbench` → CBO), JSON 키 → 열 이름, `CTS 유형` 값(IMG/PGM). 엔진에는 양식 글자가 없다.
- `plugins/harness/skills/cts/SKILL.md`: "트랜스포트에서 채우기" 절(읽기 도구만, 서버·사용자는 `env/adt-tiers.yaml` 기준으로 확인, JSON 은 저장소 밖, 명령, 종료코드, 사람이 확인할 칸). "자동 채우기는 #563" 문구 갱신, 규칙 설치 표에 매핑 추가.
- `checker/tests/test_cts_fill.py`(24개), `CLAUDE.md`·`plugins/harness/README.md`·길잡이 CTS 탭 안내. plugin.json 0.10.159.

## 정한 것

- **채우는 칸:** `NO`·`Request NO`·`Description`·`요청자`(소유자)·`Target System`·`CTS 유형`. 오픈단계·모둘·주요변경 및 특이사항·Client 종속여부·Target Client·처리 칸은 사람만 알아서 비운다.
- **요청일은 기본 비움.** 080 실측 응답에 생성일·요청일 필드가 없고 `tm:lastchanged_timestamp` 는 마지막 변경 시각이라 요청일과 다르다. 매핑 `요청일_출처: lastchanged` 로 명시한 경우만 그 날짜(14자리 `YYYYMMDDhhmmss` 의 앞 8자리)를 쓴다.
- **ADT 응답 변환은 엔진이 한다**(`--adt`, `adt_to_transports`): `category` 는 최상위 키, `tasks` 는 행이 아니고, 기본은 `modifiable` 만(`--include-released` 로 릴리스된 요청까지). 모양이 다르면 검사 불능.
- **읽기 경로:** `userTransports` 가 비면(080 실측: 빈 배열) `transportConfigurations` → `configurations[0].link` → `transportsByConfig`.
- 실측 응답 견본 `checker/tests/data/adt-transports-sample.json`(사용자 ID 는 TESTUSER 로 바꿈).
- **검사 불능(종료 2, 아무것도 쓰지 않음):** JSON 을 못 읽음, `transports` 없음, 날짜가 `YYYY-MM-DD`·`YYYYMMDD`·ISO 날짜가 아님(숫자 타임스탬프 포함), 모르는 `category`, 번호·소유자 빠짐·중복, `unread` 에 읽지 못한 트랜스포트가 있음, 작업본에 요청 표가 없거나 `NO` 가 숫자가 아님.
- **경고(종료 3):** 채울 작업본이 없는 종류의 트랜스포트가 있으면 그 건을 조용히 버리지 않고 `unrouted` 로 알린다.
- JSON 모양은 스킬이 MCP 응답을 바꿔 쓰는 중간 형식이다. 엔진이 MCP 응답 모양에 묶이지 않게 했다.
- 매핑의 `NO` 열 키는 `row_no`: YAML 이 따옴표 없는 `no`·`NO` 를 false 로 읽는다.

## 독립 검토 뒤 보완

- worktree 를 origin/main(0.10.159)에 맞췄다. plugin.json 은 열린 #533 수정 PR 이 0.10.160 을 써서 0.10.161. 길잡이 레일 표기도 0.10.161.
- 읽은 요청이 0건이면 빈칸 통과가 아니라 종료 3 경고 `type: no-transports`("읽을 요청이 없거나 읽기 경로가 틀렸다 — userTransports 가 비면 transportsByConfig 로"). 보고에 변환된 요청 수 `read` 와 `warnings` 목록을 넣었다(`unrouted` 도 같은 목록에 들어간다). 3 이어도 라우팅된 작업본은 반영된다.
- 매핑의 열(`열.*`, `값` 의 대상 열)이 작업본 요청 표 머리글에 없으면 조용히 버리지 않고 종료 2(지도·매핑 오류). 예전 `skipped_columns` 는 없앴다. `열.row_no` 도 필수가 됐다.
- `--transports` 를 여러 번 받는다(설정이 여러 개일 때). 파일마다 검증하고 합치며 같은 요청 번호는 한 번만 쓴다. 한 파일이라도 이상하면 어느 파일인지 밝히고 종료 2.
- 쓰기: 임시 파일에 원본 권한을 복사했고, 작업본이 여러 개면 모두 임시 파일에 먼저 쓴 뒤 교체한다. 준비 중 실패하면 아무것도 바뀌지 않고, 교체 중 실패하면 이미 바꾼 것을 원래 내용으로 되돌려 본다(교체 도중 프로세스가 죽는 경우까지는 보장하지 않는다). 자리표시 행(`<값>`)의 NO 는 이어 매기기에서 뺀다.
- 인자 오류(argparse)도 JSON 한 줄(종료 2)로 낸다.
- 작업본 파일명 정규식을 엔진 코드에서 매핑 `작업본_파일명` 으로 옮겼다. `## 양식 항목` 은 `export.py`·`form_columns` 와 같은 작업본 공통 약속이라 코드에 둔다(같은 방식).
- 스킬: 설정이 여러 개면 전부 읽고 몇 개·설정별 몇 건인지 알리게 했고, 종료코드 절에 3 도 반영됨을 적었다. 길잡이 CTS 탭의 "자동 채우기 없음" 문구와 "아직 없어(#563)" 를 새 동작으로 고치고 "트랜스포트에서 채워줘" 예시를 더했다.

## 확인하지 못한 것

- 구현 중에는 두 서버가 401 이어서 응답을 못 봤다. 이후 메인 세션이 재로그인해 080 에서 읽은 실제 응답으로 변환·시험을 맞췄다. 100(커스터마이징)에서 읽은 응답은 없다 — `customizing` 쪽 모양은 같은 구조라는 가정이다.
- 전체 시험은 로컬 메모리 부족으로 돌리지 않았다.
