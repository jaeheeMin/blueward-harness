# #508 병합 1번에 뜨는 job 을 4개에서 2개로 줄이기 (2026-10-28)

## 배경

Project Repository(public-cloud) 에서 PR 이 병합되면 job 이 4개 뜬다. `pr-checks`(closed 실행), `main-checks`,
`ledger-complete`, 그리고 public-cloud 가 따로 갖고 있던 `notify-teams-on-merge`. 각 job 은 1분 단위로 깎인다.

10-25 ~ 10-27 사흘 실측: 합계 178분, 그중 notify 10분, ledger-complete 10분. 또 `main-checks` 의 pr-queue 단계는
매번 `Resource not accessible` 로 실패했다. 같은 계산(병합 순서·차례 알림)을 PR 이 닫힐 때 도는 `pr-checks` 의
pr-queue 단계가 이미 하고 있어서, main-checks 쪽은 중복이면서 실패만 남기고 있었다.

## 결정

| 대상 | 결정 | 이유 |
|---|---|---|
| `main-checks` 의 pr-queue 단계 | 뺀다 | `pr-checks` 의 pr-queue 는 `closed` 에서도 돌아 병합으로 앞이 빈 PR 의 차례 알림까지 한다. main-checks 쪽은 중복이고 권한 부족으로 매번 실패 |
| ledger-complete | `main-checks` 의 단계로 옮긴다. 입력 `ledger-complete`(boolean, 기본 false) | 따로 `ledger-complete.yml` 을 부르는 caller 가 아직 있어, 기본을 켜 두면 이슈가 두 번 열린다. 켜는 쪽이 caller 에 `with: ledger-complete: true` 를 준다 |
| 병합 Teams 알림 | `pr-checks` 의 단계로 옮긴다. 선택 secret `TEAMS_MERGE_WEBHOOK_URL` | 병합된 PR 의 `closed` 실행이 어차피 돈다. 기본 브랜치로 병합된 경우에만, secret 이 있을 때만 보낸다 |

- ledger-complete 단계는 `ledger-complete.yml` 의 판정을 그대로 옮겼다. 종료 0(ok·skipped)은 pass, 1 은 fail, 2 와
  그 밖은 unknown(검사 불능)이다. fail·unknown 이면 같은 제목(`ledger-complete: 진행 원장이 완료로 표시돼 있지 않다`)
  의 이슈를 열거나 코멘트를 달고, 종합 단계가 `::error` 와 함께 job 을 실패시킨다. 이슈를 열지 못해도 실패다.
  `ledger-complete.yml` 파일 자체는 그대로 둔다.
- 병합 알림 실패는 종합에서 판정에 넣지 않고 `::warning` 과 요약으로 남긴다(조용한 초록이 아니다). 이미 병합된 PR 의
  `pr-checks / check` 를 붉게 만들어도 되돌릴 것이 없고, 알림은 검사가 아니기 때문이다. secret 이 비어 있으면
  `::notice` 로 건너뛴다. public-cloud 의 옛 단계는 secret 이 없으면 실패했는데, 선택 secret 이라 건너뛰는 쪽이 맞다.
- `main-checks` 는 `TEAMS_PLUGIN_ALERT_WEBHOOK` secret 선언을 남긴다. 선언 없는 secret 을 넘기는 caller 는 오류가
  나기 때문이다(받기만 하고 쓰지 않는다).
- 안내 문구 정정: pr-queue 의 "GitHub 를 못 읽으면 job 이 실패 / merge-order status 가 error" 는 사실과 달랐다.
  실제로는 종료코드 2 로 status 를 쓰기 전에 끝나 이전 status 가 그대로 남고, `continue-on-error` 라 job 은 초록이며
  경고만 남는다. `pr-checks.yml`·`pr-review.yml`·`plugins/harness/README.md`·길잡이를 고쳤다(main-checks 쪽 문구는 단계와 함께 사라졌다).
- 스캐폴드: `main-checks.yml` caller 에 `with: ledger-complete: true`, `ledger-complete.yml` caller 는 skeleton 에서 지웠다.
  `pr-checks.yml` caller 에는 병합 알림을 켜는 한 줄을 주석으로 안내한다.

한계: 포크·Dependabot 이 일으킨 closed 이벤트는 토큰이 읽기 전용이라 pr-queue 가 쓰지 못하는데, 예전에는 main push
실행이 그 빈틈을 메웠다. 이제는 다음 PR 이벤트가 바로잡는다. main 에 PR 없이 직접 들어온 커밋도 순서를 다시 계산하지 않는다.

## public-cloud 이전 절차 (이 PR 이 병합돼 `stable` 이 새로 붙은 뒤)

`stable` 이 새 판을 가리키기 전에 caller 에 `with:` 를 넣으면 "입력을 모른다" 오류가 나므로 순서가 중요하다.

1. 이 PR 병합 → Actions 가 `v0.10.128` 과 `stable` 을 붙인 것을 확인.
2. public-cloud 에서 한 PR 로:
   - `.github/workflows/main-checks.yml` caller 에 `with: ledger-complete: true` 추가.
   - `.github/workflows/pr-checks.yml` caller 의 `secrets:` 에 `TEAMS_MERGE_WEBHOOK_URL: ${{ secrets.TEAMS_WEBHOOK_URL }}` 추가.
   - `.github/workflows/ledger-complete.yml` 삭제.
   - `.github/workflows/notify-teams-on-merge.yml` 삭제.

```diff
 # main-checks.yml
   main-checks:
     uses: jaeheeMin/blueward-harness/.github/workflows/main-checks.yml@stable
+    with:
+      ledger-complete: true
     secrets:
 # pr-checks.yml
     secrets:
       TEAMS_PLUGIN_ALERT_WEBHOOK: ${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}
+      TEAMS_MERGE_WEBHOOK_URL: ${{ secrets.TEAMS_WEBHOOK_URL }}
```

## 배포 뒤 확인

- 병합 1번에 뜨는 job 이 `pr-checks`(closed) + `main-checks` 둘뿐인지.
- `main-checks` 요약 표에 `ledger-complete` 행이 있고(`통과` 또는 대상 PR 이 없으면 통과), pr-queue 경고가 사라졌는지.
- 병합 시 `pr-checks` closed 실행에서 `PR 병합 Teams 알림` 단계가 돌고 Teams 에 카드가 오는지. 병합이 아닌 close, 기본
  브랜치가 아닌 base 로 병합된 경우에는 단계가 건너뛰어지는지.
- 원장이 `완료` 가 아닌 대표 이슈 PR 을 병합했을 때 이슈가 열리고 job 이 실패하는지(실제 사고 때까지 기다려도 되고,
  처음 한 번만 확인해도 된다).
- main-checks 소요가 22~52초 범위에서 크게 늘지 않았는지(단계 추가는 엔진 호출 한 번과 gh 호출 몇 번이다).

## 범위 밖(남김)

- 시험은 워크플로 구조만 본다. 실제 Actions 실행(`ledger-complete` 단계·Teams 전송)은 병합 뒤 public-cloud 에서 확인해야 한다.
- `ledger-complete.yml` 은 이 PR 에서 지우지 않는다. 다른 caller 가 쓸 수 있다.
