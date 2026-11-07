# #687 — DEV 없는 PR 이 판 번호 순서만으로 DEV 줄기에 묶이던 문제

- 원인: `checker/pr_queue.py` `_groups()` 가 번호 없는 PR 묶음이 `after` 이웃으로 닿는 DEV 줄기가 하나면 그 줄기에 넣었는데, `after` 에는 "plugin.json version 이 더 낮음" 관계도 들어 있어 #685(웹 콘솔)가 #680(DEV-008 매뉴얼) 줄기에 들어가 "DEV-008(매뉴얼 …)" 이름 아래 묶였다.
- 고침: `_real_after()` 를 더해 `after_reasons` 에 판 번호 순서 말고 다른 근거(먼저: 줄·base 브랜치·같은 DEV 단계)가 있는 앞 PR 만 DEV 줄기 합류 판단의 이웃으로 센다. 병합 순서 계산(`build_order`·`topo_order`)은 그대로다.
- 판 번호 순서로만 이어진 PR 은 DEV 줄기에 안 들어가고 번호 없는 줄기(또는 단독 칸)가 되며, 순서 칸에는 `(앞: #n)` 꼬리표로 앞 PR 이 보인다.
- 번호 없는 줄기가 실제 관계 없이 판 번호 순서로만 이어져 있으면 이름 끝에 " · 판 번호 순서" 를 붙인다(`_chain_name`).
- 시험: `test_version_order_alone_does_not_pull_unnumbered_pr_into_dev_chain`(#678·#680·#685 재현), `test_real_base_chain_of_unnumbered_prs_stays_one_chain_beside_dev_chain`(base 쌓기 묶음), `test_unnumbered_chain_linked_only_by_version_order_says_so_in_name`. 기존 시험은 바꾸지 않았다.
