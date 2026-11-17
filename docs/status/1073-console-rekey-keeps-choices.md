# #1073 웹 콘솔이 띄운 세션에 훅이 먼저 오면 고른 권한·모델이 사라지는 문제 (2026-11-17)

## 배경
콘솔이 새 세션을 띄우면 임시 id(`m-…`) 세션에 고른 값을 적고, init 이 오면 `store.rekey` 로 실제 id 세션에 옮긴다. 같은 실제 id 로 훅이 init 보다 먼저 오면 `ensure` 가 실제 세션을 먼저 만들고, `rekey` 합치기 분기는 `managed·cwd·title·log·chat` 만 옮겨서 나머지가 사라졌다(권한·모델·effort 가 기본값으로 돌아감). 병렬 시험(#1061) 뒤 `test_permission_change_rejects_values_outside_allowed_set[bogus]` 가 ubuntu 에서 한 번 깨진 것도 이 경쟁으로 본다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/store.py` | `LAUNCH_KEYS`(`managed.py _launch` 가 임시 세션에 적는 키)를 합칠 때 임시 세션 값으로 덮어쓴다 |
| `checker/tests/test_web_console.py` | 훅이 먼저 온 경우를 store 단위로 만드는 시험(고치기 전엔 `KeyError: 'starting'` 으로 실패) |
| `plugins/harness/console/whats_new.json`, `plugin.json` | 0.10.325 |

## 판단
- 옮기는 키: `starting`, `managed_alive`, `modelChoice`, `effortChoice`, `permissionChoice`, `forkedFrom`, `startChecks`. 훅이 만든 세션엔 없거나 기본값이라 임시 세션이 이긴다.
- `ended` 는 옮기지 않는다. init 이 왔으니 살아 있는 세션이고 실제 세션 기본값(False)이 맞다.
- launch 뒤 임시 세션에 쓰는 title(`TITLE_PROMPT`)은 기존 title_rank 비교로 이미 옮겨진다.
- 시험이 launch 직후 `store.get(sid)[...]` 로 읽는 값(`modelChoice` 등)은 임시 세션을 직접 읽어 원래 경쟁이 없었고, 합친 뒤 읽어도 이제 값이 남는다.

## 남은 것
- 병합 뒤 PR 검사 ubuntu·windows 확인(`docs/guide/harness-guide.html` 은 동작 설명이 바뀌지 않아 고치지 않았다).
