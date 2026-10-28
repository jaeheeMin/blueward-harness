# #521 GitHub Actions 부품을 Node.js 24 판으로 올리기 (2026-10-28)

GitHub 가 Node.js 20 지원 종료를 예고해 모든 job 에 "Node.js 20 is deprecated" 경고가 떴다(강제로 Node 24 로 돌아 동작은 함).

| action | 전 | 후 | 근거 |
|---|---|---|---|
| actions/checkout | v4 | v5 | v5 action.yml `using: node24` |
| astral-sh/setup-uv | v5 | v7 | v6 은 아직 node20, v7 부터 node24. v6·v7 breaking(기본 cache-dependency-glob, server-url 제거)은 `enable-cache: true` 만 쓰는 이 저장소에 해당 없음 |
| actions/github-script | v7 | v8 | node24 |
| actions/upload-artifact | v4 | v6 | v5 는 node20, v6 부터 node24 |

최신 대판(checkout v7, setup-uv v10 등)이 아니라 node24 로 바뀐 가장 낮은 판을 골라 다른 breaking 을 줄였다. 재사용 워크플로라 version 0.10.133. pr-checks·main-checks 는 이 저장소 CI 에서 돌지 않으므로 배포 뒤 public-cloud 첫 PR 에서 확인한다.
