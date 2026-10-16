# #346 병합 뒤 진행 원장 완료 표시 자동화 (2026-10-16)

## 왜

2026-09-28 에 "원장 `완료` 는 손으로" 로 정했다(자동화 안 함). 그 뒤 원장 등록(#173 등)이 시작되자 손으로 바꾸는 것이 문제가 됐다. main 직접 커밋이 금지라 `완료` 한 줄을 바꾸려고 PR 이 하나 더 생긴다. 그래서 결정을 바꿔, 병합될 때 Actions 가 main 에 직접 커밋한다. 추가 PR 은 만들지 않는다.

## 동작

- 새 재사용 워크플로 `.github/workflows/ledger-complete.yml` 이 Project Repository 의 main push 마다 `scripts/ledger_complete.py apply --repo --sha --root` 를 부른다(엔진 `checker/ledger_complete.py`).
- `commits/{sha}/pulls` 에서 병합된 PR 을 고르고, 본문의 `Closes|Fixes|Resolves #N` 이슈 중 제목이 `[DEV-xxx]` 로 시작하는 대표 이슈만 대상이다. 하위 작업(`... (DEV-xxx)`)·DEV 번호 없는 이슈는 대상이 아니다.
- 원장 파일은 대표 이슈 본문의 `진행 원장: DEV-xxx (audit/ledger/<파일>.md)` 줄이 있으면 그 파일, 없으면 `audit/ledger/*.md` 전부에서 찾는다. 행은 정확히 하나여야 한다. 상태 칸을 `완료`, 마지막 PR 칸을 `#<PR>` 로 바꾼다(다른 칸·다른 줄·줄 끝 문자 보존).
- 종료 0: 바꿨음 / 이미 완료 / 병합 PR 없음 / 완료 대상 아님 / `audit/ledger` 없음. 종료 2(판정 불능, 파일은 아무것도 안 씀): gh 실패, 원장 파일은 있는데 ID 행이 없음·둘 이상, 표 형식을 못 읽음, 이슈 본문이 가리킨 파일이 없음. 위반(1)은 없다.
- 워크플로: job `if` 가드는 없고, 엔진이 처리 대상 커밋 중 제목이 정확히 `docs: 진행 원장 완료 표시` 인 것(이 워크플로의 커밋)을 건너뛴다. 실패 처리 단계는 `always() && outcome != 'done'` 이고 `reason.txt` 가 없어도 이슈·에러가 나온다. 재시도 루프는 `scripts/ledger_complete_loop.sh` 에 있다(시험이 임시 git 저장소에서 실제로 돌린다). 최대 5번(사이에 1~5초 랜덤 대기) `fetch + reset --hard origin/main` → `apply` → 커밋(`docs: 진행 원장 완료 표시`, 본문 `Refs #a, #b` 처리한 PR 들) → `git push origin HEAD:main`. 판정 불능(종료 2)이면 되풀이하지 않고 멈춘다. apply 가 종료 0 인데 출력 JSON 의 `status` 를 못 읽으면(빈 출력) "바꿀 것 없음" 이 아니라 실패다. 못 하면 job 실패 + 이슈 "ledger-complete: 진행 원장 완료 표시를 못 했다"(같은 제목 열린 이슈는 `--limit 500` 으로 찾아 코멘트만).
- `concurrency` 를 쓰지 않는다. 대기 중인 실행은 새 실행이 오면 조용히 취소돼, 연달아 병합하면 그 병합의 완료 표시가 빠진다. 대신 push 가 밀리면 다음 시도가 새 main 위에서 다시 계산한다. 한 push 에 커밋이 여럿일 수 있어 `apply` 는 `--sha` 를 여러 번 받는다. 워크플로는 `github.event.before` 가 0 이 아니고 히스토리에 있으면 `before..sha` 전체를(오래된 것부터), 아니면 `github.sha` 하나를 넘긴다. 각 커밋의 병합 PR(`merged_at` 있고 base 가 main)을 모두 처리하고 같은 DEV 가 여러 번이면 마지막 PR 기준이다.
- 판정 세부: 이슈 본문에 원장 파일 지정이 없을 때 `## 개발 건` 절이 아예 없는 `audit/ledger/*.md` 는 건너뛴다. 절은 있는데 표가 깨졌으면(`ID` 머리 없음, `상태`·`마지막 PR` 열 없음) 판정 불능이고, 어느 파일에서도 행을 못 찾아도 판정 불능이다. `Closes` 는 코드 펜스·인라인 코드·HTML 주석·인용 줄을 걷어낸 뒤 읽는다. 칸 안의 `\|` 는 칸 경계가 아니다. BOM·줄 끝 문자는 보존한다.
- scaffold 에 caller `ledger-complete.yml` 추가(`@stable`, contents: write, pull-requests: read, issues: write). `release-tag.yml` paths 에 재사용 워크플로로 추가. 시험 기대 목록·SKILL.md 파일 목록 갱신.
- 표 파싱은 `checker/pairing.py` 를 재사용하려고 `section_span`·`table_indexed` 를 공개 이름으로 뺐다(`_section`·`_table` 은 그 위에서 그대로 동작).
- 문서 문구("완료는 사람이") 고침: deliver·start·srs SKILL, plugins/harness/README.md, audit-ledger 템플릿, audit/README.md, 길잡이(`docs/guide/harness-guide.html` 의 설정 행, 병합 흐름 노드, 병합 뒤 할 일, 한눈에 목록, 검사 표에 `ledger-complete` 행). 루트 README 의 재사용 워크플로 목록에도 추가.
- Plugin version 0.10.78 → 0.10.79.

- 2차 검토 반영: `commits/{sha}/pulls` 가 비면 `git log -1 --format=%s` 로 읽은 제목 끝의 `(#N)` 으로 `pulls/N` 을 직접 조회(병합됐고 base 가 main 일 때만, 조회 실패는 검사 불능, 제목을 못 읽어도 검사 불능). `Closes` 전처리는 HTML 주석을 먼저 지우고 펜스·4칸(탭) 들여쓴 줄·인라인 코드·인용 줄을 걷는다. push 실패는 `non-fast-forward`·`fetch first`·`[rejected]` 일 때만 재시도하고 권한·훅 거부(`remote rejected`)는 즉시 실패한다. 404 이슈가 하나라도 있으면 전체가 검사 불능인 것은 원칙 7 에 맞아 그대로 둔다.
- 수용한 한계: 같은 DEV 를 서로 다른 PR 이 거의 동시에 닫으면 마지막 PR 칸의 순서가 뒤집힐 수 있다.

## 범위 밖

- 하위 작업 PR 만 있는 DEV 의 완료 판정(어느 PR 이 마지막인지 모른다). 그 경우 사람이 바꾼다.
- 유료 요금제로 main 을 브랜치 보호로 잠그면 이 job 의 push 만 예외로 열어야 한다.
- 병합 뒤 길잡이 아티팩트 재게시(`docs/guide/README.md`).

## 시험

- `checker/tests/test_ledger_complete.py`(엔진 동작·판정 불능·보존·여러 커밋·PR 선별·본문 파싱, 워크플로·caller 구조)와 `test_ledger_complete_loop.py`(재시도 루프를 가짜 apply·가짜 bare 원격으로 실행: push 충돌 1회 후 성공, 시도 소진 시 실패, 종료 2 시 실패, 빈 출력 시 실패, before 범위). 두 파일 46개 통과.
- 관련 시험 `test_scaffold.py`·`test_pairing.py`·`test_engine_pin.py`·`test_plugin_version.py`: 163 passed, 4 skipped.
- 전체 `uv run pytest checker/tests -q`: 1981 passed, 13 skipped, 2 xfailed (34분 36초).
- 시험 중 잡은 것: `read_text` 가 CRLF 를 LF 로 바꿔 CRLF 원장의 줄 끝이 사라지던 것 → `newline=""` 로 읽고 씀.

## 확인하지 못한 것

- 실제 GitHub Actions 에서 돌려 보지 못했다(워크플로 YAML 은 구조 시험, 루프 셸은 로컬 git 에서만). 특히 `GITHUB_TOKEN` push 의 실제 동작(브랜치 보호가 없어야 한다), 재사용 워크플로 안 job `if: github.event.head_commit...` 평가, `github.event.before` 값이 재사용 워크플로에 caller 이벤트 그대로 오는지.
- 루프 시험은 Windows git bash 에서 돌렸고 ubuntu 러너에서는 돌려 보지 못했다. bash·jq·git 이 없으면 건너뛴다.
- force push 등으로 `before` 가 히스토리에서 사라졌으면 SHA 하나만 처리한다(앞선 커밋의 병합 PR 은 못 본다).
