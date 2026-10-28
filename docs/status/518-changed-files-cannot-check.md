# #518 바뀐 파일 목록을 못 구하면 전체 파일 검사 대신 검사 불능으로 처리 (2026-10-28)

## 배경

- `pr-checks.yml`·`main-checks.yml` 의 doc-guard 단계는 `git diff ... > changed.txt || git ls-files > changed.txt` 로 바뀐 파일을 구했다.
- diff 가 실패하면(기준 브랜치를 못 받음, 갈라진 지점 없음, main-checks 의 직전 커밋 SHA 가 비거나 없음) 저장소 전체가 "바뀐 파일" 이 됐다. 원래 있던 파일의 위반이 이 PR 탓으로 나오거나, 위반이 없으면 "이번 변경을 확인하지 못했다" 가 "통과" 로 가려졌다(원칙 7 위반). #504 작업 중 발견(`docs/status/504-changed-files-base.md`).

## 결정

- 두 워크플로 모두 `ls-files` 대체를 없앴다. diff 의 stderr 를 `changed-err.txt` 에 받고, 실패하면 `status=unknown`, `reason="바뀐 파일 목록을 구하지 못해 검사하지 못했다. git diff <명령> 오류: <stderr 앞 200자>"` 로 검사기를 부르지 않고 끝낸다.
- 새 표현을 만들지 않았다. 기존 검사 불능 경로(`status=unknown` + `reason`)를 그대로 쓴다: commit status(`doc-guard status 달기`, 140자로 잘림)와 종합 job 요약 표의 사유 칸에 나오고, 로그에도 찍힌다. `has_report` 는 false 라 PR 코멘트는 없다(기존 `render-failed` 경로와 같다).
- main-checks 의 `BEFORE_SHA` 가 비었거나 0 으로만 된 경우(첫 푸시 등): 옛 코드는 `git diff "" HEAD` 가 실패해 전체 파일 검사로 넘어갔다. 이제 같은 검사 불능이다. 근거: 첫 푸시는 "전부 새 파일" 이 맞을 수도 있지만 그렇다고 단정할 근거가 이 단계에 없고, 기본 원칙이 검사 불능을 드러내는 것이다. main 에서 검사 불능이면 기존 "main push 실패를 이슈로 알리기" 가 이슈를 연다. main 에 처음 올리는 저장소는 드물어 알림 비용이 작다.
- 스켈레톤 caller(`plugins/harness/skills/scaffold/skeleton/`)는 재사용 워크플로를 부를 뿐이고 `ls-files`·`BEFORE_SHA` 가 없어 영향 없다.

## 재현 (임시 저장소, 워크플로의 doc-guard 단계 `run` 을 YAML 에서 꺼내 실행, 검사기 `uv` 는 대역)

| 상황 | 결과 |
|---|---|
| PR: 없는 기준 브랜치(`origin/nobranch`) | `status=unknown`, 사유에 `fatal: ambiguous argument 'origin/nobranch...HEAD'`, 검사기 호출 없음 |
| PR: 갈라진 지점 없음(고아 브랜치) | `status=unknown`, `fatal: origin/main...HEAD: no merge base` |
| PR: 정상 | 바뀐 파일 `p.txt` 한 개만 검사, `status=pass` |
| main: BEFORE_SHA 빈 값 / 0 으로만 | `status=unknown`, "비었거나 0 으로만 되어 있다" |
| main: 없는 SHA | `status=unknown`, `fatal: bad object ...` |
| main: 정상 | 바뀐 파일 한 개만 검사, `status=pass` |

## 시험

- `test_pr_checks_workflow.py`·`test_main_checks_workflow.py` 끝에 각 한 건: `ls-files` 없음, stderr 를 받음, 실패 가지가 `status=unknown` 이고 명령·오류를 사유에 담으며 검사기를 부르지 않음, (main) 0 SHA 판정.
- 두 파일 46 통과.

## 남은 일

- 병합 뒤 실제 Project Repository 에서 이 경로가 뜬 적이 있는지(사유 문구가 commit status 140자 안에서 읽히는지) 본다.
- plugin version 0.10.132 (main 0.10.130, #516 이 0.10.131).
