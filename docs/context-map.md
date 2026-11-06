# 문서 지도

작업 전에 이 문서를 읽고 실제 코드·설정·스크립트와 대조합니다. 구현과 문서는 같은 PR에서 수정합니다. 운영 검증을 로컬 검증으로 대신하지 않습니다.

| 문서 | 목적 | 변경 시 검토 |
| --- | --- | --- |
| [README](../README.md) | 실행·검사·현재 범위 | 진입 명령, 도구 버전, 구현 상태 |
| [운영](operations.md) | 배포 전제·비밀 관리·장애 대응 | Worker 설정, 워크플로, 운영 절차 |
| [검증](verification.md) | 판정 조건과 실제 확인 범위 | 검사 실행, 운영 증거 추가 |
| [Nightly walkthrough](nightly-walkthrough-2026-11-06.md) | 2026-11-06 인계와 실환경 판정 | 실제 실행 결과와 추가 준비 사항 |

## 결정 이력

- [0001 홈서버의 분 단위 슬라이딩 윈도우와 서킷 브레이커](adr/0001-home-circuit-breaker.md)

장기적인 인프라·인증·일관성·장애 전환 결정은 ADR에 배경·결정·대안·영향과 한계를 남깁니다. 결정을 바꾸면 새 ADR로 대체 관계를 기록합니다.
- [0002 예약 운영과 운영 E2E 증거](adr/0002-scheduled-operation-and-e2e.md)
- [0003 소유자 리뷰와 관리자 bypass](adr/0003-owner-review-and-admin-bypass.md)
- [0004 SSH release 바이너리 입력을 WSL에 직접 전달](adr/0004-native-ssh-release-input.md)
