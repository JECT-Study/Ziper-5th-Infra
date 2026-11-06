# 2026-11-07 nightly walkthrough

[기계 판독 상태](evidence/2026-11-07/e2e-status.json)의 운영 E2E는 **미완료**다. 기존 홈 릴리스는 정상 응답하지만 GitHub Actions가 보호 origin에 접근하면 Cloudflare의 브라우저 challenge가 반환되어 쌍 배포가 사전 조건에서 중단된다. 새 Cloud Run runtime과 Worker를 배포하거나 장애를 주입하지 않았다. 로컬 검사·이미지 준비 성공을 운영 배포 성공으로 계산하지 않는다.

이 문서·ADR·배포 구현·정제한 증거의 소유 위치는 **Ziper-5th-Infra**다. Server에는 앱·응답 계약·고정 SHA의 수동 workflow 진입점만 둔다. 원래 Server 작업 디렉터리의 사용자 수정은 보존하고 별도 worktree에서 작업했다. 실행별 최종 판정은 [Infra PR #1](https://github.com/JECT-Study/Ziper-5th-Infra/pull/1)에 연결한다.

현재 Source main은 `03f60eeb6206da1b4cd0aa9f05f75f03510e485a`이며 [main CI42301615516](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42301615516)이 성공했다. caller의 `uses`와 `infra_sha`는 모두 실제 Infra main `bcc852e5884bbb0d22f8fd651984441faafcd734`를 가리킨다. [pin 조회 증거](evidence/2026-11-07/source-main-pin.json)를 보존했다. 이 Source의 runtime 배포는 아직 시도하지 않았다. 이번 보고서·읽기 전용 경계 probe는 runtime workflow를 바꾸지 않으므로 그 문서 commit으로 pin을 다시 바꿀 필요는 없다.

## 실제 확인 범위

| 항목 | 실제 확인 결과 | 증거와 한계 |
| --- | --- | --- |
| GHCR 전달 방식 | CI의 tested JAR로 발행하고 홈은 exact manifest digest를 pull하도록 구현·병합 | [ADR0007](adr/0007-ghcr-home-delivery.md). 새 registry 경로의 실제 홈 앱 배포는 미실행 |
| 같은 이미지 준비 반복 | Source `6df199895f35781dd47a43d2166e581a14e44f5c`의 두 수동 실행 성공, 동일 metadata 유지 | [preparation-repeat.json](evidence/2026-11-07/preparation-repeat.json). 종료 시간대 runtime은 보류, home job 생략 |
| 최신 runtime 시도 | Source `1536b7d926953c4d3f32145a18e9e9cd632aa6f6`/Infra `bb929769d23b60ca2990812c6a2f80e22b444d53`의 발행·AR 미러 성공, 보호 origin403으로 중단 | [42296858319](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42296858319), attempts1/2. Cloud Run deploy·home deploy 미실행 |
| Google 인증 | 실제 GitHub OIDC WIF와 AR 미러링 통과 | [preparation-latest.json](evidence/2026-11-07/preparation-latest.json). Cloud Run 앱 startup·DB 연결·Worker ID token 교환 증거와 별개 |
| 비용 설정 | Cloud Run native cap 월 KRW1,000, CONFIGURED 조회 | [spend-cap.json](evidence/2026-11-07/spend-cap.json). 집계 지연·AR/Secrets 비용·실제 청구액·0원 보장은 검증하지 않음 |
| Cloud Run runtime 존재 | 07:02 KST provider 조회에서 ziper-backup 서비스 없음 확인 | [cloud-run-runtime-scope.json](evidence/2026-11-07/cloud-run-runtime-scope.json). 준비한 Secret·이미지·IAM과 실행 중인 앱을 구분 |
| 현재 홈 공개 health | 07:00 KST 무렵 `/livez`·`/readyz` 3쌍 연속 정상 | [home-public-health-current.json](evidence/2026-11-07/home-public-health-current.json). 200·리다이렉트 거부·JSON UP·no-store·쿠키/캐시·크기 계약을 실제 검사기로 확인. 기존263 릴리스이며 Worker 경로 아님 |
| 06시 장비 복귀 | 설정된 BIOS 일정의 시간대에 Windows 부팅 시각과 이미 실행 중인 Ubuntu 확인. 기존 집어 app·전용 tunnel은 정지 상태여서 수동 복구 | [boot-recovery-scope.json](evidence/2026-11-07/boot-recovery-scope.json). 첫 정상 관측06:10:55 KST. BIOS가 원인이었음을 독립 검증하거나 자동 앱 복구·600초 SLA 성공으로 계산하지 않음 |
| 재기동 정책 | 새 compose의 app·전용 tunnel을 restart: always로 변경, 격리 Docker29.6.2 daemon에서 차이 확인 | [ADR0009](adr/0009-resume-after-scheduled-boot.md), [restart-policy.json](evidence/2026-11-07/restart-policy.json). 현재 기존 릴리스는 unless-stopped. 새 정책의 다음 전체 BIOS 부팅 미검증 |
| trusted control | 검토된 아홉 파일을 설치하고 해시 대조 | [home-control-installation.json](evidence/2026-11-07/home-control-installation.json). 배포 코드·timer 설치이며 새 앱 배포 성공 아님 |
| 독립 복구 timer | 무해한 seconds0 lease 이후 다음 systemd tick이 already_running을 기록하고 lease 해소 | [recovery-timer-setup.json](evidence/2026-11-07/recovery-timer-setup.json), [proof](evidence/2026-11-07/recovery-timer-proof.json). 실제 정지 앱 복구는 미실험 |
| Discord | 준비 보류 알림 두 건의 지정 채널·메시지 ID 확인 | [preparation-repeat.json](evidence/2026-11-07/preparation-repeat.json). 새 쌍 배포 성공 알림·사용자 클라이언트 표시·Sentry issue bot 알림은 별개 |
| Infra main 보호 | 관리자에게도 보호 강제, PR 예외는 joonamin 한 명. CODEOWNERS·리뷰1명·stale 무효화·마지막 push 승인·strict CI·force push/삭제 금지 보존 | [개인 예외 재조회](evidence/2026-11-07/branch-protection-owner-bypass.json), [ADR0010](adr/0010-owner-only-review-bypass.md). [이전 snapshot](evidence/2026-11-07/branch-protection.json)은 관리자 전체 우회였다. 다른 관리자 로그인 거부·파괴적 force push는 직접 실험하지 않음 |
| Sentry 접근 구성 | Sponsored Team, 비공개 프로젝트, Open Membership 꺼짐, ziper팀→ziper-server, fakedev팀→client/server 조회 | [sentry-scope.json](evidence/2026-11-07/sentry-scope.json). 초대 명단·다른 구성원 로그인 E2E·이번 실행의 실제 오류 수집과 Sentry issue 알림은 미검증 |
| Sentry Uptime | 무료1개를 기존 tocktock이 사용 중, 집어 monitor0개 | 같은 증거. 기존 monitor 보존·유료 활성화 없음. 미저장 양식은 운영 monitor가 아님 |
| 로컬 회로·배포 검사 | Workers32·Node10·Python64, 합계106개와 타입·린트·번들 통과 | runtime pin의 [Infra main CI42300015630](https://github.com/JECT-Study/Ziper-5th-Infra/actions/runs/42300015630)은99개, 이후 경계 probe2개·보안 API2개·재기동과 전송3개 추가. 가짜 시간·응답·CLI와 실제 로컬 workerd/SQLite 범위. 운영 failover는 미검증 |

## 확정한 오류와 남은 가설

기존 큰 SSH archive 전달은 실제 실행에서 Broken pipe로 끝났다. GHCR pull로 이미지 전달을 변경했으며 SSH에는 작은 제어 metadata와 짧은 job token만 보낸다. 로그만으로 물리적 종료 원인을 확정하지 않는다. GHCR manifest digest와 OCI config digest는 종류가 달라 각각 기록한다.

실제 GitHub OIDC subject는 저장소 숫자 ID를 포함하는 불변 형식이었다. 알려진 구형 subject 조건을 이행한 뒤 실제 Google 인증과 미러링에 성공했다. 저장소 ID·main·production 조건은 유지한다.

06시 Windows·Ubuntu 기동 후 기존 unless-stopped 컨테이너가 정지 상태를 유지했다. 기록된 이미지·release·labels를 대조한 기존 두 컨테이너만 시작해 복구했다. 어떤 종료 명령이 정지 상태를 남겼는지는 확정하지 않았다. 새 always 정책은 독립 Docker 실험으로 확인했지만 실제 다음 장비 부팅은 남아 있다.

현재 배포 차단은 **정상 자격과 다른 값이 전달된 문제로 설명되지 않는다**. [원래 읽기 실행](evidence/2026-11-07/protected-origin-before.json)과 [새 진단 실행](evidence/2026-11-07/protected-origin-challenge.json)을 구분한다. 새 실행은 알려진 정상 자격과의 비교가 true이고 HTTP403·`cf-mitigated: challenge`다. 공식 [challenge 응답 식별](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)과 일치한다. 어느 보안 제품·규칙이 발생시켰는지는 Security Events 확인 전에는 확정할 수 없다. 고정 User-Agent·Accept만 추가해도 challenge는 계속됐다.

과거 실행42222169766의 HTTP530은 당시 상세 오류 코드가 없었다. Tunnel 기동 지연은 여전히 가설이며 이번403과 같은 원인이라고 단정하지 않는다. `/livez`·`/readyz` 경로는 바꾸지 않았다. Actuator content negotiation과 제한 공개 준비 대기는 이미 수정된 계약을 유지한다.

## 사용자가 필요한 부분

먼저 등록된 자격의 **보안 API 읽기 진단**을 실행한다. API의 보안 이벤트 조회 권한·호환성은 아직 미검증이다. 이 경로에서도 조회되지 않으면 Cloudflare 관리 세션 또는 별도 읽기 전용 자격이 필요하다. 현재 자동화 브라우저는 로그인 화면이며 사용 중인 외부 Chrome 세션과 별개다. Security Events에서 `origin-ziper.joonamin.dev`, 위 실행 시각·403을 대조해 차단 제품·규칙을 확인한다. 토큰·비밀번호를 채팅에 보내거나 기존 Secret을 모두 재등록할 필요는 없다.

확인된 규칙에 대해 집어 origin의 자동화 요청에 필요한 범위만 조정한다. Access의 전용 Service Auth 인증은 유지하며, tocktock까지 영향을 주는 전역 보안 해제는 하지 않는다. 제품에 따라 무료 플랜에서 hostname 예외를 지원하지 않을 수 있으므로 이벤트 확인 없이 특정 skip 설정이 가능하다고 약속하지 않는다.

GitHub 조직의 Actions 추가 사용 예산0원 설정은 조회 권한이 없어 확인하지 못했다. 실제 청구액 검증과 Cloud Run cap 조회를 같은 증거로 취급하지 않는다.

이후 별도 결정은 집어의 지속 Uptime 검사 공급자와 초대 명단이다. Sentry의 기존 무료 monitor를 삭제하거나 유료 플랜을 켜지 않았다. Discord 배포 webhook은 이미 동작하므로 이를 새로 만들 필요는 없다.

## 차단 해소 후 실행 순서와 완료 조건

1. Infra main CI 성공 후 `Verify Cloudflare access manually`를 읽기 전용 실행한다. 자격 비교 true·protected200, 인증 없는 protected403을 확인한다. challenge가 남으면 배포를 재시도하지 않는다.
2. Source 두 pin이 실제 성공한 Infra SHA를 가리키고 Source main CI도 성공했는지 확인한다. `Deploy production manually`를 수동 실행한다. 이전 실행이 모호하게 끝났으면 먼저 provider·revision을 읽고 배포 명령을 맹목적으로 재발행하지 않는다.
3. Cloud Run private Ready·실제 DB readiness·동일 image config·release, 홈의 GHCR pull·strict public health를 확인한다. 성공 Discord 응답의 지정 채널·메시지 ID를 수집한다. 서비스가 생기면 invoker 권한을 프로젝트에서 해당 서비스로 좁히고 재조회한다.
4. Infra production의 실제 `BACKUP_ORIGIN`, `BACKUP_ENABLED=true`를 준비하고 main CI 후 `Deploy edge manually`를 수동 실행한다. namespace를 삭제하지 않는다. 실제 public/ops·직접 origin 인증·Google ID token 호출을 확인한다. 준비한 `verify-production-boundaries.py`는 이 시점에 실행하며 아직 실제 실행하지 않았다.
5. 실제1분 alarm의 고유한10개 정상 슬롯을 확보한다. 짧은 집어 app 장애와 동시 읽기 요청을 넣어 사용자 실패가 표본을 늘리지 않고 CLOSED를 유지하는지 확인한다. 회복 후 정상 슬롯을 다시 채운다.
6. 독립 timer와 현재 release 고정 lease를 재확인한 뒤 집어 app만 최대540초 정지한다. 컨트롤러 단조 시계 marker부터 첫 cloudrun UP200 완료까지600초 이내인지 측정한다. 최소3회 정상 backup 응답·OPEN·실패한 HALF_OPEN·timer 복구·3회 연속 정상 뒤 CLOSED/home 복귀를 기록한다. 홈 CLOSED 복귀까지600초라는 뜻은 아니다.
7. 같은 source/digest의 수동 재실행을 성공시켜 idempotence와 새 Discord 성공 메시지를 대조한다. 다음 실제03–06시 장비 주기, 공통 DB 장애·장기 outage·실제 부하·청구액은 별도 범위로 남긴다. 준비 반복 두 번으로 이 조건을 대체하지 않는다.

## 운영상 논의할 한계

홈·백업이 같은 Supabase DB를 쓰므로 DB 전체 장애는 failover로 해결되지 않는다. 성공한 health만으로 모든 업무 API가 정상임을 보장하지 않는다. 사용자 쓰기를 다른 origin으로 자동 재전송하지 않으며 결과가 불명확한 쓰기는 중복 실행하지 않는다. 많은 사용자 실패가 표본을 증폭하는지, 실제 alarm 지연과 cold start가600초 목표에 미치는 영향은 운영 장애 실험에서 확인해야 한다.

리뷰: gpt-6-astra가 진단 코드·정제된403 증거를 독립 검토하고 Node10개를 격리 실행했다. 자격 비교는 지정한 기준값과의 동일성만 증명하고, 본문 오류 코드는 원인 확정이 아니라 단서라는 제한을 확인했다. 다른 공급자 모델과 전체 transcript 경로는 제공되지 않았으므로 해당 범위의 교차 검토를 했다고 주장하지 않는다. 최종 기록은 [계획](evidence/2026-11-07/plan.md)·[결정 로그](evidence/2026-11-07/decisions.tsv)를 따른다.

## 보안 API 후속 조회와 기존 재기동 정책의 적용 준비

[실제 API 조회](evidence/2026-11-07/cloudflare-security-readback.json)는 기존 Worker token을 사용했습니다. zone·security_level·browser_check 조회는200, Bot 설정 조회는403, Security Events GraphQL은200 응답 안에서 authorization 거부였습니다. security_level=essentially_off·browser_check=on은 현재 설정이며 과거 challenge 원인을 확정하지 않습니다. 보안 이벤트를 읽을 관리 세션 또는 별도 읽기 자격이 필요합니다. 전용 토큰을 선택한다면 해당 계정 Account Analytics Read와 joonamin.dev Zone Read를 Infra production Secret CLOUDFLARE_SECURITY_API_TOKEN에 등록합니다. 기존 배포 token 권한은 확대하지 않습니다.

새 이미지 배포와 독립적으로 기존 두 컨테이너의 정책만 정합하는 [ADR0011](adr/0011-reconcile-existing-restart-policy.md)과 [실제 읽기 계획](evidence/2026-11-07/existing-restart-plan.json)을 추가했습니다. 아직 이 계획의 적용은 CI 뒤 별도로 실행합니다. 기존 파일·시작 시각 보존과 반복 no-op을 확인한 뒤에만 적용 성공으로 기록합니다. trusted rollback은 과거 compose의 unless-stopped를 다시 적용할 수 있어 rollback 뒤 정책 readback도 필요합니다.
