# #651 웹 콘솔 브라우저 알림

시안 19 설정의 "알림" 묶음(스위치 셋)을 만들고, 켜 두면 콘솔 탭이 열려 있을 때 브라우저 알림을 보낸다. 서비스 워커는 쓰지 않는다(탭을 닫으면 알림도 없다).

## 바꾼 것

- 서버 `console/server.py`: `GET/PUT /api/settings/notify` → `{turn, blocked, done}`(기본 모두 false). 상태 폴더의 `notify.json`(`NOTIFY_FILE`)에 저장해 브라우저와 무관하고 재기동 뒤에도 남는다(읽을 때마다 파일을 읽는다). PUT 은 보낸 키만 바꾸고, bool 이 아닌 값·모르는 키·빈 본문은 400, 깨진 파일은 꺼진 것으로 본다. 상태 폴더가 없는 실행(시험)은 메모리.
- 서버 `console/store.py` `public_session`: `lastBlock: {t, kind} | null`(최근 block 대화 항목). 대화(chat)는 단일 세션 응답에만 있어, 목록 SSE 갱신만으로 새 막힘을 알아채기 위한 가벼운 값.
- 비교 로직 `static/flow-logic.js` `notifyEvents(prev, next, cfg, opts)` (순수 함수). prev 가 없으면 무알림(첫 목록·처음 본 세션). 탭이 보이면(opts.visible) 무알림.
  - turn: `group` 이 todo 로 새로 들어오거나 새 `pendingRequestIds` → "내 차례야 · 세션 이름", 본문 질문/승인/다음 단계(요청 종류를 모르면 "답할 일"), 이동 `/r/<요청 id>` 또는 `/s/<id>`.
  - blocked: `lastBlock.t` 가 직전보다 새로움 → "막혔어 · …" / cannot_check 면 "확인 못 함 · …".
  - done: running → idle/todo → "AI가 끝냈어 · …". 같은 전환에서 내 차례 알림이 나가면 끝남 알림은 겹쳐서 생략한다.
  - tag: `bh-turn-<id>[-<요청 id>]`, `bh-blocked-<id>-<t>`, `bh-done-<id>` (같은 일은 브라우저가 한 번만 보인다, `renotify`).
- 화면 `static/app.js`: `mergeSession` 이 직전 모델과 비교해 알림을 보낸다(`loadedOnce` 전 = 첫 목록은 기준만). 질문/승인을 알아야 하는 새 요청은 받아 온 뒤에 보낸다. 알림을 누르면 `window.focus()` 후 `go(path)`.
  알림을 켜 두고 권한이 허용이면 탭이 숨겨져도 SSE 를 닫지 않는다(기존엔 숨은 탭은 연결을 닫아 알림이 올 수 없었다). 아니면 예전과 같다.
  설정 화면: "알림" 묶음 스위치 셋(`role="switch"`, 시안 19 문구), 권한 한 줄(허용됨 / 막힘 / 아직 안 물음 / 미지원). 처음 켤 때 클릭 안에서 `Notification.requestPermission()`; denied 면 켠 채 두지 않고 "브라우저가 알림을 막았어 · 주소창 왼쪽 자물쇠에서 알림을 허용해 줘". `Notification` 이 없으면 "이 브라우저는 알림을 지원하지 않아"(스위치 비활성).
- `static/app.css`: `.swrow` `.sw` 스위치 모양(기존에 스위치가 없어 새로 만듦, 토큰만 사용).

## 시험

- `test_web_console.py`: 설정 API(기본값·저장·부분 저장·잘못된 값 400·깨진 파일), 목록의 `lastBlock`.
- `test_web_console_ui.py`: 비교 로직 순수 함수(첫 목록·todo 진입·새 요청 질문/승인·새 block·running→idle·끈 스위치·보이는 탭), 설정 화면(스위치 셋·권한 문구·처음 켤 때 묻기·denied·미지원), 가짜 DOM 에 Notification 가짜를 넣어 SSE 갱신 → 알림 한 번, 클릭 이동.
  기존 `test_settings_screen_matches_design` 의 `"알림" not in text` 는 알림이 생겨 스위치 셋 확인으로 바꿨다.

## 남은 것

- 실제 브라우저에서 권한 창·알림 표시는 눈으로 확인하지 못했다(가짜 Notification 으로만 시험).
- 처음 보는 세션(prev 없음)이 이미 todo 면 알리지 않는다(기준이 없어서).
- 콘솔 탭이 아예 닫혀 있으면 알림은 없다(서비스 워커 없음).
