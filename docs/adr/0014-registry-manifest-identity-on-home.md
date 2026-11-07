# 0014 홈 이미지의 Registry manifest 식별과 Docker export 의존 제거

- 상태: 채택 — 실제 새 수신기의 운영 활성화는 실행별 증거로 확인
- 날짜: 2026-11-07
- 관계: ADR0005의 홈 수신기 config 식별 방법을 대체한다. config digest와 JAR 해시를 함께 검증하는 계약은 유지한다.

## 배경

Source 실행42350926001은 Cloud Run 생성과 비공개 probes3쌍을 통과했지만 Home 활성화 전에 실패했다. 제한 SSH check와 일반 명령 거부, GHCR pull은 성공했다. 새 release 디렉터리·runtime tag는 없었고 기존263558 릴리스는 계속 정상 응답했다.

Home Docker29.2.1은 linux/amd64 이미지의 config·RootFS8개를 inspect로 반환하고, 중지 상태의 임시 컨테이너에서 추출한 JAR도 CI 해시와 일치했다. 그러나 docker save는 성공 코드0과 함께 manifest blob만 포함한 tar를 만들었다. manifest.json이 가리키는 config blob과 layers가 없었다. platform을 지정한 export도 실패했다. 이는 실제 호스트에서 재현한 export 문제이며 모든 Docker29 환경에 같은 결함이 있다고 일반화하지 않는다.

공식 Moby [49473](https://github.com/moby/moby/issues/49473)·[52193](https://github.com/moby/moby/issues/52193)는 containerd 저장소에서 유사한 export 누락을 보고한다. 공유 Docker daemon이나 저장소 전환·업그레이드는 tocktock에 영향을 줄 수 있어 이번 수정에서 수행하지 않는다.

## 결정

홈 수신기는 docker save 대신 기존 임시 Docker 인증 설정으로 immutable digest의 `docker manifest inspect --verbose`를 읽는다. Raw base64를 디코딩하여 SHA256이 요청한 manifest digest와 정확히 일치해야 한다. Ref·Descriptor digest/size/mediaType도 일치시킨다. 단일 Docker schema2 또는 OCI image manifest만 허용하며 index는 거부한다. linux/amd64·config digest 형식·config 크기·layer digest와 수를 검증한다.

Raw manifest의 config digest를 CI release manifest와 비교한다. 로컬 엔진은 classic의 config ID 또는 containerd의 manifest ID와 일치한 Descriptor로 같은 객체에 연결한다. 로컬 플랫폼·RootFS 형식·diff ID 형식·레이어 수도 대조한다. compressed layer digest와 uncompressed diff ID를 같은 값으로 비교하지 않는다. 이후 실제 임시 컨테이너에서 추출한 JAR SHA256을 검사한다. 모든 확인이 끝나기 전에는 runtime tag·release 파일·앱을 바꾸지 않는다.

이는 로컬 export에서 config 원본 바이트를 다시 해시하던 절차를, 해시가 검증된 Registry Raw manifest의 config 참조와 Docker engine의 content-addressed 객체 연결로 대체하는 결정이다. Docker pull의 digest 검증과 로컬 엔진을 신뢰하는 경계는 유지한다. 손상되거나 악의적인 Docker daemon 자체에 대한 원격 증명은 아니다.

Registry 조회는60초, 로컬 inspect는30초로 제한한다. stdout 크기를 제한하고 토큰·원본 응답·원본 오류를 로그나 artifact로 남기지 않는다. 조회 실패·hash/플랫폼/descriptor 불일치는 즉시 실패하며 배포 쓰기를 자동 재실행하지 않는다. 기존 8KiB 입력, 공유 잠금, 복구 lease, 예약 가드, 자격 임시 보관·삭제와 롤백은 유지한다.

CI의 게시 전 로컬 빌드·AR 검증은 기존 엄격한 archive config 해시 경로를 유지한다. 정상 export를 지원하는 해당 실행의 결과와 홈 export 결함을 구분한다. 홈에는 Raw 필드를 제공하는 Docker CLI가 필요하며 이번 대상은29.2.1이다.

## 대안과 검증 한계

- config 검증 삭제 또는 opaque Docker ID를 config digest로 취급: 식별 계약을 약화하므로 제외한다.
- platform 옵션만 추가: 실제 Home에서 실패하여 해결책으로 사용하지 않는다.
- 공유 daemon 재시작·containerd 비활성화: 다른 앱의 운영 영향을 피하려고 제외한다.
- CI image archive를 SSH로 전달: GHCR digest pull 계약을 유지하므로 제외한다.

Registry Raw 읽기와 실제 Home inspect·JAR 추출은 각각 확인한다. 새 홈 CLI의 인증된 Registry 조회와 실제 앱 활성화 성공은 후속 Actions에서 별도로 확인한다. Cloud Run만 성공한 실행을 쌍 배포 성공으로 기록하지 않는다.
