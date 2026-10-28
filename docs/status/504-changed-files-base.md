# #504 PR 검사의 바뀐 파일 목록에 main 의 새 변경이 섞이는 문제 (2026-10-28)

## 배경

- `pr-checks.yml` doc-guard 단계가 `git diff --name-only --diff-filter=d origin/<base> HEAD`(두 점)로 바뀐 파일을 구했다.
- `pull_request` 이벤트의 HEAD 는 PR 병합 ref(그때의 main + PR)다. 그 뒤 main 이 움직이면 최신 `origin/main` 과의 두 점 차이에 main 의 새 변경이 반대 방향 차이로 섞인다.
- public-cloud PR #427(Spec 안 바꿈)에 Spec 변경이 있는 것처럼 객체 겹침 경고가 떴다.

## 재현 (임시 저장소)

- main: 커밋 A(a.txt) → PR 브랜치 커밋(pr.txt) → main 커밋 M0(m0.txt) → 병합 ref 상당 merge 커밋 → main 커밋 B(b_new.txt 추가), B2(a.txt 수정). 실행기처럼 전체 clone 후 병합 ref 를 checkout.
- 옛 명령(`--depth=1` fetch + 두 점): `a.txt`, `pr.txt` — main 이 고친 a.txt 가 섞였다. B 가 새로 추가한 파일은 HEAD 쪽에서 "삭제" 로 잡혀 `--diff-filter=d` 에 걸려 빠지므로, 섞이는 건 main 이 **이미 있던 파일을 고친** 경우다(#427 의 Spec).
- 세 점 + `--depth=1` 유지: `fatal: no merge base`(`.git/shallow` 에 origin/main 끝 커밋이 적힘). 이 상태에선 `|| git ls-files` 로 넘어가 전체 파일이 검사 대상이 된다. 세 점만 바꾸고 depth 를 두면 더 나빠진다.
- 세 점, depth 없이: `pr.txt` 만. 병합 ref 의 첫 부모(`HEAD^1`)도 `pr.txt` 만.

## 결정

- `pr-checks.yml` 을 세 점(`"$base"...HEAD`)으로 바꾸고 `git fetch` 의 `--depth=1` 을 뺐다. checkout 이 이미 fetch-depth 0 이라 이력이 있어 depth 가 필요 없고, 얕은 경계는 갈라진 지점 찾기를 깨뜨린다.
- `HEAD^1` 은 병합 ref 가 아닌 HEAD(PR 이 병합 커밋이 아니게 checkout 된 경우)에서 틀리므로 쓰지 않았다.
- 다른 곳: `main-checks.yml`(push)은 `BEFORE_SHA`→HEAD 로 같은 브랜치의 앞뒤 커밋을 비교해 병합 ref 문제가 없다. `ai-review.yml` 은 PR 의 base.sha·head.sha 를 고정 SHA 로 써서 해당 없다. 스크립트·엔진·scaffold 의 skeleton 워크플로에는 바뀐 파일 계산이 없다(재사용 워크플로를 부른다). `deliver` 스킬의 `origin/{base}...HEAD` 는 이미 세 점이다.
- 시험: `test_pr_checks_workflow.py` 에 세 점 사용·`--depth` 없음 확인.
- plugin version 0.10.129.

## 제안만 (바꾸지 않음)

- `|| git ls-files` 대체는 "바뀐 파일을 못 구함" 을 "전부 바뀜" 으로 바꿔 검사한다. 무관한 파일의 위반이나 겹침 경고가 이 PR 탓으로 보일 수 있어 원칙 7(검사 불능을 위반으로 뭉개지 않기)과 어긋난다. 실패하면 status=unknown 으로 검사 불능을 밝히고 끝내는 편이 맞다. 별도 이슈로 다룬다. main-checks.yml 의 같은 대체도 마찬가지다.

## 남은 일

- 길잡이에는 바뀐 파일 계산 방식 설명이 없어 고치지 않았다.
- 병합 뒤 public-cloud 에서 main 이 움직인 PR 의 doc-guard "바뀐 파일" 로그가 PR 의 파일만 담는지 확인한다.
