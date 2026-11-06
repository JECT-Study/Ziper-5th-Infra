# 0007 GHCR digest pull로 홈 이미지 전달

- 상태: 채택 — 로컬 계약 검증 완료, 운영 GHCR 발행·pull은 별도 검증
- 날짜: 2026-11-07

## 배경

기존 홈 단독 배포는 tested-release JAR로 이미지를 만든 뒤 docker save·gzip 결과 전체를 SSH stdin으로 전달했다. 대용량 전달은 필수 요건이 아닌 초기 구현 선택이다. 사용자는 GHCR pull 방식과 실제 Cloud Run 장애 전환 검증을 요청했다. 1MiB 전송 사전 검사는 실제 이미지 전송 성공을 대신하지 않는다.

## 결정

publish job은 packages:write의 일시적 GITHUB_TOKEN으로 ghcr.io/ject-study/ziper-server에 소스 SHA tag를 발행한다. 동일 tag가 있으면 기존 digest를 읽고 tested JAR·소스 번들을 재검증해 재사용한다. HEAD 404만 미발행으로 취급하고 인증·네트워크 오류를 미발행으로 간주하지 않는다. 결과가 불명확한 push는 자동 재시도하지 않는다. 외부 작성자가 tag를 바꾸지 못하는 별도 registry 정책까지 적용했다고 주장하지 않는다.

registry-release artifact에는 sourceSha·고정 repository·registry digest·OCI config digest·JAR SHA256만 담는다. home deploy job은 packages:read의 별도 일시적 토큰을 사용하며, 이 metadata와 actor·token을 최대 8KiB JSON으로 SSH에 전달한다. 장기 PAT를 추가하지 않는다.

수신기는 deploy-registry와 40자리 SHA만 허용하고 repository를 고정한다. 비밀은 argv나 로그에 넣지 않는다. Docker login은 password-stdin을 사용하고 인증 config는 mode 0700 임시 디렉터리에 만들며 성공·실패 후 제거한다. 정확한 registry digest를 pull한 뒤 실제 OCI config와 내부 JAR를 다시 검증한다. 검증된 로컬 tag만 기존 신뢰 compose/deploy에 넘기며 runtime의 pull_policy:never는 유지한다.

기존 source·Infra main CI gate, main 수동 실행, 02:30–06:00 KST 보류, 공개 준비 검사 180초, Discord 실패·보류·성공 판정은 유지한다. 새 workflow에서는 대용량 SSH 전달과 1MiB binary fixture를 사용하지 않는다. 기존 archive 수신 명령은 설치 전환 중 호환성을 위해 유지하되 새 배포가 호출하지 않는다.

## 대안

- 대용량 SSH 전달 유지: registry가 제공하는 이미지 배포를 제한 수신기에 중복 구현하고 전송 장애를 늘리므로 새 경로에서는 제외한다.
- latest tag만 실행: 같은 이름이 다른 이미지로 바뀔 수 있어 digest를 고정한다.
- publisher의 write 토큰을 홈으로 전달: 별도 read-only job 토큰을 전달해 권한을 줄인다.
- 홈에 장기 PAT 보관: 현재 요구에는 job 토큰으로 충분해 제외한다.

## 영향과 한계

receive.py·image_identity.py·registry_release.py를 홈 신뢰 디렉터리에 함께 설치해야 한다. Source caller는 packages:write를 허용하고 검사한 Infra main SHA의 두 참조를 갱신해야 한다. GHCR 조직의 package 생성·접근 정책은 실제 발행으로 검증한다. private package는 이 Server 저장소의 Actions가 접근할 수 있어야 한다.

registry digest와 OCI config digest는 다른 종류의 값이다. 실제 Cloud Run 전개 경로는 별도로 같은 이미지의 digest·config·release를 대조해야 한다. 로컬 CLI fixture 테스트나 CI green을 운영 GHCR pull·서버 readiness·failover 성공으로 기록하지 않는다.

근거: [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry), [Docker digest pull](https://docs.docker.com/reference/cli/docker/image/pull/), [password-stdin](https://docs.docker.com/reference/cli/docker/login/).
