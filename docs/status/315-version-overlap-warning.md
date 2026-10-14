## 열린 PR 끼리 문서 판 번호가 겹치면 PR 에서 미리 경고(#315, 2026-10-14)

public-cloud 에서 PR #200(REQ-003)과 PR #205(REQ-004)가 둘 다 main 의 SRS `버전: 0.2` 에서 출발해 각자 `버전: 0.3` 과 `BW_Backlog List_v0.3.xlsx` 를 만들었다. REQ 번호는 번호 찜이 막았지만 판 번호는 병합 뒤에야 알 수 있었다(#234: export 는 origin/main 에 같은 판이 있으면 거부하므로 main 이 깨지지는 않는다). doc-guard 가 PR 을 볼 때 다른 열린 PR 과 판 번호가 같으면 코멘트에 **경고**한다. 막지 않는다(통과 유지).

**판정**(`checker/version_overlap.py`, 네트워크 없음): (a) 이 PR 이 **추가**(added·renamed)한 `_v<판>.(xlsx|docx|pptx)` 파일(`templates/` 제외)의 경로가 다른 열린 PR 의 추가 파일과 같음, (b) 이 PR 이 `docs/ssot/SRS.md` 의 `버전:` 을 base 와 다른 값으로 바꿨는데 다른 열린 PR 도 같은 값으로 바꿈. 이미 있던 산출 파일을 고친 것, SRS 를 고쳤으나 버전이 그대로인 것, 자기 PR 은 제외한다. 메시지: "이 판 번호(v0.3)를 열린 PR #200(제목) 도 씁니다 … 먼저 병합되는 쪽이 v0.3 을 갖고, 다른 쪽은 sync 뒤 0.4 로 다시 산출해야 합니다." 산출 파일 이름 규칙은 양식 지도에 따로 없고 파일명 끝의 `_v<판>` 이라 그 모양만 본다.

**열린 PR 읽기**(`scripts/fetch_open_prs.py`): 재사용 워크플로의 새 스텝 "열린 PR 의 판 번호 읽기"가 `GITHUB_TOKEN` 으로 `GET /pulls`(열린 PR), `/pulls/{n}/files`, SRS 를 바꾼 PR 의 `contents`(head·base sha)를 불러 `open-prs.json` 에 저장한다. `gh` 가 아니라 `urllib` 이라 러너 도구에 기대지 않고, 응답 처리는 가짜 API 로 테스트한다. 이 PR 이 판 번호를 건드리지 않으면(추가한 판 있는 산출 파일도, 바꾼 SRS 버전도 없음) 다른 PR 을 읽지 않고 `not_needed` 만 쓴다. 스위치가 꺼져 있어도 읽지 않는다. `scripts/check_changed.py` 는 환경변수 `DOC_GUARD_OPEN_PRS`(그 경로)·`DOC_GUARD_PR_NUMBER` 가 있고 바뀐 파일에 SRS 나 `_v<판>` 산출 파일이 있을 때만 돌려 리포트 키 `version_overlap` 으로 합친다.

**판단 — 권한:** 늘릴 것이 없다. 부르는 쪽(Project Repository)의 `pull-requests: write`(읽기 포함)와 `contents: read` 로 다른 PR 의 파일 목록과 SRS 내용을 읽을 수 있다. 스켈레톤 caller(`plugins/harness/skills/scaffold/skeleton/dot-github/workflows/doc-guard.yml`)에 `contents: read`·`pull-requests: write`·`issues: write` 가 이미 있어 바꾸지 않았다. 이미 깔린 public-cloud caller 도 같은 권한이 있으면 그대로 되고, `contents: read` 나 `pull-requests` 가 빠진 caller 만 추가해야 한다(그쪽 수정은 public-cloud 세션 몫, 확인 필요). 실제 Actions 에서 `GET /pulls/{n}/files`·`contents` 가 이 토큰으로 읽히는지는 **아직 못 봤다**(첫 실제 PR 에서 확인).

**판단 — 검사 불능(사용자 결정 2026-10-14: 목록을 못 읽으면 빨간 불, 종료코드 2 유지):** 다음은 `version_overlap.status = cannot_check` 이고 **종료코드 2** 다(CLAUDE.md 7번 — 통과로도 위반으로도 뭉개지 않는다).

- 열린 PR 목록·파일 목록·`contents` 읽기 실패(401·403·5xx·네트워크), 쪽수 상한 초과, **시간 예산(120초) 초과**, `open-prs.json` 없음·깨짐, 이 PR 이 목록에 없음.
- **SRS 를 바꾼 PR 의 head 쪽 SRS 가 404 이거나 `버전:` 줄이 없어 판을 알 수 없음.** `None` 으로 두면 자기 PR 은 "판을 안 건드림"(`not_needed`), 다른 PR 은 조용히 비교에서 빠지므로 `srs_error` 로 올린다. 이 PR 자신의 SRS 가 그러면 `not_needed` 가 아니라 `ok` 로 기록하고 검사 불능이 된다. `None` 이 정상인 것은 **base 쪽에 SRS 가 아직 없는 경우**(이 PR 이 처음 만듦)뿐이다.

