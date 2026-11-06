# 0011 기존 집어 컨테이너 재기동 정책의 정합

- 상태: 채택 — 실제 적용은 실행 receipt로 구분
- 날짜: 2026-11-07

## 배경

ADR0009는 새 release를 always로 구성했지만 Cloudflare challenge로 이미지 배포가 막혀 기존263 컨테이너는 unless-stopped를 유지한다. 기존 파일을 수정하지 않고 재기동 정책만 동기화하면 다음 daemon 부팅에서도 같은 정지 상태를 남길 위험을 줄일 수 있다. 새 이미지 배포나 다음 전체 장비 부팅의 성공으로 계산하지 않는다.

## 결정

기록한 app·전용 cloudflared ID와 current-version·SENTRY_RELEASE·project/service label·실행 상태를 대조한 뒤 Docker update --restart=always만 실행한다. 배포 공통 lock과 미해소 recovery lease 거부, 승인된 일정 파일 해시와 시간 가드를 적용한다. 다른 서비스·daemon·장비는 시작하거나 재부팅하지 않는다.

`scripts/reconcile-home-restart-policy.py`는 기본값이 실제 읽기 계획이다. --apply는 스크립트가 검토된 main SHA와 일치하고 해당 main CI가 성공한 경우에만 가능하다. 작은 압축 control payload로 전달하며 native SSH 명령 길이 상한을 검사한다. 변경 전후 컨테이너 ID·StartedAt·실행 상태와 current-version·참조 compose 파일의 불변을 확인한다. 이미 always면 update를 발행하지 않는다. 결과가 불명확하면 실패로 기록하고 실제 상태를 먼저 읽는다.

## 영향과 한계

기존 release 파일·manifest와 이미지 기록은 보존한다. 그 compose의 과거 unless-stopped 값과 현재 Docker runtime 설정의 차이는 이번 전환 receipt에 기록한다. 향후 성공한 새 배포는 검토된 always compose로 수렴한다. 과거 compose를 수동 재적용하거나 trusted deploy의 rollback이 과거 compose를 선택하면 unless-stopped가 복원될 수 있다. rollback 뒤에도 실제 정책을 재조회하고 필요하면 새 컨테이너 ID·release로 계획을 다시 검토한다. Docker policy readback·현재 공개 health와 다음 실제03–06시 전체 부팅은 별도 검증이다.
