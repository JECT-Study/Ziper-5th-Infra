# 운영 E2E 실행 계획

- [x] poteto-mode Principles와 실제 배포 흐름 검토
- [x] 기준선: main CI 성공, 최신 홈 배포 42250905425 실패, 현재 홈 릴리스 263558f...의 두 공개 probe 200
- [ ] 최신 실패 root cause 식별 및 GHCR digest pull 경로 작성·검증
- [ ] GCP spend cap 재조회 → 최소 권한·비밀 구성 → Cloud Run 동일 이미지 준비
- [ ] Infra·Server CI와 사용자 승인 bypass 병합 → main 수동 배포
- [ ] Worker 배포 → 1분 alarm·10분 표본·직접 origin 인증 검증
- [ ] 자동 복구 watchdog 무해 검증 → 집어 앱 장애 → 600초 내 Cloud Run 전환
- [ ] 복구 및 HALF_OPEN 실패·CLOSED 전이 확인
- [ ] 03:00 KST 예정 종료 관찰, 새벽 복귀는 실제 관찰 범위를 명시
- [ ] PR #1·최종 보고서에 실제 증거와 실패·미실행 범위 기록

## 완료 판정

동일 release SHA와 이미지 config digest가 홈과 Cloud Run에서 일치하고, 외부 단조 시계로 홈 장애 직전부터 백업의 첫 정상 응답까지 600초 이내다. 공개 요청과 읽기 전용 ops의 실제 상태 전이를 함께 기록한다. Discord는 webhook 응답의 실제 채널·메시지 ID를 대조한다. 단위 테스트·CI·사후 현재 200을 운영 E2E 통과로 대체하지 않는다.

## 경계

02:30–06:00 KST 홈 배포 보류를 유지한다. 03:00 장비 종료를 우회하지 않는다. tocktock·다른 Tunnel·운영 DB 데이터는 변경하지 않는다. 장애는 집어 app 컨테이너만 대상으로 하며 독립 복구 장치 확인 전에 주입하지 않는다. GCP 월 KRW 1,000 Cloud Run cap과 min0/max1을 재조회하며 비용 절대 상한을 주장하지 않는다.
