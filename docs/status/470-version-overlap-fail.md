# #470 열린 PR 끼리 plugin version 겹침을 경고에서 실패로 (2026-10-26)

## 원인

`checker.yml` 의 "열린 PR 끼리 plugin version 겹침 확인" 단계(#324)는 겹침을 잡았지만 `::warning::` 과 종료코드 0 이라 체크가 초록이었다. 병합 판단에서 경고를 보지 않아 #462·#464 가 같은 0.10.115 로 병합됐고, 나중 쪽은 `v0.10.115` 태그가 이미 있어 배포되지 못했다(#468 이 0.10.116 으로 땜질).

## 바꾼 것

- `checker/plugin_version_overlap.py` — 겹침이면 `VIOLATION` 과 `violations` 를 낸다. 올릴 다음 값은 main·이 PR·읽은 열린 PR 의 version 중 가장 큰 값 + 1 이다.
- `scripts/check_plugin_version_overlap.py` — 겹침이면 `::error title=plugin version 겹침::…` 를 내고 종료코드 1.
- 규칙: 검사가 도는 순간 같은 version 을 쓰는 다른 열린 PR 이 있으면 지금 PR 이 실패한다(먼저 차지한 쪽이 이긴다 — 상대 PR 의 체크는 다시 돌지 않는다).
- 그대로: version 을 안 올린 PR 은 네트워크 없이 통과(not_needed), 다른 PR 한 건만 못 읽으면 그 PR 만 건너뛰고 경고, 목록·내 version 을 못 읽으면 검사 불능 종료코드 2(원칙 7).
- `checker.yml` 단계 주석, `plugins/harness/rules/issue-and-release.md` 의 엔진 배포 절(실패로 바뀜, version 은 main 과 열린 PR 을 모두 보고 더 큰 다음 값). deliver 스킬에는 version 정하는 안내가 없어 규칙 문서 한 곳에만 적었다. 길잡이에는 이 검사 언급이 없어 건드리지 않았다.
- 시험 `checker/tests/test_plugin_version_overlap.py` 를 새 동작으로 고쳤다.
- plugin.json version 0.10.117 -> 0.10.118.

## 메시지 예시

이 PR 의 version 0.10.83 을 열린 PR #10(`다른 작업`) 이 이미 씁니다. 이 PR 의 version 을 0.10.84 로 올려 다시 푸시하세요(먼저 병합되는 쪽만 v0.10.83 태그를 받아 배포됩니다).
