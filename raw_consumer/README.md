# Kafka 원본 컬렉션 라우팅

Kafka를 작은 배치로 읽고 종류별 컬렉션에 원본을 직접 저장한다.
원본 적재 후 별도 분류 프로세스, 업무 정제/집계, 청크 재조립은 없다.
기존 raw_events는 과거 기록으로 유지하며 새 메시지를 추가하지 않는다.

## 구성

| 항목 | 값 |
|---|---|
| 프로젝트 / 서비스 | ticket-guard-raw / raw-consumer, mongo-raw |
| Kafka / 토픽 | kafka:9092 / ticketguard.events.v1 |
| 그룹 | ticketguard-raw-db-v1 |
| DB | mongo-raw:27017 / ticketguard_raw |
| 네트워크 | 공통 ticket-guard_default + 전용 raw-backend |
| 호스트 DB 관리 접속 | local override 사용 시 localhost:27020 |
| 배치 | 200건 / 첫 메시지 후 1초 / key+value+headers 4 MiB |

조건 중 먼저 도달하면 저장한다. 다음 메시지로 바이트 상한을 넘으면 먼저 기존
배치를 저장한 뒤 새 배치를 시작한다. 상한을 넘는 단일 메시지는 별도 배치로 저장한다.
각 원본은 독립 문서이고 저장 요청만 컬렉션별 bulk_write로 묶는다.

배치 상한은 프로세스 전체 메모리 상한이 아니다. JSON 해석, BSON 문서·bulk 객체와
Kafka 클라이언트 내부 버퍼가 추가 메모리를 사용한다. 클라이언트 큐 목표 8 MiB,
fetch 목표 8 MiB로 제한하지만 큰 단일 메시지는 브로커/클라이언트 동작에 따라 이를
넘길 수 있다. 메시지 크기 및 실제 부하에 따라 메모리 사용을 측정해야 한다.

## 명시적 라우팅 v1

v1/v2 모두 아래 목록을 사용한다. 접두어 자동 분류는 하지 않는다.

| 컬렉션 | eventType |
|---|---|
| behavior_events | page_enter, page_exit, search_change, genre_change, show_select, schedule_select, seat_select, seat_cancel, quantity_change, ui_interaction, page_lifecycle |
| booking_events | queue_enter, queue_register, queue_admitted, queue_cancel, connection_timeout, captcha_success, captcha_wrong, captcha_limit_reached, captcha_refresh, booking_confirm_request, booking_confirm_success, booking_confirm_fail, booking_access_rejected, booking_not_open, booking_confirm_rejected, booking_confirm_replayed |
| auth_events | login_success, login_fail |
| http_events | browser_request_start, browser_request_body, browser_response_headers, browser_request, server_request, server_response_headers |
| performance_events | resource_timing, navigation_timing, performance_entry |
| browser_errors | browser_error |
| collector_events | collector_limitation, collector_failure, scenario_executed |
| raw_chunks | capture_chunk |
| unclassified_events | null/빈 payload, UTF-8/JSON 파싱 실패, JSON 비객체, 미지원 버전, 잘못된/미등록 eventType |

## 원본 문서

기존 _id 생성 알고리즘은 바꾸지 않았다. JSON 배열
[source, topic, partition, offset]을 separators=(',', ':')로 직렬화한 SHA-256이다.

| 필드 | 타입/의미 |
|---|---|
| _id | 문자열, 원본 위치 기반 고유 키 |
| source / topic | 문자열, 출처 세대 / 토픽 |
| partition / offset | 정수 / BSON Int64 |
| key / value | Binary 또는 null, 빈 바이트와 null 구분 |
| headers | {key: 문자열, value: Binary 또는 null}의 순서 있는 배열 |
| timestampMs / timestampType | BSON Int64 / Kafka timestamp 타입 |
| ingestedAt | 최초 적재 시각 BSON Date(UTC) |
| routing | {version: 'raw-routing-v1', reason?: 미분류 사유} |

