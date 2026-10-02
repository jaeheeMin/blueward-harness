# blueward-harness

문서가 정해진 템플릿을 따르는지 검사하고, 맞지 않으면 거절하면서 쓸 템플릿을
안내하는 체계(**doc-guard**)를 만드는 저장소다.

## 무엇이 어디 있나

```
checker/            검사 엔진. 문서를 읽어 규칙 위반 목록을 낸다
plugins/harness/    위 엔진과 협업 Skill·규칙·훅을 함께 부르는 Claude Code 플러그인
.claude-plugin/     이 저장소가 플러그인 마켓플레이스임을 선언
.claude/            harness 플러그인 설치 설정 (enabledPlugins) — 스킬·훅 자체는 plugins/harness/ 에 있다
.githooks/          main 직접 커밋·푸시를 막는 git hook
```

### 검사 엔진이 플러그인 밖에 있는 이유

같은 엔진을 두 곳에서 부르기 때문이다.

| 진입점 | 도는 곳 | 엔진을 어떻게 얻나 |
|---|---|---|
| 플러그인 훅 | 팀원 PC 의 Claude | 이 마켓플레이스에서 설치 |
| GitHub Actions | GitHub 서버 | 대상 저장소에 번들로 들어가야 함 |

Actions 는 팀원 PC 에 설치된 플러그인을 쓸 수 없다. 엔진을 `plugins/` 안으로
옮기면 Actions 경로가 끊긴다.

### 규칙은 코드가 아니라 데이터다

검사 규칙은 고객사별 `rules.yaml` 에 적고, `checker/rules/` 아래 모듈은 규칙
*종류* 를 구현한다. 새 규칙을 추가할 때 엔진 코드를 고치게 된다면 설계가
어긋난 것이다.

템플릿 원본과 `rules.yaml` 은 별도의 저장소에 모아 두지 않는다. 고객사
프로젝트마다 생기는 Project Repository 안에 그 프로젝트의 산출물과 함께
`templates/` 와 `rules/` 로 둔다. 엔진은 검사할 문서에서 위로 올라가며 이
둘을 함께 든 폴더를 찾으므로, 기준을 찾으러 Project Repository 밖으로 나갈
일이 없다.

## 지금 어디까지 왔나

**검사 엔진 MVP 가 동작한다.** 규칙 파일 스키마, 파일명·위치 규칙, md·docx 필수 섹션
규칙, xlsx 필수 시트·표 헤더 규칙, pptx 레이아웃 규칙, 그리고
`check <파일...> --rules <규칙 파일 또는 폴더>` CLI 까지 들어 있다. 자세한 것은
`checker/README.md` 를 읽는다.

다음 할 일은 플러그인 훅이다. 지금은 검사만 하고 아무것도 막지 못한다 — 엔진이 위반을
종료코드로 알리지만 그것을 받아 거절하는 껍데기가 아직 없다.

협업 Skill(`/harness:start`, `/harness:deliver`, `/harness:wrapup`) 과 공통
규칙 5개, 그것을 강제하는 훅 3개를 `plugins/harness/` 플러그인에 담았다.
저장소 쪽 `.claude/skills` 와 `.claude/hooks` 와 루트 `rules/` 의 옛 사본은
지웠고, 이 저장소도 `.claude/settings.json` 의 `enabledPlugins` 로 그
플러그인을 설치해 쓴다.

## 설치와 사용

플러그인 훅이 생긴 뒤에 아래로 설치한다. 그 전에는 엔진을 직접 부른다.

```bash
uv run doc-guard --rules <Project Repository>/rules/ <Project Repository>/docs/파일.md
```

```
/plugin marketplace add jaeheeMin/blueward-harness
/plugin install harness@blueward-harness
```

플러그인은 저장소가 아니라 **사람** 에게 설치된다. 한 번 설치하면 어느 저장소를
열든 동작한다.

훅은 Claude 를 쓸 때만 돈다. GitHub 웹이나 터미널 git 으로 올리면 그냥
지나가고, 그쪽은 GitHub Actions 검사가 잡는다.

## 개발 규칙

작업은 항상 `/harness:start` 로 시작해서 `/harness:deliver` 로 마친다. 이
스킬들은 저장소 자체가 아니라 `harness` 플러그인이 제공한다.

