# #803 길잡이 레일의 harness 판 표기 갱신

## 무엇을 했나

- `docs/guide/harness-guide.html` 레일 아래 표기를 "harness 0.10.177, public-cloud main 기준 (2026-11-04)" 에서
  "harness 0.10.203, public-cloud main 기준 (2026-11-08)" 으로 바꿨다. 0.10.203 은 브랜치를 딴 시점 main 의 plugin.json 판이다.

## 왜

- `docs/guide/README.md` 는 길잡이를 고칠 때 이 표기를 현재 플러그인 판에 맞추라고 한다. 그런데 0.10.178~0.10.203 동안
  길잡이 본문을 고친 PR(#753·#755·#757·#759 등)이 표기는 두어, 11-08 #759 병합 뒤 재게시한 길잡이에 옛 판이 남았다.

## 남은 일

- 병합 뒤 길잡이 아티팩트(https://claude.ai/artifact/XcbPn4JkPkeLGgVKBG4yEi)를 다시 게시한다.
- 이 PR 이 병합되기 전에 다른 PR 이 판을 더 올리면 표기가 다시 한두 판 뒤처질 수 있다. 표기는 "이 판 이후 기준" 정도의 뜻이라
  매 판마다 따라잡지는 않는다.
