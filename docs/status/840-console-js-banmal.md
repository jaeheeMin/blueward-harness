# 840 웹 콘솔 화면 코드(static js)의 존댓말 문구를 반말로

## 배경

#826 은 서버(`plugins/harness/console/*.py`)가 내는 화면 문구만 반말로 바꿨다. 화면 코드(`plugins/harness/console/static/*.js`)에는
합니다체(…습니다/…십시오/…세요)와 ~요 체(…어요/…해요/…할까요)가 화면 문구로 남아 있었다. 이번에 모두 반말(~야/~어/~했어, 부탁은 ~해 줘)로 맞췄다.
판 0.10.275.

## 찾은 목록과 처리

찾기: `grep -nE "(니다|십시오|세요|해요|돼요|어요|아요|이에요|예요)" static/*.js`, 그리고 `요[.?!'"]` 로 끝나는 문구(`할까요?`·`인가요?`·`게요`) 따로.

| 파일 | 바꾼 줄(화면 문구) | 안 바꾼 줄 | 이유 |
|---|---|---|---|
| app.js | 40줄 | 12줄 | console.warn·console.debug 로그 10, 코드 주석 2 |
| flow-ui.js | 57줄 | 2줄 | console.debug 로그 1, 코드 주석 1 |
| flow-logic.js | 18줄 | 2줄 | 코드 주석 2 |
| theme.js | 0 | 1줄 | console.debug 로그 |
| trouble.js | 0 | 2줄 | 코드 주석 |

- 바꾼 예: "요청을 처리하지 못했습니다 (" → "요청을 처리하지 못했어 (", "콘솔을 다시 여세요." → "콘솔을 다시 열어 줘.",
  "질문이 있습니다" → "질문이 있어", "사용을 허용할까요?" → "사용을 허용할까?", "어떤 일인가요?" → "어떤 일이야?",
  "끝났어요"(단추) → "끝났어", "내 차례예요" → "내 차례야".
- 안 바꾼 것: 개발자 로그(console.*), 코드 주석, Claude 에게 보내는 글(이 파일들엔 해당 없음), whats_new.json(~요 체 유지), 서버 *.py(#826 에서 함).
- 판단이 갈린 것: 이슈 본문은 합니다체(59곳)만 말하지만, flow-ui.js·flow-logic.js 에 같은 화면 문구가 ~요 체로 많이 남아 있어 함께 바꿨다
  (기존 콘솔 규칙: 화면 문구는 모두 반말, whats_new 만 예외).

## 같이 고친 곳

- 시험: `checker/tests/test_web_console_ui.py`(끝났어요·확인하지 못했어요·다시 불러왔어요·어떤 일인가요?·다음 규칙이 추가돼),
  `checker/tests/test_web_console.py`(다음 규칙이 추가돼).
- `docs/guide/harness-guide.html`: 레일 판 0.10.275, "글로 물어본 세션" 탭의 제목 인용 "내 답을 기다리는 듯해(추정)."(app.js 세션 제목과 같게).
- 메인 세션 대조: 바뀐 129줄의 ASCII 부분(코드)이 바뀌기 전과 같다 — 한글 문구만 바뀌었다.
- `plugins/harness/.claude-plugin/plugin.json` 0.10.275, `console/whats_new.json` 0.10.275 항목.
- 서버가 내는 문구를 화면이 비교해 분기하는 곳은 찾지 못했다(문구로 요소를 찾던 `console_ui_smoke.js`·`screen_config.py` 에도 바뀐 문구가 없다).

## 시험 결과

- `test_web_console_ui.py`: 128 passed (4분 8초)
- `test_web_console.py`: 1118 passed, 4 skipped (5분 55초)
- 시안 검사(`console_mockup.check_console`): 24개 화면 중 23개 통과, 1개 실패(G-11, 원래 알려진 차이), 0개 검사 불능
- 마지막 확인: 바뀐 diff(`whats_new.json` 제외)에서 `니다|십시오|세요` 가 든 추가 줄 0건. `static/*.js` 에 남은 것은 개발자 로그(console.*)와 코드 주석뿐.
