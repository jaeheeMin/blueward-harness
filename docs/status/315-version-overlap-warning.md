## 열린 PR 끼리 문서 판 번호가 겹치면 PR 에서 미리 경고(#315, 2026-10-14)

public-cloud 에서 PR #200(REQ-003)과 PR #205(REQ-004)가 둘 다 main 의 SRS `버전: 0.2` 에서 출발해 각자 `버전: 0.3` 과 `BW_Backlog List_v0.3.xlsx` 를 만들었다. REQ 번호는 번호 찜이 막았지만 판 번호는 병합 뒤에야 알 수 있었다(#234: export 는 origin/main 에 같은 판이 있으면 거부하므로 main 이 깨지지는 않는다). doc-guard 가 PR 을 볼 때 다른 열린 PR 과 판 번호가 같으면 코멘트에 **경고**한다. 막지 않는다(통과 유지).

**판정**(`checker/version_overlap.py`, 네트워크 없음): (a) 이 PR 이 **추가**(added·renamed)한 `_v<판>.(xlsx|docx|pptx)` 파일(`templates/` 제외)의 경로가 다른 열린 PR 의 추가 파일과 같음, (b) 이 PR 이 `docs/ssot/SRS.md` 의 `버전:` 을 base 와 다른 값으로 바꿨는데 다른 열린 PR 도 같은 값으로 바꿈. 이미 있던 산출 파일을 고친 것, SRS 를 고쳤으나 버전이 그대로인 것, 자기 PR 은 제외한다. 메시지: "이 판 번호(v0.3)를 열린 PR #200(제목) 도 씁니다 … 먼저 병합되는 쪽이 v0.3 을 갖고, 다른 쪽은 sync 뒤 0.4 로 다시 산출해야 합니다." 산출 파일 이름 규칙은 양식 지도에 따로 없고 파일명 끝의 `_v<판>` 이라 그 모양만 본다.

**열린 PR 읽기**(`scripts/fetch_open_prs.py`): 재사용 워크플로의 새 스텝 "열린 PR 의 판 번호 읽기"가 `GITHUB_TOKEN` 으로 `GET /pulls`(열린 PR), `/pulls/{n}/files`, SRS 를 바꾼 PR 의 `contents`(head·base sha)를 불러 `open-prs.json` 에 저장한다. `gh` 가 아니라 `urllib` 이라 러너 도구에 기대지 않고, 응답 처리는 가짜 API 로 테스트한다. 이 PR 이 판 번호를 건드리지 않으면(추가한 판 있는 산출 파일도, 바꾼 SRS 버전도 없음) 다른 PR 을 읽지 않고 `not_needed` 만 쓴다. 스위치가 꺼져 있어도 읽지 않는다. `scripts/check_changed.py` 는 환경변수 `DOC_GUARD_OPEN_PRS`(그 경로)·`DOC_GUARD_PR_NUMBER` 가 있고 바뀐 파일에 SRS 나 `_v<판>` 산출 파일이 있을 때만 돌려 리포트 키 `version_overlap` 으로 합친다.

**판단 — 권한:** 늘릴 것이 없다. 부르는 쪽(Project Repository)의 `pull-requests: write` 가 읽기를 포함하고 이미 코멘트를 남기려고 주고 있다. 재사용 워크플로·스켈레톤 caller 의 permissions 는 그대로이고, public-cloud caller 도 바꿀 필요가 없다. 실제 Actions 에서 `GET /pulls/{n}/files`·`contents` 가 이 토큰으로 읽히는지는 **아직 못 봤다**(첫 실제 PR 에서 확인).

**판단 — 검사 불능:** 열린 PR 목록을 못 읽으면(401·403 권한, 네트워크, 5xx, 너무 많음), `open-prs.json` 이 없거나 깨짐, 이 PR 이 목록에 없음, 겹침 판정에 필요한 SRS 버전을 못 읽음은 `version_overlap.status = cannot_check` 이고 **종료코드 2** 다(다른 교차 검사와 같은 관례, CLAUDE.md 7번 — 통과로도 위반으로도 뭉개지 않는다). 판 번호를 건드리는 PR 에서만 읽으므로 막히는 범위는 SRS·산출 파일 PR 에 한정되고, 일시 오류는 다시 실행하면 풀린다. 경고만 하는 검사가 일시 오류로 PR 을 막는 것이 과하다고 판단되면 종료코드를 0 으로 낮추되 코멘트에는 검사 불능을 남기는 방식으로 바꿀 수 있다 — 지금은 조용히 넘어가지 않는다는 요구를 더 엄격히 읽어 2 로 했다.

**판단 — 로컬 훅:** 돌리지 않는다. 다른 열린 PR 은 GitHub 에 물어야 알고, 훅은 PR 이 생기기 전·네트워크 없이도 도는 보조 관문이라 PR 문맥이 없다. 환경변수가 없으면 이 검사는 대상이 아니라 키도 없다(push 도 같다).

**스위치:** `rules/cross-checks/switches.yaml` 의 `판_겹침`(기본 true, `checker/cross_switches.py` 허용 키에 추가). 끄면 리포트 `{"status": "disabled"}` 와 코멘트 "판 번호 겹침: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" 한 줄. 스켈레톤 switches.yaml·rules/README.md·checker/README.md·길잡이 gate 탭 검사 표("판 번호 겹침" 행)를 맞췄다.

**켜는 순서:** 병합 뒤 엔진 태그(`v0.10.71`)와 `stable` 이 붙어야 한다. 재사용 워크플로와 엔진은 같은 `@stable` 이라 함께 바뀌고, public-cloud caller 는 손댈 것이 없다. 옛 엔진은 `판_겹침` 키를 몰라 이 키가 든 switches.yaml 을 모르는 키(검사 불능)로 읽는다 — 스켈레톤을 새로 만든 저장소는 엔진 v0.10.71 이상(stable)이 된 뒤에 써야 한다. 기존 Project Repository 는 `판_겹침` 줄을 넣지 않으면 그대로 켜진다. plugin.json 0.10.69·0.10.70 은 다른 세션의 PR #322(#317 재배포)·#325 몫이라 0.10.71 로 올렸다.

테스트 `checker/tests/test_version_overlap.py`(겹침 있음·없음, SRS 버전만, 산출 파일만, 목록 읽기 실패, 스위치 끔, 자기 PR 제외, 기존 파일 수정 제외, 가짜 API 로 읽기, check_changed 통합, 워크플로 스텝). 한계: 비교는 열린 PR 전부(기준 브랜치 무관)이고, 페이지 상한(3000건)을 넘으면 검사 불능이다. 포크 PR 의 head sha 를 `contents` 로 읽을 수 있는지는 못 봤다(못 읽으면 그 PR 의 `srs_error` 로 검사 불능). 병합 뒤 판 번호 자동 산출은 범위 밖이다. Plugin version 0.10.71.
