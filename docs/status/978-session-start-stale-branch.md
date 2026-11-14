# #978 세션 시작 훅이 병합된 브랜치·앞선 로컬 main 을 최신으로 잘못 알리는 문제 (0.10.296)

## 배경
`session-start-sync.sh` 를 임시 저장소에서 돌려 확인한 두 버그.
1. 원격 브랜치가 지워진(`[gone]`) 브랜치에서 "이미 최신 상태입니다" 라 하고 origin/main 을 병합 커밋으로 합쳤다.
2. 로컬 main 이 origin/main 보다 앞서도 "이미 최신 상태입니다" 라 했다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/hooks/session-start-sync.sh` | `[gone]` 이면 합치지 않고 `report_gone_branch`: gh(`pr list --head <브랜치> --state merged`)로 병합 PR 번호를 찾아 "끝난 작업(PR #n 병합됨)" 안내. 병합된 PR 이 없으면 그대로 알림, gh 실패·없음은 "검사 불능". 로컬 main 이 `origin/main`(upstream 있으면 그것)보다 앞서면 최신이라 하지 않고 앞선 커밋 수·뒤처진 수와 섞임 경고, 자동 리베이스·reset 안 함 |
| `checker/tests/test_plugin_layout.py` | gone+병합됨, gone+gh 실패, gone+병합 PR 없음, 정상 추적 브랜치(gh 안 부름), 로컬 main 앞섬, 로컬 main 같음. 가짜 gh 를 PATH 앞에 끼움 |
| `docs/guide/harness-guide.html` | 설치 탭 "세션을 열 때마다 자동으로" 에 한 줄(병합 뒤 아티팩트에 다시 올린다) |
| `plugins/harness/console/whats_new.json` | 0.10.296 |
| `plugins/harness/.claude-plugin/plugin.json` | 0.10.296 |

## 결정
- 브랜치를 지우거나 옮기지 않고 안내만 한다.
- gone 인데 병합된 PR 이 없으면(gh 는 성공) "끝난 작업" 이라 하지 않고 따로 알린다. 닫힌 PR 이나 원격에서 직접 지운 브랜치일 수 있다.
- 로컬 main 이 앞서 있으면 behind 가 있어도 리베이스하지 않는다(앞선 커밋을 사람이 보기 전에 건드리지 않는다).
- 앞섬 검사는 현재 브랜치가 main 일 때만 한다. 작업 브랜치는 원격보다 앞서는 것이 정상이다.
