# #971 heredoc 커밋 뒤 줄에 읽기 명령이 붙으면 자동 허용하지 않음 (0.10.290)

## 배경
#955(이슈 951)로 `git commit -F - <<'EOF' … EOF` 는 자동 허용이 됐지만, heredoc 밖에서 줄바꿈 뒤에 명령이 더 있으면 "여러 줄 명령" 사유로 unknown(일반 카드)이었다. 시험 B 2회차(11-14, 콘솔 0.10.288)에서 `/harness:deliver` 의 커밋 명령이 `… EOF` 다음 줄에 `git log -1 --format=%h` 를 붙여 일반 카드로 떴다. 길잡이는 "git add · commit 은 묻지 않아" 라고 한다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/risk.py` | 따옴표·heredoc 밖 줄바꿈은 bash 처럼 `;` 와 같은 명령 구분이다. "여러 줄 명령" 사유를 없애고 줄마다 판정한다(모두 safe 면 safe, 하나라도 irreversible 이면 노랑, unknown 이 섞이면 묻기) |
| 〃 | 줄 잇기(`\` + 줄바꿈)는 두 줄을 한 명령으로 잇는다. 전에는 뒤 줄바꿈을 명령 구분으로 읽었다(이제 나누지 않고, 지금처럼 "줄을 잇는 \\" 사유로 묻는다) |
| `checker/tests/test_web_console.py` | `ls\nls`·heredoc 커밋+`git status`·`git add -A\ngit status` 를 safe 로, 시험 B 2회차 커밋 모양 safe, 다음 줄 원격 올리기는 irreversible, 판정 못 하는 줄은 unknown, CRLF·빈 줄, 줄 잇기 |

## 결정
- 줄바꿈을 따로 막을 이유가 남지 않았다: 따옴표 안 줄바꿈은 따옴표 처리, heredoc 은 본문 건너뛰기(#955), 주석은 줄 끝까지 건너뛰기(#955 점검), 줄 잇기는 한 명령으로 이음. 그 밖의 줄바꿈은 bash 에서 `;` 와 같다.
- `a &&` 뒤 줄바꿈은 지금처럼 나누지 않는다(빈 조각 방지).