원문 JSON은 저장 위치 선택에만 사용하고 버린다. 업무 유효성은 검사하지 않는다.
새 문서도 원문 Binary를 보존하며 $setOnInsert로 최초 시각/원문을 덮어쓰지 않는다.
Kafka offset이 다르면 payload/eventId가 같아도 별도 문서다.
청크 조각의 원래 이벤트 종류를 추정하지 않는다.

## 설치·기존 DB 적용

저장소 루트에서 실행한다. 기존 .env는 복사/덮어쓰지 않는다.
새 설치만 raw_consumer/.env.example을 .env로 복사하고 credentials placeholder를 바꾼다.
비밀번호는 관리자와 writer를 구분하고 충분히 긴 값으로 설정한다.

```powershell
docker compose --env-file raw_consumer/.env -f compose.raw.yml config --quiet
docker compose --env-file raw_consumer/.env -f compose.raw.yml build raw-consumer
docker compose --env-file raw_consumer/.env -f compose.raw.yml -f compose.raw.local.yml up -d --wait mongo-raw
docker compose --env-file raw_consumer/.env -f compose.raw.yml exec -T mongo-raw mongosh --quiet --norc --port 27017 /opt/raw/setup.js
docker compose --env-file raw_consumer/.env -f compose.raw.yml up -d --no-deps raw-consumer
```

신규 DB는 init.js에서 사용자와 raw_events, 라우팅 컬렉션들을 만든다.
기존 볼륨은 init.js가 다시 실행되지 않으므로 setup.js를 명시적으로 실행한다.
setup은 기존 데이터·사용자를 변경하지 않고 9개 컬렉션과 비고유 인덱스
raw_kafka_position_v1 {source:1,topic:1,partition:1,offset:1}을 멱등 생성한다.
raw_events 인덱스는 변경하지 않는다. TTL/업무 validator는 없다.
현재 실행 중인 DB를 재생성하지 않고 setup만 적용하려면 다음도 가능하다.

```powershell
Get-Content -Raw raw_consumer/mongo/setup.js | docker compose --env-file raw_consumer/.env -f compose.raw.yml exec -T mongo-raw mongosh --quiet --norc --port 27017 --file /dev/stdin
```

컨테이너 내부 서비스 통신은 27017을 사용하고, 호스트에서 Compass로 접속할 때만 27020을 사용한다.
DB 호스트 공개가 필요 없으면 compose.raw.local.yml을 생략한다.

## 실행·조회

```powershell
docker compose --env-file raw_consumer/.env -f compose.raw.yml ps -a
docker compose --env-file raw_consumer/.env -f compose.raw.yml logs --tail 30 raw-consumer
docker compose --env-file raw_consumer/.env -f compose.raw.yml exec -T mongo-raw mongosh --quiet --norc --port 27017 /opt/raw/verify.js
docker compose --env-file raw_consumer/.env -f compose.raw.yml stop raw-consumer
```

Compass: localhost:27020, 실제 .env의 raw_writer 계정, 인증 DB ticketguard_raw.
새로고침 후 각 컬렉션 Documents에서 다음 Filter와 Sort 사용:

```javascript
// Filter
{topic: "ticketguard.events.v1"}
// Sort
{ingestedAt: -1}
// 인증된 mongosh
db.getSiblingDB('ticketguard_raw').http_events.countDocuments({topic:'ticketguard.events.v1'})
db.getSiblingDB('ticketguard_raw').unclassified_events.aggregate([
  {$group:{_id:'$routing.reason',count:{$sum:1}}}
])
```

## 실패·소유권·종료

자동 커밋/offset 저장은 비활성화한다. 모든 컬렉션의 w=1,j=true 쓰기 확인 후
각 파티션의 마지막 저장 offset+1을 동기 커밋한다. 일부 저장 실패 시 전체 배치를
커밋하지 않는다. 커밋의 일부 파티션만 성공해도 DB는 전체 저장된 상태이므로
남은 파티션의 재수신을 멱등 쓰기로 처리한다.

