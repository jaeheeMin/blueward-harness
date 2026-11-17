# Post 테마 검증 갈래 A — 파이프라인 탭(2026-11-18)

이슈 없음(사용자 지시: Post 테마 검증·수정 묶음, 로컬 main 에만 합침). 시안은 confirm 세션 scratchpad 의 `pipeline-mockup/pipeline.html`.
#1025 에서 실제 데이터가 없어 뺐던 화면을 처음 구현했다.

## 한 일

- `console/pipeline.py`(새): 저장소의 요구사항마다 칸을 정할 사실을 읽는다. 설정·표준·Spec 판정은 `devready.read` 를 그대로 쓰고
  (같은 기준), origin/main 의 SRS(제목·Status)·원장(내용·상태)을 더 읽는다. 열린 PR 은 `gh pr list --json files,...` 로 읽어
  바뀐 Spec 파일 이름·PR 제목·브랜치의 REQ-/DEV- 번호로 요구사항에 붙인다(`src/` 를 바꿨으면 작업 PR, Spec 파일이면 Spec PR).
  합쳐짐 = 원장 상태 `완료` 또는 SRS Status `Done`. Dropped·Duplicate·On hold 는 판에서 빼고 수만 센다.
- `GET /api/pipeline?cwd=`: `/api/dev-ready` 패턴(known_root·cached(wait=False)·state yes/no/unknown). 캐시 열쇠는 git 공통 폴더라
  같은 저장소의 worktree 들은 한 번만 읽고, 응답의 `repo.key` 로 화면이 한 판에 모은다. gh 를 못 읽으면 판은 보이되 `prs.state=unknown`.
- `static/post-pipeline.js`(새): 세션 → 요구사항(세션 이름·갈래 사유·브랜치 번호, 다음 갈래 옵션 번호, 세션 PR 번호가 그 요구사항의 열린 PR),
  칸 배정(시안 laneOf), 칸 안 정렬(막힘 > 내 차례 > 번호), 820px 이하 1열·칸 머리 접힘(aria-expanded). 폴더는 세션 작업 폴더(+마지막 폴더) 최대 12개.
  unknown 은 이유 문장, SRS·원장 없는 폴더와 없어진 폴더(403)는 아래 한 줄로 이름만. 판이 하나도 없으면 빈 상태 판.
- `static/post-pipeline.css`(새): `:root[data-theme="post"] .po-pl-*` 만. 토큰·판 틀(.light.po-panel·.po-ph)·상태 글자(.po-st-*)는 theme-post.css 것.
- `app.js`: `/pipeline` 경로, 뷰 표, Post 레일 「파이프라인」(route 아이콘), `pipelineView`(Sauce 면 안내 상자). `server.py` SPA_PATHS 에 `pipeline`.
- 시험: test_web_console.py 끝(API 6건), test_web_console_ui.py 끝(node 로 순수 함수, 배선·CSS 범위 검사).

## 확인

- `uv run pytest checker/tests -n 8`: 6236 passed.
- Aside, 별도 포트(4891, 실제 세션 저장소 복사본): public-cloud 실제 데이터 SRS 24건이 칸 1·0·13·3·7 로 뜸
  (검토 = 열린 작업 PR #812·#837·#858, 합쳐짐 = 원장 완료 7건). Post 라이트·다크 × 1440·390 스크린샷, 가로 넘침 없음, 콘솔 오류 없음.
  390 에서 1열, 3·5칸 머리를 눌러 접힘(aria-expanded=false, 목록 숨김).
- 카드 클릭: 실제 저장소에는 요구사항 번호가 붙은 세션이 없어서(public-cloud 세션 3개는 제목·브랜치에 번호 없음),
  **시험 서버에만** 훅으로 public-cloud 세션 하나(첫 말 "DEV-013 …")를 넣어 확인 → REQ-013 카드가 a 로 바뀌고 누르면 `/s/pl-check-1`.
- 빈 상태: 세션 없는 시험 서버(4892, 마지막 폴더 = SRS 없는 이 저장소) → 「보일 요구사항이 없어」 + 뺀 폴더 이름.
- Sauce 로 `/pipeline`: 레일·탭 없음, 「파이프라인은 Post 테마에서 보여」 안내.

## 남은 것·판단 대기

- unknown(origin/main 을 못 받음) 화면은 API 시험으로만 확인했다(실제로 네트워크를 끊어 보지는 않았다).
- 세션 기억 고리는 % 를 아는 세션만 그린다(모르면 그리지 않는다). 실제 화면에서 % 가 있는 연결 세션은 보지 못했다.
- 작업 PR 판정 기준 `src/` 는 Project Repository 표준 구조 기준. 다른 폴더에 코드를 두는 고객사가 생기면 다시 본다.
