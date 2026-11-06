# 0009 예약 종료 후 기존 컨테이너 재기동

- 상태: 채택 — 격리 Docker 검증과 운영 설정 적용을 각각 기록하며 실제 다음 BIOS 부팅은 별도 검증
- 날짜: 2026-11-07

## 배경

06:00 Windows 부팅과 Ubuntu 실행은 WSL 배포판을 실행하지 않는 읽기 진단으로 확인했다. 그러나 집어 app과 전용 cloudflared는 03:00의 종료 상태를 유지했고 두 컨테이너의 재시작 정책은 unless-stopped였다. 이 상태에서 공개·보호 origin은 530을 반환했다. 당시 종료가 어떤 명령으로 기록됐는지는 확정하지 않는다.

## 결정

새 release의 두 서비스에 restart: always를 사용한다. Docker의 always는 명시적으로 stop한 동안에는 재시작하지 않고, daemon 재기동 때는 다시 시작한다. 따라서 운영 중 app만 중지하는 leased 장애 실험과 독립 복구 timer는 유지된다. 운영 daemon·장비를 재시작하여 이 설정을 시험하지 않는다.

기존 릴리스 파일과 manifest는 수정하지 않는다. 새 Infra main CI와 두 Source pin 갱신을 완료한 뒤 새 Source SHA로 배포하여 컨테이너의 실제 RestartPolicy를 읽어 대조한다. 기존 종료 상태의 복구는 기록된 버전·image ID·SENTRY_RELEASE·project/service labels를 대조하고 공통 lock 아래 해당 두 컨테이너만 start한다.

새 이미지 배포가 외부 challenge로 막힌 동안 기존 두 컨테이너의 runtime 정책만 정합하는 절차는 [ADR0011](0011-reconcile-existing-restart-policy.md)을 따른다. 기존 이미지·파일은 보존하고 적용 전후 readback과 전체 다음 장비 부팅을 구분한다.

## 대안

- unless-stopped 유지: 종료 상태가 다음 부팅에도 유지되는 현재 사례를 수용하지 않는다.
- 별도 부팅 스크립트·자동 배포 대기열: 동일한 기동 책임을 중복하지 않고 Docker의 재시작 정책을 사용한다.
- 공유 Docker daemon 또는 장비 재부팅 시험: tocktock 등 다른 서비스에 영향을 주므로 제외한다.

## 영향과 한계

수동으로 app을 중지한 후 Docker daemon이 재기동되면 app이 다시 시작한다. 영구 폐기할 때는 restart 정책 해제 또는 명시적인 서비스 제거 절차가 필요하다. 예약 장애 실험에서는 daemon을 건드리지 않는다.

`scripts/verify-restart-policy.py`는 로컬의 일회용 nested daemon에서 수동 stop과 daemon 재기동의 차이를 확인한다. 이 결과와 운영 컨테이너의 정책 readback은 새 설정으로 전체 홈서버가 다음 BIOS 주기에 부팅됐다는 증거를 대신하지 않는다. [Docker 공식 설명](https://docs.docker.com/engine/containers/start-containers-automatically/)을 따른다.
