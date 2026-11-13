# #930 PR 병합 Teams 알림 카드 제목에 PR 작성자 표시

## 배경

`pr-checks.yml` 의 `merge-notify` 단계(#508)가 보내는 Adaptive Card 맨 위에 Teams Workflow 를 만든 사람
이름("워크플로(주체: …)")이 붙는다. Teams 쪽에서 바꿀 수 없어, 모든 병합 알림이 그 사람 PR 처럼 보였다.
작성자는 카드 안 작은 "작성자" 칸에만 있었다. public-cloud 담당 세션이 사용자 결정으로 요청했다.

## 바꾼 것

- 카드 제목 `PR이 main에 병합되었습니다` → `($author + " 의 PR 이 병합됐습니다")`(GitHub 아이디 그대로, 실명 매핑 없음),
  긴 아이디를 위해 `wrap: true`.
- 제목에 작성자가 들어가 `FactSet`(작성자 칸)을 뺐다. PR 제목 줄·[PR 보기] 버튼은 그대로.
- `checker/tests/test_pr_checks_workflow.py` 기대값 갱신(새 제목 식, "작성자" 칸 없음).
- plugin.json 0.10.277(0.10.275·276 은 #840·#836 예약), whats_new.json, 길잡이 레일 표기.
- 길잡이 본문은 카드 문구를 적지 않아 그대로 뒀다.

## 확인

- 워크플로에서 jq 식을 뽑아 따옴표 든 PR 제목으로 돌려 JSON 을 확인했다: 제목 `erpsarang 의 PR 이 병합됐습니다`,
  둘째 줄 `fix: "따옴표" 제목 (#9)`, 버튼 그대로.
- 실제 Teams 표시는 병합 뒤 public-cloud(`@stable`) 다음 병합 알림에서 본다.
