# 0003 소유자 리뷰와 관리자 bypass

- 상태: 채택
- 날짜: 2026-11-06

## 배경

사용자는 Infra 변경에 joonamin의 승인을 요구하면서 관리자 bypass도 사용할 수 있어야 한다고 명시했다. 초기에는 관리자까지 보호를 강제했지만 PR 작성자와 소유자가 동일하면 자기 PR 승인이 불가능했다.

## 결정

Infra main의 CODEOWNERS를 `@joonamin`으로 두고 일반 PR에 승인 1개와 code owner 리뷰, 최신 check, 대화 해결을 요구한다. force push와 브랜치 삭제는 금지하고 push·merge 가능 사용자는 joonamin으로 제한한다. 관리자에게는 bypass를 허용한다.

Infra main의 이력 보호는 별도 활성 ruleset으로 분리한다. `non_fast_forward`와 `deletion` 규칙에 bypass 대상을 두지 않으므로 PR 리뷰의 관리자 bypass가 이력 변경까지 허용하지 않는다. 설정 원본은 `config/github-main-history.json`이다. [공식 규칙 합성 문서](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets#about-rule-layering)에 따라 ruleset과 기존 브랜치 보호를 함께 적용한다.

Server develop·main에도 기존 검사·리뷰·force push 금지 규칙을 보존한 채 관리자 강제를 해제한다. 최초 운영 연결은 사용자가 허용한 관리자 병합을 사용한다. CI 통과와 관리자 병합은 사람의 리뷰 승인과 구분해 기록한다.

## 대안

- 관리자 bypass 금지: 사용자의 수정 요구와 충돌하므로 제외한다.
- 리뷰 규칙 전체 삭제 또는 force push 허용: 소유자 검토·이력 보존 요구를 약화하므로 제외한다.

## 영향과 한계

관리자는 승인이나 검사 요구를 우회할 수 있다. 모든 변경에 사람의 승인이 기술적으로 강제된다고 표현하지 않는다. 이력 ruleset 자체를 변경할 수 있는 관리자 권한까지 제거하지는 않는다. 실제 설정은 GitHub API 재조회와 nightly 증거 JSON으로 확인한다. 운영 main을 실제 force push하거나 삭제하는 파괴적 검증은 수행하지 않는다.
