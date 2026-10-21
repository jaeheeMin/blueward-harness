# #407 병합 순서의 같은 DEV 연결이 본문에 스친 번호로 묶이던 문제 (2026-10-21)

## 문제

`build_order` 의 "같은 DEV 의 SRS → Spec → 개발" 연결이 `_dev_numbers` 로 소속 DEV 를 구했다. 이 함수는 제목·브랜치·본문에 나온 `DEV-n`·`REQ-n` 을 전부 모은다. public-cloud #208(DEV-005, 본문에 "main 의 REQ-001~004, 006 내용은 그대로" 등)이 DEV-004 의 SRS 단계로 잡혀, 상관없는 DEV-004 Spec PR #211 과 그 뒤 개발 PR 들이 #208 을 기다렸다.

## 결정

- `checker/pr_queue.py` 에 순서 전용 `_order_devs` 추가. 소속 = 제목 끝 `(DEV-xxx, DEV-yyy)` 전부 ∪ 제목·브랜치의 번호 ∪ 바꾼 Spec 파일 번호. 모두 비면 본문에서 처음 나온 번호 하나(`_primary_dev` 의 마지막 fallback 과 같은 규칙).
- `build_order` 의 단계 연결만 `_order_devs` 로 바꿨다. `--json` 의 `devs`(`_dev_numbers`), `_primary_dev`, 줄기 묶기(#390)는 그대로.
- 시험: `test_pr_queue.py` 에 #208 모양, 본문 첫 번호 하나만, `_order_devs` 단위 시험.
- 길잡이 병합 순서 문구에 소속 판정 기준을 반영. plugin.json 0.10.100.

## 알려진 한계

- SRS PR 이 제목·브랜치·Spec 파일에 번호가 없고 본문 첫 번호도 실제 소속이 아니면 여전히 잘못 묶일 수 있다. SRS diff 의 REQ 줄로 소속을 정하는 방법은 구현하지 않았다.
- 제목·브랜치에 다른 DEV 를 스치듯 적은 PR 은 그 번호에도 묶인다.
