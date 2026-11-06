# 0005 전송·로드 검증의 OCI config digest

- 상태: 채택, 실제 release 재검증 진행 중
- 날짜: 2026-11-06

## 배경

실제 Actions 실행 42214052911에서 1MiB 사전 검사와 162,880,062바이트 release 전달이 통과했다. Docker load 후 image inspect의 Id 비교가 달라 앱 기동 전에 차단됐다.

CI 빌드 ID는 `sha256:72d6a7f29bd1306c4bd2bfd1c0e6502d35bf14d08c3885bd3747c53dddace331`이었다. 홈 containerd의 Id와 Descriptor는 `sha256:b9dbfb633baa97ee4d214c03eee9eaa39f28c1dc012d8337a88fa44198c730d7`이었다. 홈에서 해당 이미지를 다시 export한 config blob의 SHA256은 CI 값과 일치했다. 서로 다른 종류의 digest를 비교한 문제다.

## 결정

release manifest의 `imageConfigDigest`를 OCI config blob 원문 바이트의 SHA256으로 정의한다. CI는 docker save 결과에서 이를 계산한다. 수신기는 전달된 archive와 로드 후 다시 export한 이미지에서 같은 digest를 계산해 manifest와 대조한다. tag·단일 이미지·linux/amd64·config 내용 주소·rootfs diff_ids를 검사하고, JAR SHA256·archive SHA256·설치 계약 검증도 유지한다.

이는 [OCI config 명세](https://github.com/opencontainers/image-spec/blob/main/config.md)의 실행 설정과 압축 전 layer diff_ids에 묶인 식별자다. [OCI manifest](https://github.com/opencontainers/image-spec/blob/main/manifest.md)와 digest 종류를 혼용하지 않는다. manifest 형식은 기존 imageId에서 명시적인 imageConfigDigest로 함께 이행하며 예전 필드의 호환 분기는 두지 않는다.

호스트의 `image-id` 파일은 해당 Docker 엔진이 보고한 로컬 Id로 유지한다. 로컬 tag 변조 확인·롤백에 사용하며 서버 간 동일성 판단에 사용하지 않는다. CI는 비밀 없는 release manifest도 artifact로 남겨 실패 시 비교 근거가 보존되게 한다.

## 대안

- ID 검사를 생략하고 JAR만 확인: OS layer·실행 설정의 동일성을 잃으므로 제외한다.
- 공유 홈 Docker 저장소를 변경: 다른 프로젝트와 이미지 상태에 영향을 줄 수 있어 제외한다.
- runtime Id·registry manifest·config digest를 같은 값으로 취급: 이번 실제 실패를 반복하므로 제외한다.

## 영향과 한계

CI 패키징 코드와 설치 수신기·image_identity.py를 함께 갱신해야 한다. 로드 후 export를 한 번 더 수행하므로 임시 디스크와 I/O가 추가된다. Registry manifest digest와 동일한 종류의 값이라고 표현하지 않는다. 홈과 Cloud Run을 비교할 때에도 config descriptor digest와 registry digest를 구분해 증거에 남긴다.
