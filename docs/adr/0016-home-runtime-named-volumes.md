# 0016 홈 런타임 파일을 Docker named volume으로 공급

- 상태: 채택 — 다음 예약 부팅의 자동 재기동은 실행별 증거로 확인
- 날짜: 2026-11-15
- 관계: [ADR 0009](0009-resume-after-scheduled-boot.md)·[ADR 0011](0011-reconcile-existing-restart-policy.md)이 전제한 "restart: always면 예약 부팅 후 재기동된다"를 보완한다. [ADR 0015](0015-secret-manager-single-source.md)의 불변 설정 묶음은 원본으로 유지한다.

## 배경

2026-11-08 06:02 KST부터 11-15까지 매일 예약 부팅 후 홈 app과 전용 tunnel이 `Exited (127)`에 머물렀다. 두 컨테이너는 `restart: always`였고 restart count는 0이었다. Docker가 남긴 오류는 WSL 배포판 경로 `/opt/ziper/private/db-ca.pem`의 bind source인 `/run/desktop/mnt/host/wsl/docker-desktop-bind-mounts/Ubuntu/<hash>`가 파일이 아니라는 것이었다.

Docker Desktop은 WSL 배포판 안의 경로를 배포판 프록시가 만든 bind-mounts 경로로 연결한다. 백엔드 로그에서 프록시가 이 파일을 다시 연결한 시각은 부팅 직후(11-14 21:02:50Z 등)였고, daemon의 자동 재시작은 그 전에 실패한 것으로 판단한다. daemon 로그는 약 10분마다 교체되어 시도 시각 자체는 관측하지 못했다. 같은 장비에서 Windows 경로(`C:\...`)를 bind하는 다른 서비스는 매 부팅 재기동되었다. 배포판 안에서 `docker start`를 실행하자 즉시 복구되었다. 11-07 06시의 같은 증상은 `unless-stopped` 정책으로 판단했으나 실제 원인은 이 bind 경로였을 가능성이 높다. 조사 기록은 [home-boot-outage.json](../evidence/2026-11-15/home-boot-outage.json)에 있다.

## 결정

- app의 설정 묶음과 tunnel 토큰을 WSL bind 대신 external named volume으로 마운트한다. volume은 Docker Desktop VM 안에 있어 배포판 프록시 없이 daemon이 바로 마운트한다.
- 설정 volume 이름은 `ziper-config-<묶음 ID>`, 토큰 volume은 `ziper-tunnel-<토큰 sha256 앞 24자>`다. app은 토큰 volume을, cloudflared는 설정 volume을 보지 않는다.
- `deploy.sh`는 배포 lock 아래에서 이미지 확인 후 volume을 만든다. 실행하지 않는 helper 컨테이너(`--network none`)에 `docker cp`로 넣고 다시 꺼내 원본과 바이트 단위로 비교한다. 이미 있는 volume도 매번 비교한다.
- volume은 `/opt/ziper/private/config/<ID>/`의 불변 묶음에서 파생한 사본이다. 내용이 다르고 사용 중이 아니면 다시 만들고, 사용 중이면 배포를 거부한다. 복사에 실패하면 volume을 지우고 이전 release·설정으로 되돌린다.
- 파일 소유자는 volume에서 보존되지 않으므로 권한은 모드 0444로만 맞춘다.

## 대안

- Windows 경로로 이동: `/mnt/c`가 `metadata` 없이 마운트되어 모드·소유자가 적용되지 않고, 그 Windows 사용자의 모든 프로그램이 비밀 파일을 읽을 수 있다.
- 복구 timer가 기동 실패 컨테이너를 `docker start`: 수정은 작지만 부팅마다 1~2분 지연되고 실패 원인이 남는다.

## 영향과 한계

- 첫 배포에서 app과 cloudflared가 새 mount로 재생성된다. 이전 release의 compose로 롤백하면 해당 compose의 WSL bind를 다시 쓰므로 그 release는 부팅 재기동 문제가 남는다.
- 사용하지 않는 오래된 volume은 자동으로 지우지 않는다. 실행·롤백 대상이 아닌지 확인한 뒤 수동으로 정리한다.
- 실제 예약 부팅 후 자동 재기동은 다음 06시 부팅에서 확인한다. Docker Desktop 재시작 실험은 같은 장비의 다른 서비스를 멈추므로 하지 않았다.