DB 배치 작업 전체에 CSOT 35초 예산을 적용하며 일시 연결 오류는 최대 3회 시도한다.
문서 크기·쓰기 오류 등 영구 실패는 제한 없이 반복하지 않고 종료한다.
max.poll.interval=300초, Kafka socket timeout=5초, Compose 종료 유예=60초다.
SIGTERM은 새 수신을 멈추고 진행 배치만 저장·커밋한다. 종료 목표 예산은 45초이며
저장/커밋 전 기한을 검사한다. 진행 중 동기 호출은 즉시 취소되지 않지만 DB CSOT와
Kafka timeout으로 제한한다. 강제 종료 시 미커밋 데이터는 재수신된다.

range/eager 할당을 사용한다. revoke/lost 시 배치를 커밋하지 않고, 미처리 배치가
있으면 종료해 재시작 시 재수신한다. 쓰기 전후 소유권을 검사하며 broker의
generation fencing/커밋 오류도 확인한다. callbacks가 poll에서 전달되는 점 때문에
로컬 소유권 검사만으로 네트워크 장애를 판정하지 않는다. 재시작 정책은 no이다.
오류 원인을 해결한 후 up -d --no-deps raw-consumer로 재시작한다.

## 라우팅 규칙 변경 정책

raw-routing-v1은 불변 계약이다. RAW_ROUTING_FINGERPRINT는 매핑 및 파서 계약의
SHA-256이며 현재 Compose 기본값과 실제 .env에 고정한다. 매핑을 수정하면 시작을
거부한다. 환경 fingerprint를 단순히 바꿔 기존 그룹에 적용하면 안 된다.

새 규칙은 기존 그룹을 정지·완전히 drain한 뒤 파티션별 커밋 경계를 기록하고,
그 경계 이전은 v1, 이후는 v2가 되도록 위치 기반 라우팅 버전 선택을 구현·검증한
후 전환한다. 그 기능을 구현하기 전에는 v1을 유지한다. 전체 replay가 필요하면
새 DB/명시적 저장 namespace와 별도 그룹을 사용한다. 기존 그룹 reset, 컬렉션 간
데이터 이동, eventId 기반 삭제는 하지 않는다.

출처 source는 재시작 시 유지하고 클러스터/토픽 세대 교체 시 갱신한다.
그룹 offset이 만료돼 사라지면 신규 그룹과 구별할 수 없어 과거 원본이 재수신될 수
있다. 과거 raw_events와 새 컬렉션 간 전역 중복 제거는 하지 않는다.

## 검증

```powershell
docker compose --env-file raw_consumer/.env -f compose.raw.yml run --rm --no-deps raw-consumer python -m unittest discover -s tests -v
docker compose --env-file raw_consumer/.env -f compose.raw.yml run --rm --no-deps raw-consumer python integration.py
```

integration은 독립 UUID 테스트 토픽/그룹만 사용하고 테스트 source로 문서를 남긴다.
공유 앱 토픽에 메시지를 넣지 않는다. 테스트 토픽의 메시지 retention은 1시간이다.
공유 서비스와 기존 데이터는 삭제하지 않는다. at-least-once + 멱등 DB 쓰기이며
종단 간 exactly-once나 여러 컬렉션의 원자 트랜잭션을 보장하지 않는다.

AWS: 네트워크/advertised listener/인증 연결을 실제 환경에 맞춰야 한다.
현재 Kafka는 PLAINTEXT이며 SASL/TLS가 필요한 경우 추가 구현이 필요하다.
DB 포트를 인터넷에 공개하지 않고 VPC/터널을 사용한다.

참고: https://docs.confluent.io/kafka-clients/python/current/index.html
https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/csot/
