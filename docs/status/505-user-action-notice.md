# #505 사람이 직접 해야 하는 훅 알림을 화면에 바로 띄우고 🚨 표시 붙이기 (2026-10-28)

업데이트 알림 등이 `additionalContext` 로 Claude 에게만 가서 답 속에 묻히고, 거절 메시지의 "사람이 할 일 - …" 도
문장 끝이라 눈에 띄지 않는다는 피드백.

- 공통 표시 `🚨 직접 해 주세요:` — 파이썬 훅은 `plugins/harness/hooks/user_action.py` 의 `USER_ACTION`,
  셸 훅·hooks.json·checker 는 같은 문자열을 글자 그대로 적는다. 사람만 할 수 있는 일에만 붙인다.
- `update_notice.py` 가 `additionalContext` 는 그대로 두고 최상위 `systemMessage`(표시로 시작, 한두 줄)도 낸다.
  "세션당 한 번" 억제는 그대로라 systemMessage 도 한 번만 뜬다.
- 거절·안내 메시지의 "사람이 할 일 - / —" 를 "🚨 직접 해 주세요:" 로, 괄호 꼬리 "(사람이 할 일)" 는
  "(🚨 직접 해 주세요)" 로 맞췄다. 의미는 그대로. 단언하던 시험도 같이 고쳤다.
- `rules/governance.md` 에 Claude 가 사람이 할 일을 답 맨 앞에 🚨 표시로 따로 적는 규칙을 넣었다. 길잡이 "막혔을 때" 탭에 한 줄.

범위 밖(남김): `session-start-sync.sh`·`stop-deliver.sh`·`pre-bash-git-guard.sh` 의 거절은 평문 출력이거나
Claude 용 사유라 systemMessage 를 붙이지 않았다. `.github/workflows/ai-review.yml` 의 "다음: 사람이 할 일 - …"
는 워크플로 로그 문구라 손대지 않았다.
