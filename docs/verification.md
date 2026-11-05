# 검증 조건과 실제 확인 범위

## 대상과 경계

- 저장소: **[JECT-Study/Ziper-5th-Infra](https://github.com/JECT-Study/Ziper-5th-Infra)**
- 로컬 경로: `/Users/kangminjun/Documents/Projects/Ziper-5th-Infra`
- 작업 브랜치: `codex/home-circuit-breaker`
- 정책: [ADR 0001](adr/0001-home-circuit-breaker.md)
- 이번 작업은 위 Infra 저장소에만 코드·설정·ADR·검증 기록을 추가했다. `Ziper-5th-Server`의 기존 작업 파일은 수정하지 않았다.

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
