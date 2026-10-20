# #386 PR 상태·병합 순서 알림에서 PR 을 링크로 보이기 (2026-10-20)

#370 의 PR 표·알림이 PR 을 `#303 제목` 처럼 번호로만 보여 줬다. 저장소가 여럿이라 번호만으로는 어느 저장소의 PR 인지 모른다. PR 을 알릴 때는 항상 링크(`[#303](https://github.com/<repo>/pull/303)`)를 같이 둔다. 0.10.93.

## 한 것

- `checker/pr_queue.py`: `pr_url`(gh 의 `url`, 없으면 `https://github.com/{repo}/pull/{n}`)·`pr_link` 추가. 사람용 표의 PR 칸과 "먼저 병합할 PR" 칸, "주의: #a 병합 뒤 #b" 줄, `--pr N` 텍스트가 링크. 제목 자르기(28자)는 그대로. JSON 은 PR 항목의 `url` 이 늘 채워지고(gh 값 유지, 없으면 만듦), `--pr --json` 의 `url`·`before[].url` 이 추가됐다. 기존 `after` 는 번호 목록 그대로(링크는 사람용 출력에서 만든다).
- 세션 시작 PR 요약(`session-start-sync.sh`)은 엔진 출력을 그대로 내므로 엔진 변경으로 충분하다(훅은 안 고침).
- 병합 훅(`pre-bash-git-guard.sh`) 순서 거부 메시지: 앞 PR 마다 `[#n](url) 제목`(jq 로 `.url`, 없으면 `$repo` 로 만듦), 대상 PR 과 "먼저 …을 병합" 도 링크. 메시지 이스케이프(`tr -d '\r"\\`$'`)가 지우는 글자는 URL 에 들어가지 않는다.
- pr-queue Actions(`pr_queue_actions.py`): PR 코멘트의 앞 PR 목록, 차례 알림 코멘트(본인 PR·병합된 앞 PR), Teams 카드의 제목·본문 마크다운 링크(기존 "PR 열기" 액션 유지). 병합돼 열린 목록에서 빠진 PR 은 url 이 없어 저장소와 번호로 만든다. merge-order 커밋 status 설명은 링크를 못 담아 그대로 번호.
- 스킬 `prs`·`start`·`deliver` 에 "PR 을 말할 때는 번호·제목과 함께 링크" 규칙.
- 길잡이 "내 PR 확인하기" 탭에 PR 링크 설명(표 예시는 없었다), 판 0.10.93.

## 한계

- 새 판이 병합돼 태그가 붙기 전에는 훅·세션 요약이 이전 판 엔진이라 번호만 나온다.
- 커밋 status 설명(`#n 먼저 병합`)은 링크가 안 된다(GitHub status 설명은 평문).
