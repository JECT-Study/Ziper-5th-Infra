# 운영

이 저장소는 Worker·DO·홈 배포 수신기·재사용 배포 workflow의 소유 저장소다. Server는 수동 실행 진입점과 애플리케이션을 관리한다. 운영 Worker·DO·route와 Cloud Run은 아직 생성하지 않았다. 현재 실행 결과와 제한은 [검증 문서](verification.md)와 [nightly walkthrough](nightly-walkthrough-2026-11-06.md)를 따른다.

## 배포 전제

1. Server 저장소에서 실제 애플리케이션을 배포하고 홈의 `/readyz`가 DB 준비 상태를 반영해 200 또는 503을 반환하는지 확인한다.
2. 홈 전용 HTTPS 호스트를 전용 Tunnel에 연결한다. 예: `origin-ziper.joonamin.dev`. 이 호스트는 공개 API Worker route와 겹치면 안 된다. 현재 `home-origin.invalid`는 실제 호스트가 아니다.
3. 홈 전용 호스트에 Cloudflare Access Self-hosted 애플리케이션과 **Service Auth** 정책을 설정한다. Worker 전용 service token만 허용한다. 로그인용 Allow 정책이나 공개 Bypass 정책을 붙이지 않는다. 토큰 없는 직접 접근이 차단되는지 확인한다. 홈 애플리케이션은 외부 포트를 공개하지 않는다.
4. 공개 API DNS와 해당 zone의 Workers route 사용 권한을 확인한다. 기존 Tock 서비스·다른 Tunnel·route는 변경하지 않는다. Cloudflare Free에서 요청 한도 초과 시 **fail closed**하도록 zone의 Worker failure mode를 확인한다. 계정·플랫폼 단계의 우회는 코드의 try/catch로 막을 수 없다.
5. GitHub `production` 환경을 만들고 배포 허용 브랜치를 main으로 제한한다. API token은 해당 계정의 Workers Scripts 편집, 해당 zone의 Workers Routes 편집 및 Wrangler가 요구하는 최소 조회 권한만 부여한다. DNS/Tunnel/Access 관리자 토큰을 CI에 재사용하지 않는다. 실제 요구 권한은 토큰 정책과 배포 응답으로 확인한다.

