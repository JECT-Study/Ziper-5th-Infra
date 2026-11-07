# 운영

## 보호 origin 사전 검사와 403 진단

`Diagnose Cloudflare security manually`는 성공한 같은 main CI 뒤 보안 API를 읽기만 한다. 먼저 선택적인 production Secret `CLOUDFLARE_SECURITY_API_TOKEN`, 없으면 기존 Worker API token을 사용한다. 기존 토큰의 권한을 임의로 늘리지 않는다. 특정 account의 joonamin.dev와 origin의 /readyz 최근2시간·최대20개 sampled 이벤트에 한정하고 제품·작업 enum, 검증된 rule ID·시각·ray만 남긴다. IP·query·User-Agent·설명·원문·오류문은 저장하지 않는다. HTTP403/GraphQL 오류·빈 sampled 결과를 서로 구분하고 설정이 켜져 있다는 사실만으로 과거 차단 원인을 확정하지 않는다. 각 요청10초·본문64KiB 한도, 리다이렉트 거부다. API 조회 권한도 없으면 관리 세션 또는 별도 읽기 전용 자격이 필요하다.

`verify-origin.ts`는 배포 변경 전에 `/readyz`를 5초 한도로 한 번 확인하며 200 이외에는 배포를 막는다. Accept `application/json`과 User-Agent `ziper-deployment-verification`을 명시한다. 자동 재배포나 인증 우회는 하지 않는다. 선택적인 production Secret `HOME_ACCESS_CREDENTIALS_SHA256`은 알려진 정상 Client ID, 줄바꿈 하나, Client Secret의 SHA-256이다. 비교값과 자격은 출력하지 않고 일치 여부만 기록하며 불일치하면 요청 전에 중단한다. 비밀 값을 바꿀 때 비교값도 같은 자격으로 갱신한다.

실패 artifact `home-origin-health`에는 자격의 존재·일치 여부, HTTP 상태, `cf-mitigated: challenge` 여부와 검증된 Cloudflare 오류 코드만 남긴다. 본문은 최대 4096바이트만 읽어 `error code:` 또는 `cf-error-code` 표식의 1010·1015·1016·1020·1033·1101·1102만 추출하고 원문은 저장하지 않는다. 코드가 없다는 사실로 Access 또는 WAF 원인을 확정하지 않는다. 실제 배포 전 같은 main의 `verify-cloudflare.yml`을 수동 실행해 읽기 전용으로 진단할 수 있다.

현재 실제 차단과 이어서 실행할 조건은 [2026-11-07 walkthrough](nightly-walkthrough-2026-11-07.md)에 둔다. `scripts/verify-production-boundaries.py`는 실제 Worker·Cloud Run 배포 뒤 `--release`·`--expected-origin`·`--backup-origin`·`--output`을 지정해 읽기 전용으로 실행한다. 로컬 private 파일의 JWT·ops token은 메모리에서만 사용하고 유효/잘못된 JWT 전달, upstream 헤더 위조 시 정상 응답·비밀 헤더 응답 노출 없음, ops GET 인증·POST 거부, 직접 origin 비공개 경계를 검사한다. 업무 데이터 쓰기·다른 구성원 계정·부하 검사가 아니며 준비만 된 스크립트를 운영 통과로 기록하지 않는다.

Infra main의 현재 리뷰 예외는 [ADR0010](adr/0010-owner-only-review-bypass.md)을 따른다. 관리자 강제는 켜고 PR allowance의 사용자만 joonamin으로 지정한다. 설정 원본 `config/github-main-review.json`의 review 부분은 GitHub의 required_pull_request_reviews PATCH, 관리자 강제는 enforce_admins POST로 적용하며 변경 후 status check·push 제한·별도 이력 ruleset도 재조회한다. Source 보호 설정은 이 구성의 대상이 아니다.

## GHCR 홈 이미지 전달

