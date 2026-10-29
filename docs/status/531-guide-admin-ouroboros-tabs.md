# #531 길잡이에 GitHub 관리자 · Ouroboros 탭 추가 (2026-10-29)

길잡이(`docs/guide/harness-guide.html`)에 탭 둘을 더했다. #529(손글씨 디자인, PR #530) 위에 쌓은 작업이다.

- **무엇을 만들지 정하기**(`ouroboros`, "문서 작업" 묶음 맨 앞): Ouroboros(`ouroboros@ouroboros` 0.54.4, 플러그인 캐시로 판 확인)가 하는 일(인터뷰 → Seed → 실행 → 평가 → 진화, 애매함 0.2 이하까지 질문), `ooo` 명령표, harness 와 나누기(PRD 는 참고 자료, 정본은 `docs/ssot/SRS.md`), MCP 연결 문제 대처. public-cloud work3 세션이 사용자 요청으로 전달한 내용을 기준으로 썼다.
- **GitHub 관리자**(`admin`, "운영 담당" 묶음 끝): 코워크 현황 메일(10-29 메일 기준 제목 · 숫자 · 팀원별 표 · 🔴🟡🟢), 할 일과 Skill(`/harness:prs --team` · `/harness:approvals` · `/harness:prs --all` · `/harness:version` · `/harness:update`), 알림 이슈 넷, 운영 파일 patch(`git am`) 반영, 관리자를 바꿀 때 고칠 곳, 하지 않는 것. 하네스 소개 아티팩트의 관리자 장표와 같은 내용이다.
- 이전 · 다음 순서: 처음 준비하기 → 무엇을 만들지 정하기 → SRS 만들기, 릴리즈 내기 → GitHub 관리자 → 막혔을 때.
- 확인: 로컬 Chrome 에서 두 탭과 이웃 탭을 글꼴 7종 × 넓은 화면 · 400px 폭으로 넘침이 없음을 재고, 레일 탭과 이전 · 다음 단추 이동을 눌러 확인했다.
- 줄임말 표기: 사용자 요청으로 SRS · PR · MCP · ATC · ABAP 등 줄임말을 탭마다 처음 나올 때 괄호에 풀네임을 붙였다(코드 · 도식 SVG · 고객사 양식 열 이름 `Priority (PO)` 은 제외). 번호 꼴에 제목 괄호가 이미 있는 곳(REQ-002(판매오더 조회 앱))은 덧붙이지 않았다. README 문체 결정에 한 줄 추가.
