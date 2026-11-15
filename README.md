# Ziper-5th-Infra

집어의 Cloudflare Worker 라우팅·Durable Object 서킷 브레이커·인프라 배포 설정을 관리합니다. 애플리케이션 코드는 [Ziper-5th-Server](https://github.com/JECT-Study/Ziper-5th-Server)에 둡니다.

정책은 [ADR 0001](docs/adr/0001-home-circuit-breaker.md)에 기록합니다. 홈 전용 readiness를 1분에 한 번 검사하고 최근 10분 슬롯의 실패율이 60% 이상이면 홈 회로를 엽니다. 사용자 요청의 실패 횟수는 윈도우에 합산하지 않습니다. 복구는 2분 쿨다운 후 3회 연속 정상 관측으로 확인합니다.

Node.js 24를 사용합니다.

```sh
npm ci
npm run check
```

타입 생성·타입 검사·린트·Workers 런타임과 SQLite 테스트·배포 dry-run을 실행합니다. 바인딩 타입은 `wrangler types --strict-vars false --include-runtime false`로 생성해 버전 관리하며 secret 이름만 별도 타입으로 선언합니다. 대용량 runtime 타입은 `.wrangler/types/runtime.d.ts`에 매번 생성합니다. TypeScript는 현재 ESLint 지원 범위인 6.0으로 고정합니다.

**쌍 운영 배포·failover E2E·새벽 예약 전환을 2026-11-16 운영에서 확인했습니다.** 운영 route `api-ziper.joonamin.dev/*`는 `ziper-edge` Worker가 처리합니다. 홈 앱 장애 주입 후 384초에 첫 Cloud Run 200을 받았고 홈 복구 후 CLOSED로 돌아왔습니다. 03:00–06:00 예약 구간에는 Cloud Run이 응답했고 06:02 부팅 후 앱과 Tunnel이 스스로 재기동해 06:08에 홈으로 복귀했습니다. 전환 직후 Cloud Run 콜드 스타트 동안의 무응답 구간과 미검증 항목(Sentry Uptime, 실제 중복 쓰기, 부하·비용)은 [검증 이력](docs/verification.md#2026-11-16-운영-failover-e2e와-새벽-예약-전환)에 있습니다. 저장소 기본 설정은 예약 도메인 `.invalid`이며 운영 값은 배포 워크플로가 `config/production.json`과 환경 값으로 생성합니다. PR과 main push는 CI만 실행하고 운영 배포는 성공한 main CI 이후 수동 워크플로로 실행합니다.

[검증 조건과 실제 확인 범위](docs/verification.md) · [문서 지도](docs/context-map.md)

## 홈서버 운영 일정

BIOS에서 관리하는 예정 종료는 **매일 03:00–06:00, Asia/Seoul**입니다. 외부에서 전원이나 BIOS 설정을 바꾸지 않습니다. 이 시간대에는 회로의 실패율 판정을 기다리지 않고 Cloud Run을 선택하고, 종료 후에는 홈 회복이 확인되어야 돌아갑니다.

일정의 출처는 `config/production.json`입니다. BIOS 일정이 달라지면 이 파일과 README를 함께 수정하고 Worker를 다시 배포합니다. 배포는 종료 전 30분 안전 여유를 포함한 **02:30–06:00**에 보류하며 이후 홈 준비 확인 후 수동 재실행합니다. 현재 Cloud Run native spend cap은 월 KRW1,000으로 조회했으며 집계 지연·다른 서비스 비용까지 포함한 절대 상한은 아닙니다.

현재 예약 라우팅·읽기 전용 조회·배포 시간 가드·Discord 전송 스크립트는 작성했고 홈 수동 workflow에 연결했습니다. Cloud Run 실제 배포·600초 이내 백업 응답·새벽 한 주기 관찰은 2026-11-16에 완료했습니다([증거](docs/evidence/2026-11-16/)). [ADR 0002](docs/adr/0002-scheduled-operation-and-e2e.md)에 합의 정책과 남은 제한을 기록합니다.
