# 652 웹 콘솔 산출물 칩을 파일 기준으로 판정

## 한 일

- 서버 `GET /api/sessions/<id>/files` 가 파일마다 `upload: {state, prs, reason}` 를 낸다(`gitstate.upload_states`, `server.annotate_upload`).
- 판정은 내용으로 한다(squash 병합이라 커밋 조상으로는 합쳐짐을 모른다).
  1. 커밋 안 됨 -> `local`(안 올림)
  2. `origin/<기본>` 의 같은 경로 blob 이 HEAD 와 같음 -> `merged`(합쳐짐). `git ls-tree` 를 파일 수와 상관없이 한 번씩 부른다.
  3. 열린 PR 의 바뀐 파일에 있음 -> `review`(검토 중, PR 번호들). `gh pr list --state open --json number,url,headRefName,files --limit 50`, 저장소당 60초 기억.
  4. 그 밖 -> `committed`(안 올림, 열린 PR 없음)
- git 실패 -> `unknown`. gh 실패는 3 이 필요한 파일만 `unknown`(사유 포함). 바뀐 파일이 100개 이상인 열린 PR 이 있으면(목록이 잘렸을 수 있음) 못 찾은 파일은 `committed` 가 아니라 `unknown`.
- 화면 `docChip` 은 `f.upload` 가 있으면 그것으로 칩을 정하고, 없으면(옛 서버) 예전처럼 세션 PR 로 짐작한다.

## 남은 것 / 한계

- 커밋에 없는 파일(.gitignore 등)은 `local` 로 본다.
- 결과 전체의 짧은 기억은 두지 않았다(gh 만 60초 기억).
