# #490 AI 리뷰가 PR head checkout 에 엔진 폴더가 지워져 모든 PR 에서 검사 불능

## 증상

- 0.10.121(#486) 배포 뒤 public-cloud 의 ai-review 가 세 번 모두 실패했다(2026-10-26 06:17·07:39·07:50, run 40288213856 등).
- `Claude 리뷰` 단계 로그: `error: Project directory .harness-engine does not exist`. 결과 정리 단계가 검사 불능으로 밝혀 통과로 새지는 않았다(원칙 7).

## 원인

- `PR head 가져오기`(actions/checkout, path 없음)가 작업 폴더가 그 저장소가 아니라며 `Deleting the contents of '/home/runner/work/public-cloud/public-cloud'` 로 내용을 지웠다. 먼저 받아 둔 `.harness-engine` 도 그 안에 있어 함께 지워졌다.
- `clean: false` 는 이 삭제를 막지 못한다. 기존 주석과 테스트는 막는다고 잘못 적고 있었다.
- 옛 방식(claude-code-action)은 PR checkout 뒤에 엔진을 다시 부르지 않아 드러나지 않았다. #486 의 로컬 시험은 엔진을 직접 불러 이 단계를 거치지 않았다.

## 결정

- PR head 를 하위 폴더 `pr` 에 받고 엔진에 `--repo "$GITHUB_WORKSPACE/pr"` 를 넘긴다. 엔진 폴더와 겹치지 않는다.
- 워크플로 테스트가 PR checkout 의 `path` 가 `pr` 이고 엔진 폴더와 다르며, 엔진이 그 폴더를 리뷰하는지 확인한다.
- plugin version 0.10.123.

## 남은 일

- 병합 뒤 public-cloud 의 다음 ai-review 실행(주인이 커밋을 올릴 때)에서 엔진이 돌고 결과가 나오는지 확인한다.
