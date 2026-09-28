# CLAUDE.md

이 저장소에서 지킬 행동 규칙의 요약과 세부 문서 색인이다. 진행 이력과 미결
사항은 [`docs/status.md`](docs/status.md) 에 있다 — 훅, Actions, 스캐폴드, 승인
검사, 코드 검사 등을 건드리기 전에 관련 절을 읽는다.

## 이 저장소는 무엇인가

문서가 정해진 템플릿을 따르는지 검사하고, 어긋나면 거절하며 쓸 템플릿을
안내하는 체계(**doc-guard**)의 Plugin Repository(`jaeheeMin/blueward-harness`)다.

- `checker/` — 검사 엔진. 문서·코드를 읽어 규칙 위반 목록을 낸다.
- `plugins/harness/` — 엔진을 부르는 훅과 협업 Skill·규칙을 담은 Claude Code
  플러그인. 엔진은 들어 있지 않다. 이 저장소 자체가 마켓플레이스다.
- `.github/workflows/doc-guard.yml` — Project Repository 가 불러 쓰는 재사용 워크플로.

**Project Repository** 는 고객사 프로젝트마다 따로 생기며, 산출물과 함께 검사
기준(`templates/`, `rules/`)을 담는다. 검사는 거기서 PR 을 열 때 걸리고, 엔진만
이 저장소에서 가져간다.

## 건드리기 전에 알아야 할 것

1. **엔진은 플러그인 밖에 둔다.** 같은 엔진을 훅(팀원 PC)과 Actions(GitHub
   서버) 두 곳에서 부른다. Actions 는 이 저장소를 체크아웃하고, 훅은 `uvx` 로
   이 저장소의 GitHub 원격을 받는다(마켓플레이스 설치본엔 엔진이 없다).
2. **규칙은 코드가 아니라 데이터다.** 고객사별 `rules.yaml`, 규칙 종류는 모듈
   등록. 규칙이 늘 때 엔진 코드를 고치게 되면 설계가 어긋난 것이다.
3. **기준은 Project Repository 안에 둔다.** 저장소 간 읽기 권한이 필요 없게.
4. **주 관문은 Actions, 훅은 보조다.** 오피스로 만든 문서는 훅을 안 거친다.
5. **문서를 올리는 사람은 쓴 팀원이다.** 고객사 직접 업로드는 범위 밖.
6. **문서 버전은 파일명에 남긴다**(`개발사양서_v1.0.xlsx`), 이전 판도 지우지 않는다.
7. **"검사를 못 했다" 를 "통과" 나 "위반" 으로 뭉개지 않는다.** 검사할 수
   없으면 통과시키지도, 위반이라 하지도 말고 검사 불능이라고 말한다.
8. **`plugins/harness/` 안 파일을 바꾸면 `plugins/harness/.claude-plugin/plugin.json`
   의 version 을 올린다.** 같으면 팀원 PC 설치본이 갱신되지 않는다.

## 가장 중요한 세 가지

1. **main 에 직접 커밋하지 않는다.** `/harness:start` 로 이슈와 브랜치부터 만든다.
2. **푸시는 `/harness:deliver` 로 한다.** 맨손 `git push` 는 훅이 거부한다.
3. **조사와 실행은 `sonnet` 서브에이전트에 맡긴다.** 메인 세션은 무엇을 할지
   정하고 결과를 판정한다.

## 규칙 색인

정본은 `plugins/harness/rules/` 이고, 이 문서와 어긋나면 그쪽을 따른다.

| 문서 | 내용 |
|---|---|
| `branching.md` | 브랜치 이름 형식, main 직접 커밋·푸시 금지 |
| `commit-and-pr.md` | 커밋·PR 형식, 푸시 전 fetch·rebase, `--force` 금지 |
| `issue-and-release.md` | 이슈 제목·본문·라벨, 이슈 크기, 릴리즈 버전과 노트 |
| `delegation.md` | 메인 세션과 서브에이전트 역할, 모델 고정, 자기 승인 금지 |
| `governance.md` | 리뷰·병합, 스킬을 거쳐야 하는 작업, 훅이 막았을 때 대응 |

## 스킬

`harness` 플러그인이 제공한다(`.claude/settings.json` 의 `enabledPlugins`).

| 스킬 | 언제 |
|---|---|
| `/harness:start` | 새 작업 시작 — 이슈와 브랜치 |
| `/harness:deliver` | 작업 마무리 — 커밋, 동기화, 푸시, PR |
| `/harness:wrapup` | 못 끝낸 작업을 이슈로 |
| `/harness:scaffold` | Project Repository 표준 구조 만들기 |
| `/harness:prd` | PRD 만들기·고치기 |
| `/harness:spec` | PRD 요구사항으로 개발 Spec 만들기·고치기 |
| `/harness:sync` | GitHub 의 최신 상태를 지금 로컬 브랜치로 당겨받기 |

`/release`, `/intake` 는 필요해지면 `jaeheeMin/public-cloud` 에서 가져온다.
