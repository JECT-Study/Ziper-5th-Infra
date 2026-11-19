# 0017 외부 커스텀 도메인(Cloudflare for SaaS)의 `ziper-edge` Worker 경유 라우팅

- 상태: 채택 — 운영 `EXTRA_PUBLIC_ORIGINS` 배포와 `/readyz` 응답은 실행별 증거로 확인
- 날짜: 2026-11-20
- 관계: [ADR 0001](0001-home-circuit-breaker.md)·[ADR 0002](0002-scheduled-operation-and-e2e.md)·[ADR 0008](0008-private-cloud-run-and-production-e2e.md)의 `ziper-edge` 단일 진입점과 Cloud Run failover·예약 전환 계약을 외부 커스텀 도메인(`api.ziper.cc` 등)에도 동일하게 확장한다.

## 배경

외부 도메인(`api.ziper.cc`)을 `joonamin.dev`의 Cloudflare for SaaS(Custom Hostnames, Fallback Origin `api-ziper.joonamin.dev`)로 연결했을 때, 기존 `ziper-edge` Worker는 `api-ziper.joonamin.dev/*` route와 단일 `PUBLIC_ORIGIN`만 허용했다. 이로 인해 `api.ziper.cc` 요청은 Worker를 거치지 않고 Fallback Origin 뒤의 홈 `cloudflared` 터널로 직행해 빈 404를 반환했다.

홈 `cloudflared` 터널의 로컬 `config.yml` 또는 catch-all 규칙으로 `api.ziper.cc`를 직접 열면 일시적으로 홈 응답은 받을 수 있으나, `ziper-edge` Worker가 완전히 우회되어 매일 03:00–06:00 KST 예약 전환·장애 시 Google Cloud Run failover·`origin-ziper.joonamin.dev` Cloudflare Access 경계와 헤더 정제가 모두 무력화된다.

## 결정

- `ziper-edge`에 선택 환경 변수 `EXTRA_PUBLIC_ORIGINS`(쉼표 구분 HTTPS origin 목록, 기본 빈 문자열)를 도입해 `PUBLIC_ORIGIN`과 함께 허용된 공개 origin만 프록시한다. 미등록 도메인은 계속 404를 반환하며, `/_ops/circuit`은 기존 `PUBLIC_ORIGIN` 전용으로 유지한다.
- `ziper-edge`는 기존과 동일하게 `X-Forwarded-Host`에 실제 인입 호스트(`api.ziper.cc`), `X-Forwarded-Proto`에 `https`를 설정해 홈(`origin-ziper.joonamin.dev`)과 비공개 Cloud Run(`*.run.app`) 양쪽에 전달한다.
- `EXTRA_PUBLIC_ORIGINS`에 `CLOUDFLARE_ZONE_NAME` 외부 도메인이 포함된 경우, `prepare-deploy.ts`는 기존 `${hostname}/*` route 외에 Cloudflare for SaaS 요청을 수신하는 `*/*` route를 추가한다.
- `*/*` route가 `joonamin.dev`의 기존 서브도메인(`origin-ziper.joonamin.dev`, `ssh.joonamin.dev`, `tock.joonamin.dev`, `n8n.joonamin.dev` 등)과 루트 도메인을 가로채지 않도록, `deploy-edge.yml`은 `wrangler deploy` 직전에 `scripts/ensure-saas-bypass-routes.py`로 `*.${CLOUDFLARE_ZONE_NAME}/*` 및 `${CLOUDFLARE_ZONE_NAME}/*`의 `None`(script 미지정) bypass route 존재를 보장한다. 두 패턴에 이미 다른 Worker script가 바인딩되어 있으면 덮어쓰지 않고 배포를 중단한다.
- `scripts/remove-edge-route.py`는 `EXTRA_PUBLIC_ORIGINS`가 설정된 경우 `ziper-edge`에 바인딩된 `*/*` route도 함께 제거하며, `None` bypass route와 다른 Worker의 route는 건드리지 않는다.

## 대안

- 홈 `cloudflared` 터널의 로컬 `config.yml` 전환 또는 catch-all 변경: `ziper-edge`를 우회해 03:00–06:00 예약 전환과 장애 시 Cloud Run failover가 동작하지 않으며, `/opt/ziper/ci/` 배포 구조와 충돌한다.
- Cloudflare Origin Rules의 Host Header Override: Enterprise 전용 기능으로 Free 플랜에서 사용할 수 없으며, 원본 호스트 전달과도 맞지 않는다.
- 별도 무료 Worker 프록시 추가: `ziper-edge`와 중복 홉을 만들고 일일 요청 한도·관리 표면을 늘린다.

## 영향과 한계

- 홈서버(`/opt/ziper/ci/`)와 `ziper-production` 터널은 수정하지 않으며, Durable Object `HomeCircuit` 스키마·마이그레이션 이력도 변경하지 않는다.
- `api.ziper.cc`의 DNS CNAME·Custom Hostname·SSL 인증서 활성 상태 및 백엔드 OAuth Redirect URI / `CORS_ALLOWED_ORIGINS` 정합은 별도 운영 확인 대상이다.
- 로컬 `npm run check`는 가짜 네트워크 경계와 route API mock만 검증하며, 실제 `api.ziper.cc`의 운영 failover·OAuth 흐름은 배포 후 별도 확인한다.
