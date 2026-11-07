# 승인된 새 이미지 쌍 배포 검증 계획

2026-11-07 사용자 승인에 따라 새 main 이미지의 Home·Cloud Run 최초 쌍 배포와 동일 run의 전체 재실행을 검증한다. GitHub Actions를 수동 시작하고 성공 CI의 tested-release만 사용한다. Source와 Infra의 실제 main CI가 성공한 고정 SHA를 기록한다. 미래 SHA를 기입하지 않는다.

성공은 두 환경의 source SHA·OCI config digest·JAR 해시 일치, 새 release·origin의 엄격한 /livez·/readyz 3회 연속 정상, 보류·skip 없는 작업 성공, 시도별 서로 다른 Discord 메시지의 POST wait=true 및 GET 내용 일치로 판정한다. 모든 배포 artifact에 시도 번호를 붙여 보존한다. Discord API 저장 확인과 개인 기기 푸시는 구분한다.

Cloudflare protected origin의 실제 Actions 접근 성공을 runtime 배포 선행 조건으로 둔다. 차단 제품·규칙을 먼저 식별하고 전역 보안 완화나 Access 공개 bypass를 하지 않는다. 새로운 진단 자격은 읽기 전용으로 제한하며 값은 GitHub Secret에만 저장한다. 읽기 권한으로 보안 설정을 변경하지 않는다.

첫 실행은 08:00–23:30 KST에 시작하며 기존 02:30–06:00 보류를 유지한다. 결과가 불명확한 배포 쓰기·Discord POST는 자동 재실행하지 않는다. 첫 완전 성공과 현재 상태를 확인한 뒤에만 동일 SHA를 전체 재실행한다. 알림 실패만으로 서버를 재배포하지 않는다.

Worker 업로드·사용자 트래픽 failover·장애 주입·600초 복구·개인 기기 푸시·물리 BIOS 재기동·장기 uptime은 이번 통과 범위 밖이다. 구현은 Infra ADR0012와 Source 검증기 PR에, 실행 증거와 한계는 Infra PR #1 및 기존 nightly walkthrough에 남긴다.
