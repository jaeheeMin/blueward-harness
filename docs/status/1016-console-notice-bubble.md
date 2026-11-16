# #1016 웹 콘솔 알림 말풍선·팝업 응답과 헤더 계정 한도 표시 (2026-11-16)

## 배경
알림(내 차례·막힘·API 오류)이 홈 위쪽 띠(`.ann-slot`)에만 나와 다른 화면에서는 안 보였고, 계정 한도는 경고·한도 참일 때만 세션 카드에 보였다. #1013(PR #1019, `feat/1013-console-post-theme`) 위에 쌓았다.

## 한 것
| 파일 | 내용 |
|---|---|
| `console/managed.py` | `rate_limit_event` 마다 종류(rateLimitType)별 마지막 값을 `s["rateWindows"]` 에 allowed 일 때도 남긴다. 기존 `s["rateLimit"]`(경고·한도 참 안내)은 그대로 |
| `console/store.py` | `account_limits(store)`: 세션들의 값을 종류별로 모아 가장 늦게 받은 값 하나씩(5시간 → 7일 → 그 밖) |
| `console/server.py` | `GET /api/account-limits` → `{windows, source}`. 응답 경로는 새로 만들지 않았다 |
| `console/static/notice-logic.js` (새) | 순수 함수: 말풍선에 띄울 한 건 고르기, 닫은 알림 정리, 승인 단추 말, 한도 글자(`limitView`) |
| `console/static/app.js` | 헤더 알림 단추(≡ + 점)·말풍선(`role=status`, ✕)·한도 칸, 팝업(role=dialog, aria-modal, Esc, Tab 가두기, n/m, 초점 복귀), 닫은 알림 sessionStorage |
| `console/static/app.css`, `theme-post.css` | 새 클래스(`.nb-*`, `.lim*`)와 `--bub-*` 변수. Post 는 변수만 덮음 |
| `console/static/index.html`, `whats_new.json`, `plugin.json` | 스크립트 연결, 안내 줄, 0.10.304 → 0.10.305(main 0.10.302, 열린 PR #1011 0.10.303·#1019 0.10.304) |
| `docs/guide/harness-guide.html` | 웹 콘솔 "화면 모양" 설명 |
| `checker/tests/*` | 한도 기록·API, 순수 함수, 말풍선·팝업·한도 헤더 화면 시험. 스모크에 sessionStorage·키보드·초점 동작 추가 |

## 계정 한도 출처
- **채택: 콘솔이 관리하는 세션이 받은 `rate_limit_event`** 를 계정 단위로 모아 낸다. 이유: 이미 받고 있는 값이고 하네스 훅·설정을 건드리지 않는다.
- **상태줄(statusline) 입력의 `rate_limits`**(five_hour·seven_day 의 `used_percentage` 0~100, `resets_at` 초. claude-hud 0.8.0 `src/stdin.ts` 가 읽는 방식)는 **쓰지 않았다**. 쓰려면 사용자 `settings.json` 의 statusLine 을 가로채거나 새 명령을 끼워야 하는데, 이미 claude-hud 같은 상태줄을 쓰는 PC 와 충돌하고 하네스 설정 파일 쓰기를 건드린다.
- 쓴 비율(utilization)은 0~1 비율로 다룬다(기존 시험 픽스처 0.99 와 같음). **allowed 일 때도 utilization 이 오는지는 실제 로그로 확인하지 못했다**(이 PC 에서 `rate_limit_event` 실측 로그를 못 찾음). 안 오면 비율 자리에 `?` 로 보이고 풀리는 시각만 보인다. 지어내지 않는다.
- 값이 없거나 풀릴 시각이 지났으면 "한도 알 수 없어"(title 에 0% 가 아니라고 적음). 30분 넘은 값은 흐리게, 받은 시각을 title 에.

## 판단
- 알림 출처는 기존 `sideData`. 순서는 내 차례 → 막힘·확인 못 함 → API 오류 → 합쳐짐 → 새 판(띠 순서).
- 기존 띠는 DOM 에 두고 `.ann-slot[data-bubble]` 로 감췄다(같은 알림이 두 군데 겹치지 않게, 기존 시험·폴백 유지).
- 닫은 알림 id: `req:<rid>`·`turn:<sid>`·`fix:<sid>`·`blk:<sid>:<kind>:<t>`·`api:<sid>:<t>`. 목록에서 사라진 id 는 잊는다(같은 일이 다시 생기면 다시 뜬다).
- 팝업 승인은 `POST /api/requests/<id>/answer {decision}`, 질문은 `{answers}`. 보기 하나·단일 선택 질문은 누르면 바로 보내고, 그 밖은 골라 두고 [답 보내기]. 계획 고쳐 달라고 하기·MCP 질문·직접 적기는 전체 화면(`/r/<id>`)으로 보낸다.

## 확인
- 시험: `uv run pytest checker/tests -q -k "console or theme or static or whats_new or plugin_version"` (결과는 작업 보고에).
- 헤드리스 Chrome(시험 콘솔 `console_mockup`)으로 Sauce·Post 홈 말풍선, 팝업, 한도 헤더, 390px 을 찍어 봤다. 한도 값은 서버가 아니라 브라우저 쪽에서 `/api/account-limits` 응답을 흉내 냈다(시험 콘솔에 rate_limit_event 가 없다).

## 검토 반영
- 포커스 가두기가 `NodeList.filter` 를 불러 진짜 브라우저에서 TypeError 였다 → `Array.prototype.slice.call`. 스모크의 가짜 DOM 도 `querySelectorAll` 이 filter·map 없는 NodeList 모양을 돌려주게 해서 같은 실수를 시험이 잡는다.
- 팝업 승인은 `/r/<id>` 와 같은 내용을 다 보여 줄 수 있는 요청(Bash·Read·Glob·Grep·WebFetch·WebSearch 중 샌드박스 해제·백그라운드 아님, 600자 이하)만 빠른 허락 단추를 둔다. 600자 이하는 자르지 않고 스크롤 상자로 전체를 보인다. 파일 쓰기·고치기·MCP·샌드박스 해제·백그라운드·긴 명령·계획은 [자세히 보기](→ `/r/<id>`)와 [거절]만(계획은 [계획 보기 · 진행 정하기]만). 상세 그리기를 공용으로 빼는 것은 `requestView` 가 클로저 상태에 묶여 있어 이번엔 하지 않았다.
- "허용하고 이 세션에서 다시 묻지 않기" 는 추가될 규칙(`suggestionText`)을 먼저 보여 줄 수 있을 때만 둔다.
- 팝업이 열릴 때 초점은 제목(tabindex=-1). 눌렀던 단추가 사라지면 제목으로.
- 보던 알림이 다른 곳에서 처리돼 사라지면 "이 알림은 이미 처리됐어" 를 1초 보이고 단추를 막은 뒤 다음 알림을 보인다. 내가 답해서 사라진 알림은 안내 없이 다음으로 가며 결과 안내를 한 번 보인다(알림이 바뀌면 고른 답·오류는 비우고, 결과 안내는 내가 답한 직후 한 번만 남긴다).
- `nbMove` 는 응답을 보내는 동안·잠긴 동안 막고, 결과 안내·오류는 그 응답을 보낸 알림 id 에만 붙는다.
- 팝업은 같은 알림이면 통째로 다시 만들지 않고 바뀐 곳만 고친다(`patchChildren`). 그래서 초점·스크롤·alert 반복 읽기가 없고, 핸들러는 누른 때의 값을 다시 읽는다.
- 한도 단위: 0~1 은 비율, 1 초과 100 이하는 이미 퍼센트(서버가 100 으로 나눠 저장), 그 밖은 `?`. 빈 status 는 allowed(서버·화면 같다).
- 닫은 알림 정리는 저장처럼 최근 100개를 남긴다. `api:` id 는 받은 때를 모르면 종류·상태코드를 쓴다.
- 문구: "한도 알 수 없음" → "한도 알 수 없어", "여유 있음" → "여유 있어"(반말 규칙). 그 밖에 존댓말은 없었다.

## 남은 한계
- 한도는 이 콘솔에서 연 작업의 값만 안다. 터미널에서 직접 연 세션·다른 PC 의 사용은 모른다.
- 실제 `rate_limit_event` 의 allowed 값에 utilization 이 있는지 미확인.
- 말풍선은 한 번에 한 건이라 하나를 닫으면 다음 알림이 바로 뜬다.
- 좁은 화면에서 알림 단추가 한도 칸 아래 줄에 놓일 수 있다(넘치지는 않음).
