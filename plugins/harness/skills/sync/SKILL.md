---
name: sync
description: GitHub 의 최신 상태를 지금 로컬 브랜치로 당겨받는다. 사용자가 "최신으로 맞춰줘", "당겨받아줘", "pull 해줘", "동기화해줘" 라고 하거나 작업 전에 원격 변경을 받아야 할 때 사용한다. 이럴 땐 쓰지 않는다 — 새 작업의 이슈와 브랜치를 만드는 말이면 start 스킬로, 커밋·푸시까지 하려는 말이면 deliver 스킬로.
compatibility: git 과 origin 원격이 필요하다.
---

# /harness:sync

지금 로컬 브랜치를 GitHub 의 최신 상태로 맞추는 스킬이다. 리베이스나 병합(merge)만
하고 커밋도 푸시도 하지 않는다 — 그 둘은 각각 `/harness:deliver` 의 몫이다.

인자로 `--base {브랜치}` 를 받는다. 생략하면 main 을 기준으로 삼는다.

## 절차

1. **컨텍스트**: `git rev-parse --abbrev-ref HEAD` 로 현재 브랜치를 본다.
   `git rev-parse --git-dir` 로 얻은 git 디렉터리 아래 `rebase-merge`,
   `rebase-apply` 가 있거나 `MERGE_HEAD` 파일이 있으면 이미 리베이스나
   병합이 진행 중인 것이다 — 아무것도 건드리지 않고 그 사실을 보고한 뒤
   멈춘다.
2. `git remote get-url origin` 이 실패하면(origin 원격이 없으면) 그 사실을
   보고하고 멈춘다.
3. `git fetch --all --prune` 을 실행한다. 실패하면 네트워크나 인증 상태를
   먼저 확인하라고 안내하고 멈춘다. **가져오지 못한 것을 "최신" 이라고
   보고하지 않는다.**
4. **기준(target) 결정**: `git rev-parse --abbrev-ref --symbolic-full-name @{u}`
   가 성공하면(원격에 이미 올린 브랜치) 먼저 그 upstream 으로 맞추고
   (`{target}` = upstream, 리베이스), 그다음 `origin/{base}`(기본
   `origin/main`)도 합쳐 받는다(`{merge-target}`). 실패하면(upstream 없음,
   detached HEAD) `origin/{base}` 를 기준으로 삼아 리베이스만 하고 합치기는
   없다. 올린 브랜치를 `origin/{base}` 로 리베이스하면 이미 원격에 올라간
   이력이 바뀌어 다음 푸시에 `--force-with-lease` 가 필요해진다. 그래서
   `origin/{base}` 는 **리베이스가 아니라 `git merge` 로 합쳐** 올린 이력을
   그대로 둔다 — 다음 `/harness:deliver` 는 `HEAD..origin/main` 이 0 이라
   리베이스 없이 평범한 푸시로 올린다(그 뒤 main 이 또 바뀌어 deliver 가
   리베이스하면 합친 기록은 사라진다). 현재 브랜치가 `{base}` 자신이면
   합치기는 하지 않는다(upstream 맞추기만). 어떤 기준을 썼는지 사용자에게
   보고한다. 합치기가 필요한지는
   `git rev-list --count HEAD..origin/{base}` 가 0 보다 큰지로 본다(upstream
   리베이스를 한 뒤의 HEAD 로 다시 센다).
5. 두 숫자를 센다: `git rev-list --count HEAD..{target}`(upstream 이 있으면
   upstream, 없으면 `origin/{base}`)과, upstream 이 있는 브랜치라면
   `git rev-list --count HEAD..origin/{base}`. **둘 다 0 일 때만** "이미
   최신" 이라고 보고하고 끝낸다(아래 "플러그인 버전 확인" 은 하고 끝낸다).
   **미커밋 변경이 있어도 여기서 끝나므로 그 변경은 건드리지 않는다.**