새 deploy-home workflow는 publish → deploy → notify로 나눈다. publish는 packages:write로 tested-release 이미지를 GHCR의 source SHA tag에 발행하고 registry-release artifact를 만든다. 기존 tag는 digest를 조회해 JAR·소스 번들 검증 후 재사용하며 덮어쓰지 않는다. 404 이외의 registry 조회 오류는 중단한다. repo 이름은 ghcr.io/ject-study/ziper-server로 고정한다.

deploy job은 packages:read의 별도 job 토큰과 작은 metadata JSON만 SSH로 전달한다. 수신기의 deploy-registry는 정확한 digest를 pull하고 OCI config·JAR를 검증한 뒤 기존 신뢰 compose/deploy를 실행한다. Docker 인증은 임시 config에만 남고 종료 시 제거한다. runtime은 검증한 로컬 이미지만 사용한다. 새 수신기는 기존 image archive 전송 명령을 거부한다. caller를 먼저 새 GHCR workflow로 전환한 뒤 수신기를 설치하며, 이전 컨테이너·로컬 이미지와 release manifest는 보존한다.

홈 `/opt/ziper/ci`에는 receive.py·image_identity.py·registry_release.py·deploy.sh와 config/production.json의 production.json을 함께 설치한다. Source caller에는 packages:write 권한이 필요하며 두 Infra pin을 성공한 실제 main SHA로 함께 갱신한다. `publish.outputs.image`와 `digest`, `registry-release` artifact는 Cloud Run 경로가 소비할 수 있다. 백업을 연결할 때 publish와 home deploy 사이에 검증 gate를 두며 홈만 성공한 결과를 쌍 배포로 기록하지 않는다. 정책은 [ADR 0007](adr/0007-ghcr-home-delivery.md)을 따른다.

새 artifact의 receiver-control-proof에는 check·일반 명령 거부·registry deploy 판정과 payload 크기·정적 실패 코드만 저장한다. 토큰·전체 stderr·응답 본문은 저장하지 않는다. 실제 발행·pull·readiness 결과는 실행별 증거를 따른다.

이 저장소는 Worker·DO·홈 배포 수신기·재사용 배포 workflow의 소유 저장소다. Server는 수동 실행 진입점과 애플리케이션을 관리한다. 2026-11-06 홈 릴리스가 실행되었고 공개·보호 origin의 HTTP 200을 확인했다. Worker·DO·route와 Cloud Run의 완료 여부는 실행별 증거를 따른다. 현재 실행 결과와 제한은 [검증 문서](verification.md)와 [nightly walkthrough](nightly-walkthrough-2026-11-06.md)를 따른다.

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

예약 시간과 예산 목표는 `config/production.json`, 정책은 ADR 0002를 따른다. `node scripts/deployment-window.ts`는 배포 가능 여부를 GITHUB_OUTPUT의 `deferred`와 실행 요약에 기록한다. `node scripts/notify-discord.ts`는 등록한 webhook으로 한 번 전송한 뒤 같은 메시지를 조회해 채널·내용·ID를 대조하고 시도별 영수증을 남긴다. 두 스크립트는 `deploy-home.yml`에 연결했다. 실제 전송 여부는 실행별 메시지 ID로 확인한다.

`OPS_READ_TOKEN`은 최소 32자 전용 비밀로 생성해 Worker와 외부 검증 제어기에만 등록한다. `/_ops/circuit`에 GET과 Bearer 인증으로 접근한다. 사용자 JWT와 다른 토큰이며 query string에 넣지 않는다. 조회는 상태·최근 전이·다음 alarm만 반환하고 표본·회로를 변경하지 않는다. 운영 배포 생성기는 이 Secret 없이는 차단한다.

Server 저장소 production 환경은 main만 허용하도록 생성·조회 확인했다. 등록 Secret의 값은 읽지 않는다. Cloud Run 구성·청구 계정·자동 복구 watchdog이 확인되기 전에는 장애를 주입하지 않는다.

## main 보호와 수동 홈 배포 준비

기존 릴리스의 재기동 정책만 정합할 때는 [ADR0011](adr/0011-reconcile-existing-restart-policy.md)의 기본 읽기 계획을 먼저 확인한다. 명시한 두 container ID·release·검토된 Infra SHA로만 --apply하며 CI·시간·lease·lock 검사를 통과해야 한다. 이미지 배포를 대신하거나 배포 명령을 재실행하는 도구가 아니다. source 파일·start time·정책 readback과 공개 health를 별도로 기록한다.

