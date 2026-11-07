# 검증 조건과 실제 확인 범위

## 최신 판정: 2026-11-07

[Nightly walkthrough](nightly-walkthrough-2026-11-07.md)의 표와 [원본 증거](evidence/2026-11-07/)가 최신 상태입니다. GHCR/AR 준비를 같은 release로 두 번 성공했지만 새 runtime 쌍 배포·Worker 배포·실제 장애 전환은 미완료입니다. 최신 읽기 전용 Actions 실행은 자격 일치 true와 HTTP403, `cf-mitigated: challenge`를 기록했습니다. 정확한 Cloudflare 규칙은 보안 API 또는 대시보드 이벤트 확인이 필요합니다. 아래 과거 실행은 그 당시의 범위이며 최신 운영 성공으로 승격하지 않습니다.

로컬 최신 검사는 Workers32·Node10·Python64, 총106개와 타입·린트·번들입니다. runtime pin의 main CI42300015630은99개이며 이후 경계 probe2개·보안 API2개·재기동 정책과 전송 가드3개를 추가했습니다. 격리 nested Docker restart-policy 검증은 별도 실제 실행이며 이106개에 포함하지 않습니다. 운영 컨테이너의 다음 전체 BIOS 부팅이나 실제 Cloud Run 600초 복구를 증명하지 않습니다.

## 2026-11-06 운영 E2E 재개

20:17 KST에 실제 Server main 수동 배포 `42209209521`을 시작했다. CI gate·artifact 다운로드·이미지 패키징을 통과했지만 SSH 입력 전달 단계에서 정체됐다. 기존 이중 PowerShell 수신 경로는 4바이트 fixture를 거부했으나 128KiB에서 시간 초과됐다. 이는 작은 fixture 거부만으로 대용량 전달이 검증되지 않았음을 보여준다.

WSL에 직접 연결하는 별도 진단 키에서 128KiB·1MiB의 길이와 SHA256 일치를 확인했다. 수정 수신기에서 check 성공, 일반 명령 거부, 1MiB 전체 수신과 잘못된 archive 거부도 확인했다. [정제한 SSH 증거](evidence/2026-11-06-native-ssh-stream.json)는 개인 Access 세션을 사용한 결과이며 CI 서비스 토큰·실제 앱 배포 성공은 별도 판정한다. 로컬 검사는 기존 37개에 입력·크기·명령 경계 3개를 추가한 총 40개와 타입·린트·dry-run을 통과했다. [ADR 0004](adr/0004-native-ssh-release-input.md)에 수정 이유와 강제 명령을 연결했다.

