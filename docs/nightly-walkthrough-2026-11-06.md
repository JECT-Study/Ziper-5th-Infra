# Nightly walkthrough · 2026-11-06

운영 E2E는 아직 완료되지 않았다. 로컬 Worker 테스트·원격 CI·SSH 수신기 사전 검증과 실제 운영 배포를 구분한다. 실행 최종 판정은 이 문서와 [정제한 원본 JSON](evidence/2026-11-06-nightly.json)에 기록한다.

## 저장소와 설정 위치

인프라 본체·배포 수신기·재사용 workflow·예약 운영 설정·ADR·검증 결과는 **Ziper-5th-Infra**에 있다. Server에는 애플리케이션과 main의 수동 workflow 진입점만 둔다. 원래 Server 작업 디렉터리의 사용자 수정은 보존했다.

- Infra [PR #1](https://github.com/JECT-Study/Ziper-5th-Infra/pull/1)은 main에 병합했다. main SHA `974c6b74b0e0d52c2250e5a0dbfd1138151566e5`의 [CI](https://github.com/JECT-Study/Ziper-5th-Infra/actions/runs/42080482858)가 성공했다.
- Server [PR #13](https://github.com/JECT-Study/Ziper-5th-Server/pull/13)은 develop에 병합했다. 고정 Infra SHA를 반영한 [PR CI](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42081104306)는 harness·quality·test·container-smoke가 모두 성공했다. PR 정책도 통과했다.
- Server [PR #14](https://github.com/JECT-Study/Ziper-5th-Server/pull/14)는 develop을 처음 main에 반영했다. [PR CI](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42081744774)와 develop push CI 모두 성공 후 관리자 bypass로 병합했다. main SHA는 `b3f0fd7eb74a724caadcc90a13adbdf171b20c4d`다. 별도 main CI·수동 실행 판정은 아래 실행 결과에 기록한다.

## 변경한 보호 정책

Infra main의 CODEOWNERS는 `@joonamin`이다. 일반 PR의 승인·검사 요구를 유지하고 사용자 요청으로 관리자 bypass를 허용했다. Server develop·main도 기존 규칙을 유지하면서 관리자 강제를 해제했다. 최초 병합에 관리자 bypass를 사용했으며 이를 사람의 리뷰 승인으로 기록하지 않는다.

Infra의 force push·삭제 금지는 별도 활성 ruleset `26637239`로 보호한다. 이 ruleset의 bypass 대상은 비어 있다. 현재 설정은 API로 재조회했다. 실제 main 이력을 손상하는 force push나 삭제 실험은 수행하지 않았다. 정책 원본은 [config/github-main-history.json](../config/github-main-history.json), 결정은 [ADR 0003](adr/0003-owner-review-and-admin-bypass.md)에 있다.

## 검증 범위

| 검증 조건 | 확인한 범위 | 최종 판정 |
| --- | --- | --- |
| Worker 정상·오류 경로, 실패 표본 중복 방지, FSM | 로컬 workerd·SQLite DO·가짜 origin으로 검증 | 로컬 통과. 운영 Worker 미배포 |
| 10분 이내 백업 전환 | 실제 홈 장애와 Cloud Run 성공 응답까지 측정해야 함 | 미검증. Cloud Run 미생성 |
| 홈 복구 후 HALF_OPEN·CLOSED·홈 복귀 | 실제 alarm·상태 조회·응답 origin을 대조해야 함 | 미검증 |
| 전용 SSH 키의 제한 명령 | check 성공, 일반 명령과 잘못된 archive 거부 | 사전 검증 통과. 개인 Access 세션 사용 |
| GitHub CI 서비스 토큰 SSH 인증 | runner에서 전용 서비스 토큰으로 연결해야 함 | 미검증 |
| 실제 앱 배포와 공개 readiness | 동일 release SHA의 이미지·응답 헤더·DB 준비 확인 필요 | 미검증 |
| Discord 수신 | 실제 보류 실행에서 webhook 응답의 채널 ID와 메시지 ID 확인 | 보류 알림 통과. 배포 성공·실패 알림은 미검증 |
| 예정 종료와 새벽 한 주기 | 03–06시 백업 유지, 06시 이후 홈 복귀를 외부 관찰해야 함 | 미검증 |

Infra 로컬 검사는 37개 테스트와 타입·린트·Wrangler dry-run을 통과했다. 1,000개 동시 실패 테스트는 사용자 실패가 헬스 표본으로 증폭되지 않는지 확인한 것이며 1,000명 처리량 측정이 아니다. 가상 시간의 10분 윈도우 검사는 실제 복구 시간 측정이 아니다.

## 실제 실행 결과

03:07 KST의 공개 `/readyz`는 기본 Python 클라이언트에서 HTTP 403을 반환했다. 이후 다른 User-Agent의 요청은 HTTP 530을 반환했다. 이 결과는 클라이언트·시각이 다른 별개의 관찰이며 앱의 readiness 성공 증거가 아니다. 예정 종료 시간에는 배포 가드를 우회하지 않는다.

Server main SHA `b3f0fd7eb74a724caadcc90a13adbdf171b20c4d`의 [main push CI](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42082268167)는 harness·quality·test·container-smoke가 모두 성공했다. 이후 03:17:45 KST에 [수동 배포 실행 42082844118](https://github.com/JECT-Study/Ziper-5th-Server/actions/runs/42082844118)을 main에서 시작했고 성공으로 종료했다.

이 실행의 성공 범위는 **예약 시간에 따른 배포 보류와 실제 Discord 보류 알림 수신**이다. 시간 가드가 성공했고 artifact 다운로드·이미지 생성·SSH 전송·공개 readiness 검사는 `skipped`였다. production의 앱 배포 완료를 뜻하지 않는다.

[Discord 메시지](https://discord.com/channels/1537397802366144524/1566809692779323402/1567966560079843328)의 ID는 `1567966560079843328`이다. 전송 CLI는 `wait=true` 응답의 `channel_id`가 지정 채널 `1566809692779323402`인지 대조한 뒤 이 ID를 출력했다. 사람의 UI 열람 여부까지 확인한 것은 아니다. 실제 앱 배포 성공·실패 알림과 Worker failover 알림을 보냈다고 기록하지 않는다.

마지막 공개 HTTP 결과와 모든 선택 실행·보호 정책은 원본 JSON의 `observedAt`을 기준으로 한다. 실제 03–06시 백업 운영과 06시 복귀는 관찰하지 않았다. 자동 재실행 작업이나 대기열도 생성하지 않았다.

## 추가로 필요한 준비

1. **Cloudflare Worker 배포 인증**을 완료한다. 현재 Access의 `CF_ACCESS_CLIENT_ID/SECRET`은 SSH용이며 Worker 배포 API 권한이 아니다. Wrangler OAuth 동의는 완료되지 않아 시간 초과됐다. 대안은 제한된 `CLOUDFLARE_API_TOKEN`을 Infra `production` Secret에 등록하는 것이다. 토큰 값을 대화로 보내지 않는다. 네이티브 브라우저 자동 제어가 권한 거부 상태라 대신 클릭할 수 없었다.
2. 인증 후 집어 전용 Home origin과 Access Service Auth를 만든다. `HOME_ORIGIN`의 현재 `.invalid`는 배포할 수 없는 자리표시자다. Worker 전용 `HOME_ACCESS_CLIENT_ID/SECRET`과 읽기 전용 `OPS_READ_TOKEN`을 등록한다. 기존 SSH 정책·tocktock 서비스는 보존한다.
3. GCP 청구 연결은 확인했지만 Cloud Run·Registry·invoker와 비용 제어는 아직 만들지 않았다. 월 US$1은 목표이며 지연된 사용량과 다른 서비스 비용을 포함한 절대 상한을 보장하지 않는다. 비용 제어를 먼저 검증한 뒤 동일 이미지의 백업을 만든다.
4. 06시 이후 홈이 켜지고 Docker·WSL·전용 Tunnel이 준비됐는지 확인한 뒤 수동 배포를 다시 실행한다. 현재 보류 경로에는 자동 대기열이 없다.
5. 양쪽 readiness·digest 일치와 복구 watchdog을 확인한 다음 집어 앱에만 장애를 주입한다. 다른 서비스나 장비 전원을 조작하지 않는다. 외부 단조 시계로 장애 직전부터 백업 첫 정상 응답 완료까지 600초 이하를 측정한다. 이후 홈 복구와 HALF_OPEN 재실패 경로도 확인한다.

현재 등록한 CF Access Secret을 다시 전달할 필요는 없다. 다음 사용자 작업은 먼저 Worker 배포 인증을 완료하는 것이다.

등록 위치를 준비하도록 Infra에도 `production` 환경을 만들고 배포 브랜치를 main 하나로 제한했다. zone·공개 origin·백업 비활성의 비밀이 아닌 변수만 등록했다. API token·실제 Home origin·Worker 전용 Access·OPS Secret은 아직 없으므로 Worker 배포를 시도하지 않았다.

## 증거 다시 수집하기

`scripts/collect-nightly-evidence.py`는 명시한 실행의 GitHub 상태·선별한 설정·공개 readiness만 수집한다. 원본 workflow 로그를 파일로 보존하지 않고 Discord 전송 확인 메시지 ID만 추출한다. 실제 장애 주입이나 Worker 배포를 대신하지 않는다. 최종 실행 ID를 아래 명령에 넣는다.

```sh
python3 scripts/collect-nightly-evidence.py \
  --infra-run 42080482858 \
  --server-run 42081104306 \
  --server-run 42081675102 \
  --server-run 42081744774 \
  --server-run 42082268167 \
  --server-run 42082844118 \
  --output docs/evidence/2026-11-06-nightly.json
```

## 다음 운영 검토에서 다룰 문제

- 공통 Supabase 장애는 홈과 Cloud Run 모두의 readiness를 실패시킬 수 있다. 이때 failover로 DB 장애가 해결되지는 않는다.
- 사용자 트래픽의 실패는 헬스 윈도우에 합산하지 않으므로 단일 장애가 동시 접속 수만큼 증폭되지 않는다. 반면 readiness가 성공하는 특정 업무 API 오류는 회로가 감지하지 못한다.
- Cloud Run 비용 제어가 차단된 상태에서 홈이 종료되면 503을 허용해야 한다. 현재는 백업 자체가 없으므로 예약 구간의 서비스 연속성도 보장하지 않는다.
- CI green이나 Discord 보류 알림은 운영 반영의 증거가 아니다. 다음 실제 배포에서는 이미지 ID·source SHA·HTTP 헤더와 DB readiness를 함께 확인해야 한다.
