# Kafka 연결 · 2단계

## 구현 범위

후속 Spark 원본 적재 코드와 비적재 점검은 [Spark 문서](spark.md)를 따른다. 현재 실제 적재는 하지 않았으며 아래 별도 원본 Consumer/정제 구상은 이전 단계의 기록이다.

MongoDB 실행 환경은 실제 저장소 C:/workspace/Ticket_Guard에 추가했습니다. [MongoDB 문서](mongodb.md)의 격리 프로젝트 명령을 사용합니다. 원본 적재 Consumer와 Spark는 이번 MongoDB 구축 범위에 포함하지 않았으며 실제 데이터 적재는 하지 않았습니다.

실제 Django → Apache Kafka 발행이 구현되었습니다. MongoDB 원본 적재 Consumer와 Spark 정제/집계는 아직 구현하지 않았으며 최종 필수 후속 범위입니다. 예매 데이터 자체는 여전히 웹 프로세스 메모리입니다.

```text
브라우저 → Django 수집·검증 ─┐
                           ├→ Kafka ticketguard.events.v1
Django 서버 처리 결과 ─────┘

후속: Kafka ─┬→ 원본 적재 Consumer → MongoDB raw_events
             └→ PySpark → MongoDB clean_events / event_metrics
```

## 선택한 버전과 실행

