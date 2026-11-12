# #911 계획 파일 자동 허용: plans 링크 대상이 설정 폴더 안인지까지 확인 (0.10.272)

## 배경

#909(#878)의 남은 낮은 위험(558 세션 리뷰): `<설정 폴더>/plans` 를 작업 폴더 밖 **다른 저장소의 `plans/`** 로 미리 링크해 두면, 그 폴더 바로 아래 `.md`(보호 이름 제외) 쓰기가 계획 파일로 묻지 않고 허용됐다.

## 바꾼 것

- `console/risk.py` `_is_plan_file`: 링크 대상(`realpath(plans)`)의 부모가 원래 설정 폴더(링크가 아닌 경우의 그 폴더)이거나 이름이 `.claude` 인 폴더일 때만 계획 폴더로 본다. Orca 프로필(`<프로필 home>/plans` → `~/.claude/plans`)은 부모가 `.claude` 라 그대로 되고, 링크가 아닌 plans 는 설정 폴더 이름(예: Orca 의 `home`)과 상관없이 된다.
- 시험 `test_risk_plan_dir_link_is_allowed_only_to_another_plans_outside_work` 에 다른 저장소 plans 로 가는 링크(`notes.md`·`wise-fox.md` 안 safe)와 링크 아닌 `profile/home/plans`(safe) 를 더함. 고치기 전 코드로 실패 확인.
- 이 PC 의 실제 링크된 plans 에서 `x-plan.md` 가 그대로 safe 인 것 확인.
- `docs/design/web-console.md`, 길잡이 레일 판. whats_new 는 팀원이 몰라도 되는 보안 조임이라 적지 않음. 0.10.271 은 #914 예약.
