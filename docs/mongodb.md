<!--
[홍석환] MongoDB 설치와 연결 안내
시스템·원본 DB의 계정·네트워크·초기화·검증 절차를 설명한다.
-->
# MongoDB 설치와 계정

시스템 DB와 원본 DB는 별도 서버·계정·볼륨을 사용한다.

| 항목 | 시스템 DB | 원본 DB |
|---|---|---|
| 환경 파일 | 루트 `.env` | `raw_consumer/.env` |
| Compose | `compose.yml`, `mongo` 프로필 | `compose.raw.yml` |
| 프로젝트 | `ticket-guard-workspace-db` | `ticket-guard-raw` |
| 내부 주소 | `ticket-guard-workspace-db-mongo-1:27017` | `mongo-raw:27020` |
| 기본 DB / 일반 계정의 인증 DB | `ticketguard` | `ticketguard_raw` |
| root 인증 DB | `admin` | `admin` |
| PC 포트 공개 | `mongo/compose.local.yml`의 `MONGO_HOST_PORT` | `compose.raw.local.yml`의 `27020` |

시스템 DB의 최초 설치, 조회 계정 생성, 기존 DB 적용, Compass와 AWS 설정은
[관리자 대시보드 설치 문서](../admin_dashboard/README.md#db-연결-설정)를 따른다.
원본 DB는 [원본 적재 설치 문서](../raw_consumer/README.md#설치기존-db-적용)를 따른다.

빈 볼륨에서만 초기화 스크립트가 실행된다. 기존 볼륨의 비밀번호는 환경 파일을
바꾸거나 컨테이너를 다시 만들어도 변경되지 않는다. 기존 DB의 계정 추가에는
유효한 관리자 인증이 필요하며, 기존 계정과 설정이 다르면 변경 없이 중단한다.
데이터를 보존하려면 `down -v`나 볼륨 삭제로 인증 문제를 해결하지 않는다.

검증 명령은 저장소 루트에서 `python -m unittest discover -s mongo/tests -v`다.
Docker, `mongo:8.0.34` 이미지, Python의 `pymongo==4.10.1`이 필요하다.
검사는 별도의 빈 볼륨을 사용하며 기존 DB와 실제 환경 파일을 변경하지 않는다.
실제 AWS 배포는 별도 검증 대상이다.

## QA 실제 DB 연결

시스템 DB는 기존 대시보드 조회 계정을 함께 사용한다. 원본 DB는 최초 실행에
writer와 reader를 함께 생성한다. QA 자체 DB의 계정과 구조는 변경하지 않는다.

루트 `.env`에서 아래 설정을 준비한다. URI의 비밀번호는 URL 인코딩하며 실제
비밀번호는 커밋하지 않는다. 시스템 DB의 DB 이름·조회 계정을 변경했다면 두
URI에도 그 값을 반영한다.

```dotenv
TICKET_GUARD_QA_SYSTEM_MONGO_URI=mongodb://ticketguard_admin_reader:ENCODED_SYSTEM_READER_PASSWORD@ticket-guard-workspace-db-mongo-1:27017/ticketguard?authSource=ticketguard
TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI=mongodb://raw_reader:ENCODED_RAW_READER_PASSWORD@ticket-guard-raw-mongo-raw-1:27020/ticketguard_raw?authSource=ticketguard_raw
TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID=원본_환경파일의_RAW_SOURCE_ID와_같은_값
TICKET_GUARD_ADMIN_MONGO_NETWORK=ticket-guard-workspace-db_mongo-backend
TICKET_GUARD_QA_RAW_MONGO_NETWORK=ticket-guard-raw_raw-backend
```

`TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID`에는 `raw_consumer/.env`의 `RAW_SOURCE_ID`를
그대로 복사한다. 루트의 `RAW_SOURCE_ID`에 의존하지 않도록 연결 파일이 명시적
QA 값을 전달한다. `KAFKA_EVENTS_TOPIC`과 `RAW_KAFKA_TOPIC`도 일치해야 한다.
`qa/compose.qa-live.yml`을 쓰더라도 **compose.qa-db-access.yml을 마지막에** 붙인다.

먼저 두 DB의 최초 설치 또는 기존 계정 설정을 완료하고 Kafka·웹·QA 자체 DB를
[관리자 설치 문서](../admin_dashboard/README.md)에 따라 준비한다.
읽기 전용 접속 검사는 다음과 같다. 서버 주소 해석·인증·조회 권한을 실제 확인하며
QA 시험이나 정답표·실행 기록 처리를 시작하지 않는다.

```powershell
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml -f compose.qa-db-access.yml config --quiet
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml -f compose.qa-db-access.yml build qa-dashboard
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml -f compose.qa-db-access.yml run --rm --no-deps --entrypoint python qa-dashboard /opt/ticketguard/verify-qa-connections.py
```

두 DB 모두 조회 검사에 성공하면 실행한다. 기존 웹·Kafka·DB를 재생성하지 않는다.

```powershell
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml -f compose.qa-db-access.yml up -d --no-deps qa-dashboard
```

연결 파일은 기존 `default`, `qa-backend`에 두 DB의 외부 네트워크만 추가한다.
QA DB 서버는 `qa-backend`에만 남는다. 새 공개 포트·Docker 소켓을 추가하거나
토픽 주입·장애 복구를 활성화하지 않는다. QA 이미지는 최신 Dockerfile로 빌드해야
브라우저 실행 환경도 포함된다. 실제 시험 실행 여부는 QA 화면에서 별도로 선택한다.

출처 조회 결과가 없으면 빈 DB이거나 설정이 다른 경우일 수 있다. 접속 검사 성공만으로
출처 값의 일치까지 보장하지 않는다. 적재기 설정과 대조하고 실제 적재 후 다시 검사한다.

## 같은 PC · 팀 내부망 · AWS

- 같은 PC: 각 `*.local.yml`로 연 `127.0.0.1` 포트에 Compass를 연결한다.
- 팀 내부망: 팀원 PC에서 `localhost`는 팀원 자신의 PC다. 시스템 DB는 기존
  `mongo/compose.lan.yml`과 `MONGO_LAN_BIND_IP`로 지정한 서버의 LAN IP에
  연결할 수 있다. 접근 가능한 내부망·방화벽 범위를 확인하고 승인된 환경에서만
  사용한다. 원본 DB에는 LAN 포트 구성을 새로 추가하지 않았다. 필요하면 SSH 터널을 사용한다.
- AWS: 도커 네트워크는 같은 호스트에서만 공유된다. 단일 EC2에서는 실제 프로젝트
  이름에 맞게 위 네트워크·호스트를 설정한다. 서로 다른 EC2, 관리형 DB, TLS·인증,
  SSH 터널 설정과 실제 AWS 배포는 별도 검증 대상이다. LAN override를 AWS에서
  그대로 사용해 DB를 인터넷에 공개하지 않는다.