6. **미커밋 변경 확인**: `git status --porcelain --untracked-files=all` 을
   `session-start-sync.sh` 와 같은 규칙으로 걸러 `.superpowers/` 와
   `*handoff*.md` 는 제외한다. 남는 변경이 있으면 **멈추고** 파일 목록을
   보여준 뒤 사용자에게 다음 중 하나를 고르게 한다(확인 없이 진행하지
   않는다):

   - (a) 먼저 `/harness:deliver` 로 커밋한 뒤 다시 `/harness:sync`
   - (b) 임시 커밋으로 치워 두고 당겨받은 뒤 커밋 전 상태로 되돌리기
   - (c) 취소

   현재 브랜치가 main 이면 (b) 는 제시하지 않는다 — main 직접 커밋
   금지 훅 때문에 커밋 자체가 거부된다. 이 경우 (a) 대신 `/harness:start`
   로 브랜치부터 만들도록 안내하고, (c) 만 남긴다.

   **`origin/{base}` 합치기가 필요한 경우(5단계의 두 번째 숫자가 0 보다
   큼)에도 (b) 는 제시하지 않는다** — 임시 커밋 위에 병합 커밋이 생기면
   `git reset --mixed HEAD~1` 로 임시 커밋만 되돌릴 수 없다. 이 이유를 한 줄
   알리고 (a)·(c) 만 준다. upstream 리베이스만 필요한 경우에는 (b) 를 그대로
   준다.

   **`git stash` 는 쓰지 않는다.** stash 스택은 같은 저장소를 둔 모든
   git worktree 가 공유해서, 이 스킬이 쓴 stash 를 다른 작업 중인
   worktree 가 실수로 pop 하거나 반대로 다른 세션이 쌓아 둔 stash 를
   이 스킬이 건드릴 수 있다. 그 대신 이 저장소 자신에게만 남는 임시
   커밋을 쓴다.

   (b) 를 골랐으면 다음 순서로 진행한다.
   1. `git add -A` 로 모두 스테이징한다(`.superpowers/` 나
      `*handoff*.md` 를 뺄 필요는 없다 — 어차피 곧바로 되돌릴 임시
      커밋이다).
   2. `commit-and-pr.md` 형식에 맞는 임시 커밋을 만든다. 예:
      `chore: /harness:sync 임시 보관`. 커밋 훅이 거부하면 `--no-verify`
      로 우회하지 않는다 — 거부 사실을 그대로 보고하고 멈춘다.
   3. 7단계로 진행해 리베이스한다(이 경우는 upstream 리베이스만 필요한
      때뿐이므로 7-2 의 합치기는 하지 않는다).
   4. 리베이스가 끝나면 `git log -1 --format=%s` 로 HEAD 의 제목이 방금
      만든 임시 커밋 제목과 같은지 확인한 뒤 `git reset --mixed HEAD~1`
      로 되돌린다. 제목이 다르면(리베이스 중 임시 커밋이 다른 커밋과
      합쳐졌거나 순서가 바뀐 경우) 되돌리지 않고 상황을 그대로 보고한다.
   5. 되돌린 뒤 변경된 파일 목록을 다시 보여준다. **스테이징 여부(인덱스
      상태)는 되돌리기 전과 같게 복원되지 않는다** — `reset --mixed` 는
      인덱스를 모두 비운다. 이 사실을 보고에 한 줄 넣는다.
