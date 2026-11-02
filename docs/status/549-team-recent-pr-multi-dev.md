# #549 팀 현황의 최근 PR 이 여러 개발 건을 고친 PR 을 첫 건에만 붙이던 문제 (2026-11-02)

**배경.** public-cloud#350 `fix: 실적 업로드 앱 대기(Q) 고착과 화면 미갱신 수정 (DEV-006·007·009)` 이 DEV-006 에만 붙어 DEV-009 가 "최근 7일 PR 없음" 으로 나왔다. 원인은 둘이다. (1) `pr_team.compute_team` 의 `recent` 가 PR 하나를 `_primary_dev`(개발 건 하나)에만 붙였다. (2) `pr_queue._TITLE_END_DEV` 가 뒤 번호에 `DEV-` 가 없는 줄임 표기(`DEV-006·007·009`, `DEV-006/007`, `DEV-006, 007`)를 못 읽어 `_title_end_devs` 가 None 이었다(제목 끝 괄호를 통째로 무시).

**결정.**
- `_TITLE_END_DEV`: 첫 번호만 `DEV-`/`REQ-` 로 시작해야 하고, 뒤 번호는 접두를 생략해도 읽는다. 전은 `(?:DEV|REQ)-0*\d+(?:\s*[,/·]\s*(?:DEV|REQ)-0*\d+)*`, 후는 뒤 반복의 접두를 `(?:(?:DEV|REQ)-)?` 로 선택으로 바꿨다. 번호 추출은 `_DEV_REF`(접두 필수)를 쓸 수 없어 `_END_NUMBER` 를 새로 두었다. `(2026)`·`(006·007)`·`(2026, DEV-006)` 처럼 첫 번호가 DEV/REQ 가 아닌 괄호는 잡지 않는다.
- 최근 PR(`recent`)은 PR 이 속한 개발 건 전부에 붙인다. 근거는 `pr_queue._order_devs(raw)`(제목 끝 번호 전부·제목/브랜치 번호·바꾼 Spec 파일, 모두 비면 본문 첫 번호 하나). 본문에 스쳐 간 번호로는 붙이지 않는다. 열린 PR 항목과 `read_merged` 결과에 `dev_all`(정렬된 번호 목록)을 더했고 `note` 가 이를 돈다.
- 담당 추정(`recent_strong`)은 지금처럼 `dev_strong` 하나(첫 번호)만 쓴다. 여러 개발 건을 고친 PR 의 작성자를 다른 개발 건의 담당으로까지 넓게 추정하지 않는다(#549 결정).

**기존 동작이 바뀐 곳.**
- `_title_end_devs` 를 쓰는 `_order_devs`·`_primary_dev`·`_dev_of`·`_chain_name` 은 줄임 표기 제목에서 이제 괄호를 읽는다. 첫 번호는 그대로 줄기 번호(`_primary_dev` = 6)이고, 순서 계산(`_order_devs`)은 {6,7,9} 로 넓어진다. 괄호가 이름에서 빠진다(`_chain_name` 의 `without_end`).
- `pr_queue --json` 의 PR 항목에 키 `dev_all` 이 늘었다(`test_json_and_pr_outputs_unchanged_by_render_change` 의 기대 키 집합에 추가).

**시험.** `test_pr_queue.py`: `test_title_end_devs_reads_shortened_numbers_after_the_first`(줄임 표기 `·` `/` `, `, 첫 번호가 DEV 가 아닌 괄호 무시, `_primary_dev`=6·`_order_devs`={6,7,9}). `test_pr_team.py`: `test_pr_with_several_devs_is_recent_pr_of_each_but_owner_guess_uses_first_only`(병합·열린 PR 모두 각 DEV 의 최근 PR 로 found, 담당 추정은 첫 번호만). `uv run pytest checker/tests/test_pr_team.py checker/tests/test_pr_queue.py -q` 170 통과. 전체 checker/tests 는 로컬 메모리 부족으로 돌리지 않았다.

**한계.** 본문에만 번호가 적힌 PR 은 여전히 첫 번호 하나만 잡는다. 줄임 표기는 제목 끝 괄호만 읽는다(제목 중간의 `DEV-006·007` 은 첫 번호만 `_DEV_REF` 로 잡힌다). 길잡이(`docs/guide/harness-guide.html`)에 이 동작을 적은 곳이 있는지는 확인하지 않았다. Plugin version: 열린 PR #593 이 0.10.152 를 써서 0.10.153.
