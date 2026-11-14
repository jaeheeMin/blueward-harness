# #974 SRS 고치기와 고객에게 주기(산출) 분리 (0.10.292)

## 배경
public-cloud 에서 SRS 를 여럿이 동시에 고치면 `버전:` 줄과 같은 이름 Backlog 엑셀이 부딪혀 PR 이 계속 충돌했다. SRS 를 고치기(내용 PR)와 고객에게 주기(산출 PR)로 나누고, 규칙은 문서가 아니라 PR 검사로 강제한다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/skills/srs/SKILL.md` | 만들기·고치기·사후 등록에서 `버전:` 올림·엑셀 산출을 뺌. "고객에게 주기 — 산출 모드"(백로그 뽑아 줘)와 "미리보기" 절 추가 |
| `checker/export.py` | `--out <.xlsx>` 미리보기 경로. 저장소 안이면 거부, 판 이름·패턴·main 판 거부를 건너뛰고 덮어씀. 기존 동작은 그대로 |
| `checker/srs_split.py` (새) | diff·추가 파일 목록으로 `mixed`·`bump`·`orphan_xlsx` 판정, 못 읽으면 검사 불능 |
| `scripts/check_changed.py`, `scripts/render_report.py`, `checker/cross_switches.py` | 리포트 키 `srs_split`, 코멘트 절, 스위치 `SRS_분리`, exit2 원인 |
| `checker/version_overlap.py` | 주석만: 이제 산출 PR 끼리의 판 겹침 경고 |
| `plugins/harness/workflow.json` | 새 갈래 `srs-export`(고객에게 줄 백로그 뽑기), srs 갈래 설명에서 엑셀 문구 제거 |
| 길잡이·README·skeleton `rules/README.md`·`switches.yaml` | 설명 맞춤 |

## 결정
- **새 SRS 의 첫 엑셀은 산출 모드로 낸다.** 만들기는 틀의 `버전: 0.1` 줄을 그대로 두고 엑셀을 내지 않는다. 첫 엑셀은 0.1 + 0.1 = `v0.2`(v0.1 엑셀은 없다). 만들기에서 같이 내면 첫 PR 이 `버전:` 줄+엑셀+내용을 함께 담아 산출 PR 규칙과 섞인다.
- 새 SRS 를 만드는 PR(base 에 SRS.md 없음)은 `mixed`·`bump` 대상이 아니다(`버전:` 줄이 새로 생기는 것이라 분리할 수 없다). 엑셀을 같이 넣으면 `orphan_xlsx` 가 판을 맞춰 본다.
- 스위치 `SRS_분리` 를 다른 교차 검사처럼 둔다. 파일에 없으면 켠다.
- Backlog 엑셀은 양식 지도(`원본: SRS` 표의 `산출.폴더`·`산출.파일명`, 자리 `버전: {메타: 버전}`)로 알아본다. 그런 지도가 없는 저장소는 엑셀 짝을 따지지 않는다.
- 재사용 워크플로는 `DOC_GUARD_DIFF_FILE`·`DOC_GUARD_ADDED_FILES` 를 PR 이벤트에서 조건 없이 넘기므로 워크플로는 고치지 않았다(시험이 확인).
- 산출 기록의 종류는 템플릿의 기존 값 "기타" 를 쓴다(템플릿은 안 고침).

## 남은 일
- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
- 산출 PR 이 `audit/changes/` 산출 기록을 갖췄는지는 검사하지 않는다(스킬 약속).
