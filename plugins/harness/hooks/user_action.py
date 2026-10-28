"""사람이 직접 해야 하는 일을 알리는 공통 표시(#505).

훅 메시지 중 사람만 할 수 있는 일(플러그인 갱신과 `/reload-plugins`, 도구 설치, Claude Code 재시작,
표식 파일 정리, GitHub 에서 사람이 병합·승인)에만 붙인다. Claude 가 스스로 할 수 있는 일(다시 시도,
deliver 실행 등)에는 붙이지 않는다. 셸 훅·hooks.json·checker 의 문구는 같은 문자열을 글자 그대로
적는다(시험이 어긋남을 잡는다).
"""
from __future__ import annotations

USER_ACTION = "🚨 직접 해 주세요:"
