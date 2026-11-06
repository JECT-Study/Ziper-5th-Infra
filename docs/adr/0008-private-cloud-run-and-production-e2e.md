# 0008 비공개 Cloud Run 백업과 운영 장애 검증

- 상태: 채택 — 설정 준비·로컬 검증, 운영 실행별 판정은 증거로 기록
- 날짜: 2026-11-07

## 배경

사용자는 실제 홈 장애에서 Cloud Run으로 600초 이내 전환되고 복구되는지 확인하려 한다. 홈은 03–06시 종료하고 런타임 배포는 02:30–06:00에 보류한다. 03시 실제 공개 530을 관측했으나 당시 Worker·백업은 연결되지 않았으므로 이를 새 구성의 전환 성공으로 기록하지 않는다. 기존 전송은 1MiB 검사를 통과했지만 실제 이미지 SSH 전달에서 Broken pipe로 끝났다. ADR 0007은 GHCR digest pull로 전송 방식을 교체한다.

## 결정

성공한 main CI의 JAR로 이미지를 한 번 발행하고 GHCR의 manifest digest와 OCI config digest·JAR 해시를 기록한다. Cloud Run용으로 같은 이미지를 Singapore Artifact Registry에 미러링하고 양쪽 canonical config digest를 대조한다. registry manifest digest와 config digest는 다른 종류의 식별자로 보존한다. 발행·미러링은 준비 작업이므로 종료 구간에도 가능하지만, 앱 런타임 변경은 각 변경 직전에도 시간을 검사하며 보류한다. 자동 배포 대기열은 만들지 않는다.

CI는 GitHub OIDC WIF를 사용한다. 저장소 숫자 ID·main ref·production subject를 모두 확인하며 deployer SA는 Run developer·전용 AR writer·runtime SA actAs만 사용한다. worker invoker는 별도 계정이며 비공개 Cloud Run 호출 역할만 부여한다. 최초 서비스 생성 전의 프로젝트 invoker 권한은 서비스 생성 후 해당 서비스로 좁히고 재조회한다. Worker의 현재 RSA 어댑터에는 이 전용 invoker 키가 필요하며 Infra production Secret과 비밀 로컬 파일로만 관리한다. CI용 장기 GCP 키는 만들지 않는다.

Cloud Run은 요청 기반 CPU·min0/max1·1CPU/1GiB·CPU boost 끔으로 시작한다. 서비스는 비공개이며 allUsers/allAuthenticatedUsers를 부여하지 않는다. 런타임 SA는 두 Secret에만 접근한다. app DB·JWT·Sentry 설정 파일과 DB CA를 서로 겹치지 않는 읽기 전용 디렉터리에 마운트한다. Cloud Run에서는 Flyway와 백그라운드 metrics를 끄고 이미 생성된 ziper 스키마를 검증한다. 홈·백업이 동일 DB를 쓰므로 공통 DB 장애를 failover가 해결한다고 주장하지 않는다.

월 KRW1,000의 Cloud Run native spend cap은 프로젝트·서비스·gross 비용·MONTH 설정까지 조회한다. 집계 지연과 저장·다른 서비스 비용까지 포함한 절대 상한은 아니다. 비용 차단을 확인하려고 일부러 과금하지 않는다. 데이터·현재 namespace·기존 release manifest는 검증 때문에 삭제하지 않는다.

백업 revision suffix는 source SHA로 고정한다. 같은 SHA를 재실행하면 기존 revision·이미지·환경·규모를 읽어 검증하며, 재조정 중인 쓰기는 다시 발행하지 않는다. 공개·비공개 probes와 제공업체 Ready·실제 imageDigest를 구분해 확인한다. 성공 Discord 문구는 양쪽 readiness가 모두 통과한 경우만 paired로 표시한다. 준비 오류는 보류보다 우선해 실패로 알린다.

장애는 집어 app 한 컨테이너로 제한한다. root-private lease는 ID·compose labels·실제 SENTRY_RELEASE·current-version을 고정하고 deploy.lock을 공유한다. 독립 systemd timer가 만료 lease를 복구한다. 먼저 이미 실행 중인 app으로 만료 lease의 무해한 timer 실행을 실제 확인한 후 장애를 주입한다. 컨트롤러의 단조 시계 marker 직전부터 cloudrun의 첫 UP/200 완료까지 측정하고 SQLite 전이·분 단위 표본·공개 origin 헤더를 함께 보존한다. 가상 시간 검사는 운영 600초 증거가 아니다.

## 대안

- GHCR에만 발행하고 Cloud Run에서 임의 private registry 주소를 직접 사용: 지원·인증 경계를 명확히 하려고 AR 미러링을 사용한다.
- CI용 서비스 계정 JSON 키: 장기 키 노출을 줄이려고 WIF를 사용한다.
- 공개 Cloud Run: 호출 권한과 사용자 JWT를 분리하려고 전용 invoker와 X-Serverless-Authorization을 사용한다.
- 컨트롤러 finally만으로 장애 복구: 네트워크·프로세스 종료에 대비한 독립 복구가 아니므로 제외한다.
- 테스트를 위해 장비 전원·공유 Tunnel·다른 app을 조작: 범위를 집어 app으로 제한한다.

## 영향과 한계

자격·URL·revision·cap·자동 복구·실제 API 결과를 각각 검증해야 한다. 06시 BIOS 부팅과 Docker/WSL 자동 기동은 별도 관측 대상이며 SSH로 수동 기동한 것을 자동 복구로 기록하지 않는다. 예정 구간 routing은 실제 회로 failover와 구분한다. 이전 실패와 새 코드의 통과를 덮어쓰지 않으며 실제 실행 전에는 운영 E2E 통과를 주장하지 않는다.

복구 lease의 arm부터 해소까지 receiver·trusted deploy·control installer는 공통 잠금 아래 배포를 거부한다. 명령 단위의 잠금만으로는 lease 사이의 배포 교체를 막을 수 없어 존재하는 lease를 별도로 확인한다. 만료·오염·symlink 상태도 자동 무시하지 않는다.
