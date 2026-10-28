# #501 하네스 저장소 설정에 마켓플레이스 자동 업데이트 켜기 (2026-10-28)

이 저장소의 `.claude/settings.json` 에 `autoUpdate` 가 없어, plugin-work 폴더 세션이 하네스 0.10.94 에 머물렀다.
`/harness:update`·`/harness:version` 스킬이 없어 "Unknown command" 가 났고, `claude plugin update` 는 다른 폴더의
설치본(analyze-plugin-project)을 올려 이 폴더는 `claude plugin install --scope project` 로 다시 설치했다(설치본은 폴더마다 따로다).

`extraKnownMarketplaces.blueward-harness.autoUpdate` 를 public-cloud 와 같이 `true` 로 넣었다. 설정 파일만 바꿔
배포 파일이 아니므로 plugin.json version 은 올리지 않는다.
