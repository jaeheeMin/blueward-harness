# #951 웹 콘솔 위험 판정이 heredoc 뒤 명령을 읽음 (0.10.283)

## 배경
실사용 시험 B(시험 저장소 harness-console-sandbox, 콘솔 0.10.280, 11-14)에서 `cat > /tmp/pr.md <<'EOF' … EOF` 다음 줄의 `gh pr create`·`gh issue create` 가 노랑(되돌릴 수 없는 일) 카드가 아니라 일반 승인 카드로 떴다. 일반 카드엔 "이 세션에서 다시 묻지 않기" 가 있다. `git commit -q -F - <<'EOF' … EOF` 는 길잡이("git add · commit · 새 브랜치는 묻지 않아")와 달리 승인을 물었다.

## 원인 (코드 확인)
`risk.tokenize` 가 따옴표 밖 줄바꿈을 "여러 줄 명령" 사유로만 남기고 조각을 나누지 않았다. 그래서 heredoc 본문과 다음 줄 `gh pr create …` 가 모두 첫 조각 `cat` 의 인자로 붙어 `cat` 판정(unknown) 하나로 끝났다. `<<` 도 일반 리디렉션으로 보아 커밋은 unknown 이었다. 명령 길이 상한(2,000자)도 PR 글이 길면 판정 전에 unknown 을 냈다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/risk.py` | 따옴표 밖 줄바꿈을 `\n` 연산자로 조각을 나눈다. `<<`·`<<-` 의 끝 표시를 읽고 다음 줄부터 닫는 줄까지 본문을 건너뛴다(데이터). heredoc 밖에서 줄바꿈 뒤에 명령이 더 있으면 지금처럼 "여러 줄 명령" 사유(unknown)지만, 조각 하나라도 irreversible 이면 irreversible 이다 |
| 〃 | `git commit -F -`·`--file -`·`--file=-`(표준 입력 메시지)만 허용. `-F <파일>` 은 목록에 없어 unknown |
| 〃 | 길이 상한은 heredoc 본문을 뺀 길이로 2,000자, 본문 포함 100,000자 |
| `checker/tests/test_web_console.py` | heredoc 표 시험 29건 + 길이 시험. 고치기 전 코드로 14건 실패 확인 |

## 판정 원칙 (애매하면 묻는다)
- 끝 표시를 따옴표로 막지 않은 heredoc(`<<EOF`) 본문에 `$` 나 백틱이 있으면 unknown(셸이 풀어 쓰고 `$( )` 는 실행한다). Claude 가 쓰는 `<<'EOF'` 는 본문을 그대로 넘긴다.
- 닫히지 않은 heredoc, 끝 표시가 없는 `<<`, here-string `<<<` 은 unknown.
- `bash <<'EOF'` 처럼 본문을 실행하는 명령은 명령 자체가 목록에 없어 unknown.
- `a &&` 뒤 줄바꿈은 조각을 나누지 않는다(빈 조각 방지). `(ls)` 뒤 줄바꿈은 나눈다.

## 알려진 한계
- `git commit -m "$(cat <<'EOF' … EOF)"` 꼴은 `$(` 때문에 여전히 unknown(묻는다).
- 셸 주석(`#`)은 해석하지 않는다. 주석 처리한 `# git push` 줄은 irreversible 로 묻는다(안전 쪽).
