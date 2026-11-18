# Cozy Office 이름 바꾸기(Post 테마 표시 이름, 2026-11-18)

웹 콘솔 테마의 **보이는 이름**을 `Post`(우체국) → `Cozy Office`(사무실)로 바꿨다. 내부 id(`post`)·파일 이름(`theme-post.*`, `post-*.js`)·CSS 선택자(`data-theme="post"`)·저장 값(`bh-theme=post`)·코드 주석·내부 함수 이름은 그대로 둔다(이미 고른 사람의 설정이 깨지지 않게). 브랜치 `post/cozy-name`, push·PR·이슈·판 올리기 없음(빠른 개발 모드).

## 바꾼 곳

| 파일 | 지금(바뀐 뒤) 문구 |
|---|---|
| `static/theme.js` `THEMES` | name `Cozy Office`, tagline `사무실 · 세션이 팀 자리에 앉아 일해`. 설정 테마 고르기 카드·위쪽 줄 테마 단추(글자·title·aria-label)는 이 값을 읽어 와서 따로 안 고쳤다 |
| `static/app.js` 파이프라인 안내(Sauce 로 주소를 열었을 때) | `파이프라인은 Cozy Office 테마에서 보여` / `설정에서 테마를 Cozy Office 로 바꾸면 …` |
| `static/app.js` 설정 밝기 설명 | `장면 그림은 낮 우체국 그대로 두고` → `낮 모습 그대로 두고` |
| `docs/guide/harness-guide.html` 620·633행 | `테마(Sauce · 우체국 Post)` → `테마(Sauce · Cozy Office)`, 「Post 를 고르면」·「Post 는 색만이 아니라」·「Post 의 "바뀐 파일" 목록」·「Post 는 산출물 탭에」 → `Cozy Office …`. 길잡이에 `Post`·`우체국` 은 0개 |
| `checker/tests/test_web_console_ui.py` | 끝에 `test_cozy_office_display_name` 덧붙임(문구 단언 줄은 기존에 없어 고친 줄 없음) |

## 바꾸지 않은 것(이유)

- 코드 주석·내부 이름(`isPostTheme`, `po-*`, `BHPost*`, `theme-post.js` 등): 지시(내부 이름 보존).
- `static/theme-post.js:151` 장면 aria-label `우체국 장면. 세션 N개가 다섯 창구 … 앞에 서 있어`와 `:26` console.debug: 사무실 장면이 안 실렸을 때 붙는 **옛 우체국 장면(대체 그림)** 의 이름이지 테마 이름이 아니다. `office-post.js` 가 있어 사무실 장면이 붙으면 이 문구를 만드는 길은 안 타서 사실상 죽은 경로다(리뷰 확인). 대체 그림을 없앨지는 판정 대기.
- 우체국 도장(`보냄`·`접수`·`반송`): 장면·부품이 아니라 동작 이름이라 그대로.
- `whats_new.json`·`whats_new.d/1078.json` 안의 `Post`·`우체국`: 이미 낸 새 소식(역사) 또는 이번 범위 밖(whats_new 조각을 새로 만들지 않는 과제). 아래 「다음 판 올릴 때 넣을 한 줄」로 알린다. 옛 줄의 「Post 테마」는 판이 지나간 기록이라 둔다(사용자 판정 대기).
- `server.py:190` 같은 코드 주석 속 `Sauce·Post`: 주석.
- `static/theme-post.css` 안의 `우체국` 말들: 주석.
- **설정 테마 고르기 카드의 미리보기 그림(`.tc-post`)** 은 항공우편 줄무늬(우체국 편지봉투 모양)다. 이름은 Cozy Office 인데 그림이 우체국 느낌이다 → 디자인 판정 대기(CSS 라 이번 범위 밖).

## 실화면(Aside, 시험 세계 포트 4961, 끝나고 pid 로 끔)

- Cozy Office 라이트·다크 × 1440·390 의 설정(테마 고르기)·오늘 화면: 카드 `Cozy Office / 사무실 · 세션이 팀 자리에 앉아 일해`, 위쪽 줄 단추 `Cozy Office`(title `테마 바꾸기 · 누르면 Sauce`, aria-label `테마 Cozy Office · 누르면 Sauce(으)로 바뀌어`), 가로 넘침 없음, `page.console.logs()` 비었음. 화면 어디에도 `우체국`·`Post` 글자 없음(본문 검색).
- 390 에서는 위쪽 줄 테마 단추가 아이콘만 보인다(원래 글자를 숨기던 것). aria-label 은 Cozy Office 로 읽힌다.
- `bh-theme=post` 가 저장된 브라우저가 그대로 Cozy Office 로 열림(`data-theme=post`). 위쪽 줄 단추 → Sauce, 설정 카드로 Sauce ↔ Cozy Office 전환·새로 고침 뒤 유지 모두 정상, 저장 값은 `post`/`sauce` 그대로.
- 스크린샷: 시험 scratchpad `cozy-{settings,home}-{light,dark}-{1440,390}.jpg`.

## 시험

`uv run pytest checker/tests/test_web_console.py checker/tests/test_web_console_ui.py -q -n 8` → 1576 passed, 2 skipped(기존 1575 + 새 1).

## 다음 판 올릴 때 새 소식에 넣을 한 줄(조각은 아직 안 만듦)

- 「테마 Post 의 이름이 Cozy Office 로 바뀌었어. 설정에서 고른 테마는 그대로 이어져.」

## 독립 리뷰

sonnet 읽기 전용 리뷰 결과와 처리:
- 남은 보이는 문구: `theme-post.js:151` 우체국 장면 aria-label 하나뿐(위 「바꾸지 않은 것」과 같다, 죽은 경로). 조사(는·를·로) 어색한 곳 없음. 내부 id·저장 값·선택자 건드린 곳 없음(`THEMES` 는 모두 id 로 비교).
- 시험이 `theme.js` 안 `우체국` 글자 하나로도 깨질 만큼 빡빡해서 `"우체국" not in theme`·`'Post'` 따옴표 검사를 `"name: 'Post'" not in theme` 로 줄였다. 길잡이 전체 검사(`Post`·`우체국` 0개)는 그대로 둔다(길잡이는 우리 문서라 의도한 것).
- 장면 이야기의 길잡이 본문(「창구」「손님」「붉은 도장」 같은 우체국 장면 말)은 장면·부품 이름이라 그대로 둔다. 사무실 장면에 맞게 다시 쓸지는 판정 대기.
- `name` 이 길어진 것(`Cozy Office`)은 실화면에서 1440·390 설정 카드·위쪽 줄 단추 모두 넘침 없이 들어감을 확인했다.
