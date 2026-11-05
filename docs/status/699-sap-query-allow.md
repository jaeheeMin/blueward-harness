# #699 SAP 조회 허락 묻기 줄이기 — 하네스 쪽(data_access: allow)

## 바꾼 것
- `plugins/harness/hooks/adt_tiers.py`: `data_access` 에 `allow` 를 더했다(`DATA_ACCESS_VALUES`, 오류 문구, 파일 오류 안내 갱신).
  allow 서버의 `data_tools` 판정은 `decide()` 에서 한다.
  - `SELECT *`·`FIELDS *` 가 입력에 있으면 deny(CR-003, "필드 목록을 적어 다시 요청").
  - 비어 있지 않은 `sqlQuery` 가 있는 `runQuery`(필드를 고른 쿼리)는 통과 — 훅이 아무것도 내지 않는다.
  - 그 밖(쿼리 글자를 못 찾는 `runQuery`, `tableContents`)은 ask 유지.
- 기본값은 그대로 ask. 파일·값이 없거나 다른 서버·`servers` 에 없는 서버는 지금과 같이 ask, deny 서버는 그대로 deny.
- scaffold `env/adt-tiers.example.yaml` 에 allow 선택지를 주석으로 보였다(예시 서버 값은 ask 그대로).
- README 의 표와 길잡이(`docs/guide/harness-guide.html` 데이터 조회 callout)에 한두 문장.

## tableContents 입력 확인
ADT MCP 서버(`mcp-abap-abap-adt-api`)의 `tableContents` 도구 정의(Claude Code 에 실린 도구 스키마, 2026-11-05 확인):
`ddicEntityName`(필수), `decode`, `rowNumber`, `sqlQuery`("An optional SQL query to filter the data").
필드를 고르는 입력이 없어 테이블 통째 = 모든 칸이므로 allow 서버에서도 ask 를 유지한다. `sqlQuery` 에 `SELECT *` 가 있으면 deny.
`runQuery` 는 `sqlQuery`(필수), `decode`, `rowNumber`.

## 알아 둘 것
- 훅이 통과시켜도 Project Repository 의 `.claude/settings.json` `permissions.allow` 에 도구가 없으면 Claude Code 가 따로 물을 수 있다. 그 목록은 이 PR 범위 밖(public-cloud/scaffold 뼈대 후속).
- `has_select_star` 는 입력의 모든 글자 값을 본다. 필드 목록 판정(모든 필드가 맞는지)은 하지 않는다.

## 범위 밖(이슈 #699 의 남은 일)
public-cloud `env/adt-tiers.yaml`·`.claude/settings.json`, scaffold `.claude/settings.json` 읽기 도구 허용 예시, 콘솔(#649) 읽기 도구 자동 허용.