이 검사 불능에는 `read_failure: true` 를 달아, "규칙·설정 문제" 와 구분한다(읽기 문제는 다시 돌리면 풀릴 수 있다). 메시지는 "다른 열린 PR 을 읽지 못해 판 번호 겹침을 확인하지 못했습니다(GitHub 일시 오류일 수 있습니다) … 다음: 이 실행을 다시 돌리십시오(Re-run)" 이고, 리포트 절은 "문서의 문제가 아닙니다. 위 문서 검사 결과는 그대로 유효합니다" 를 덧붙인다. 워크플로 판정 스텝은 종료코드 2 일 때 `render_report.py --exit2-cause report.json` 으로 원인을 보고, 읽기 실패 **뿐이면**(`retry`) "규칙·설정을 고쳐야 합니다" 대신 Re-run 안내를 낸다. 다른 검사 불능(스위치 파일 오류, 번호 짝·객체 겹침, 코드 검사)이 섞이면 지금처럼 `config` 문구다. 문서 위반(1)과 함께 나오면 종료코드는 2(검사 불능이 위반보다 앞선다 — 기존 합치기 관례)지만, 코멘트에는 위반 표가 그대로 보인다(테스트로 확인). 판 번호를 건드리는 PR 에서만 읽으므로 막히는 범위는 SRS·산출 파일 PR 에 한정된다.

**판단 — 비교 대상·API 호출량:** (1) 이 PR 과 `base.ref` 가 다른 열린 PR 은 비교에서 뺀다. 판 번호 겹침은 같은 브랜치로 병합될 PR 끼리만 의미가 있고, 빼면 파일 목록 호출도 줄어든다. (2) **초안(draft) PR 은 포함한다.** 초안도 같은 판을 만들 수 있고, 먼저 병합되는 쪽이 판을 갖는 문제는 초안이 준비 완료로 바뀌는 순간 터지므로 미리 보는 편이 낫다. (3) 이미 있던 단축: 이 PR 이 판 번호를 건드리지 않으면 아무 PR 도 읽지 않고(`not_needed`), 다른 PR 의 `contents` 는 SRS 를 바꾼 PR 만 읽는다. (4) 읽기 전체에 시간 예산 120초를 두고, 넘으면 검사 불능이다(PR 마다 요청당 30초 제한은 그대로).

**판단 — 코멘트에 넣는 다른 PR 제목:** 제목은 백틱 코드 조각으로 감싸고(`@멘션`이 알림을 만들지 않고, 링크·마크다운이 깨지지 않는다), 줄바꿈을 공백으로 바꾸고, 60자로 자른다. 기존 `render_report._cell` 은 `|` 와 줄바꿈만 처리해 멘션은 막지 못하므로 `checker/version_overlap.py` 의 `_title` 에서 처리한다.

**판단 — 로컬 훅:** 돌리지 않는다. 다른 열린 PR 은 GitHub 에 물어야 알고, 훅은 PR 이 생기기 전·네트워크 없이도 도는 보조 관문이라 PR 문맥이 없다. 환경변수가 없으면 이 검사는 대상이 아니라 키도 없다(push 도 같다).

**스위치:** `rules/cross-checks/switches.yaml` 의 `판_겹침`(기본 true, `checker/cross_switches.py` 허용 키에 추가). 끄면 리포트 `{"status": "disabled"}` 와 코멘트 "판 번호 겹침: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" 한 줄. 스켈레톤 switches.yaml·rules/README.md·checker/README.md·길잡이 gate 탭 검사 표("판 번호 겹침" 행)를 맞췄다.

**켜는 순서:** 병합 뒤 엔진 태그(`v0.10.71`)와 `stable` 이 붙어야 한다. 재사용 워크플로와 엔진은 같은 `@stable` 이라 함께 바뀌고, public-cloud caller 는 손댈 것이 없다. 옛 엔진은 `판_겹침` 키를 몰라 이 키가 든 switches.yaml 을 모르는 키(검사 불능)로 읽는다 — 스켈레톤을 새로 만든 저장소는 엔진 v0.10.71 이상(stable)이 된 뒤에 써야 한다. 기존 Project Repository 는 `판_겹침` 줄을 넣지 않으면 그대로 켜진다. plugin.json 0.10.69·0.10.70 은 다른 세션의 PR #322(#317 재배포)·#325 몫이라 0.10.71 로 올렸다.

테스트 `checker/tests/test_version_overlap.py`(겹침 있음·없음, SRS 버전만, 산출 파일만, 목록 읽기 실패, 스위치 끔, 자기 PR 제외, 기존 파일 수정 제외, 가짜 API 로 읽기, check_changed 통합, 워크플로 스텝). 한계: 페이지 상한(3000건)을 넘거나 120초를 넘으면 검사 불능이다. 포크 PR 의 head sha 를 `contents` 로 읽을 수 있는지는 못 봤다(404 면 그 PR 의 `srs_error` 로 검사 불능). 같은 base 브랜치 필터와 초안 포함 판단은 위에 있다. 병합 뒤 판 번호 자동 산출은 범위 밖이다. Plugin version 0.10.71.
