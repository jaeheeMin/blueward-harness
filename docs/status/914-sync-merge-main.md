# #914 이미 올린 브랜치에서 sync 가 origin/main 을 합쳐 받게 함

- 2026-11-12, 판 0.10.271(main 0.10.269, 열린 PR #917 이 0.10.270).
- 증상: `/harness:sync` 와 세션 시작 훅은 upstream 이 있는(이미 원격에 올린) 브랜치에서 기준을 그 upstream 으로만 잡아, origin/main 에 새 커밋이 있어도 받지 않고 숫자만 알렸다. 사용자는 sync 가 "main 과 맞추기" 라고 기대한다.
- 결정(A안): upstream 이 있는 작업 브랜치는 upstream 맞추기(리베이스, 지금 동작 그대로)를 한 뒤 `git rev-list --count HEAD..origin/main` 이 0 보다 크면 `git merge origin/main` 으로 합쳐 받는다. 리베이스가 아니라 merge 인 이유: 올린 이력을 바꾸지 않아 다음 `/harness:deliver` 가 평범한 푸시로 올라간다(deliver 는 `HEAD..origin/main` 이 0 이면 리베이스 없이 `git push -u`). 저장소는 squash 병합만 허용해 합친 기록은 병합 때 사라진다.
- 바뀌지 않는 것: upstream 없는 브랜치·detached HEAD 는 origin/main 으로 리베이스. 현재 브랜치가 main 이면 합치지 않는다.
- 바꾼 것
  - `plugins/harness/skills/sync/SKILL.md` 4·5·6·7·8단계와 "하지 않는 것". "이미 최신" 은 upstream·base 두 숫자가 모두 0 일 때만. 합치기가 필요하면 미커밋 변경의 (b) 임시 커밋 보기를 주지 않는다(임시 커밋 위에 병합 커밋이 생기면 `reset --mixed HEAD~1` 로 못 되돌린다). 병합 충돌은 풀지 않고 파일 목록 → `git merge --abort` → 보고, abort 실패는 성공처럼 보고하지 않는다.
  - `plugins/harness/hooks/session-start-sync.sh` 에 `run_merge` 추가, upstream 처리 뒤 합치기. upstream 리베이스가 실패하면 합치지 않고, 미커밋 변경이 있으면 지금처럼 건너뛴다.
  - `docs/guide/harness-guide.html` sync 탭과 "올리기 전 정리 안 된 변경" 행.
- 합치기 커밋 메시지: `chore: main 의 새 변경 합쳐 받기`. 이 저장소 `.githooks/` 에는 commit-msg 훅이 없고(pre-commit 은 브랜치 이름만 보며 MERGE_HEAD 가 있으면 건너뜀), `pre-bash-git-guard.sh` 는 `git commit`·`push` 만 보므로 `git merge` 는 걸리지 않는다. 메시지는 `commit-and-pr.md` 형식(명사형 제목)에 맞췄다.
- 시험: `checker/tests/test_plugin_layout.py` 에 임시 저장소 4개 — 합쳐짐(원격 브랜치가 HEAD 의 조상), 충돌 시 되돌림(HEAD 그대로·MERGE_HEAD 없음·충돌 파일 표시), main 에선 합치지 않음, upstream 없는 브랜치는 리베이스.
- 확인 남음: Project Repository 쪽 commit-msg 훅은 scaffold 가 깔지 않아 따로 없음을 코드에서 확인했을 뿐 실제 Project Repository 로 합쳐 보지는 못했다. 병합·배포 뒤 실제 올린 브랜치에서 `/harness:sync` 를 한 번 돌려 본다.