```
사용자> /harness:start 파일명 규칙 검사 추가

Claude> 이슈 #5 "파일명 규칙 검사 추가" 를 만들었습니다.
        브랜치 feat/5-add-filename-rule 로 이동했습니다.

(... 작업 ...)

사용자> /harness:deliver

Claude> 커밋했습니다. origin/main 을 rebase 했습니다. 푸시했습니다.
        PR #6 을 열었습니다.
```

| 스킬 | 언제 |
|---|---|
| `/harness:start` | 새 작업 시작. 이슈와 브랜치를 만든다 |
| `/harness:deliver` | 작업 마무리. 커밋·동기화·푸시·PR 을 한 번에 |
| `/harness:wrapup` | 못 끝낸 작업을 이슈로 남길 때 |
| `/harness:sync` | GitHub 의 최신 상태를 지금 로컬 브랜치로 당겨받을 때 |

main 에 직접 커밋하거나 맨손 `git push` 하면 훅이 거부한다. 훅이 막으면
우회하지 않는다. `--no-verify` 로 건너뛰지도 않는다. 거부 메시지의 안내를
따르고, 안내가 상황과 맞지 않으면 판단을 사람에게 맡긴다.

자세한 규칙은 `plugins/harness/rules/` 가 정본이다. 요약은 `CLAUDE.md` 에 있다.

**위험한 PR 만 승인을 요구한다(#102).** 고객사 Project Repository 에는 `/harness:scaffold` 가
`.github/risk-gate.yaml`(기준)과 `.github/workflows/risk-gate.yml`(PR 검사·병합 뒤 감지)을
넣는다. 크기, 위험 경로, 비밀값, 다른 검사 결과 중 하나라도 걸리면 승인자 목록의 사람(작성자
제외)이 마지막 커밋에 Approve 해야 통과하고, Claude 병합 훅도 같은 판정(`checker.risk_gate`)으로
거부한다. 기준은 `.github/risk-gate.yaml` 에서 고치고 파일을 지우면 꺼진다. 이 저장소
자신은 승인자가 한 명뿐이라 아직 이 파일을 두지 않았다(게이트 꺼짐).

> **브랜치 보호가 걸려 있지 않다.** 이 저장소는 개인 계정의 private 저장소이고
> 요금제가 Free 라, GitHub 서버 쪽에서 main 을 강제로 지킬 수 없다. 지금
> main 을 지키는 것은 로컬 훅뿐이고, 훅을 설치하지 않은 clone 에서는 막을
> 수단이 없다. 서버 강제가 필요해지면 Team 요금제로 올리거나 조직 저장소로
> 옮긴다.

## 처음 세팅하는 사람

필요한 것: git, GitHub CLI(`gh`), `jq`, Claude Code.
`jq` 가 없으면 Claude 훅이 git 명령을 전부 거부하니 반드시 설치한다.

운영체제별 설치 명령과 Windows 주의사항은
[public-cloud 의 README](https://github.com/jaeheeMin/public-cloud#처음-시작하는-사람이-할-일)
를 따른다. 같은 하네스를 쓰므로 설치 절차가 같다. 이 문서에 옮겨 적지 않는
이유는, 저장소마다 한 벌씩 복사하면 설치법이 바뀔 때 고칠 곳이 갈라지기
때문이다.

clone 한 뒤 git hook 을 설치한다. Claude Code 세션에서는 시작 훅이 자동으로
해 준다.

```bash
bash scripts/install-hooks.sh
```

아래 출력이 `.githooks` 면 된 것이다.

```bash
git config --get core.hooksPath
```

## 저장소 설정 기록

- 이슈 라벨 5개 생성 완료 (`type:feat`, `type:fix`, `type:docs`, `type:chore`,
  `status:blocked`). `gh issue create --label` 은 라벨이 없으면 실패하므로
  `/harness:start` 가 이것에 의존한다.
- 브랜치 보호 규칙은 위 사유로 걸지 않았다.
- Teams 알림 워크플로는 옮기지 않았다. 붙이려면 이 저장소에 웹훅 시크릿
  `TEAMS_WEBHOOK_URL` 을 따로 등록해야 한다.