전체 경로의 CODEOWNERS는 @joonamin이다. 현재 Infra main은 관리자에게도 보호를 강제하고 PR allowance는 joonamin 개인에게만 둔다. force push·삭제는 금지하고 승인·check·대화 해결·최신 push 승인과 push/merge 사용자 joonamin 제한을 유지한다. 개인 PR 예외를 사용해도 CI 통과 후 병합하며 이를 사람의 리뷰 승인으로 기록하지 않는다. 현재 정책과 한계는 [ADR0010](adr/0010-owner-only-review-bypass.md)을 따른다. CODEOWNERS는 PR #1의 main 병합으로 활성화됐으며, 최초 연결의 관리자 전체 bypass는 [ADR0003](adr/0003-owner-review-and-admin-bypass.md)의 과거 정책이다.

Infra main의 force push·삭제는 bypass 대상이 없는 별도 ruleset `26637239`로도 차단한다. PR 리뷰 bypass와 이력 보호를 분리하며 원본은 `config/github-main-history.json`에 둔다. 관리자가 ruleset 설정 자체를 바꾸는 권한까지 제한한 것은 아니다.

`deploy-home.yml`은 Server main에서만 재사용하도록 제한하며 source와 Infra SHA의 성공한 main CI를 요구한다. 검사한 JAR와 Sentry source bundle로 만든 이미지는 GHCR에 발행하고 metadata만 SSH로 전달한다. 수신기는 고정 repository의 digest와 JAR를 검증하며 관리자 설치 compose/deploy만 실행한다. runtime 배포와 Cloud Run 동일 이미지 검증은 실행별 증거를 따른다.

Windows의 집어 전용 키 강제 명령은 `C:\Windows\System32\wsl.exe -d Ubuntu --exec python3 /opt/ziper/ci/receive.py $env:SSH_ORIGINAL_COMMAND`다. 기존 Windows 기본 PowerShell이 원래 명령을 데이터 인수로 전달하며 새 수신기는 check 또는 deploy-registry와 40자리 SHA만 허용한다. 다른 키나 공유 sshd의 기본 셸은 변경하지 않는다. 기존 deploy archive 명령은 거부한다. Source caller를 먼저 새 pin으로 반영하고 신뢰 수신기·정책을 함께 설치한 다음 실제 실행한다.

CI·홈 간 동일성은 release manifest의 imageConfigDigest와 내부 JAR SHA256으로 비교한다. GHCR imageManifestDigest로 pull 대상을 고정하며 OCI config digest와 같은 종류의 값으로 비교하지 않는다. 검증용 임시 tag와 runtime release tag를 구분한다. 설치 파일 목록은 위 GHCR 절을 따른다. [ADR 0005](adr/0005-portable-image-identity.md)의 이미지 식별 결정과 [ADR 0007](adr/0007-ghcr-home-delivery.md)의 전달 프로토콜을 함께 검토한다. release-manifest artifact에는 비밀 설정을 포함하지 않는다.

현재 확인한 Server production Secret은 DISCORD_DEPLOY_WEBHOOK_URL, ZIPER_CI_SSH_KEY, ZIPER_SSH_KNOWN_HOSTS_B64다. CF_ACCESS_CLIENT_ID와 CF_ACCESS_CLIENT_SECRET은 Server와 Infra Repository secrets에서 이름을 확인했다. Server는 `secrets: inherit`로 전달하므로 production 환경에 중복 등록할 필요가 없다. 사용자에게 값 전달을 요청하지 않고 Secret 이름만 조회한다.

## Tunnel 시작과 origin 실패 진단

