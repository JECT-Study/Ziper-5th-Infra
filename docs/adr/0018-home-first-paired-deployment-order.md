# 0018 쌍 배포에서 홈(Flyway 실행) 선행 배포와 실패 Cloud Run revision 대체 허용

- 상태: 채택 — 새 Infra main SHA 고정 후 실제 쌍 배포 실행 증거로 검증
- 날짜: 2026-11-22
- 관계: [ADR 0008](0008-private-cloud-run-and-production-e2e.md)의 비공개 Cloud Run 쌍 배포 순서를 조정하고 [ADR 0012](0012-paired-deployment-receipts.md)의 4개 job·8개 artifact 계약을 유지한다.

## 배경

기존 `.github/workflows/deploy-home.yml`은 `publish → backup (Cloud Run) → deploy (홈) → notify` 순서로 실행했다. 그러나 두 origin의 데이터베이스 마이그레이션 권한과 역할은 비대칭적이다.

- 홈 origin은 `ziper-home-migration-properties`를 마운트해 Flyway 스키마 마이그레이션을 실행한다.
- Cloud Run 백업 origin은 최소 권한 원칙([ADR 0015](0015-secret-manager-single-source.md))에 따라 마이그레이션 자격이 없으며 `SPRING_FLYWAY_ENABLED=false`와 Hibernate `ddl-auto: validate`로 기동한다.

신규 Flyway 마이그레이션이 포함된 Server 릴리스(예: `v1.1.0`, `V7`~`V12` 추가)를 기존 순서로 배포하면, 아직 마이그레이션이 적용되지 않은 공유 DB에 대해 Cloud Run이 먼저 기동하면서 `SchemaManagementException`으로 `/readyz` startup probe에 실패(`HealthCheckContainerError`)한다. 그 결과 홈 배포(`deploy`)는 시작조차 되지 않고, Cloud Run에는 실패한 revision이 `latestCreatedRevisionName`으로 남는다.

여기에 더해 Cloud Run은 실패 상태라도 `latestCreatedRevisionName` 삭제를 허용하지 않으며(`FAILED_PRECONDITION`), 기존 `scripts/deploy-cloud-run.py`는 `is_ready(service) == False` 또는 `latestCreatedRevisionName != latestReadyRevisionName`이면 무조건 `preceding_deployment_not_ready_inspect_before_retry`로 중단해 새 소스 SHA로도 자동 복구할 수 없는 교착 상태가 발생했다. 또한 `gcloud run deploy` 실패 시 일괄적으로 `gcloud_run_deploy_ziper-backup_outcome_unknown`만 반환해 실패 사유(`HealthCheckContainerError` 등)를 워크플로 로그에서 즉시 식별하기 어려웠다.

## 결정

- `.github/workflows/deploy-home.yml`의 실행 순서를 `publish → deploy (홈) → backup (Cloud Run) → notify`로 변경한다.
  - 보호 홈 origin 사전 검사(`scripts/verify-origin.ts`)와 `home-origin-health-attempt-N` artifact 업로드를 `deploy` job의 런타임 변경 직전으로 이동해, 홈이 비정상일 때 두 origin 모두 변경하지 않도록 유지한다.
  - 홈 `deploy`가 Flyway 마이그레이션과 공개 readiness 검증을 통과한 뒤에만 `backup` job이 Cloud Run 런타임을 갱신한다.
  - 보류 시간(02:30–06:00 KST)에는 `publish`가 `deferred=true`를 내보내 `deploy`가 `skipped`되더라도 `backup`이 실행되어 Artifact Registry 이미지 미러(`prepare`)만 수행하고 Cloud Run 런타임 변경은 건너뛴다.
  - 기존 4개 job 이름(`publish`, `deploy`, `backup`, `notify`)과 8개 artifact 이름은 그대로 유지해 `scripts/verify-paired-evidence.py` 및 [ADR 0012](0012-paired-deployment-receipts.md) 계약을 보존한다.
- `scripts/deploy-cloud-run.py`에서 이전 revision이 진행 중이 아닌 확정 실패 상태일 때만 **새 소스 SHA**로 대체 배포를 허용한다(`preceding_revision_terminally_failed`).
  - 허용 조건은 모두 동시에 만족해야 한다: 서비스 `Ready=False` 및 `ConfigurationsReady=False`, `latestCreatedRevisionName != latestReadyRevisionName`, `latestCreatedRevisionName != target_revision`, 기존 `latestReadyRevisionName`이 100% 트래픽을 서빙 중, 그리고 `revisions describe`로 확인한 `latestCreatedRevisionName`의 `Ready` 상태가 확정 `False`.
  - 서비스나 revision이 `Unknown`(조정 중)이거나, 트래픽이 정상 revision에 100% 고정되어 있지 않거나, 같은 소스 SHA를 재시도하는 경우에는 기존과 동일하게 `preceding_deployment_not_ready_inspect_before_retry`로 중단한다.
- `gcloud run deploy`가 `gcloud_run_deploy_ziper-backup_outcome_unknown`으로 실패하면 생성된 revision을 읽기 전용 `revisions describe`로 한 번 조회해 `Ready=False`인 경우 비밀이 없는 정적 사유 코드(`cloud_run_revision_failed_<reason>`)로 분류해 보고한다.

## 대안

- Cloud Run에 Flyway 실행 권한 부여: [ADR 0015](0015-secret-manager-single-source.md)의 최소 권한 원칙(`ziper-home-migration-properties`는 홈 전용)에 위배되며, Cloud Run과 홈 간 마이그레이션 경합 위험을 만든다.
- Cloud Run의 Hibernate `ddl-auto: validate` 비활성화: 스키마 불일치를 기동 시점에 조기 탐지하지 못하고 실제 요청 시 런타임 SQL 오류로 이어진다.
- 별도 Flyway 전용 사전 job 도입: 홈과 동일한 DB 네트워크·비밀 경로를 별도 실행 환경에 중복 구성해야 하며, 홈이 이미 마이그레이션 실행과 롤백·잠금을 소유하고 있어 불필요한 복잡도를 늘린다.

## 영향과 한계

- 홈이 새 스키마로 마이그레이션된 뒤 Cloud Run이 갱신되기까지 짧은 구간(수십 초~수 분) 동안 Cloud Run은 직전 릴리스를 유지한다. 이 구간에 홈 장애가 발생하더라도 구 Cloud Run이 동작할 수 있도록 Server의 Flyway 마이그레이션은 가능한 한 하위 호환(expand-and-contract) 원칙을 유지하는 것이 권장된다.
- 홈 `deploy`가 성공한 뒤 `backup`이 실패하면 `notify`는 실패로 기록하며, 양쪽 readiness가 모두 통과한 경우에만 쌍 배포 성공(`paired`)으로 판정한다.
- 단위 테스트는 offline fixture로 순서·대체 조건·사유 분류를 검증하며, 실제 운영 DB 마이그레이션 및 Cloud Run revision 대체는 새 Infra SHA 고정 후 Server 수동 배포 실행 증거로 확인한다.