7. **맞추기와 합치기.** 순서대로 한다.
   1. `HEAD..{target}` 이 0 보다 크면 `git rebase {target}` 을 실행한다.
      **충돌이 나면 스스로 해결하지 않는다.** 예외는 하나 — 아래 "SRS 줄 추가 충돌" 이다.
      1. `git diff --name-only --diff-filter=U` 로 충돌 파일 목록을 모은다.
         목록이 `docs/ssot/SRS.md` 하나뿐이면 먼저 "SRS 줄 추가 충돌" 절차를 한다(mode=`rebase`).
         `merged` 면 `GIT_EDITOR=true git rebase --continue` 로 잇고, 또 충돌하면 다시 이 1번부터(상한 20번).
         그 밖이면 2번으로 간다.
      2. `git rebase --abort` 로 리베이스 전 상태로 되돌린다.
      3. 6단계에서 (b) 로 임시 커밋을 만들었다면, 위 6-4·6-5 와 같이
         HEAD 제목을 확인하고 `git reset --mixed HEAD~1` 로 원상 복구한다.
      4. 충돌 파일 목록과 함께 실패를 보고한다(합치기는 하지 않는다).
         **`git rebase --abort` 가 실패하면 성공한 것처럼 보고하지
         않는다** — 실패 사실과 함께 저장소가 리베이스 진행 중 상태로 남아
         있다고 알린다.
   2. upstream 이 있는 브랜치이고 현재 브랜치가 `{base}` 가 아니면,
      7-1 을 마친 HEAD 로 `git rev-list --count HEAD..origin/{base}` 를 다시
      센다. 0 보다 크면
      `git merge --no-edit -m "chore: main 의 새 변경 합쳐 받기" origin/{base}`
      로 합친다(메시지는 `commit-and-pr.md` 형식 — 명사형 제목. 훅이
      거부하면 `--no-verify` 로 우회하지 않고 거부 사실을 그대로 보고하고
      멈춘다). **충돌이 나면 스스로 해결하지 않는다.** 예외는 하나 — 아래 "SRS 줄 추가 충돌" 이다.
      1. `git diff --name-only --diff-filter=U` 로 충돌 파일 목록을 모은다.
         목록이 `docs/ssot/SRS.md` 하나뿐이면 먼저 "SRS 줄 추가 충돌" 절차를 한다(mode=`merge`).
         `merged` 면 `git commit -m "chore: main 의 새 변경 합쳐 받기"` 로 커밋하고 끝낸다(`--no-verify` 금지).
         그 밖이면 2번으로 간다.
      2. `git merge --abort` 로 합치기 전 상태로 되돌린다.
      3. 충돌 파일 목록과 함께 실패를 보고한다. **`git merge --abort` 가
         실패하면 성공한 것처럼 보고하지 않는다** — 실패 사실과 함께
         저장소가 병합 진행 중 상태로 남아 있다고 알린다.
      합치기 전에 이미 7-1 의 리베이스가 끝났다면 그 결과는 그대로 둔다
      (되돌릴 대상은 합치기뿐이다).
8. **보고**: 다음을 모두 담는다.
   - 어떤 기준(target)으로 맞췄는지, upstream 유무, `origin/{base}` 를
     합쳤는지 여부
   - 새로 받은 커밋 목록(`git log --oneline {이전 HEAD}..{target}` 최대
     10개, 넘으면 "... 외 N개"). 합쳤다면 합쳐 받은 `origin/{base}` 쪽
     커밋 목록도 같은 방식(`git log --oneline {합치기 전 HEAD}..origin/{base}`)
     으로 적는다.
   - 그 위에 다시 얹은 로컬 커밋 수
   - 최종 `git status -sb`
   - upstream 이 없는 브랜치였다면: "원격에 아직 짝 브랜치가 없다. 첫
     `/harness:deliver` 에서 생긴다." upstream 을 이 스킬이 임의로
     설정하지 않는다.
   - 아래 "플러그인 버전 확인" 결과. 5단계에서 "이미 최신" 으로 끝날 때도
     이 확인은 한다.

## 플러그인 버전 확인