홈 공개 검사는 Server의 `scripts/verify-public-health.py`를 `--checks 3 --interval 10 --timeout 10 --startup-timeout 180 --retry-interval 5`로 실행한다. Infra의 기존 광범위한 예외 재시도 wrapper는 제거한다. 요청당 10초와 전체 180초를 제한하고 남은 시간에 맞춰 요청·대기를 줄인다. POSIX Linux runner에서 실행한다. 두 경로가 모두 통과한 검사 쌍이 10초 간격으로 3회 연속 성공해야 하며 일시적 실패는 횟수를 초기화한다. 기본 CLI는 opt-in 옵션이 없으면 기존처럼 첫 오류에 실패한다.

HTTP 502·503·504·520~524·530, 연결 거부·재설정·중단·도달 불가·시간 초과와 일시적 DNS 오류만 5초 간격으로 재시도한다. 인증 오류, 리다이렉트, TLS 검증 실패, 영구 DNS 오류, 나머지 HTTP 상태와 잘못된 200 계약은 즉시 실패한다. Server는 `Accept: application/json`을 요청하고 기존 엄격한 JSON·캐시·본문 계약을 유지한다. 한도에 도달하면 실패한다. 배포나 쓰기 요청은 재실행하지 않는다.

`public-health` artifact에 경로별 HTTP 상태·시도·경과 시간·요청 한도·정적 실패 이유·재시도 여부와 최종 연속 정상 횟수를 보존한다. 응답 본문과 자격은 기록하지 않는다. Cloudflare 상세 오류 코드는 추출하지 않으며 HTTP 530만으로 원인을 확정하지 않는다.

문제 실행의 Infra pin은 `bdc15a71bfd478187932eeb063822e307022c323`이었다. 현재 두 pin은 Server의 `.github/workflows/deploy-production.yml`에서 확인한다. 이 변경을 Infra에 머지하는 것만으로 Server 배포에 반영되지 않는다. Infra PR CI → Infra main 머지 → 해당 실제 SHA의 main push CI 성공 → Server의 새 CLI 구현과 두 SHA 참조를 같은 변경으로 반영 → develop·main CI 성공 → main 수동 배포 순서로 진행한다. 참조 갱신은 그때 존재하는 커밋만 사용한다. 해당 시점의 기록이며, 후속 실행과 pin 갱신의 실제 결과는 PR #1에 둔다.

`Verify Cloudflare access manually`는 보호 origin의 읽기 검사도 수행한다. `home-origin-health`에는 설정·요청·응답 중 실패 단계, HTTP 상태 또는 제한한 네트워크 오류 코드만 저장한다. 비밀과 응답 본문은 기록하지 않는다. 이 기록 없이 origin 검사 실패를 자격·DNS·Tunnel 중 하나로 확정하지 않는다.

Linux workflow는 `timeout --signal=KILL 180s`로 검사 프로세스 전체에도 상한을 적용한다. Python 신호 처리가 지연되는 경우도 운영 단계가 계속 대기하지 않는다. 검사 JSON은 요청 전후 원자적으로 갱신하므로 강제 종료 시 마지막 경로·시도와 미수신 상태를 확인할 수 있다. 이 경우 `termination: running`은 성공을 뜻하지 않으며 Actions의 강제 종료 결과와 함께 실패로 판정한다.

## Registry 전환의 잠금·복구·시간 경계

고유 verification tag에서 config·JAR를 검사하며, 실패한 metadata는 기존 release tag를 바꾸지 않는다. 수신기부터 deploy.sh까지 공통 deploy.lock을 유지한다. inherited fd의 inode를 확인하며 별도로 같은 lock을 다시 열어 교착시키지 않는다. 복구 작업도 같은 lock을 사용해야 한다.

cloudflared 시작이나 current-version 기록 실패도 app/readiness 실패와 같은 롤백으로 처리한다. 이전 runtime과 current-version을 보존하고 최초 실패는 app을 중지한다. 같은 release를 다시 실행하다 Tunnel 단계가 실패했다고 기존 app을 무조건 중지하지 않는다.

보류 시간에도 GHCR 발행·재검증은 가능하지만 runtime 변경은 하지 않는다. publish 시작 당시와 home mutation 직전 workflow 시간을 구분하며 수신기도 production.json으로 재검사한다. pull 중 02:30 경계를 넘으면 release tag·컨테이너를 변경하지 않고 보류한다. 공개 readiness 단계는 보류 시 건너뛰고 Discord에도 보류를 전달한다. publish 자체가 실패했다면 보류 시간에도 실패 알림으로 기록한다.

