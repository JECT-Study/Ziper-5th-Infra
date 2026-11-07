# 0013 무료 Bot Fight Mode와 자동 상태 검사

- 상태: 채택 — 사용자 직접 설정 변경, 후속 운영 검증은 실행별 증거 참조
- 날짜: 2026-11-07

## 배경

알려진 정상 Access 자격과의 비교가 true인 Actions 실행42300183067은 2026-11-06T21:52:35.406Z에 보호 origin /readyz의 HTTP403·cf-mitigated:challenge를 기록했다. 사용자가 제공한 Security Events 화면의 같은 초 이벤트는 host origin-ziper.joonamin.dev, path /readyz, 동일 검사 User-Agent에 Bot Fight Mode의 관리 챌린지를 표시한다. 이 과거 실행의 차단 제품을 식별한 증거이며 모든 후속 403을 같은 원인으로 단정하지 않는다.

전용 읽기 토큰은 Account Analytics·Zone 읽기만으로 GraphQL 권한 거부를 받았다. Zone Analytics 읽기를 추가한 실행42348234455는 조회에 성공했지만 최근2시간 표본이0건이었다. 표본 없음은 차단 해소나 제품 원인의 증거가 아니다. 로컬 Node·Python의 같은 자격 요청은200으로 응답했지만 Actions의 후속 검사42348372280은 계속403 challenge였다.

## 결정

사용자는 joonamin.dev 전체 및 tocktock에도 영향을 준다는 설명을 확인하고 Bot Fight Mode를 직접 OFF로 변경했다고 응답했다. 초기 계획의 전역 보안 완화 금지에 대한 명시적 예외다. 도구는 보안 설정을 변경하지 않았다. 읽기 토큰에는 쓰기 권한을 추가하지 않는다.

무료 Bot Fight Mode는 도메인 전체에 적용되고 WAF custom Skip·Page Rule로 특정 호스트만 예외 처리할 수 없다. Actions의 자동 요청을 브라우저 challenge로 막지 않도록 해당 기능을 해제한다. 유료 봇 플랜을 활성화하거나 GitHub 전체 IP 범위를 허용하지 않는다. Access Service Auth와 다른 WAF는 별개이며 이 결정으로 공개 Bypass 정책을 추가하지 않는다.

변경 후 Actions 보호 origin 검사200과 직접 익명 접근403을 확인해야 runtime 배포를 시작한다. 읽기 검사 실패를 배포 명령 재실행으로 해결하지 않는다. 설정 OFF는 사용자 확인 뒤 열린 대시보드의 Bot Fight Mode Switch 값0을 접근성 도구로 읽어 대조했다. Bot Management 설정 API readback은 현재 읽기 토큰으로 확인하지 못했다. 검증한 응답 결과와 설정 조회의 한계를 구분한다.

## 대안과 영향

- WAF Skip 규칙: 무료 Bot Fight Mode에는 적용되지 않아 제외한다.
- 유료 플랜으로 호스트별 봇 예외: 추가 비용을 피하는 운영 조건에 따라 제외한다.
- GitHub 공용 IP 대역 허용: 넓고 변하는 IP를 신뢰 경계로 사용하지 않는다.
- 전역 Bot Fight Mode 유지: 현재 자동 요청의 차단이 남아 쌍 배포를 보류해야 한다.

이 결정은 tocktock을 포함한 같은 zone의 Bot Fight 보호를 해제한다. Access 인증을 대체하지 않으며 별도 기능의 설정을 확인한 것으로 확대하지 않는다. 향후 봇 보호를 다시 활성화하면 자동 검사와 Worker-origin 경로를 재검증하고 회귀 여부를 기록한다. 되돌리기는 같은 설정에서 Bot Fight Mode를 ON으로 바꾸는 것이며 자동 배포가 다시 차단될 수 있다.

## 근거

- [Bot Fight Mode의 범위와 Skip 제한](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/#rules)
- [원래 Actions 응답](../evidence/2026-11-07/protected-origin-challenge.json)
- [사용자 제공 이벤트의 비밀 없는 전사](../evidence/2026-11-07/paired-bot-fight-event.json)
- [후속 실행 범위](../nightly-walkthrough-2026-11-07.md)

[대시보드 OFF 읽기 확인](../evidence/2026-11-07/paired-bot-fight-ui-off.json)은 설정 화면 관측이며 Actions HTTP 성공을 대신하지 않는다.
