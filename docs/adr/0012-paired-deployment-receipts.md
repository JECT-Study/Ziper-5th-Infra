# 0012 쌍 배포의 릴리스 식별과 시도별 알림 증거

- 상태: 채택 — 구현·운영 검증 결과는 PR #1의 실행 증거로 구분
- 날짜: 2026-11-07

## 배경

정상 health만으로는 새 이미지 대신 이전 릴리스가 응답한 경우를 구별하지 못한다. 기존 Discord 전송은 메시지 ID를 로그에 남기지만 저장된 메시지의 내용과 실행 시도를 대조하지 않는다. 같은 Actions 실행을 전체 재실행해도 이전 시도의 자료를 보존해야 한다.

## 결정

Server 공개 검사 CLI에 expected-release와 expected-origin을 함께 지정한다. Home의 /livez·/readyz가 모두 예상 source SHA와 home origin을 반환해야 한다. 누락·불일치는 HTTP200 계약 위반으로 즉시 실패한다. 헤더에서 검증한 SHA와 origin만 기록하고 기존 JSON·캐시·크기·시간 계약은 유지한다. 내부 준비 한도는 180초이며 외부 강제 종료는 195초로 결과 저장 여유를 둔다.

모든 쌍 배포 artifact 이름에 github.run_attempt를 붙이고 같은 시도의 manifest만 내려받는다. CI의 tested-release는 별도의 source main CI 실행에서 가져오며 이 이름을 바꾸지 않는다. 두 환경의 source SHA·OCI config digest·JAR 해시를 대조한다. registry 간 manifest digest와 OCI config digest를 같은 종류의 값으로 비교하지 않는다.

Discord는 wait=true POST 한 번 후 받은 메시지를 같은 webhook의 GET으로 조회한다. 채널·메시지 ID·전체 예상 내용의 일치를 확인한다. 메시지에는 SHA·run ID·시도 번호가 들어간다. GET만 연결 오류·429·5xx에 한해 최대 3회, 요청당 10초, 시도 사이 2초로 제한한다. 인증·리다이렉트·내용 불일치는 즉시 실패한다. POST는 결과가 불명확해도 자동 재전송하지 않는다.

시도별 영수증에 검증된 SHA·run/attempt·결과·scope·message/channel ID·조회 횟수와 상태를 남긴다. webhook URL·token·응답 원문은 저장하지 않는다. unknown·posted와 confirmed를 구분한다. 배포 성공 알림은 두 runtime readiness가 모두 성공한 경우만 발송하며 알림 실패로 배포를 다시 실행하지 않는다.

## 대안과 영향

- health200만 확인하면 이전 릴리스를 새 배포로 오인하므로 제외한다.
- artifact를 덮어쓰면 이전 시도의 증거를 잃으므로 시도별 이름을 쓴다.
- POST 자동 재시도는 중복 알림을 만들 수 있어 제외한다.
- API 전송·재조회는 채널 메시지 저장 증거다. 개인 기기의 푸시·읽음 확인은 아니다.

Infra main CI를 통과한 실제 병합 SHA로 Server의 uses와 infra_sha를 함께 갱신한다. Server 검증기와 pin 갱신은 같은 PR에 넣어 구 CLI에 새 옵션을 전달하지 않는다. 운영 성공은 로컬 검사와 별도로 두 번의 실제 실행 증거를 확인한다. Worker 장애 전환·600초 복구는 이 쌍 배포 검증의 통과 범위에 포함하지 않는다.