허용 시간에 이미 시작한 배포가 실패하면 이전 상태 복구는 보류 구간에도 시도한다. 복구를 이용해 새 release를 추가 배포하지 않으며, 이 경우 결과는 성공이나 단순 보류가 아닌 실패·복구 판정으로 기록한다.

## 비공개 백업과 운영 검증 준비

쌍 배포는 GHCR 발행 → AR 미러 준비 → protected home 확인 → Cloud Run runtime·private probes → 홈 runtime·public probes 순서다. 준비 발행은 보류 중에도 가능하며 런타임은 각 변경 직전의 시간 가드로 차단한다. 준비 오류를 deferred로 숨기지 않는다. 배포 성공 알림은 양쪽 readiness가 통과한 때만 paired다.

GCP 부트스트랩은 `ZIPER_GCLOUD=<gcloud 경로> python3 scripts/bootstrap-gcp-production.py`로 명시 실행한다. 비밀 원본은 로컬 .config/ziper/deployment이고 값은 출력하지 않는다. source protection과 전용 WIF 조건을 먼저 설정하며 CI 장기 GCP 키는 만들지 않는다. 비용 cap은 Cloud Run 범위이며 지출 0원의 보장은 아니다.

`deployment/home/recovery.py`는 root 전용 lease로 집어 app만 복구한다. 독립 systemd timer를 설치하고, 실행 중인 app에 seconds0 lease를 arm하여 다음 tick의 already_running과 lease 제거를 실제 대조한 후에만 stop한다. `scripts/observe-production-e2e.py`는 token을 private 파일에서 읽고 origin·release·분 표본·전이·단조 시계를 보존한다. 예정 backup은 circuit failover 성공으로 계산하지 않는다. 자세한 결정은 [ADR 0008](adr/0008-private-cloud-run-and-production-e2e.md), 실행 범위는 PR #1과 날짜별 증거를 따른다.

WIF 실패 시 `scripts/inspect-oidc-claims.py`는 GitHub 발급 토큰을 메모리에서만 해석하고 repository ID·ref·environment·subject·workflow 참조만 출력합니다. JWT·Bearer credential·원본 응답은 저장하거나 artifact로 올리지 않습니다. 제공자 조건은 이 실제 claim과 대조한 뒤 수정하며 조건 거부를 우회하기 위해 main/production 경계를 제거하지 않습니다.

`install-home-control.py`는 기본값이 계획만 생성합니다. 검토한 main 조상 SHA의 공개 코드·정책·timer 아홉 파일만 작은 ASCII chunk로 전달하고 원격 해시가 일치할 때 공통 잠금 아래 설치합니다. 실제 설치는 `--install` 명시와 로컬 시간 가드가 필요하며 비밀·이미지는 보내지 않습니다. 설치 후 scheduler와 private/public readiness는 별도로 검증합니다.

2026-11-07 GitHub OIDC 설정 API에서 Server 저장소의 `use_immutable_subject=true`와 owner/repository ID를 포함한 prefix를 확인했습니다. [GitHub 공식 설명](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)에 맞춰 WIF의 정확한 subject를 갱신하며 repository ID·main ref·production 환경 제한을 보존합니다. bootstrap은 알려진 구형 조건만 이행하고 다른 조건·issuer·mapping 변경은 중단합니다. 갱신 뒤 provider readback과 실제 Actions 인증을 각각 확인합니다.

독립 복구 timer 정의는 `deployment/home/systemd/`가 소유합니다. 검토된 설치 후 root에서 `systemctl daemon-reload`와 `systemctl enable --now ziper-recovery.timer`를 명시 실행하고 실제 다음 tick을 기다립니다. timer는 매분 root 전용 lease만 확인하고 lease가 없으면 앱을 건드리지 않습니다. `arm --seconds 0`의 lease 제거와 `already_running` 결과를 확인하기 전에는 장애를 주입하지 않습니다.

