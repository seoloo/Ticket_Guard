<!--
[홍석환] MongoDB 설치와 연결 안내
시스템·원본 DB의 계정·네트워크·초기화·검증 절차를 설명한다.
-->
# MongoDB 설치와 계정

최초 설치·인증 검사·Compass·재시작과 오류 해결은
[루트 README DB 매뉴얼](../README.md#db별-포트-번호)을 기준으로 한다.
모든 Docker 운영 명령은 저장소 루트에서 `--env-file .env`를 사용한다.
기존 `raw_consumer/.env`는 보관 파일이며 실행에 사용하지 않는다.

| 항목 | 시스템 DB | 원본 DB | QA 자체 DB |
|---|---|---|---|
| 환경 파일 | 루트 `.env` | 루트 `.env` | 루트 `.env` |
| 프로젝트 | `ticket-guard-workspace-db` | `ticket-guard-raw` | `ticket-guard` |
| 서비스 | `mongo` | `mongo-raw` | `qa-mongo` |
| 내부 포트 | `27017` | `27020` | `27017` |
| PC 포트 | `MONGO_HOST_PORT`, 기본 `27017` | `27020` | `QA_MONGO_HOST_PORT`, 기본 `27021` |
| 기본 DB / 일반 계정 인증 DB | `ticketguard` | `ticketguard_raw` | `ticketguard_qa` |
| 기본 계정 | `MONGO_WRITER_*` | `RAW_MONGO_WRITER_*` | `QA_MONGO_USERNAME/PASSWORD` |

PC 포트는 각 local override를 적용한 경우에만 공개된다. root 인증 DB는 `admin`이다.
reader는 선택 사항이다. 기본 관리자 앱과 Compass는 writer 계정으로 조회할 수 있다.
QA 자체 DB 저장과 외부 시스템·원본 DB 검증은 구분한다.

## 초기화와 기존 데이터

빈 볼륨에서만 초기화 스크립트가 계정을 생성한다. 환경 파일 통합은 기존 계정·DB·포트를
바꾸지 않으며 DB 재생성이 필요 없다. `.env` 수정만으로 기존 비밀번호가 바뀌지 않는다.
계정 추가 도구는 유효한 관리자 인증을 요구하고 기존 비밀번호·권한이 다르면 변경 없이
중단한다. 인증 해제나 볼륨 삭제를 복구 수단으로 사용하지 않는다.

## 선택적 QA 외부 DB 검증

기존 DB를 읽어 적재 결과를 대조하는 기능이며 QA 전용 원본 DB를 만들지 않는다.
읽기 전용 계정·URI·네트워크를 준비한 경우에만
[선택적 연결 명령](../README.md#4-선택-별도-읽기-계정과-qa-외부-db-검증)을 사용한다.
기본 `$teamArgs`에는 연결 파일과 검사 명령을 포함하지 않는다.

- 시스템 reader: `MONGO_ADMIN_READER_USERNAME/PASSWORD`, 인증 DB `MONGO_DATABASE`
- 원본 reader: `RAW_MONGO_READER_USERNAME/PASSWORD`, 인증 DB `RAW_MONGO_DATABASE`
- URI: `TICKET_GUARD_QA_SYSTEM_MONGO_URI`, `TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI`
- 출처: 같은 루트 `.env`의 `TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID`와 `RAW_SOURCE_ID` 일치
- 토픽: `KAFKA_EVENTS_TOPIC`과 `RAW_KAFKA_TOPIC` 일치
- 네트워크: `TICKET_GUARD_ADMIN_MONGO_NETWORK`, `TICKET_GUARD_QA_RAW_MONGO_NETWORK`

URI의 자격 증명은 URL 인코딩하고 DB별 내부 호스트·포트를 명확히 지정한다.
`qa/compose.qa-live.yml` 뒤에 `compose.qa-db-access.yml`을 마지막에 추가해야 검사
스크립트도 마운트된다. 연결 파일 없이 검사 경로를 실행하면 파일 없음 오류가 발생한다.
출처 문서가 없다는 안내는 빈 DB와 출처 불일치를 별도로 확인해야 한다는 뜻이다.

## 같은 PC · 팀 내부망 · AWS

- 같은 PC: local override의 `127.0.0.1:<공개포트>`를 사용한다.
- Docker 내부: 연결된 네트워크의 서비스·컨테이너 호스트명과 내부 포트를 사용한다.
- 팀 내부망: 다른 PC의 localhost는 그 PC 자신이다. 시스템 DB는 기존
  `mongo/compose.lan.yml`과 `MONGO_LAN_BIND_IP`로 서버의 LAN IP를 공개할 수 있다.
  허용된 내부망·방화벽 범위를 확인한다. 원본 DB에는 새 LAN 포트를 추가하지 않았다.
- AWS: VPC·SSH 터널 등 허용된 접근 경로를 준비하고 DB 포트를 인터넷에 공개하지 않는다.
  Docker 네트워크 공유는 같은 호스트에서만 가능하며 여러 EC2·관리형 DB·TLS와 실제
  AWS 배포는 별도 검증 대상이다.

환경 파일 통합·복원 시에는 값 보존과 Compose 문법만 확인하며 실제 서비스를 재설치하지
않는다. 별도 DB 통합 검사는 `python -m unittest discover -s mongo/tests -v`이며
테스트 프로젝트·볼륨을 생성하므로 운영 환경 설정 복원 검증과 구분한다.
