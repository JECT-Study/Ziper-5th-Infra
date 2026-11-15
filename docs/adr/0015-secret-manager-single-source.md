# 0015 Secret Manager 고정 버전을 두 운영 origin의 단일 원본으로 사용

- 상태: 채택 — 실제 운영 배포의 활성화는 실행별 증거로 확인
- 날짜: 2026-11-15
- 관계: ADR0008의 "비밀 로컬 파일" 공급 방식을 대체한다. Cloud Run의 Secret 파일 마운트와 전용 runtime SA 경계는 유지한다. Server ADR 0006의 홈 호스트 환경 파일 기준도 함께 대체한다.

## 배경

운영 비밀값은 세 곳에 복사되어 있었다. 운영자 노트북의 `~/.config/ziper/deployment/runtime.env`가 사실상의 원본이었고, `bootstrap-gcp-production.py`가 그중 `MIGRATION_*`를 뺀 값을 Secret Manager `ziper-runtime-properties`로 복사했다. 홈은 같은 파일을 `/opt/ziper/private/runtime.env`로 수동 복사해 compose `env_file`로 읽었다.

2026-11-15 세 사본의 키 이름과 값 해시를 대조했고 모두 일치했다. 다만 값을 교체할 때마다 세 곳을 따로 갱신해야 하며 어긋남을 자동으로 발견할 수단이 없었다.

## 결정

Secret Manager의 고정 버전을 홈과 Cloud Run이 함께 읽는 단일 원본으로 둔다.

- Secret은 `ziper-runtime-properties`, `ziper-db-ca`, `ziper-home-migration-properties` 세 개다. 마이그레이션 계정은 홈만 사용하므로 별도 Secret으로 분리한다. Cloud Run runtime SA는 이 Secret을 읽을 수 없다.
- 버전은 `config/production.json`의 `secretVersions`에 고정한다. `latest`를 읽지 않는다. 두 origin은 같은 번호를 읽으며, 값을 교체하려면 새 버전을 추가하고 이 번호를 PR로 올린 뒤 쌍 배포한다.
- 홈은 GCP 자격 증명을 갖지 않는다. deploy job이 전용 `ziper-config-reader` SA로 WIF 인증하고, 고정 버전을 runner 임시 디렉터리(0600)에 읽은 뒤 기존 제한 SSH 수신기 페이로드로 전달한다. 이 SA에는 세 Secret의 `secretAccessor`만 부여하고 deployer SA 권한은 늘리지 않는다.
- 수신기는 이미지 검증이 끝난 뒤 `deploy.lock` 아래에서 설정 묶음을 `/opt/ziper/private/config/<묶음 ID>/`에 쓴다. 묶음 ID는 고정 버전과 파일별 SHA256에서 계산한다. 같은 ID의 디렉터리는 바꾸지 않으며, 내용이 다르면 거부한다. 디렉터리는 root 전용이고 파일은 0444다. 컨테이너는 파일만 마운트하므로 비root 앱 사용자가 읽을 수 있다.
- `deploy.sh`는 `current-config`에 묶음 ID를 `current-version`과 함께 기록한다. 활성화가 실패하면 이전 release와 이전 묶음으로 함께 되돌린다. 운영자의 수동 재배포는 기록된 묶음을 다시 사용한다.
- 홈 compose는 `env_file`을 쓰지 않고 Cloud Run과 같이 `SPRING_CONFIG_IMPORT`로 properties 파일을 읽는다. 마이그레이션 properties는 두 번째 파일로 함께 가져온다.
- `bootstrap-gcp-production.py`는 기본적으로 노트북 파일을 읽지 않는다. 최초 이관에만 `--import-runtime-env`를 명시한다.

## 대안

- 홈 호스트가 직접 Secret Manager를 읽음: SA 키는 장기 비밀을 하나 더 만들고, X.509 WIF는 인증서 발급·갱신 체계가 필요하다. 부팅 때마다 GCP를 호출하면 GCP 장애가 홈 기동 실패로 이어진다.
- 앱의 사용자 정의 `ConfigDataLoader`(Server ADR 0002 원안): 앱이 GCP 자격과 네트워크에 의존하게 된다. 파일 마운트로 두 origin이 같은 형식을 쓸 수 있으므로 채택하지 않는다.
- 묶음을 release 디렉터리에 함께 저장: release 디렉터리는 source SHA별로 불변이므로 같은 source의 비밀 교체를 막는다.

## 영향과 한계

- 비밀값이 GitHub runner를 거친다. 값은 출력·artifact에 남기지 않고 마지막 단계에서 삭제하지만, runner 침해에는 이 경계가 보호하지 못한다.
- 페이로드 한도는 8KiB에서 64KiB로, 파일당 16KiB로 늘었다.
- 새 수신기는 `config`가 없는 페이로드를 거부한다. 홈 제어 파일 설치와 Server caller의 Infra pin 갱신은 같은 배포 창에서 함께 수행한다.
- Cloud Run revision 구성은 source SHA별로 불변이므로 버전을 올릴 때는 새 source가 필요하다. pin 갱신 자체가 Server 커밋이므로 이 조건을 만족한다.
- 이 방식 이전의 release로 롤백하면 해당 release의 compose가 `runtime.env`를 요구한다. 새 방식으로 두 번 이상 성공 배포한 뒤에 홈 `runtime.env`와 노트북 원본을 삭제한다.
- 이전 묶음 디렉터리는 자동 삭제하지 않는다. 실행 중이거나 롤백 대상인 컨테이너가 마운트하기 때문이다.
- GitHub Secrets(SSH 키, Cloudflare Access, Discord), Worker Secrets, 홈 Tunnel 토큰은 이번 단일 원본 범위 밖이다.