git 을 맞춰도 Claude Code 플러그인(훅·스킬)은 따로 갱신된다. 자동 업데이트가
켜져 있으면 새 버전을 뒤에서 내려받지만, **이미 열린 세션은 처음 올린 버전을
계속 쓴다**(공식 문서 code.claude.com/docs/en/plugins/loading "When
auto-update runs"). 그 차이를 알려 준다. 플러그인을 이 스킬이 대신 갱신하지는
않는다 — 아래 명령은 사람이 친다.

1. **세션 버전**: `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`
   의 `version`. 지금 세션에 **실제로 실린** 플러그인이다(스킬 본문의
   `${CLAUDE_PLUGIN_ROOT}` 는 로드될 때 실린 판 폴더로 치환된다). 이것이 판정의 기준이다(#471).
2. **내려받은 버전**: 저장소 루트에서
   `uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/installed_version.py" --loaded-root "${CLAUDE_PLUGIN_ROOT}"`
   를 실행해 JSON 의 `installed`(이 폴더 항목의 판, 경로 비교는 스크립트가 한다)를
   참고로 쓴다. 같은 저장소의 worktree 가 여럿이면 세션이 다른 worktree 항목의 판을 싣기도 하므로
   이 값만으로 stale 이라고 판정하지 않는다. `installed` 가 null 이거나 실행이 안 되면 "모름" 으로 둔다.
   모든 플러그인의 판을 표로 보려면 `/harness:version` 을 안내한다.
3. **최신 버전**: GitHub main 의 `plugins/harness/.claude-plugin/plugin.json`
   `version`.
   `gh api repos/jaeheeMin/blueward-harness/contents/plugins/harness/.claude-plugin/plugin.json --jq .content`
   (base64) 로 읽고, gh 가 안 되면
   `curl -fsSL https://raw.githubusercontent.com/jaeheeMin/blueward-harness/main/plugins/harness/.claude-plugin/plugin.json`
   로 읽는다. 둘 다 실패하면 **"최신 버전을 확인하지 못했다" 고 보고하고
   최신이라고 하지 않는다.**
4. 판정과 안내(버전은 점으로 나눈 숫자로 비교한다):
   - 세션 = 최신: "플러그인 최신(0.x.y)" 한 줄.
   - 세션 < 최신, 내려받은 버전 = 최신: "새 버전이 내려받아져 있지만 이
     세션은 옛 버전이다. `/reload-plugins` 를 치거나 세션을 새로 여십시오."
   - 세션 < 최신, 내려받은 버전 < 최신 또는 모름: "아직 내려받지 않았다.
     `/plugin` → Installed → harness → **Update now**(셸에서는
     `claude plugin update harness@blueward-harness`) 뒤 `/reload-plugins`."
     자동 업데이트는 세션의 첫 메시지 뒤 최대 10분 안에 돌므로 방금 연
     세션이면 조금 뒤 다시 확인해도 된다고 덧붙인다.
   - 세션 > 최신: 개발 중인 로컬 플러그인일 수 있다 — 버전만 알리고 안내하지
     않는다.
   세 버전을 모두 보고에 적는다.

## SRS 줄 추가 충돌(#977)

충돌 파일이 `docs/ssot/SRS.md` 하나뿐일 때만 엔진이 자동으로 합친다. 양쪽이 같은 자리에 줄만 추가했고, `버전:` 줄·표 머리글이
아니고, 새 REQ/DEV 번호가 겹치지 않고, 표 행의 열 수가 맞고, 합친 결과가 SRS 모양 검사와 같은 줄 중복 검사를 통과할 때다.
순서는 main 줄 먼저 → 내 줄이다. 직접 고치지 말고 엔진을 부른다.

```
e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "SRS 자동 합치기 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
uvx --from "$e" python -P -m checker.srs_automerge --mode merge --root .
```

(리베이스 중이면 `--mode rebase`.) 방식마다 ours/theirs 가 반대라 `--mode` 를 반드시 맞게 준다. 결과 JSON 의 `status` 로 판단한다.

- `merged`(종료코드 0): 작업 폴더에 쓰고 `git add` 까지 했다. 위 절차대로 커밋하거나 `rebase --continue` 한다.
  보고에 "SRS 에서 양쪽이 줄만 추가한 충돌 N곳을 자동으로 합쳤어 — 올리면 승인을 다시 받아야 해" 를 넣는다(합친 커밋은 SRS 승인을 낡게 만든다).
- `refused`(1)·`cannot_check`(2)·엔진을 못 부름: 합치지 않았다. 통과로 보지 말고 지금처럼 abort 하고 충돌 파일 목록과 `reason` 을 보고한다.

## 하지 않는 것

이 스킬은 로컬 브랜치만 바꾼다. 다음은 하지 않는다.

- `--force` / `--force-with-lease` 푸시 — 이 스킬은 애초에 푸시하지 않는다.
- `git reset --hard`
- 올린 브랜치를 `origin/{base}` 로 리베이스(합치기는 `git merge` 로만 한다)
- 병합 충돌을 스스로 푸는 것(`merge --abort` 로 되돌리고 보고만 한다. 예외: 위 "SRS 줄 추가 충돌" 을 엔진이 `merged` 로 합친 것)
- `git stash` (위 6단계 이유 참고)
- upstream 을 임의로 설정하는 것(`git branch --set-upstream-to` 등)

## 관련 규칙

기준 판단과 리베이스·합치기 절차의 근거는
`<이 스킬의 base directory>/../../rules/branching.md` 와
`<이 스킬의 base directory>/../../rules/commit-and-pr.md` 를 따른다.
`<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는 경로다.
