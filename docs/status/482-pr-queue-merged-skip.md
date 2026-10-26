# #482 병합 순간 pr-queue 실행이 겹쳐 병합된 PR 에 취소가 남는 문제

## 증상

- #477 병합 직후 그 PR 의 `pr-queue / queue` 가 실패로 보였다(`gh pr checks` 가 fail). 실행 결과는 `cancelled`, 1초, 단계 없음(run 40254800812).
- 같은 초에 `push: main` 실행(40254800549)이 떠서 성공했다. #474 병합 때는 반대로 push 쪽(40252412476)이 취소됐다.

## 원인

- `.github/workflows/pr-queue-self.yml` 은 `pull_request: closed` 와 `push: main` 둘 다로 뜬다. 병합하면 둘이 같은 순간 뜬다.
- job concurrency 가 저장소 하나에 한 그룹이고 `cancel-in-progress: true` 라 먼저 뜬 쪽이 취소된다.
- 취소된 쪽이 PR 실행이면 병합된 PR 의 head 커밋에 취소 check 가 남는다. 순서 계산은 남은 실행이 해서 동작에는 영향이 없다.

## 결정

- 병합으로 닫힌 PR(`pull_request` + `closed` + `merged`)이면 job 을 건너뛴다. push 실행이 같은 계산(차례 알림 포함 — 직전 코멘트와의 차이로 정한다)을 한다.
- 병합 없이 닫힌 PR 은 push 가 없으므로 지금처럼 돈다.
- Project Repository 의 `pr-checks.yml` 은 PR 단위 concurrency 라 같은 경합이 없다. 고치지 않는다.
- 이 파일은 재사용 워크플로(`workflow_call`)가 아니라 이 저장소 전용이므로 plugin version 을 올리지 않는다.
