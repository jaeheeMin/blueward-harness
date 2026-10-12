# 이슈와 릴리즈 규칙

## 이슈 제목과 본문

이슈 제목은 무엇을 할 것인지 한 줄로 적고 명사형으로 끝낸다. 예: `온보딩 문서 추가`.

이슈 본문에는 다음 세 가지를 담는다.

- **배경** : 왜 이 일이 필요한지
- **해야 할 일** : 무엇을 하면 되는지
- **완료 조건** : 어떤 상태가 되면 끝난 것으로 볼지

## 라벨 체계

다음 다섯 가지 라벨만 쓴다.

| 라벨 | 뜻 |
|---|---|
| `type:feat` | 새 기능이나 새 문서 추가 |
| `type:fix` | 잘못된 동작이나 내용 수정 |
| `type:docs` | 문서만 고치는 작업 |
| `type:chore` | 설정이나 잡무성 작업 |
| `status:blocked` | 다른 작업이나 결정을 기다리는 상태 |

그 밖의 라벨은 합의 없이 늘리지 않는다. 라벨이 늘어날수록 어떤 라벨을 붙여야
하는지 매번 판단해야 해서, 참여자가 라벨 자체를 신경 쓰지 않게 되기
때문이다.

## 이슈 크기

하나의 이슈는 한 번의 `/harness:start` 로 착수할 수 있는 크기여야 한다. 이슈가
너무 크면 진행 상황을 브랜치 하나로 추적하기 어렵고, 리뷰할 PR 도 함께
커진다. 크다고 판단되면 착수 전에 이슈를 나눈다.

## 릴리즈 버전

버전은 `YYYY.MM.DD` 형식을 쓴다. 같은 날 두 번째 릴리즈부터는 뒤에 `.2`,
`.3` 처럼 순번을 붙인다. 예: `2026.09.13`, `2026.09.13.2`.

## 엔진 배포 (plugin.json version 과 태그)

`plugins/harness/.claude-plugin/plugin.json` 의 version 이 곧 배포 단위다. 배포되는 파일을
바꾸면 version 을 올린다: `plugins/harness/` 전부, 엔진 `checker/`(시험 `checker/tests/` 와 안의
`*.md` 문서는 제외), `pyproject.toml`, `uv.lock`, `scripts/`, 그리고 Project Repository 가 부르는
재사용 워크플로(`workflow_call` 을 가진 `.github/workflows/*.yml`). PR 검사(`checker/plugin_version.py`)가
확인한다.

main 에 version 이 바뀐 plugin.json 이 병합되면 Actions(`release-tag.yml`)가 그 커밋에
`v{version}` 태그를 붙이고 움직이는 태그 `stable` 을 그 커밋으로 옮긴다. 사람이 따로 배포를
지시하지 않는다. 팀원 PC 훅은 엔진을 `v{version}` 으로, Project Repository 의 caller workflow 는
`@stable` 로 받는다. 같은 `v{version}` 태그가 이미 다른 커밋에 있으면(version 을 안 올리고 병합)
워크플로가 실패하고, 실패하거나 stable 을 옮기지 못하고 건너뛰면 저장소 owner 앞으로 이슈
("release-tag: 엔진 판 배포가 안 됐다")가 열린다. 병합 직후 태그가 붙기까지 잠시 걸리므로, 그 사이
갱신한 PC 에서는 엔진 판을 받을 수 없다는 안내가 나올 수 있다 — 병합 뒤 `git ls-remote --tags origin`
으로 `v{version}` 과 `stable` 이 새 커밋을 가리키는지 본 다음 플러그인을 갱신한다.

짧은 간격으로 병합이 겹쳐 중간 판의 실행이 밀려나도(실행은 줄을 서고 대기 중인 실행은 최신 하나만
남는다) 다음 실행이 직전 `stable` 이후 main 이력에서 plugin.json 이 바뀐 커밋 중 태그 없는 version 을
각각 그 커밋에 붙인다. 그래도 빠진 태그나 어긋난 `stable` 이 있으면 Actions 에서 `release-tag` 를
main 으로 수동 실행(workflow_dispatch)해 보충한다 — 그 커밋 기준으로 `v{version}` 을 붙이고 `stable` 을
옮긴다.

## 릴리즈 노트 구성

변경 내용을 다음 네 절로 나눈다.

- **추가** : 새 기능이나 새 문서
- **수정** : 기존 동작이나 내용의 수정
- **문서** : 문서만 바뀐 변경
- **기타** : 위 셋에 들지 않는 변경

각 항목 끝에는 해당 PR 번호를 붙인다. 예: `온보딩 문서 추가 (#12)`.

## 정상 경로

이슈 등록은 `/harness:start` 가, 남은 작업의 이슈화는 `/harness:wrapup` 이 수행한다.

새 개발 작업은 `/harness:start` 로 시작한다 — 진행 원장(`audit/ledger/`)이 있는
저장소면 이때 개발 건으로 등록된다. 설계 문서가 필요하면 `/harness:spec` 으로 같은
번호에 붙인다.

릴리즈 발행을 맡는 `/release` 스킬은 저장소에 따라 아직 없을 수 있다. 아직
릴리즈할 것이 없거나, 이 harness 플러그인이 그 스킬을 아직 담고 있지 않기
때문이다. 위 릴리즈 노트 형식은 그때를 위해 남겨 둔 것이고, 실제로 발행할
때가 되면 팀이 쓰는 다른 저장소나 배포에서 `/release` 스킬을 가져온다.
