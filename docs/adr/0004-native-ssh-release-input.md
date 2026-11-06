# 0004 SSH release 바이너리 입력을 WSL에 직접 전달

- 상태: 채택, 운영 release 재검증 진행 중
- 날짜: 2026-11-06

## 배경

실제 Server Actions 배포는 제한 수신기에 연결한 뒤 입력 전송에서 진행하지 못했다. 기본 셸은 Windows PowerShell이고 전용 키의 강제 명령이 PowerShell을 다시 실행했다. 같은 경로에서 4바이트의 잘못된 archive는 거부됐지만 128KiB 입력은 시간 초과됐다. 작은 archive 거부만으로 대용량 전달을 검증할 수 없었다.

별도 진단 키로 WSL Python에 직접 연결하자 128KiB와 1MiB 바이너리의 길이·SHA256이 일치했다. 기본 셸과 다른 서비스 설정을 바꾸지 않고 집어 전용 키의 강제 명령만 변경한다.

## 결정

PowerShell 수신기 `receive.ps1`을 제거한다. Windows SSH 기본 셸에서 wsl.exe를 직접 호출하고 원래 명령은 데이터 인수로 전달한다. Python은 check 또는 deploy와 40자리 SHA만 허용하며 일반 명령·셸 구문·사용자 경로를 실행하지 않는다.

입력 파일은 WSL `/opt/ziper/incoming`에 배타 생성하고 2GB를 넘기면 중단한다. 생성한 파일은 성공·실패 후 정리하며 기존 파일을 덮어쓰거나 삭제하지 않는다. archive·manifest·설치 계약·이미지·JAR의 기존 검증과 배포 잠금은 유지한다.

실제 배포 직전에 같은 SSH 연결 설정으로 check, 일반 명령 거부, 1MiB 바이너리 길이·해시와 잘못된 archive 거부를 확인한다. 이 증거를 artifact로 남기고 통과한 뒤 실제 release를 전송한다. 검증 fixture는 gzip archive가 아니므로 앱 기동이나 이미지 반영에 도달하지 않는다.

## 대안

- 공유 sshd 기본 셸 변경: 다른 프로젝트의 SSH 동작까지 바꾸므로 제외한다.
- 작은 입력 검사만 유지: 이번 장애를 감지하지 못하므로 제외한다.
- 전송 정체 중 release 재전송: 수신 상태와 충돌할 수 있어 기존 실행 상태 확인 전에는 수행하지 않는다.

## 영향과 한계

서버의 강제 명령과 설치 수신기를 함께 갱신해야 한다. 개인 Access 세션의 1MiB 검증은 GitHub CI 서비스 토큰이나 실제 이미지 배포를 증명하지 않는다. 실제 운영 실행·readiness·Discord 결과는 PR #1에 별도로 기록한다. 원래 명령의 환경 변수 확장은 현재 Windows PowerShell 기본 셸에 의존하며 셸을 변경하면 재검증한다.