- Python 3.13.15 / Django 5.2.18 / Pillow 12.0.0 유지.
- Apache 공식 `apache/kafka:4.1.2`, KRaft broker+controller 단일 노드. 공식 이미지 실제 pull 및 실행 확인.
- `confluent-kafka==2.16.1`: librdkafka 기반 Producer/Consumer/Admin API, 비동기 delivery callback과 idempotent producer 지원. 실제 cp313 manylinux x86_64 wheel 다운로드·설치 및 Kafka 4.1.2 통신 확인. 다른 CPU 아키텍처의 실행은 미검증.
- 버전 근거: [Apache Docker 안내](https://kafka.apache.org/41/getting-started/docker/), [클라이언트 API](https://docs.confluent.io/platform/current/clients/confluent-kafka-python/html/index.html), [클라이언트 배포 파일](https://pypi.org/project/confluent-kafka/2.16.1/).

```powershell
cd C:\workspace\Ticket_Guard
docker compose up -d --build
docker compose ps -a
docker compose logs --tail 30 kafka-init
```

`kafka` healthy → `kafka-init` 성공 종료 → `web` 시작 순서입니다. init가 Exit 0인 것은 정상입니다. 이미 실행 중인 웹은 이후 Kafka 장애와 무관하게 요청을 처리합니다. 새 전체 기동은 Kafka 준비를 기다리므로 Kafka를 영구적으로 사용할 수 없을 때 정상 기동된다고 주장하지 않습니다.

Kafka는 Docker 내부 `kafka:9092`에서만 접근합니다. 호스트 포트를 노출하지 않습니다. 브라우저는 Django API에만 요청합니다. 호스트 도구 연결이 필요하면 별도 localhost 전용 external listener와 advertised address를 구성해야 합니다. 내부 주소를 브라우저나 호스트 bootstrap 주소로 사용하면 안 됩니다.

## 토픽과 영속 데이터

| 항목 | 설정 |
|---|---|
| 이름 | ticketguard.events.v1 (`KAFKA_EVENTS_TOPIC`) |
| 파티션 | 3 |
| 복제 수 / min ISR | 1 / 1 |
| 정책 | delete |
| retention.ms | 604800000 (7일, 개발용 변경 제안) |
| retention.bytes | 파티션당 268435456 (256 MiB) |
| segment.bytes / segment.ms | 64 MiB / 1시간 |
| 볼륨 | Compose named volume kafka-data |

**7일은 기존 24시간 정책을 대체하는 확정 정책이 아닙니다.** 재처리용 개발 제안이며 `.env`의 `KAFKA_RETENTION_MS`로 새 토픽 생성 시 설정할 수 있습니다. MongoDB 보관 기간은 별도 결정 대상입니다. 시간/용량 한도 중 먼저 적용되는 조건에 따라 7일보다 일찍 삭제될 수 있습니다. 파티션 3개 약 768 MiB는 세그먼트·내부 토픽·인덱스 등 오버헤드를 제외한 값이며 Docker 디스크 전체의 하드 쿼터가 아닙니다. 삭제 검사는 주기적이고 세그먼트 단위입니다.

`init_kafka`는 없으면 생성하고, 기존 토픽이 있으면 **설정·데이터를 변경하지 않고 drift를 경고**합니다. 환경 변수를 바꿔도 기존 토픽의 retention/파티션이 자동 변경되지 않습니다. 파티션 증가에 따른 key 배치 변화나 retention 축소에 따른 삭제를 피하기 위한 정책입니다. 변경은 별도 검토 후 수행해야 합니다.

KAFKA_CLUSTER_ID는 기존 볼륨에 대해 유지하세요. `/var/lib/kafka/data`에 로그와 메타데이터를 같이 저장합니다. `docker compose down`은 named volume을 유지하지만 `down -v`는 데이터를 삭제하므로 사용하지 마세요. 단일 노드이므로 `acks=all`도 호스트/디스크 장애에 대한 복제를 제공하지 않습니다. plaintext는 로컬 격리 네트워크의 개발 설정이고 운영은 인증/TLS/ACL/다중 브로커 검토가 필요합니다.

## 발행과 순서

`EVENT_PUBLISHER=kafka`는 실제 발행, `mock`은 테스트용입니다. Django 설정 기본은 mock이고 기본 Compose는 kafka를 명시합니다. 기존 `.env`에서 mock을 지정하면 해당 값이 우선하므로 상태를 확인하세요.

- UTF-8 JSON. Kafka key는 bookingAttemptId → userId → eventId 순서입니다.
- 같은 key는 같은 파티션으로 전달됩니다. 파티션 안의 기록 순서이며 여러 파티션 전체나 서로 다른 HTTP 요청의 논리적 시간순을 보장하지 않습니다.
- 요청마다 전체 flush하지 않습니다. 프로세스별 producer를 재사용하고 별도 poll 스레드가 callback을 처리합니다.
- idempotence=true, acks=all, in-flight 최대 5, 내부 retries=3, delivery timeout=5초, request timeout=2초. 큐는 2,000개/8 MiB 제한입니다.
- idempotence는 producer 내부 재전송에 대한 보호입니다. 애플리케이션 재발행·재기동까지 종단 간 exactly-once를 보장하지 않습니다. 후속 원본 수신 위치는 topic/partition/offset으로, 의미상 중복은 eventId로 구분합니다.
- fork 후 lock/producer/receipt를 재생성합니다. Docker SIGTERM은 최대 3초 flush와 제한된 join으로 drain합니다. 강제 종료·호스트 장애 때는 drain을 보장하지 않습니다. 운영 worker lifecycle hooks는 별도 구성 대상입니다.

## 수신·발행 상태와 재시도

| 상태 | 의미 |
|---|---|
| received | 서버 receipt 등록. 짧은 내부 전이이며 누적 counter로 확인 |
| pending | producer 발행 시도/버퍼 등록 후 callback 대기 |
| delivered | 성공 callback 수신. Kafka topic/partition/offset 확보 |
| failed | 버퍼 부족, 설정·인증 문제, 전달 타임아웃 등 실패 |

`POST /api/events/`의 HTTP 202는 수신·대기 상태이며 브로커 저장 성공이 아닙니다. HTTP 200과 state=delivered는 callback 완료, HTTP 503은 발행 실패/수용량 부족입니다. 검증 오류는 400입니다. 사용자에게 내부 Kafka 오류는 반환하지 않습니다.

로그인한 사용자는 `GET /api/events/?eventId=<UUID>`로 자기 이벤트의 state/attempts/retryable을 확인할 수 있습니다. DEBUG 로그 뷰어는 원본 이벤트와 전달 metadata, 누적 counters/현재 상태 수를 보여줍니다. SHOW_SCENARIOS=0이면 전체 로그·metrics 조회는 숨기지만 자기 이벤트 receipt 조회는 재시도를 위해 유지됩니다.

브라우저는 이벤트를 만들 때 UUID를 한 번 생성하고 같은 payload/ID로 재시도합니다. 탭 sessionStorage 큐는 100건/15분, Django receipt는 프로세스당 2,000건/15분입니다. receipt 공간이 부족하면 완료/실패 기록부터 제거하고 pending만 가득하면 새 수신을 거부합니다. 따라서 용량 압력으로 중복 기억이 15분보다 빨리 사라질 수 있습니다.

동일 eventId의 pending/delivered 요청은 재발행하지 않습니다. retryable failed만 같은 이벤트로 다시 발행하며 애플리케이션 발행 시도는 최대 3회입니다. 다른 payload로 동일 ID를 재사용하면 400입니다. 재시도에서 첫 receivedAt과 최초 서버 문맥을 유지합니다. failed를 delivered로 간주하거나 실패 전에 영구 중복 처리하지 않습니다.

브라우저는 receipt를 확인하고 재시도하며 네트워크 실패도 제한합니다. `pagehide`는 keepalive로 보내지만 브라우저 종료, 저장소 초기화, 계정 전환·로그아웃, 큐 초과 등에서 유실될 수 있습니다. sessionStorage가 차단된 브라우저는 미검증입니다.

서버 이벤트는 Kafka 클라이언트 내부 재시도 후 callback 실패를 기록합니다. 이 단계에서는 failed 서버 이벤트의 영속 자동 재발행 큐가 없습니다. **프로세스가 종료되면 pending/failed receipt와 미전달 서버 이벤트를 잃을 수 있습니다.** delivered된 이벤트는 Kafka volume에 남지만 모의 예매·메모리 로그 뷰어는 초기화됩니다. 예매 성공을 로그 실패 때문에 취소하지 않습니다.

`ticketguard.events` logger는 eventId/오류 코드/재시도 가능 여부만 기록하고 요청 본문을 출력하지 않습니다. 실패는 counters와 totalFailures에서도 확인합니다. HTTP 접근 로그는 이벤트 데이터와 별개이며, URL의 검색어를 제거하는 운영 정책은 별도 검토 대상입니다.

## 이벤트 계약

실행 가능한 검증기는 `web/event_schema.py`입니다. 브라우저와 서버 이벤트 모두 검사합니다. 공통 필드는 모두 존재하고 단계상 없는 문맥은 null입니다.

```text
schemaVersion=1, eventId, eventType, occurredAt, receivedAt, source,
userId, pageInstanceId, pageViewId, bookingAttemptId, showId, scheduleId,
requestSequence, result, errorCode, isSimulation, scenarioName, details
```

- UTC ISO 시간, eventId UUID. 브라우저 발생 시각은 24시간 범위 검사.
- pageInstanceId는 탭, pageViewId는 매 화면 로드 UUID. page_enter/page_exit을 pageViewId로 연결합니다.
- userId/receivedAt/source/시나리오 표시는 Django가 결정. 브라우저가 신뢰 필드를 보내면 거부합니다.
- 브라우저 좌석/수량은 관측 보고이며 확정 사실이 아닙니다. 확정 결과의 금액/수량은 서버 계산값입니다.
- details는 이벤트별 allowlist·타입·범위 검사, 총 JSON 16 KiB 제한. 검색어 원문·비밀번호·보안문자·세션 토큰·임의 HTTP 본문을 받지 않습니다.
- 필드 추가는 소비자의 허용 정책과 호환성을 검토하고, 파괴적 변경은 새 schemaVersion/토픽 계획을 세워야 합니다. 기존 v1 소비자가 무조건 새 필드를 허용한다고 가정하지 않습니다.

### 브라우저 이벤트 9종

| 종류 | details / 문맥 |
|---|---|
| page_enter / page_exit | pageName, previousPageName; 공통 pageViewId |
| search_change | queryLength, resultCount; 검색 결과 화면 로드 후 발생 |
| genre_change | genre |
| show_select | clickTarget=poster/title/detail_button; 실제 클릭 공연 showId |
| schedule_select | trigger=date_change/time_change/booking_start, selectedDate, 실제 scheduleId |
| seat_select / seat_cancel | seatId, 변경 후 selectedCount |
| quantity_change | previousQuantity, quantity |

### 서버 이벤트 19종

| 종류 | 의미 / details |
|---|---|
| login_success / login_fail | 인증 결과; 실패는 userId=null |
| queue_enter | 새 예매 시도 진입 |
| queue_register | initialRank, estimatedWaitMs |
| queue_admitted | elapsedMs; 대기열 → 보안 확인 전환 시 1회 |
| queue_cancel | reason=user_cancel/menu_navigation/page_navigation/logout, elapsedMs; 기존 이름을 유지하며 대기열 이후 취소도 포함 |
| connection_timeout | reason=heartbeat_expired, elapsedMs; 만료를 서버가 확인한 시점 |
| captcha_success | 서버 정답 검증 성공 |
| captcha_wrong / captcha_limit_reached | wrongCount, remainingAttempts; 5회 시 두 의미의 이벤트가 각각 발생 |
| captcha_refresh | 사용자 문제 교체 시 reason=user_refresh; 최초 이미지 생성은 제외 |
| booking_confirm_request | 권한·sequence 검사 후 확정 처리 시작 |
| booking_confirm_success | bookingId, seatType, quantity, totalAmount, durationMs |
| booking_confirm_fail | 처리 중 실패; errorCode, seatType, durationMs. 확정되지 않은 bookingId/금액을 만들지 않음 |
| booking_confirm_rejected | 처리 전 단계/순서/입력 거부; action |
| booking_confirm_replayed | 확정 재요청의 기존 결과 반환; 신규 성공과 분리 |
| booking_access_rejected | 중복 탭/미인증/만료/직접 단계 접근 거부; action |
| booking_not_open | 서버 오픈 전 요청 거부; action |
| scenario_executed | 개발 패널 조작; scenario |

동일 실패를 뷰·서비스에서 중복 계측하지 않습니다. 로그인 실패는 login_fail로 기록하며 booking_access_rejected를 중복 생성하지 않습니다. 보안문자 오답/횟수 초과는 각각 다른 의미의 로그입니다.

### 시나리오 표시

서비스 전체는 항상 모의 예매입니다. 이벤트의 `isSimulation`은 실제/가상 서비스 구분이 아니라 **오류 재현 시나리오가 적용됐는지**를 뜻합니다. 일반 데모 이용은 false/null, 개발 패널 조작과 해당 예매 흐름은 true/scenarioName입니다. 서버 메모리에 시나리오를 기록하며 브라우저가 값을 지정하지 않습니다. 한 흐름에서 가장 최근 시나리오를 표시합니다. 재고를 바꾸는 시나리오는 다른 계정에도 영향을 줄 수 있으므로 정상 트래픽과 혼합해 해석하지 마세요.

## 진단 Consumer

```powershell
# 현재 보관 중인 가장 앞부터 최대 10개. group은 진단 전용으로 제한합니다.
docker compose exec -T web python manage.py consume_events --group ticketguard-debug-manual --from-beginning --max-messages 10 --timeout 20

# 먼저 실행한 뒤 웹에서 행동: 할당 완료 시점의 끝부터 신규 이벤트 확인
docker compose exec -T web python manage.py consume_events --group ticketguard-debug-live --max-messages 10 --timeout 30
```

토픽/파티션/offset/key와 스키마 검사를 통과한 이벤트를 출력합니다. 잘못된 payload는 원문을 출력하지 않습니다. 매 실행마다 명시적으로 beginning/end 위치를 지정하고 offset을 commit하지 않으므로, 같은 group 이름을 써도 이어 읽기가 아닙니다. future raw-writer/Spark group과 공유하지 않습니다. 제한시간/개수에 도달하면 종료하며 MongoDB 적재나 영속 아카이브 기능이 아닙니다.

## 테스트

```powershell
docker compose exec -e EVENT_PUBLISHER=mock -T web python manage.py check
docker compose exec -e EVENT_PUBLISHER=mock -T web python manage.py test web -v 2
docker compose exec -T web python manage.py verify_kafka
```

단위/HTTP 테스트는 Kafka 없이 mock으로 실행합니다. GitHub CI도 mock입니다. verify_kafka는 별도 Django 테스트 프로세스의 계정·재고와 실제 Kafka를 사용하고 live 웹 예매 상태를 바꾸지 않습니다. 전달 콜백과 key, 스키마, 동일 ID 재요청, 예매 성공/재반환, 시나리오 구분을 검사합니다. 실제 토픽에 QA 이벤트가 추가됩니다. 보안문자 자동 입력 대신 검증된 상태의 fixture를 사용하며 실제 브라우저 전체 예매 완료 검사로 표현하지 않습니다.

장애 검사는 두 터미널이 필요합니다. 첫 번째에서 아래를 실행하고 `FAILED_WAITING_FOR_RECOVERY`가 나오면 두 번째에서 100초 안에 Kafka를 시작하세요.

```powershell
docker compose stop kafka
docker compose exec -T web python manage.py verify_kafka --outage
# 두 번째 터미널:
docker compose start kafka
```

볼륨/토픽 삭제 없이 실패 callback, 예매 유지, 동일 eventId 재시도와 신규 이벤트 전달을 확인합니다. 다른 사용자의 테스트를 방해하지 않는 시간에 실행하세요.

## 이번 실행 결과

- Python 3.13.15 cp313 wheel 설치, 공식 Kafka 이미지 기동, 3파티션 토픽 생성 성공.
- mock 단위/HTTP 검사 30개 통과, 기존 20개 포함.
- 실제 Kafka 통합: 10개 이벤트 도착, 예매 금액 110,000원, 신규 성공 1회·재반환 1회 확인.
- 브라우저에서 로그인/검색 후 원본 이벤트의 전달 완료 확인. 검색 이벤트는 queryLength=4, resultCount=0이며 원문 미포함.
- Kafka 중단 중 예매 결과 유지, 복구 후 같은 eventId의 두 번째 시도 delivered와 신규 이벤트 전달 확인.
- Kafka 컨테이너 재생성 전후 동일 브라우저 이벤트의 partition=2 / offset=4 / eventId 유지. cluster.id와 directory.id 유지. 데이터 볼륨 삭제 없음.
- 원격 CI 실행, MongoDB/Spark 통합, 운영 부하·다중 노드 장애 검증은 미실행.

## 필수 후속 작업

MongoDB raw-writer는 Kafka message의 topic/partition/offset을 원본 수신 고유 키로 저장한 뒤 offset을 확정해야 합니다. 의미상 중복은 eventId로 별도 구분하세요. Spark는 독립 checkpoint로 정제·집계하고 원본 저장 성공에 종속시키지 않습니다.

서버 예매 저장과 이벤트 전달 사이 유실을 줄이기 위한 **MongoDB 영속 outbox와 재발행 worker**를 필수 검토합니다. 이번 메모리 publisher는 무손실 전달 보장이 아닙니다. 원본·정제·Kafka·집계 각각의 보관 기간, 권한, TTL, 재처리 정책을 확정해야 합니다.
