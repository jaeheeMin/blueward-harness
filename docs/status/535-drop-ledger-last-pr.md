# #535 진행 원장 `마지막 PR` 칸 삭제 (2026-10-29)

`/harness:deliver` 가 PR 마다 고치던 원장 `마지막 PR` 칸 때문에, 같은 DEV 의 PR 이 동시에 열리면 그 줄에서 반드시 충돌했다(public-cloud #374·#422 등). 칸을 지우고 PR 번호를 원장에 적지 않는다.

- 원장 템플릿(`skeleton/templates/harness/audit-ledger.md`)·`audit/README.md`, srs·spec·start 스킬의 원장 줄 예시에서 칸을 뺐다(열이 하나 줄어 `| DEV-xxx | <제목> | 설정 | <담당> | 대기 |`).
- deliver: 9단계에서 PR 번호 예측과, 옛 12단계(예측이 틀리면 원장을 고쳐 다시 푸시)를 없앴다. 상태(리뷰·완료) 갱신은 그대로이고 푸시 전에 한다(#410). 12단계가 빠져 13~15단계가 12~14단계로 한 칸씩 당겨졌고 스킬 안의 단계 참조도 맞췄다.
- 옛 원장(칸이 아직 있는 파일): 엔진은 칸을 읽지 않고(`ledger_complete.py` 는 `상태` 칸만, `pairing`·`ledger_stale` 은 머리 이름으로 칸을 찾는다), deliver 는 옛 칸을 고치지도 지우지도 않는다. 칸 제거는 원장을 따로 정리하는 PR 의 일이다.
- 팀 현황(`checker/pr_team.py`): `dev_items[].last_pr` 대신 `recent_pr` 를 낸다. 열린 PR 은 `pr_queue.compute` 가 이미 정한 `dev`(`_primary_dev`)를, 병합 PR 은 같은 `_primary_dev` 를 쓴다(병합 검색 쿼리에 `headRefName`·`body`·`files` 추가, 호출 수는 그대로). DEV 별로 가장 큰 PR 번호가 최근 PR 이다. `status` 는 `found`(번호·url·열림/병합), `none`(읽은 범위에 없음, `days: 7` 이 조회한 병합 일수 기본값), `unknown`(병합 목록을 못 읽었거나 열린·병합 목록이 잘렸거나, 병합 PR 의 파일 목록이 30개에서 잘려 DEV 를 못 찾았을 때 사유)로 구분하고 "없음" 으로 뭉개지 않는다. 담당 칸이 빈 줄의 담당 추정은 본문 언급을 뺀 근거(제목 끝 번호·브랜치·Spec 파일명)로 DEV 가 정해진 PR 의 작성자만 쓴다(`pr_queue._primary_dev(use_body=False)`, 큐 항목에 `dev_strong` 추가).
- 문구: `ledger-complete.yml`·`main-checks.yml` 의 이슈 안내문, prs 스킬, 길잡이(`docs/guide/harness-guide.html` 작업 올리기 탭)를 고쳤다. 병합 뒤 아티팩트에 다시 올려야 한다.
- 시험: 원장 표를 쓰는 시험 자료에서 칸을 빼고, `test_pr_team.py` 에 최근 PR 찾기(열림·병합·브랜치·본문, 가장 큰 번호), 없음/확인 불능 구분, 옛 원장 칸 무시 시험을 추가했다. Plugin version 0.10.137.
- 남은 일(public-cloud, 별도 PR): 원장 13개 파일과 `templates/harness/audit-ledger.md` 표에서 `마지막 PR` 칸 삭제. 이 저장소의 새 판(0.10.137)이 배포된 뒤에 해도, 먼저 해도 엔진은 둘 다 읽는다.
