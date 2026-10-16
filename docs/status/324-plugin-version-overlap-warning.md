## 열린 PR 끼리 plugin.json version 이 겹치면 PR 에서 미리 경고(#324, 2026-10-16)

2026-10-14 PR #319 와 #317 이 둘 다 `plugin.json` version 을 0.10.68 로, 10-16 에 #351 과 #353 이 둘 다 0.10.81 로 올렸다. git 은 충돌 없이 병합하고, 먼저 병합된 쪽이 `v{version}` 태그를 가져가 다른 쪽은 배포되지 못한다(release-tag 가 같은 태그가 다른 커밋에 있다며 실패). 이 저장소의 PR 검사(`checker` 워크플로)가 다른 열린 PR 과 version 이 같으면 **경고**한다. 막지 않는다(#315 와 같은 방침).

**판정**(`checker/plugin_version_overlap.py`, 네트워크 없음): 이 PR 의 version 이 main 과 다르고(올렸고) 같은 base 의 다른 열린 PR 의 head `plugin.json` version 이 같은 값이면 경고. version 을 바꾸지 않은 PR 은 main 값이라 이 PR 이 올린 값과 겹칠 수 없어 비교에서 저절로 빠진다. 자기 PR 은 제외한다. 이 PR 이 version 을 안 올렸으면 다른 PR 을 읽지 않고 끝난다. 메시지 예: "plugin.json version 0.10.83 을 열린 PR #354(`제목`) 도 씁니다. 먼저 병합되는 쪽이 v0.10.83 태그를 갖고, 다른 쪽은 그 뒤 sync 해서 version 을 0.10.84 처럼 한 칸 더 올려야 배포됩니다." 다른 PR 제목은 #315 와 같이 백틱으로 감싸고 60자로 자른다(`_title` 재사용).

**읽기·출력**(`scripts/check_plugin_version_overlap.py`): `checker.yml` 의 새 스텝 "열린 PR 끼리 plugin version 겹침 확인"이 PR 이벤트의 ubuntu 에서만 돈다(Plugin version 올림 확인 바로 뒤). `GET /pulls/{n}`, `GET /pulls?state=open`, 각 PR head sha 와 base 브랜치의 `plugin.json` 을 `contents` 로 읽는다. 결과는 로그, GitHub 주석(`::warning::`), 실행 요약(step summary)에 나온다. PR 코멘트는 만들지 않는다(`pull-requests: write` 를 새로 요구하지 않으려고). `checker.yml` 에 `permissions: contents: read, pull-requests: read` 를 명시했다.

**판단 — #315 와 한 장치로 묶지 않음:** 읽기 도구(`fetch_open_prs.py` 의 urllib 클라이언트, 쪽수 읽기, 시간 예산 120초, `FetchError`)와 검사 불능 표현(`read_failure`, 재시도 안내)은 재사용했다. 그러나 #315 는 Project Repository 의 문서 판 번호(산출 파일, SRS)를 JSON 으로 저장해 `check_changed.py` 와 리포트로 합치는 재사용 워크플로 장치이고, 고객사 저장소에는 `plugins/harness/.claude-plugin/plugin.json` 이 없다. 같은 JSON·리포트에 묶으면 모든 고객사 PR 이 쓸데없이 읽는 일을 늘리고 재사용 워크플로와 리포트 모양이 바뀐다. 그래서 판정과 읽기 스크립트를 따로 두고 읽기 도구만 공유한다(`_http`, `paged`, `FetchError`, `BUDGET_SECONDS` 를 import).

**판단 — 검사 불능:** 열린 PR 목록·파일 읽기 실패(401·403·5xx·네트워크), 쪽수 상한 초과, 시간 예산 초과, 토큰·저장소 환경변수 없음, 다른 PR 의 head 에서 `plugin.json` 을 못 읽음(404, 포크 PR 일 수 있음)이나 깨진 JSON 은 모두 검사 불능이고 스텝이 종료코드 2 로 빨갛게 된다(#315 와 같이, 통과로도 위반으로도 뭉개지 않는다). 다시 돌리면 풀릴 수 있어 "Re-run" 을 안내한다. 이 PR 이 version 을 올린 PR 에서만 읽으므로 영향은 그 PR 로 한정된다.

**판단 — Project Repository 영향 없음:** `checker.yml` 은 `workflow_call` 이 없는 이 저장소 전용 워크플로이고 새 스크립트는 `scripts/` 에 둔다. 고객사 PR 검사(`doc-guard.yml`)는 이 스크립트를 부르지 않는다. 다만 `scripts/`·`checker/` 가 배포 대상이라 plugin.json 을 0.10.83 으로 올렸다(이 저장소 전용 워크플로만 바꿨다면 `plugin_version` 검사 대상이 아니라 올리지 않아도 된다).

**한계:** 같은 base 브랜치의 PR 만 비교한다. 초안 PR 도 포함한다. 두 PR 이 version 을 올렸는데 값이 다르면(0.10.83 과 0.10.84) 겹침이 아니지만 병합 순서가 바뀌면 낮은 값이 main 보다 낮아져 `plugin_version` 검사가 잡는다. 실제 Actions 에서 `GITHUB_TOKEN` 으로 다른 PR head 의 `contents` 가 읽히는지(특히 포크 PR)는 못 봤다 — 첫 실제 PR 에서 확인한다. 길잡이(`docs/guide`)는 건드리지 않았다. Plugin version 0.10.83.

테스트 `checker/tests/test_plugin_version_overlap.py`(겹침 경고, 다른 PR 이 version 을 안 바꾼 경우 무시, 겹침 없음, 자기 PR 제외, 이 PR 이 안 올린 경우, 읽기 실패와 head 읽기 실패·깨진 JSON·시간 예산 초과의 검사 불능, 진입점, 워크플로).
