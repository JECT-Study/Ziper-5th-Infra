# 0007 GHCR digest pull로 홈 이미지 전달

- 상태: 채택 — 로컬 계약 검증 완료, 운영 GHCR 발행·pull은 별도 검증
- 날짜: 2026-11-07

## 배경

기존 홈 단독 배포는 tested-release JAR로 이미지를 만든 뒤 docker save·gzip 결과 전체를 SSH stdin으로 전달했다. 대용량 전달은 필수 요건이 아닌 초기 구현 선택이다. 사용자는 GHCR pull 방식과 실제 Cloud Run 장애 전환 검증을 요청했다. 1MiB 전송 사전 검사는 실제 이미지 전송 성공을 대신하지 않는다.

## 결정

publish job은 packages:write의 일시적 GITHUB_TOKEN으로 ghcr.io/ject-study/ziper-server에 소스 SHA tag를 발행한다. 동일 tag가 있으면 기존 digest를 읽고 tested JAR·소스 번들을 재검증해 재사용한다. HEAD 404만 미발행으로 취급하고 인증·네트워크 오류를 미발행으로 간주하지 않는다. 결과가 불명확한 push는 자동 재시도하지 않는다. 외부 작성자가 tag를 바꾸지 못하는 별도 registry 정책까지 적용했다고 주장하지 않는다.

registry-release artifact에는 sourceSha·고정 repository·registry digest·OCI config digest·JAR SHA256만 담는다. home deploy job은 packages:read의 별도 일시적 토큰을 사용하며, 이 metadata와 actor·token을 최대 8KiB JSON으로 SSH에 전달한다. 장기 PAT를 추가하지 않는다.

수신기는 deploy-registry와 40자리 SHA만 허용하고 repository를 고정한다. 비밀은 argv나 로그에 넣지 않는다. Docker login은 password-stdin을 사용하고 인증 config는 mode 0700 임시 디렉터리에 만들며 성공·실패 후 제거한다. 정확한 registry digest를 pull한 뒤 실제 OCI config와 내부 JAR를 다시 검증한다. 검증된 로컬 tag만 기존 신뢰 compose/deploy에 넘기며 runtime의 pull_policy:never는 유지한다.

기존 source·Infra main CI gate, main 수동 실행, 02:30–06:00 KST runtime 보류, 공개 준비 검사 180초, Discord 실패·보류·성공 판정은 유지한다. 이미지 발행·검증·artifact 보존은 보류 시간에도 수행할 수 있으며 홈·Cloud Run runtime 변경과 구분한다. Source caller를 새 Infra SHA와 GHCR 권한으로 먼저 전환한 뒤 새 수신기를 설치한다. 새 수신기는 legacy deploy archive 명령을 명시적으로 거부한다. 대용량 전송·archive packager·1MiB fixture와 해당 전용 테스트는 제거한다. 기존 컨테이너·로컬 이미지·이전 release manifest는 삭제하지 않는다.

홈 runtime 변경 직전 workflow에서 시간을 다시 확인하고, 수신기에서는 신뢰 production.json 정책을 잠금 전·후와 이미지 검증 완료 후 적용한다. 신뢰 deploy.sh도 컨테이너 변경 직전 확인한다. pull 중 보류 시간에 진입하면 runtime을 변경하지 않고 정적 ZIPER_DEPLOY_DEFERRED·exit75를 반환하며 sender·notify는 보류로 기록한다. 자동 대기열이나 다음 시간의 자동 재실행은 만들지 않는다.

검증은 고유한 ziper-verification 임시 tag로 수행한다. 이미지 config·JAR 검증이 모두 통과한 뒤에만 공유 ziper-server:<source> tag를 지정한다. 수신기의 전체 작업과 trusted deploy.sh·복구는 공통 deploy.lock을 사용한다. 수신기는 열린 lock fd를 자식에게 pass_fds로 넘기며 deploy.sh는 fd의 device·inode가 해당 lock 파일인지 검증하고 같은 open-file description을 재사용해 중첩 잠금을 피한다.

app readiness·cloudflared 시작·current-version 원자적 기록까지 모두 성공해야 배포 성공으로 처리한다. Tunnel 시작이나 버전 기록 실패도 동일 롤백 분기로 처리해 이전 runtime과 기록을 유지한다. 이전 release가 없는 최초 실패는 app을 중지하고 성공 기록을 만들지 않는다. 같은 release의 실패는 기존 app을 무조건 중지하지 않는다.

## 대안

- 대용량 SSH 전달 유지: registry가 제공하는 이미지 배포를 제한 수신기에 중복 구현하고 전송 장애를 늘리므로 새 경로에서는 제외한다.
- latest tag만 실행: 같은 이름이 다른 이미지로 바뀔 수 있어 digest를 고정한다.
- publisher의 write 토큰을 홈으로 전달: 별도 read-only job 토큰을 전달해 권한을 줄인다.
- 홈에 장기 PAT 보관: 현재 요구에는 job 토큰으로 충분해 제외한다.

## 영향과 한계

receive.py·image_identity.py·registry_release.py·deploy.sh와 config/production.json을 홈 신뢰 디렉터리에 함께 설치해야 한다. Source caller는 packages:write를 허용하고 검사한 Infra main SHA의 두 참조를 갱신해야 한다. GHCR 조직의 package 생성·접근 정책은 실제 발행으로 검증한다. private package는 이 Server 저장소의 Actions가 접근할 수 있어야 한다.

registry digest와 OCI config digest는 다른 종류의 값이다. 실제 Cloud Run 전개 경로는 별도로 같은 이미지의 digest·config·release를 대조해야 한다. 로컬 CLI fixture 테스트나 CI green을 운영 GHCR pull·서버 readiness·failover 성공으로 기록하지 않는다.

근거: [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry), [Docker digest pull](https://docs.docker.com/reference/cli/docker/image/pull/), [password-stdin](https://docs.docker.com/reference/cli/docker/login/).

허용 시간에 시작한 배포의 실패 시 이전 runtime 복구는 보류 시간에도 시도한다. 이 복구는 새 release 배포 허용이 아니며 실패·복구 결과로 보고한다.
