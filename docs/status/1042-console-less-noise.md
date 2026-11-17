# #1042 웹 콘솔에서 필요 없는 정보 줄이기 (2026-11-17)

## 배경
실제 Claude·GitHub 로 한 바퀴 돌려 보니 승인 카드의 규칙 원문 JSON, claude.ai 커넥터 로그인 필요 17줄, 요청 원문 전체인 세션 제목이 크게 보였다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/static/app.js` | 승인 카드 `.sugg` 의 원문 `pre` 를 "자세히 > 기술 정보 > 추가될 규칙 원문" 으로 옮김. MCP 카드는 `connectorAuth` 항목을 `details` 한 줄로 접고, 그것만 있으면 중립 한 줄. 세션 머리 h1 에 `sess-title` 클래스와 `title` 속성 |
| `plugins/harness/console/store.py` | `mcp_servers_of` 가 `scope`(없으면 `source`)를 보존, `mcp_is_connector`, `mcp_view` 항목에 `connectorAuth` |
| `plugins/harness/console/analysis.py` | SCHEMA 에 선택 필드 `title`, 프롬프트 지시, `session_title`(title → understood 첫 문장 30자 → 요청 첫 줄) |
| `plugins/harness/console/server.py` | `launch` 의 제목을 `session_title` 로 |
| `static/app.css`, `static/theme-post.css` | 제목 한 줄 말줄임, 커넥터 접힘 모양 |
| `docs/guide/harness-guide.html` | 승인·연결 도구·새 작업 설명 |

## 판단
- 커넥터 구분은 `scope`/`source` 가 `claude.ai` 이거나 이름이 `claude.ai ` 로 시작할 때. mcp_status 응답에는 `scope`·`source` 가 오지만(시험 fixture 모양) claude.ai 커넥터의 실제 값은 확인하지 못해 이름 접두를 함께 쓴다.
- 커넥터라도 `failed`·`unknown` 은 접지 않는다(로그인 전만 접음).