복구 lease가 존재하면 만료 여부와 관계없이 receiver·trusted deploy·control installer가 공통 deploy.lock 아래에서 거부합니다. 잘못된 파일이나 끊어진 symlink도 진행 허가로 취급하지 않습니다. 복구 timer/운영자의 검증된 recover가 lease를 해소한 후에만 배포합니다. 이로써 arm부터 자동 복구까지 컨테이너가 다른 배포로 교체되는 경합을 막습니다.

예약 종료 후 Windows·Ubuntu가 실행 중이어도 기존 unless-stopped 컨테이너가 종료 상태를 유지한 사례를 확인했습니다. 새 release는 [ADR 0009](adr/0009-resume-after-scheduled-boot.md)에 따라 app·전용 cloudflared를 restart: always로 구성합니다. 명시적 stop 상태는 현재 daemon 안에서는 유지되므로 leased 장애 실험은 독립 timer로 복구합니다. 새 정책의 readback과 다음 실제 BIOS 부팅 관측은 구분합니다. `python3 scripts/verify-restart-policy.py --output /tmp/ziper-restart-policy.json`은 일회용 nested daemon만 재기동하며 테스트 후 해당 컨테이너·볼륨을 제거합니다.

## 새 릴리스와 시도별 Discord 증거

[ADR 0012](adr/0012-paired-deployment-receipts.md)에 따라 공개 검사에 `--expected-release "$GITHUB_SHA" --expected-origin home`을 함께 전달한다. 두 endpoint의 SHA와 origin이 일치해야 하며 이전 release의 UP 응답도 실패한다. 내부 180초 준비 한도를 유지하고 외부 프로세스 상한은 195초로 둔다.

쌍 배포 artifact 이름은 `<기존 이름>-attempt-<github.run_attempt>`이다. registry-release의 두 다운로드도 같은 이름을 쓴다. Source CI의 tested-release는 별도 CI 실행의 검증된 JAR이며 이름을 바꾸지 않는다. 첫 성공 뒤 같은 workflow run을 전체 재실행하여 동일 SHA·config digest·JAR와 별도 Discord 메시지를 대조한다. 신규 dispatch로 변경된 main을 선택하지 않는다. 다음 실행 전 현재 release와 배포 잠금을 재확인한다.

Discord는 wait=true POST 한 번, 같은 메시지 GET으로 채널·내용·ID를 대조한다. GET만 네트워크 오류·429·5xx에 최대 3회, 요청당 10초, 간격 2초로 제한한다. 인증·내용 불일치에는 재시도하지 않는다. `discord-deploy-receipt-attempt-N`에 비밀 없는 영수증을 남기며 unknown·posted는 confirmed가 아니다. 알림 실패만으로 서버를 다시 배포하지 않는다. 메시지 저장 확인은 개인 기기의 푸시 수신 증거가 아니다.

무료 Bot Fight Mode가 보호 origin의 자동 검사를 관리 챌린지로 처리한 기록을 확인했다. 사용자가 zone 전체 영향과 tocktock 영향을 확인하고 해당 기능을 직접 OFF로 변경했다. 예외 결정·되돌리기·읽기 토큰 권한과 검증 한계는 [ADR0013](adr/0013-free-bot-fight-mode-and-machine-probes.md)을 따른다. Access 공개 bypass를 추가하지 않는다. 후속 Actions200과 익명403을 각각 확인한 후에만 쌍 배포를 시작한다.

Cloud SDK592의 run services/revisions describe는 없는 객체에 NOT_FOUND 대신 `ERROR: (gcloud.run.<kind>.describe) Cannot find <kind> [<요청 이름>]`을 반환할 수 있다. missing 조회에서 요청 명령·이름까지 정확히 일치한 형식만 부재로 허용한다. 권한·인증 오류를 먼저 분류하며 추가 문구·다른 리소스·불명확한 결과는 계속 실패한다. 이는 읽기 경계의 최초 생성 판단이며 배포 쓰기 재시도를 허용하지 않는다.
