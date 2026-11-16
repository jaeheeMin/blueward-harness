# #1005 기존 Spec 수정 PR 에 새 그림이 있으면 승인을 요구하는 문제 (2026-11-16)

## 배경
결정(#736)은 "새 Spec 만 승인 대상, 이미 있는 Spec 의 수정은 어떤 수정이든 승인 대상 아님" 이다. 그런데 risk-gate 는 `docs/spec/`
아래 새로 생긴(added) 파일이면 Spec 문서든 그림이든 위험 경로로 셌다. spec 스킬은 캡처를 `docs/spec/img/<이름>_v<판>.png` 로
판마다 새 파일로 남기므로, 캡처가 있는 Spec 을 고칠 때마다 승인 대상이 됐다. 팀원 PR 에서 `_v0.5.png` 두 장 때문에 승인이
걸렸고, 그 세션의 AI 는 그림을 빼고 `_v0.4` 로 되돌리라고 권했다(사용자가 그 PR 은 승인으로 넘김).

## 한 것
| 파일 | 내용 |
|---|---|
| `checker/risk_gate.py` | `_is_spec_image` — `docs/spec/` 아래 그림(.png·.jpg·.jpeg·.gif·.svg·.webp, 대소문자 무시)은 status 와 상관없이 위험 경로로 세지 않는다 |
| `checker/tests/test_risk_gate.py` | 기존 Spec 수정 + 새 그림 → 승인 불필요, 그림만(상태 없음) → 승인 불필요, 새 Spec + 그림 → Spec 문서로만 위험, Spec 폴더의 그림 아닌 새 파일 → 위험 |
| `plugins/harness/rules/governance.md`, `skills/spec/SKILL.md`, scaffold `risk-gate.yaml` 주석 | 그림 제외를 적고, spec 스킬엔 "그림을 빼거나 옛 판으로 되돌려 승인을 피하라고 권하지 않는다" |
| `docs/guide/harness-guide.html` | Spec 승인 안내 두 곳에 그림 제외 |
| `plugin.json`, `console/whats_new.json` | 0.10.297 → 0.10.299(0.10.298 은 #1002) |

## 판단
- 그림만 새로 추가한 PR(Spec 문서 변경 없음)도 승인 대상이 아니다. 그림은 Spec 문서가 참조할 때만 의미가 있고, 새 Spec 은
  문서가 새로 생기므로 그쪽에서 걸린다.
- 그림 판정은 확장자로 한다. 상태를 모르는 그림도 세지 않는다 — 새 Spec 인지 여부는 그림이 아니라 문서로 가리므로 원칙 7(검사
  불능을 통과로 뭉개지 않기)과 부딪치지 않는다. Spec 폴더의 그림 아닌 새 파일은 그대로 센다.

## 남은 일
- 병합 뒤 길잡이 아티팩트 재게시(`docs/guide/README.md`).
