# Ziper-5th-Infra

집어의 Cloudflare Worker 라우팅·Durable Object 서킷 브레이커·인프라 배포 설정을 관리합니다. 애플리케이션 코드는 [Ziper-5th-Server](https://github.com/JECT-Study/Ziper-5th-Server)에 둡니다.

정책은 [ADR 0001](docs/adr/0001-home-circuit-breaker.md)에 기록합니다. 홈 전용 readiness를 1분에 한 번 검사하고 최근 10분 슬롯의 실패율이 60% 이상이면 홈 회로를 엽니다. 사용자 요청의 실패 횟수는 윈도우에 합산하지 않습니다. 복구는 2분 쿨다운 후 3회 연속 정상 관측으로 확인합니다.

Node.js 24를 사용합니다.

```sh
npm ci
npm run check
```

타입 생성·타입 검사·린트·Workers 런타임과 SQLite 테스트·배포 dry-run을 실행합니다. 바인딩 타입은 `wrangler types --strict-vars false --include-runtime false`로 생성해 버전 관리하며 secret 이름만 별도 타입으로 선언합니다. 대용량 runtime 타입은 `.wrangler/types/runtime.d.ts`에 매번 생성합니다. TypeScript는 현재 ESLint 지원 범위인 6.0으로 고정합니다.

**운영 배포는 아직 완료되지 않았습니다.** 기본 설정은 운영 route 없이 예약 도메인 `.invalid`를 사용하며 Cloud Run은 꺼져 있습니다. [운영 문서](docs/operations.md)의 실제 홈 전용 호스트·Access·GitHub production 설정이 필요합니다. PR과 main push는 CI만 실행하고 운영 배포는 성공한 main CI 이후 수동 워크플로로 실행합니다.

[검증 조건과 실제 확인 범위](docs/verification.md) · [문서 지도](docs/context-map.md)
