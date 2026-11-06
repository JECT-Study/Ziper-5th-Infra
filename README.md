# Ziper-5th-Infra

집어의 Cloudflare Worker 라우팅·Durable Object 서킷 브레이커·인프라 배포 설정을 관리합니다. 애플리케이션 코드는 [Ziper-5th-Server](https://github.com/JECT-Study/Ziper-5th-Server)에 둡니다.

정책은 [ADR 0001](docs/adr/0001-home-circuit-breaker.md)에 기록합니다. 홈 전용 readiness를 1분에 한 번 검사하고 최근 10분 슬롯의 실패율이 60% 이상이면 홈 회로를 엽니다. 사용자 요청의 실패 횟수는 윈도우에 합산하지 않습니다. 복구는 2분 쿨다운 후 3회 연속 정상 관측으로 확인합니다.

Node.js 24를 사용합니다.

```sh
npm ci
npm run check
```

타입 생성·타입 검사·린트·Workers 런타임과 SQLite 테스트·배포 dry-run을 실행합니다. 바인딩 타입은 `wrangler types --strict-vars false --include-runtime false`로 생성해 버전 관리하며 secret 이름만 별도 타입으로 선언합니다. 대용량 runtime 타입은 `.wrangler/types/runtime.d.ts`에 매번 생성합니다. TypeScript는 현재 ESLint 지원 범위인 6.0으로 고정합니다.

**쌍 운영 배포와 failover E2E는 아직 완료되지 않았습니다.** 기존 홈 릴리스는 응답하지만 GitHub runner의 보호 origin 요청이 Cloudflare challenge로 차단됩니다. 자격 비교와 실제 응답 증거, 완료·미실행 범위는 [2026-11-07 nightly walkthrough](docs/nightly-walkthrough-2026-11-07.md)에 있습니다. 기본 설정은 운영 route 없이 예약 도메인 `.invalid`를 사용하며 Cloud Run은 꺼져 있습니다. PR과 main push는 CI만 실행하고 운영 배포는 성공한 main CI 이후 수동 워크플로로 실행합니다.

[검증 조건과 실제 확인 범위](docs/verification.md) · [문서 지도](docs/context-map.md)

## 홈서버 운영 일정

BIOS에서 관리하는 예정 종료는 **매일 03:00–06:00, Asia/Seoul**입니다. 외부에서 전원이나 BIOS 설정을 바꾸지 않습니다. 이 시간대에는 회로의 실패율 판정을 기다리지 않고 Cloud Run을 선택하고, 종료 후에는 홈 회복이 확인되어야 돌아갑니다.

일정의 출처는 `config/production.json`입니다. BIOS 일정이 달라지면 이 파일과 README를 함께 수정하고 Worker를 다시 배포합니다. 배포는 종료 전 30분 안전 여유를 포함한 **02:30–06:00**에 보류하며 이후 홈 준비 확인 후 수동 재실행합니다. 현재 Cloud Run native spend cap은 월 KRW1,000으로 조회했으며 집계 지연·다른 서비스 비용까지 포함한 절대 상한은 아닙니다.

현재 예약 라우팅·읽기 전용 조회·배포 시간 가드·Discord 전송 스크립트는 작성했고 홈 수동 workflow에 연결했습니다. Cloud Run 실제 배포·600초 복구·새벽 관찰은 완료되지 않았습니다. [ADR 0002](docs/adr/0002-scheduled-operation-and-e2e.md)에 합의 정책과 미완료 범위를 기록합니다.
