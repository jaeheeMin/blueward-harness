# #448 ATC 시험 피드백과 settings.json 키 순서 (2026-10-25)

## 배경

080 에서 `/harness:atc` 를 시험해 얻은 보완과, `claude plugin install --scope project` 가 `.claude/settings.json` 의 키 순서만 바꿔 저장해 Stop 훅이 deliver 를 요구한 문제.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `skills/atc/SKILL.md` | 세션 만료 "400 또는 401". 3단계 분류를 4단계로(**지적 부적절(근거 승인 대기)** 추가, 승인 시 5단계로). CVA·Message Class 분류 예시. `atcWorklists` 결과는 필요한 필드만 뽑아 요약 |
| `docs/guide/harness-guide.html` | "ATC 돌리기" 탭을 위에 맞춤. 레일 판 표기 0.10.112 |
| `hooks/json_same_as_head.py` (신규) | 작업 트리 JSON 과 HEAD 판을 파싱해 값이 같은지 판정(종료 코드 0 = 같음). HEAD 에 없음·파싱 실패·git 실패는 1 |
| `hooks/stop-deliver.sh`, `hooks/session-start-sync.sh` | `.claude/settings.json` 이 값은 같고 순서·공백만 다르면 미커밋으로 세지 않음. 같은 helper 공유 |
| `skills/update/SKILL.md` | install 이 키 순서만 바꿀 수 있고 내용이 같으면 그대로 둬도 된다는 안내 |
| `checker/tests/test_settings_order_only.py` | 순서만 바뀜 / 값 바뀜 / 파싱 불가 / 새 파일 / 다른 변경과 함께 |

## 결정

- 훅이 파일을 되돌리지 않는다(사용자 파일을 훅이 고치지 않음). 세지 않을 뿐이다.
- 판정을 못 하면(uv 없음, 파싱 실패 등) 보통 변경으로 센다 — "검사를 못 했다" 를 "같다" 로 뭉개지 않는다.
- 해당 경로의 수정(`.M`, `M.`, `MM`)일 때만 helper 를 부르므로 평소 Stop 훅의 프로세스 수는 그대로다.
- 다른 변경이 함께 있어 사본(snapshot)을 뜰 때는 settings.json 도 사본에 들어간다(해롭지 않음).