Infra Repository Secret의 CLOUDFLARE_API_TOKEN을 실제 runner에서 사용한 [읽기 검증 42210095321](https://github.com/JECT-Study/Ziper-5th-Infra/actions/runs/42210095321)은 토큰·계정·Worker 목록·zone·route 접근을 통과했다. [원본 판정](evidence/2026-11-06-cloudflare-access.json)은 쓰기 권한·Worker 배포를 검증한 결과가 아니다. OPS_READ_TOKEN을 production 환경에 등록했고 기존 SSH Access Secret의 재등록은 요구하지 않았다.

현재 인계와 실제 판정은 [2026-11-06 nightly walkthrough](nightly-walkthrough-2026-11-06.md)를 먼저 읽는다. 아래 날짜별 기록은 실행 당시의 사실이며 이후 병합·설정 변경으로 대체된 항목을 포함한다. 최신 원본은 [nightly 증거 JSON](evidence/2026-11-06-nightly.json)으로 연결한다.

03:17 KST의 Server main 수동 실행 `42082844118`은 예약 시간에 배포를 보류하고 지정 Discord 채널의 메시지 `1567966560079843328`을 확인했다. 이미지 생성·SSH 전달·readiness 검사는 건너뛰었다. 운영 앱 배포·Worker 정상/오류 경로·Cloud Run failover·600초 목표는 아직 미검증이다.

## 대상과 경계

- 저장소: **[JECT-Study/Ziper-5th-Infra](https://github.com/JECT-Study/Ziper-5th-Infra)**
- 로컬 경로: `/Users/kangminjun/Documents/Projects/Ziper-5th-Infra`
- 초기 구현 브랜치: `codex/home-circuit-breaker`
- 정책: [ADR 0001](adr/0001-home-circuit-breaker.md)
- 초기 회로 구현은 Infra에 두었다. 이후 Server PR #13·#14에 애플리케이션 관측과 수동 진입점을 반영했다. 원래 Server 작업 디렉터리의 사용자 수정은 보존하고 별도 worktree를 사용했다.

**확인한 것은 구현의 로컬 동작이다. 운영 서비스의 장애 전환 완료를 뜻하지 않는다.** 외부 네트워크가 필요한 테스트는 가짜 오리진과 응답으로 대체했고 실제 Google·홈서버·Cloudflare 계정 리소스를 호출하지 않았다. Workers 런타임과 SQLite 저장소 자체는 로컬 workerd/Miniflare를 사용했다.

## 판정 조건과 증거

| 항목 | 통과 조건 | 실제 확인 | 범위·제한 |
| --- | --- | --- | --- |
| 실패율 | 최소 6표본, 최근 10분 슬롯의 실패율 60% 이상에서 OPEN | `test/policy.test.ts` 통과 | 가상 시간의 순수 상태 전이. 실제 10분 경과 측정 아님 |
| 경계값 | 충분한 표본에서 실패 5/10은 CLOSED, 6/10은 OPEN | 위 테스트 통과 | 연속 완전 장애의 감지 조건만 확인 |
| 짧은 장애 | 임계값 미만 오류가 새 정상 표본으로 밀려나도 CLOSED | 위 테스트 통과 | 실제 홈 네트워크 간헐 장애는 미실행 |
| 복구 FSM | OPEN 2분 후 HALF_OPEN, 정상 3회 후 CLOSED·윈도우 초기화, 중간 실패 시 OPEN | 위 테스트 통과 | 시간은 모델 입력. 실제 alarm 시각 보장은 아님 |
| 누락·늦은 응답 | 120초 초과 미관측 시 OPEN, 이전 세대·분 결과 무시, HALF_OPEN 관측 누락 시 연속 성공 초기화 | 위 테스트 통과 | 예약 후 중단된 분은 누락으로 취급 |
| 알람 중복 | 동일 분의 알람 재실행은 표본 1개, 다음 alarm 유지 | `test/worker.test.ts` 통과 | 실제 로컬 SQLite DO와 alarm helper 사용 |
| 영속 상태 | DO 인스턴스 중단 후 OPEN·저장 상태·alarm 유지 | 위 테스트 통과 | 로컬 isolate 재시작. Cloudflare 리전 장애 실험 아님 |
| 실패 증폭 | 사용자 1,000건 동시 503 이후 표본 0개, 전용 검사와 재시도 이후 1개 | 위 테스트 통과 | 1,001회 가짜 오리진 호출, 사용자 요청을 표본에 합산하지 않음. **1,000명 수용량·성능 시험 아님** |
| OPEN 라우팅 | OPEN·HALF_OPEN 중 홈으로 사용자 요청을 보내지 않음 | 위 테스트 통과 | 백업 비활성 시 503. 이미 전달 중인 요청 취소는 범위 밖 |
| 쓰기 전달 | JWT·본문 보존, 실패 후 다른 오리진으로 재전송하지 않음 | Worker·backup 테스트 통과 | 가짜 네트워크 경계 검사. 실제 DB의 정확히 한 번 쓰기는 증명하지 않음 |
| 접근 헤더 | 클라이언트의 origin 인증 헤더 제거, 홈 Access 헤더 설정, Cloud Run IAM 헤더와 사용자 JWT 분리 | 위 테스트 통과 | 실제 Access·IAM 정책의 거부/허용은 미검증 |
| Cloud Run 인증 어댑터 | 테스트용 RSA 키로 JWT 생성, Google 교환 요청·audience 검사·토큰 캐시·인증 실패 처리 | `test/backup.test.ts` 통과 | Google 응답은 가짜 ID token. 실제 Google 서명 검증·IAM 수신 성공 아님 |
| 인증 동시성 | 동시 30개 결정에서 Google 교환 1회, 갱신 중 요청은 503, 만료 lease 복구 | 위 테스트 통과 | 로컬 DO·가짜 Google 응답. 실제 토큰 엔드포인트 용량 시험 아님 |
| 배포 설정 경계 | route 생성, secret 파일 0600·비밀 출력 없음, 6가지 잘못된 설정 거부 | `scripts/deployment.test.ts` 통과 | 예약 도메인의 fixture. 운영 계정·DNS 변경 없음 |
| 타입·린트 | 생성된 binding·runtime 타입, strict TypeScript, Promise 규칙 통과 | `npm run check` 통과 | 플랫폼 서비스 설정의 정확성까지 증명하지 않음 |
| 배포 번들 | Wrangler dry-run 번들 성공 | 위 명령 통과 | 업로드·route 생성·namespace 생성하지 않음 |
| Workflow 정적 검사 | 두 Actions YAML 문법·표현식·셸 검사 | `actionlint` 통과 | GitHub 호스팅 runner에서 실행한 결과 아님 |

## 2026-11-05 실행 기록

로컬 `npm run check`를 실행해 exit code 0을 확인했다. Node.js 24.15.0, Wrangler 4.158.0, Vitest 4.1.12, `@cloudflare/vitest-plugin` 1.6.0, TypeScript 6.0 계열을 사용했다. 테스트는 정책 9개 + Worker/DO 9개 + backup 6개 + Node 배포 설정 1개, 총 **25개 통과**했다. 배포 설정 테스트 한 개 안에서 정상 설정과 잘못된 설정 6개를 검사했다. 워크플로 두 개의 `actionlint`도 exit code 0이었다.

최종 검사 이전의 테스트 과정에서 Workers가 지원하지 않는 `redirect: error` 사용을 발견해 `manual`과 상태 코드 검사로 수정했다. 네트워크 mock 응답을 다른 DO 컨텍스트에서 만들어 생기는 스트림 오류와 테스트 간 Promise 공유 문제도 바로잡고 전체 테스트를 다시 통과시켰다. 최종 성공은 이 수정 이후 실행 결과다.

`npm audit --omit=dev --audit-level=moderate`는 취약점 0개를 보고했다. 전체 개발 도구 의존성에는 minimatch에서 파생된 moderate 보고 9개가 남아 있다. [운영 문서](operations.md)의 도구 제한을 참고한다. 이를 전체 의존성 보안 검사 통과로 표현하지 않는다.

## 미실행 항목과 필요한 전제

| 항목 | 현재 상태 | 다음에 필요한 확인 |
| --- | --- | --- |
| 원격 PR/main CI | 미실행; 사용자 선택으로 로컬 우선 | 비공개 조직 Actions의 추가 과금 중단 설정 확인 후 초안을 ready-for-review로 전환 |
| main 머지·수동 배포 gate | YAML 정적 검사만 통과 | 실제 main CI 성공 SHA와 수동 dispatch를 연결해 확인 |
| 운영 Worker·DO·route | 생성·배포하지 않음 | 홈 앱 배포, 전용 origin·Access, production 환경 값·제한된 API token |
| 홈 전용 호스트 차단 | 미설정·미검증 | 토큰 없는 직접 접근 거부, Worker 자격으로 readiness 허용 |
| 운영 1분 샘플링 | 미검증 | 사용자 트래픽 없이도 실제 alarm 표본이 이어지는지 관찰 |
| Cloud Run | 기본 비활성; 리소스·청구 계정·키 미생성 | 비용 조건, private IAM, 실제 서비스 URL, cold start·동일 DB 연결 |
| 10분 내 백업 성공 | **미검증·현재 비활성 백업에서는 달성 불가** | 홈 장애 주입 시각부터 최초 백업 성공 응답까지 600초 이하 측정 |
| 운영 복구 FSM | 미검증 | 홈 복구 후 쿨다운·3회 성공·CLOSED·라우팅 복귀 추적 |
| 실제 중복 쓰기 | 미검증 | 전용 테스트 데이터로 불확실한 네트워크 실패를 주입하고 DB 결과 조회 |
| 실제 부하·비용 | 미측정 | 요청당 DO 지연·병목·계정 무료 한도와 1분 검사 비용 합산 |
| Sentry uptime·Discord | 이번 작업에서 생성·수신 확인하지 않음 | 공개 서비스 준비, 별도 uptime 설정, Discord 서버 관리 권한 |

조직 예산 조회는 현재 인증의 `admin:org` 범위 부족으로 실패했다. private main 브랜치 보호 조회도 플랜 제한 403이었다. 이를 설정 완료나 강제된 승인 절차로 표현하지 않는다.

구현 커밋 `a6804a7304e195871e2bd4b16f476366c411af5a`를 Infra 원격 브랜치에 push하고 [초안 PR #1](https://github.com/JECT-Study/Ziper-5th-Infra/pull/1)을 생성했다. [CI 기록 42049530135](https://github.com/JECT-Study/Ziper-5th-Infra/actions/runs/42049530135)의 결론은 `skipped`이며, Jobs API에서 `check` job의 `runner_id`·`runner_name`이 null임을 확인했다. 원격 runner에서 테스트를 실행한 결과가 아니며 배포도 실행하지 않았다. main 머지·review 요청은 하지 않았다. 이 증거 추가는 문서만의 후속 변경이다.

## 운영 논의 시나리오

| 시나리오 | 현재 동작 | 함께 정할 지점 |
| --- | --- | --- |
| 같은 장애를 동시 사용자 다수가 경험 | 사용자 실패는 표본에 합산하지 않음 | 현재 방식으로 실패 증폭 차단. 트래픽 오류율 경보는 별도 정책 |
| 한 분의 짧은 네트워크 오류 | 실패 표본 하나; 임계값 미만이면 홈 유지 | false positive를 줄이려고 재시도할지, 실패를 숨길 위험이 큰지 |
| 과부하로 readiness 실패 | 여러 분 임계값을 넘으면 OPEN | 홈 과부하와 공용 DB 과부하 구분·DB 연결 수 예산 |
| readiness 정상, 특정 API만 실패 | 회로는 CLOSED 유지 | 업무 오류율 경보·수동 전환·별도 회로의 필요성 |
| Supabase 공통 장애 | 양쪽 앱이 실패할 수 있음 | failover가 도움 되지 않는 의존성 장애의 분류·사용자 응답 |
| Cloud Run cold start·인증 오류 | 백업 요청 실패 시 503, 홈 우회·쓰기 재전송 없음 | 0원 우선 조건과 복구 지연·첫 요청 실패의 허용 범위 |
| Cloudflare/DO 한도 또는 관측 중단 | 상태가 불명확하면 503, stale 시 홈 회로 OPEN | 일관성 우선 유지 또는 운영자가 명시적으로 우회할 기준 |
| 홈 복구 후 재장애 | HALF_OPEN 실패 한 번에 OPEN 재전환 | 3회 readiness가 충분한지, 실제 업무 검사가 추가로 필요한지 |

## 2026-11-06 CI 수신기 접속 검증

Server Repository secrets에서 CF_ACCESS_CLIENT_ID와 CF_ACCESS_CLIENT_SECRET 이름을 확인했다. 값은 조회하지 않았다. CI 키만 사용하고 개인 키와 agent를 배제한 SSH에서 `check`는 ZIPER_CI_RECEIVER_READY와 exit 0을 반환했다. 같은 키의 일반 명령은 출력 없이 거부됐다. 유효한 deploy 명령에 잘못된 압축 fixture를 보내자 원격 Python tar parser의 ReadError로 거부됐다. Access는 기존 개인 로그인 세션을 사용했으므로 서비스 토큰 인증 성공으로 표현하지 않는다.

압축 경로, 파일 종류, 중복, 전체 크기와 metadata 크기 검사 4개를 추가해 Infra 총 37개 로컬 테스트 및 타입, 린트, dry-run을 통과했다. 이미지 내부 JAR 해시 대조도 수신기에 추가했다. Windows 수신기는 전송을 2GB로 제한한다. 앱 배포, Worker 정상 및 오류 경로, Discord 수신은 여전히 미검증이다.

Server에 main 수동 진입 workflow를 작성하고 검사와 actionlint를 통과했다. 현재 pin은 Infra 후보 SHA이므로 성공한 Infra main CI가 생긴 뒤 승인된 main SHA로 갱신하기 전에는 배포 gate를 통과하지 못한다.

## 2026-11-06 예약 운영 구현 중간 증거

Infra에 일정 설정·예약 라우팅·SQLite 최근 전이·전용 토큰의 읽기 전용 조회·배포 시간 가드·Discord 전송 CLI를 추가했다. `npm run check`는 Worker/정책 26 + backup 6 + 배포 설정 1, 총 33개 테스트와 타입·린트·dry-run을 통과했다. Discord CLI는 실제 채널 수신을 아직 검증하지 않았으며 workflow 연결도 후속 작업이다. main 수동 쌍 배포·watchdog·실제 E2E는 미완료다.

Server `production` 환경을 생성하고 main 브랜치만 허용하는 정책을 API로 재조회했다. 사용자 등록 후 Secret 이름 `DISCORD_DEPLOY_WEBHOOK_URL`의 존재만 확인했다. 값은 조회하지 않았다. SSH의 정적 응답 확인은 성공했다. 원격 Docker 조회에서는 집어 전용 cloudflared만 실행 중이고 current-version 기록은 없었다. 앱 배포 성공을 뜻하지 않는다. GCP `ziper-production`은 ACTIVE이지만 billingEnabled는 false였다. GCP 리소스를 새로 생성하거나 장애를 주입하지 않았다.

공식 gitleaks v8.30.1 도구의 다운로드 SHA256을 확인한 뒤 기존 전체 3개 Git 커밋을 검사했고 발견 0개였다. 현재 수정 내용은 커밋 이후 이력 전체 검사로 다시 확인한 뒤 공개 여부를 결정한다. 공개 전환은 아직 하지 않았다.

## 2026-11-06 01:07 KST 배포 전 실환경 확인

[정제된 원본 판정 JSON](evidence/2026-11-06-predeployment.json)을 PR #1에 연결한다. 공개 HTTPS 점검은 `2026-11-05T16:07:31Z`에 HTTP 502로 실패했다. SSH·Docker는 정상이고 집어 cloudflared만 실행 중이며 앱과 current-version은 없다. 따라서 실제 배포·백업 전환 E2E 성공 증거는 아직 없다. 이전의 HTTP 403 관찰과 별개의 최신 실행이다.

Server production에는 웹훅·전용 CI SSH 키·base64 인코딩한 호스트 키 고정 Secret이 존재한다. CF_ACCESS_CLIENT_ID/SECRET은 아직 API 이름 목록에서 확인되지 않았다. GCP 청구 연결은 true로 재조회했으며 Cloud Run은 생성하지 않았다.

Infra 공개 전환 후 main 보호를 실제 적용·재조회했다: force push/삭제 금지, 관리자 우회 금지, 최신 check 성공, 승인 1개, CODEOWNERS 리뷰, 새 push 시 승인 초기화, 마지막 push 승인, 반영 사용자 joonamin 제한이다. CODEOWNERS는 PR #1에 있으나 아직 main에 없으므로 소유자 지정은 머지 후 활성화된다. 현재 PR 작성자가 joonamin이며 GitHub는 자기 PR 승인을 허용하지 않는다. 이 보호를 우회하거나 승인한 것으로 기록하지 않는다.

홈 배포 재사용 workflow와 전송·수신 스크립트는 작성하고 actionlint/문법 검사를 수행했다. Windows 제한 수신기·키의 원격 설치, CI 정책 허용, Server main 진입점과 실제 수동 실행은 미완료다. 로컬·정적 통과를 실환경 배포 통과로 대체하지 않는다.

## 2026-11-06 22시 수동 배포 진단

Server 실행 [42222169766](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42222169766)은 실제 SSH 스트림, OCI config digest 대조와 홈 readiness를 통과했다. 공개 검사는 cloudflared Started 로그 약 0.443초 뒤 HTTP 530으로 실패했다. 당시 상세 오류가 없어 Tunnel 기동 지연은 가설이며 사후 정상 응답으로 과거 원인을 확정하지 않는다. 이후 별도 실제 검사에서 공개 API와 인증한 origin이 릴리스 `263558f6f2cf97ad717f71335c95c49214ae908c`로 200을 반환하고, 인증 없는 origin은 403이었다. Actions 전체 성공과 별도 사후 검증을 구분한다.

Worker 실행 [42222983368](https://github.com/JECT-Study/Ziper-5th-Infra/actions/runs/42222983368)은 origin 사전 검사에서 실패하여 Worker 업로드를 실행하지 않았다. 기존 검사기가 모든 예외를 같은 문구로 가려 원인을 확정할 수 없었다. 단계·상태 코드를 기록하는 읽기 진단을 추가했으며 운영 원인은 다음 실행 증거로 판정한다.

## 공개 readiness 수정의 판정 범위

확정된 문제는 Accept 미지정과 application/json 전용 검사 간의 불일치, 그리고 기존 배포 흐름의 공개 준비 대기 부재다. `/livez`·`/readyz` 경로는 유지한다. 운영 중 관찰한 200과 해당 SHA의 일치는 사후 증거이며 실행 42222169766의 실패를 성공으로 바꾸지 않는다. Infra main cf8e077의 wrapper는 ValueError까지 재시도하므로 인증·계약 위반을 즉시 종료하는 요청 조건을 만족하지 못해 제거했다. 오류 분류와 가상 시간 검사는 Server 기존 health 검사·테스트로 모았다.

변경 후 로컬 검사와 CI 결과는 PR에 기록한다. 새 정책의 실제 운영 530 복구, 새로운 Server/Infra 조합의 main 배포 및 성공 Discord 알림은 이번 작업에서 실행하지 않았다. Cloud Run 전환·600초 목표·전체 FSM 검증과도 별개의 범위다.

## 2026-11-07 새벽 운영 준비

Server 실행 [42250905425](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42250905425)의 제한 SSH·일반 명령 거부·1MiB 검사는 모두 통과했지만 실제 archive 전달은 Broken pipe/255로 끝났다. 이 로그는 큰 전달 중 연결 종료를 뜻하며 서버의 물리적 종료 원인을 확정하지 않는다. GHCR exact digest pull로 경로를 바꾸고 작은 제어 JSON만 SSH로 보낸다. legacy archive 엔드포인트는 제거한다.

통합 로컬 검사는 Worker26·backup6·Node1·이미지5·registry14·운영관측10·Cloud Run16, 총78개와 타입·린트·번들을 통과했다. 가짜 CLI와 HTTP fixture를 사용한 경계 검증이며 운영 발행·배포·600초 증거가 아니다. 별도 검토가 재현한 터널 실패 롤백 누락과 늦은 시간 가드를 수정하고 실제 deploy.sh fixture로 다시 확인했다.

실제 설정에서 WIF ACTIVE와 main·production·저장소 숫자 ID 조건, AR 전용 저장소, 두 runtime Secret과 전용 계정을 조회했다. Cloud Run 앱 런타임과 Worker는 아직 반영하지 않았다. 03:00 이후 공개 두 probe의 530을 관측했으며 06시 이후의 새 코드 운영 E2E와 구분한다. 계획과 결정 이력은 [실행 계획](evidence/2026-11-07/plan.md), [결정 로그](evidence/2026-11-07/decisions.tsv)에 있다.

## 2026-11-07 기존 컨테이너 정책 정합

검토된 main317bba3와 CI42310352848 성공 뒤 실제 두 컨테이너를 always로 정합했습니다. 적용2건·반복0건 모두 ID·StartedAt·참조 파일을 보존했고 공개 health3쌍을 통과했습니다. [실제 적용](evidence/2026-11-07/existing-restart-applied.json)·[반복](evidence/2026-11-07/existing-restart-repeat.json)·[공개 검사](evidence/2026-11-07/home-public-health-after-policy.json)를 참조합니다. 새 앱·Cloud Run·Worker 배포와 fault E2E는 미완료입니다.

## 새 이미지 쌍 배포와 반복 검증의 판정

[ADR 0012](adr/0012-paired-deployment-receipts.md)의 구현은 release·origin 일치와 시도별 artifact·Discord POST/GET 영수증을 추가한다. 코드·로컬·CI·운영 결과를 구분하고 실제 실행 전에는 이 절을 통과 증거로 읽지 않는다. 최초 전체 성공 뒤 같은 run의 전체 재실행도 성공해야 반복 검증을 통과한다. 각 시도의 source/Infra SHA, GHCR/AR 식별자, runtime probes, 보류 여부와 서로 다른 Discord message ID를 PR #1에서 대조한다. Worker 전환·장애 주입·600초 복구는 별도 미검증 범위다.
