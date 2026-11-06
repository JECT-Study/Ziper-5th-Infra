# 0010 Infra 소유자 개인의 PR 리뷰 예외

- 상태: 채택 — ADR0003의 Infra 관리자 전체 리뷰 우회 결정을 대체
- 날짜: 2026-11-07

## 배경

사용자는 Infra main에서 joonamin의 리뷰를 요구하되 자신의 권한으로는 초기 설정 PR을 병합할 수 있어야 한다고 요청했다. ADR0003의 enforce_admins=false는 다른 관리자에게도 리뷰 우회를 허용하므로 그 범위가 넓다. 자기 PR 승인은 불가능하지만 GitHub는 특정 사용자의 pull request 예외를 지원한다.

## 결정

Infra main의 enforce_admins를 true로 설정하고 required_pull_request_reviews.bypass_pull_request_allowances.users를 joonamin 한 명으로 제한한다. 팀·앱 예외는 없다. 먼저 개인 예외를 등록·재조회하고 관리자 강제를 켠 뒤 전체 정책을 재조회한다. 원본은 [github-main-review.json](../../config/github-main-review.json)이다. 호출은 [GitHub 공식 branch protection API](https://docs.github.com/en/rest/branches/branch-protection)를 따른다.

리뷰1명·CODEOWNERS·마지막 push 승인·stale 승인 무효화·대화 해결·strict check와 push 사용자 제한을 보존한다. 소유자의 예외는 PR 요구에만 두며 CI는 통과 후 병합한다. 별도 이력 ruleset의 non_fast_forward·deletion에는 예외를 추가하지 않아 소유자도 force push·브랜치 삭제를 허용받지 않는다. Server 정책은 이 변경의 대상이 아니다.

## 대안

- 모든 관리자의 강제 해제 유지: 소유자 개인 예외보다 넓어 제외한다.
- 모든 리뷰 예외 삭제: 자기 PR 승인 제한과 사용자의 bypass 요구를 만족하지 못한다.
- 새 조직 팀·추가 ruleset 도입: 기존 개인 allowance로 필요한 범위를 표현할 수 있어 추가하지 않는다.

## 영향과 한계

joonamin의 병합은 사람의 리뷰 승인이 아니라 명시한 PR 예외 사용으로 기록한다. 다른 관리자 계정으로 거부를 직접 실험하지 않고 API 설정을 조회한다. 보호 설정 자체를 바꿀 수 있는 관리자·조직 소유자 권한을 제거한 것은 아니다. 계정명·CODEOWNERS를 바꾸면 allowance와 원본 설정도 함께 검토한다. 원래 설정과 이후 실제 설정·병합의 증거를 별도로 유지한다.
