# #1033 Post 테마 오늘 화면 "지금 세션들" 장면을 AI 오피스로 (2026-11-17)

## 배경
Post 오늘(홈) 화면의 "지금 세션들" 패널에 우체국 창구 장면(`theme-post.js` `BHPostScene.attach`)이 있었다. 장면만 AI 오피스(`window.BHOfficeScene`)로 바꾼다. 패널 머리줄·범례·차분(fx=0)일 때 세션 목록(calmList)은 그대로. Sauce 와 다른 화면은 그대로.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/static/post/office/office-post.js` | 사무실 장면 번들(외부 의존 없는 한 파일). 서버 `POST_ASSET` 이 `/post/` 하위 `.js` 를 이미 낸다 |
| `plugins/harness/console/static/index.html` | office-post.js 를 theme-post.js 앞에 연결 |
| `plugins/harness/console/static/theme-post.js` | `attach(host, opts, office)` — office 를 주면 사무실 장면을 붙인다. 칸이 숨겨져 폭 0 이면 폭이 생길 때까지 기다렸다 붙인다(아니면 `scale(Infinity)` 콘솔 오류). 차분·테마 전환 처리는 그대로 |
| `plugins/harness/console/static/app.js` | `sceneList` 항목에 `flow: s.flowId`, `t: s.updatedAt`. `attachScene(host)` 가 BHOfficeScene 이 있으면 사무실, 없으면 우체국 장면. 제목은 장면이 textContent 로 넣으므로 이스케이프하지 않고 그대로 준다 |
| `plugins/harness/console/static/post-home.js` | 창구 요약 줄 자리에 팀 요약(`.po-teams`): 요구분석팀(srs·srs-export)·설계팀(spec)·개발팀(dev)·기능컨설팅팀(config)·표준화팀(standard)·유지보수팀(fix) + 인원 수. 사무실 장면이 있고 차분이 아닐 때만 보임 |
| `plugins/harness/console/static/theme-post.css` | `.po-stage.is-office` 높이 2.4:1(640px 이하는 1.6:1), `.po-teams`. 모두 `:root[data-theme="post"]` 아래 |
| `plugins/harness/.claude-plugin/plugin.json`, `console/whats_new.json` | 0.10.308 → 0.10.309 |
| `docs/guide/harness-guide.html` | 웹 콘솔 탭의 Post 오늘 화면 장면 설명을 사무실로 |
| `checker/tests/test_web_console.py`, `test_web_console_ui.py` | 서버가 office-post.js 를 낸다(eval·외부 주소 없음), index 가 싣는다, sceneList 에 flow·t, 팀 이름·calmList 유지 |

## 장면 파일 다시 복사
번들은 `ai-office-iso` 에서 다시 빌드돼 바뀔 수 있다(이번 복사는 ai-office-iso 77b9826 — 외모는 세션 id 해시로 고정). 한 줄:

```
cp /Users/minjaehui/Documents/ai-office-iso/dist-lib/office-post.js plugins/harness/console/static/post/office/office-post.js
```

복사 뒤 `eval(`·`new Function`·`import(` 이 없는지, 외부 주소가 `http://www.w3.org/2000/svg` 뿐인지(시험이 확인), 판을 올릴지 본다.

## 판단·남은 것
- 장면 번들(ai-office-iso 9a75342)은 말풍선을 textContent 로 짜고 `innerHTML` 이 없다. 그래서 app.js 는 제목을 이스케이프하지 않고 `sceneList` 를 그대로 준다(시험이 번들에 innerHTML 계열이 없음을 확인). 헤드리스 hover 로 `<b>`·`&` 제목이 글자 그대로 보임을 봤다.
- 장면이 host 폭으로 compact 를 정하고 host 의 aspect-ratio 를 직접 넣는다. CSS 의 aspect-ratio 두 값은 붙기 전 자리 잡기용이다.
- 팀 요약은 갈래가 없는 세션을 어느 팀에도 세지 않는다. 리뷰 룸·카페 칸은 넣지 않았다(세션의 상태로 가릴 근거가 장면 안에만 있다).
- 차분(fx=0) 목록의 "n번 창구 …" 글은 그대로다(우체국 창구 이름).
- `theme-post.js` 의 우체국 장면 부품·`static/post` SVG 는 세션·요청 화면 아바타(`avatar`, `personOf` 등)와 사무실 번들이 없을 때의 대체로 쓰여 남겼다. 쓰지 않게 된 것은 우체국 장면 `Scene`(창구 배경·소품·`drawPlaque`) 과 그 부품(bg·stations·props·fx)이지만, 번들 없을 때 대체라 지우지 않았다.
- 시험 실행: `uv run pytest checker/tests -k "console or theme or static" -q -rs` → 1688 통과, 5 건너뜀, 0 실패.
- 실제 확인: 시험 콘솔(세션 9개, 갈래 지정)을 헤드리스 Chrome 1500px·400px 로 열어 봄. 콘솔 오류는 `/favicon.ico` 404(기존 것) 뿐, CSP 위반 0. 차분이면 장면·팀 줄이 숨고 목록 9줄, Sauce 는 변화 없음.
- 못 본 것: 내 차례·막힘 같은 말풍선 상태(시험 세션이 모두 일하는 중), 말풍선 호버, 세션 14개 넘을 때.