2026-11-05 당시 Infra는 비공개였고 2026-11-06 이력 검사 후 공개로 전환했다. 아래의 비공개 요금·권한 조회 실패는 당시 기록이다. 초안 PR에서는 CI job을 건너뛰며, ready-for-review 전환과 이후 push에서는 검사한다. main push는 항상 검사한다. 2026-11-05 조직 예산·사용량 API는 현재 인증의 `admin:org` 범위 부족으로 조회하지 못했다. 당시 브랜치 보호 조회는 private 플랜 제한으로 403이었다. 현재는 공개 전환 후 main 보호를 적용했으며 아래 main 보호 절의 실제 재조회 결과를 따른다. 플랜 업그레이드는 수행하지 않았다. 공식 근거: [Actions 비용](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [조직 예산 조회 권한](https://docs.github.com/en/rest/billing/budgets#get-all-budgets-for-an-organization).

## GitHub production 설정

| 종류 | 이름 | 값 또는 역할 |
| --- | --- | --- |
| Variable | `CLOUDFLARE_ACCOUNT_ID` | 대상 계정 ID |
| Variable | `CLOUDFLARE_ZONE_NAME` | `joonamin.dev` |
| Variable | `PUBLIC_ORIGIN` | `https://api-ziper.joonamin.dev` |
| Variable | `HOME_ORIGIN` | 준비한 홈 전용 HTTPS origin, 경로·쿼리·인증 정보 없음 |
| Variable | `BACKUP_ENABLED` | 기본 `false`; 비용·IAM·기동 검증 전 활성화하지 않음 |
| Variable | `BACKUP_ORIGIN` | 활성화 시 실제 Cloud Run 서비스 origin (`https://*.run.app`) |
| Secret | `CLOUDFLARE_API_TOKEN` | 위의 제한된 배포 권한 |
| Secret | `HOME_ACCESS_CLIENT_ID` | Worker 전용 Access service token ID |
| Secret | `HOME_ACCESS_CLIENT_SECRET` | 위 token의 secret |
| Secret | `CLOUD_RUN_SERVICE_ACCOUNT_JSON` | 백업 활성화 시만 필요. 전용 invoker 계정 JSON 키 |

비밀 값은 대화·PR·셸 인자·로그에 넣지 않는다. GitHub secrets 화면이나 보안 파일 입력을 사용한다. secrets 파일은 runner 임시 디렉터리에 mode 0600으로 만들고 마지막 단계에서 제거한다. GitHub artifact로 업로드하지 않는다. key와 token 회전은 원본 발급자 폐기 절차까지 포함해 수행한다. 백업을 비활성화해도 Wrangler는 누락한 기존 secret을 자동 삭제하지 않으므로 더 쓰지 않을 키는 별도로 폐기·삭제한다.

## 수동 배포

`Verify Cloudflare access manually`는 main CI 성공 후 토큰 유효성·대상 계정·Worker 목록·zone·route의 읽기 접근만 확인한다. JSON 증거에는 결과와 HTTP 상태만 저장하고 API 응답 본문·토큰은 기록하지 않는다. 이 검사는 쓰기 권한이나 실제 배포 성공을 증명하지 않으며 Cloudflare 리소스를 생성·변경하지 않는다. 토큰은 Repository Secret 또는 production 환경 Secret으로 등록할 수 있다. 검증 구현은 `scripts/verify-cloudflare-access.py`다.

`main`에 머지한 뒤 **CI** workflow의 해당 SHA push 실행이 성공했는지 확인하고 **Deploy edge manually**를 main에서 수동 실행한다. feature 브랜치의 dispatch는 배포 job을 실행하지 않는다. CI 성공 여부는 현재 HEAD와 동일한 SHA로 확인한다. 성공한 PR CI만으로는 배포되지 않는다.

워크플로는 검사 → 비밀을 제외한 route 설정과 임시 secret 파일 준비 → 보호된 홈 `/readyz` 확인 → Worker·SQLite DO 업로드 → 공개 `/readyz` 3회 확인 순서다. `prepare-deploy.ts`는 현재 JSON 형태의 `wrangler.jsonc`를 읽어 `.wrangler/deployment/wrangler.json`을 생성한다. 생성 파일의 실제 account·host·route는 배포 실행의 설정을 따른다. 새 애플리케이션·Tunnel·Access·DNS·Cloud Run·청구 계정은 생성하지 않는다.

공개 검사 성공은 정상 경로의 readiness만 확인한다. DO alarm의 장기 실행, OPEN/HALF_OPEN, Cloud Run, 실제 10분 목표, Sentry uptime은 이 단계로 검증되지 않는다. 첫 공개 요청은 DO와 다음 분 alarm을 초기화한다. 이후 사용자 트래픽이 없어도 alarm이 검사를 이어간다.

업로드 결과가 불명확하면 재실행하기 전에 Cloudflare 배포·route·DO 마이그레이션 상태를 조회한다. 배포 후 공개 검사가 실패해도 자동으로 route를 제거하거나 namespace를 삭제하지 않는다. 기존 DO는 OPEN 상태를 보존하므로 새 코드 업로드만으로 즉시 홈 라우팅이 재개되지 않을 수 있다. 관측 결과와 쿨다운·HALF_OPEN 상태를 먼저 확인한다.

## 장애 대응과 검증 순서

로그의 `circuit_transition`에는 이전·다음 상태와 세대 번호만 남긴다. 요청·헤더·본문·토큰·원본 예외는 기록하지 않는다. 라우터 오류는 `edge_request_unavailable`로 기록한다. 10% 로그 샘플링이므로 로그가 없다는 사실로 상태 전이가 없었다고 판단하지 않는다. Cloudflare DO 조회와 실제 응답을 함께 확인한다. 운영 원인 진단을 위한 세부 오류 분류·알림은 후속 과제다.

배포 후 먼저 정상 요청·직접 origin 차단·인증 헤더 경계를 검증한다. 다음에 홈 장애를 주입하고 timestamp를 기록한다. 10개 정상 표본이 있는 상태에서 6번째 실패가 OPEN을 만드는지, OPEN 중 홈으로 새 사용자 요청이 전달되지 않는지 확인한다. 백업이 활성화되어 있다면 최초 백업 성공까지 600초 이내인지 측정한다. 쓰기 요청은 테스트 전용 데이터를 사용하고 DB 결과를 조회해 중복 여부를 확인한다.

홈을 복구한 뒤 쿨다운·HALF_OPEN 3회 정상·CLOSED·윈도우 초기화를 확인한다. HALF_OPEN 중 한 번 실패하면 OPEN으로 돌아오는지도 확인한다. 이후 Cloud Run cold start·IAM 오류·양쪽 DB 장애·무료 한도·Cloudflare 장애를 별도 시나리오로 검토한다. 운영 장애 주입과 비용이 발생하는 백업 활성화는 준비된 환경과 합의한 실행 범위에서 진행한다.

롤백은 배포 버전과 현재 SQLite schema 호환성을 확인한 뒤 이전 Worker 버전을 선택한다. 현재 v1 스키마를 읽을 수 없는 이전 버전으로 무조건 되돌리지 않는다. namespace나 migrations를 삭제해 복구하지 않는다. DNS 우회는 회로와 origin 접근 경계를 바꾸는 별도 운영 결정이다.

## 알려진 도구 제한

2026-11-05 설치 시 `npm audit`은 minimatch의 glob 증폭 취약점에서 파생된 개발 도구 의존성 9개를 moderate로 보고했다. 런타임 의존성은 zod뿐이다. 신뢰하지 않는 glob을 운영 API에서 받지 않으며 lint glob은 저장소의 고정 명령이다. 자동 `--force`나 호환 범위를 벗어난 의존성 강제 교체는 하지 않았다. 업데이트 시 audit와 호환성을 다시 확인한다.

## 예약 운영·운영 관측 준비

예약 시간과 예산 목표는 `config/production.json`, 정책은 ADR 0002를 따른다. `node scripts/deployment-window.ts`는 배포 가능 여부를 GITHUB_OUTPUT의 `deferred`와 실행 요약에 기록한다. `node scripts/notify-discord.ts`는 등록한 webhook을 사용하며 채널 ID를 대조하고 메시지 ID만 기록한다. 두 스크립트는 `deploy-home.yml`에 연결했다. 실제 전송 여부는 실행별 메시지 ID로 확인한다.

`OPS_READ_TOKEN`은 최소 32자 전용 비밀로 생성해 Worker와 외부 검증 제어기에만 등록한다. `/_ops/circuit`에 GET과 Bearer 인증으로 접근한다. 사용자 JWT와 다른 토큰이며 query string에 넣지 않는다. 조회는 상태·최근 전이·다음 alarm만 반환하고 표본·회로를 변경하지 않는다. 운영 배포 생성기는 이 Secret 없이는 차단한다.

Server 저장소 production 환경은 main만 허용하도록 생성·조회 확인했다. 등록 Secret의 값은 읽지 않는다. Cloud Run 구성·청구 계정·자동 복구 watchdog이 확인되기 전에는 장애를 주입하지 않는다.

## main 보호와 수동 홈 배포 준비

전체 경로의 CODEOWNERS는 @joonamin이다. 현재 main 보호는 사용자 요청에 따라 관리자 bypass를 허용한다. force push·삭제는 금지하고 일반 PR에는 승인·check·대화 해결·최신 push 승인을 요구한다. push/merge 가능한 사용자는 joonamin으로 한정한다. CODEOWNERS는 Infra PR #1의 main 병합으로 활성화됐다. 최초 연결에서는 CI 통과 후 사용자가 허용한 관리자 bypass로 병합했으며 이를 사람의 리뷰 승인으로 기록하지 않는다. 정책과 한계는 [ADR 0003](adr/0003-owner-review-and-admin-bypass.md)을 따른다.

Infra main의 force push·삭제는 bypass 대상이 없는 별도 ruleset `26637239`로도 차단한다. PR 리뷰 bypass와 이력 보호를 분리하며 원본은 `config/github-main-history.json`에 둔다. 관리자가 ruleset 설정 자체를 바꾸는 권한까지 제한한 것은 아니다.

최초 검증은 홈 단독 배포를 우선한다. `deploy-home.yml`은 Server main에서만 재사용하도록 제한하며 source와 Infra SHA의 성공한 main CI를 요구한다. 검사한 JAR와 Sentry source bundle을 재사용해 이미지를 만들고 고정된 cloudflared checksum·SSH host key·전용 키·서비스 토큰으로 전송한다. 수신기는 고정 명령과 네 파일만 허용하며 관리자 설치 compose/deploy와 payload 계약을 비교한다.

Windows의 집어 전용 키 강제 명령은 `C:\Windows\System32\wsl.exe -d Ubuntu --exec python3 /opt/ziper/ci/receive.py $env:SSH_ORIGINAL_COMMAND`다. 기존 Windows 기본 PowerShell이 원래 명령을 데이터 인수로 전달하며 수신기는 check 또는 deploy와 40자리 SHA만 허용한다. 이중 PowerShell의 바이너리 stdin 경유는 제거했다. Python이 WSL의 전용 incoming 디렉터리에서 배타 생성·2GB 제한·정리까지 담당한다. 다른 키나 공유 sshd의 기본 셸은 변경하지 않는다. 대용량 전달은 실제 1MiB 바이너리의 길이와 해시를 대조하고 이후 실제 release로 검증한다. 개인 Access 세션의 검사와 CI 서비스 토큰의 운영 배포 결과는 구분한다.

현재 확인한 Server production Secret은 DISCORD_DEPLOY_WEBHOOK_URL, ZIPER_CI_SSH_KEY, ZIPER_SSH_KNOWN_HOSTS_B64다. CF_ACCESS_CLIENT_ID와 CF_ACCESS_CLIENT_SECRET은 Server와 Infra Repository secrets에서 이름을 확인했다. Server는 `secrets: inherit`로 전달하므로 production 환경에 중복 등록할 필요가 없다. 사용자에게 값 전달을 요청하지 않고 Secret 이름만 조회한다.
