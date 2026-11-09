# 시스템과 맞춘 데이터 형식

QA가 시스템 데이터를 읽거나 db 브랜치와 형식을 맞출 때 보는 문서예요. 규칙 전체는 [`../AGENTS.md`](../AGENTS.md).

- **원본**: 시스템 저장소의 `docs/architecture.md` (develop `d323060` 기준, 2026-11-03) · 이벤트 규칙은 `web/event_schema.py` · `web/views.py` `events` · `web/telemetry.py` (main `d294864` · PR #12 기준, 2026-11-06)
- 이 문서는 원본을 **QA 쪽에서 쓰기 좋게 옮긴 것**이에요. 서로 다르면 원본이 맞고, 이 문서를 고쳐요.
- 고치는 절차는 AGENTS.md 7장 "형식이 바뀔 때"를 따라요.

---

## 1. 이벤트 스키마 v1

| 시스템 필드 | QA 코드 이름 | 뜻 · 규칙 |
|---|---|---|
| `schemaVersion` | `schema_version` | 지금은 `1` · 서버가 넣음 · 브라우저가 보내면 거부 |
| `eventId` | `event_id` | UUID · 같은 내용 재전송은 중복 응답(`duplicate: true`) · 같은 ID에 다른 내용이면 거부 |
| `eventType` | `event_type` | 아래 2장 목록만 허용 |
| `occurredAt` | `occurred_at` | ISO 시각 · **UTC(+00:00)만** · 시간대 없거나 다른 시간대면 거부 · 지금과 24시간 넘게 차이 나면 거부(미래 포함) |
| `receivedAt` | `received_at` | 서버가 넣는 시각 · 브라우저가 보내면 거부 |
| `userId` | `user_id` | 서버가 넣는 사용자 · 브라우저가 보내면 거부 |
| `bookingAttemptId` | `booking_attempt_id` | 예매 시도 하나 · 예매 밖이면 `null` |
| `pageInstanceId` | `page_instance_id` | 탭 하나 · 브라우저 이벤트는 필수(80자 이하) |
| `pageViewId` | `page_view_id` | 화면 한 번 표시 · UUID · 브라우저 이벤트는 필수 |
| `showId` · `scheduleId` | `show_id` · `schedule_id` | 공연 · 회차 · 없는 공연이면 거부 · 회차는 `{showId}-evening`만 · 예매 밖이면 `null` |
| `requestSequence` | `request_sequence` | 확정 요청 순번 · 이미 받은 번호 이하면 거부 |
| `result` · `errorCode` | `result` · `error_code` | `success` · `failure` · `rejected` · 실패 이유 |
| `source` | `source` | `browser` · `server` |
| `isSimulation` · `scenarioName` | `is_simulation` · `scenario_name` | 시연 시나리오(`admit` 등)를 쓴 세션이면 `true` · 시나리오 이름 |
| `details` | `details` | 종류별 항목 · **필수 항목 누락 · 허용 값 밖 · 인증 정보 키(`password` · `token` · `answer` 등)면 거부** · 목록 밖 항목은 관측 필드로 보존(허용 · PR #12) (예: `page_enter` = `pageName` · `previousPageName` 필수) |

- 브라우저 이벤트는 `POST /api/events/`로 받아요. 보낼 수 있는 필드는 `eventType` · `eventId` · `occurredAt` · `pageInstanceId` · `pageViewId` · `showId` · `scheduleId` · `details` 8개뿐이고, **그 밖의 필드가 있으면 400**이에요.
- 응답: **200** Kafka 전달 완료 · **202** 전달 대기 · **400** 형식 오류 · **401** 로그인 안 함 · **503** 전달 실패(재시도 가능). 200과 202는 둘 다 "받음"이에요.
- 비밀번호 · 보안문자 답 · 세션 토큰은 이벤트에 들어가지 않아요. 관측 데이터의 인증 정보는 `[REDACTED]`로 가려요 (요청 본문 원문 사본 포함 · 2026-11-06 확인).

### 1-1. 관측 이벤트 (PR #12 · 스키마 v2 · `CAPTURE_ENABLED=1` 기본 켜짐)

| 항목 | 내용 |
|---|---|
| 서버 관측 | 미들웨어가 요청마다 `server_request` · `server_response_headers` 이벤트를 Kafka로 전송 (`/api/events/` · `/api/capture/` · `/health/` 제외) |
| 브라우저 관측 | `static/telemetry.js` · `POST /api/capture/` · 이벤트 종류 `browser_request` · `resource_timing` · `navigation_timing` · `browser_error` (`/api/events/`로도 받음) |
| 형식 | `schemaVersion: 2` · 스키마 v1 필드 18개 + `capture` · `details` 자유 형식 · 인증 정보 마스킹 · 빈 `details` 거부 |
| QA 영향 | 같은 토픽(`ticketguard.events.v1`)에 v1 · v2가 섞임 → QA가 토픽 · `raw_events`를 읽을 때 `schemaVersion`으로 구분 · VU 요청마다 관측 이벤트가 늘어 Kafka 부하 증가

## 2. 이벤트 종류

| 보내는 쪽 | 종류 |
|---|---|
| 브라우저 (믿지 않는 관찰 값) | `page_enter` · `page_exit` · `search_change` · `genre_change` · `show_select` · `schedule_select` · `seat_select` · `seat_cancel` · `quantity_change` · 관측 `browser_request` · `resource_timing` · `navigation_timing` · `browser_error` |
| 서버 관측 (스키마 v2) | `server_request` · `server_response_headers` |
| 서버 (확정된 사실) | `login_success` · `login_fail` · `queue_enter` · `queue_register` · `queue_admitted` · `queue_cancel` · `connection_timeout` · `captcha_success` · `captcha_wrong` · `captcha_refresh` · `captcha_limit_reached` · `booking_access_rejected` · `booking_not_open` · `booking_confirm_request` · `booking_confirm_success` · `booking_confirm_fail` · `booking_confirm_rejected` · `booking_confirm_replayed` · `scenario_executed` |

- `page_exit`는 유실될 수 있어요. QA는 이 이벤트가 없다고 실패로 보지 않아요.

## 3. 컬렉션 · 필드 대응표 (db ERD 초안 + QA 요청 · 2026-11-04)

- **원본**: db 팀 ERD 초안 · QA 요청 Issue `[QA][db] DB 스키마 초안 · QA 측정용 컬렉션 · 필드 추가 요청`
- 상태 표시: **초안** = ERD에 있음 · **요청** = QA가 추가 요청 (db 확정 전) · 확정되면 이 표를 고쳐요.
- QA 쪽 모양은 `domain/models.py`의 레코드 클래스예요. Mock(`fake_system.py`)도 같은 모양을 돌려줘요.
- Mock의 룰 이름은 `MOCK-R1` ~ `MOCK-R4`예요. 실제 R1 ~ R6와 관계없고, 화면에서 Mock 값이라는 걸 구분하려고 붙였어요.

### 3-1. 판정 · 집계 · 격리 (QA가 읽는 핵심)

| 컬렉션 | 상태 | QA 레코드 | QA가 계산하는 것 |
|---|---|---|---|
| `SESSION_VERDICTS` | 요청 | `SessionVerdictRecord` | 탐지율 · 오탐률(FPR) · 룰별 Hit 수 |
| `SESSION_FEATURES` (`event_metrics` 자리) | 요청 | `SessionFeatureRecord` | 집계 정확도 (봇이 보낸 파라미터 vs 시스템 계산 값) · Gold 반영 지연 |
| `QUARANTINE_EVENTS` | 요청 | `QuarantineRecord` | 사유별 격리 건수 · 기대 격리와 대조 |

**SESSION_VERDICTS**

| 시스템 필드 | QA 이름 | QA 사용처 |
|---|---|---|
| `bookingAttemptId` | `booking_attempt_id` | 세션 키 · Ground Truth와 대조 |
| `stage` | `stage` (`VerdictStage`) | CHALLENGE 이상 = 탐지 |
| `score` | `score` | 임계값 조정 분석 |
| `matchedRules` | `matched_rules` | B4 룰별 Hit 수 · 05 미탐 원인 |
| `ruleSetVersion` | `rule_set_version` | Run 비교 기준 |
| `decidedAt` | `decided_at` | 판정 응답 지연 |

**SESSION_FEATURES** · QA 봇 파라미터(`SessionBehavior`)와 1:1 대조 · 대응 원본은 `domain/models.py`의 `FEATURE_FIELD_BY_BEHAVIOR_FIELD`

| 시스템 필드 | QA 이름 | 대조하는 봇 파라미터 |
|---|---|---|
| `bookingAttemptId` | `booking_attempt_id` | - |
| `entryDelayAfterOpenMs` | `entry_delay_after_open_ms` | `entry_delay_after_open_ms` (진입 지연) |
| `clickIntervalMeanMs` | `click_interval_mean_ms` | `click_interval_mean_ms` (평균 간격) |
| `clickIntervalStdMs` | `click_interval_std_ms` | `click_interval_deviation_ms` (간격 표준편차) |
| `sessionsPerDevice` | `sessions_per_device` | `sessions_per_device` (병렬 세션) |
| `eventCount` | `event_count` | 집계 누락 검출 |
| `windowStart` · `windowEnd` | `window_start` · `window_end` | 이중 집계 검출 |
| `computedAt` | `computed_at` | Gold 반영 시각 |

**QUARANTINE_EVENTS**

| 시스템 필드 | QA 이름 | QA 사용처 |
|---|---|---|
| `rawEventId` | `raw_event_id` | 원본 추적 |
| `stage` | `stage` | 파싱 · 검증 · 정제 단계별 건수 |
| `reasonCode` | `reason_code` | 아래 3-4 사유 코드 · 계약 시험 기대값과 대조 |
| `quarantinedAt` | `quarantined_at` | 격리 지연 |

### 3-2. 원본 이벤트

| 컬렉션 | 상태 | QA가 확인하는 것 |
|---|---|---|
| 원본 MongoDB `ticketguard_raw` (27020 · `raw_consumer`) · 9개 컬렉션 (아래 4-2) | 구현됨 (main 2026-11-06) | Kafka 메시지 1건 = 1문서 · 위치(`topic` · `partition` · `offset`)로 찾기 · `ingestedAt` 적재 지연 · 기존 `raw_events`는 과거 기록 |
| `ACTIVITY_EVENTS` | 초안 | 이벤트 스키마 v1 필드 · `eventId` UK(요청)로 중복 0건 · `receivedAt` · `processedAt`(요청) 단계 지연 |

**Gold 반영 지연 계산**: `SESSION_FEATURES.computedAt − 그 구간 마지막 ACTIVITY_EVENTS.receivedAt` · 단계별로는 `receivedAt → RAW_EVENTS.ingestedAt → processedAt → computedAt`

### 3-3. 예매 · 계정 · 예외 시험

| 컬렉션 | 상태 | QA가 확인하는 것 |
|---|---|---|
| `ACCOUNTS` · `ROLES` · `ACCOUNT_ROLES` | 초안 | 다른 사용자 데이터 접근 거부 · 관리자 권한 |
| `SHOWS` · `SCHEDULES` · `EVENT_TYPES` | 초안 | 오픈 전 예매 거부(`bookingOpensAt`) · 좌석 방식(`seatMode`) |
| `BOOKINGS` | 초안 | `idempotencyKey` UK · 같은 확정 요청 재전송 시 예매 1건 (E20) |
| `INVENTORIES` | 초안 · `version` 요청 | 동시 확정 시 초과 판매 0건 (E12) |
| `BOOKING_ITEMS` | 초안 | 예매 수량 = 재고 차감 수량 |
| `QUEUE_TICKETS` | 요청 (권장) | 대기열 한도 · 순번 역전 (T1 · T2) |
| `SEAT_HOLDS` (또는 Redis) | 요청 (권장) | 좌석 점유 5분 만료 (E16) |
| `CAPTCHA_CHALLENGES` | 요청 (권장) | CHALLENGE 단계 통과율 |

### 3-4. 격리 사유 코드 (QA 제안 · db 확정 전 · 코드 원본 `test_suites/event_contract.py`의 `QUARANTINE_REASON_CODES`)

| 코드 | 뜻 |
|---|---|
| `PARSE_ERROR` | Kafka 메시지 값이 JSON이 아님 |
| `MISSING_FIELD` | 필수 필드 없음 |
| `INVALID_FORMAT` | 형식 오류 (eventId 형식 · 시간대 없는 시각 등) |
| `UNSUPPORTED_SCHEMA` | 처리할 수 없는 `schemaVersion` |
| `DUPLICATE_EVENT_ID` | 이미 저장된 `eventId` |

### 3-5. QA 데이터 넘기기 (요청 시 · QA 담당 승인 · 시스템 DB 밖)

- 시스템 DB(`ticketguard`)에는 QA 필드 · 컬렉션을 두지 않아요. 운영 데이터 구조만 써요.
- 규칙: `AGENTS.md` 6장 "QA 데이터 넘기기" · 코드: `qa_database/archive_export.py` · 명령 `ticket-guard-qa export-archive`
- 받는 곳: MongoDB DB `ticketguard_qa_archive` (시스템 DB와 분리 · 판정 코드 읽기 금지)
- 파일: `qa_data/archives/{archiveId}/` · 컬렉션마다 JSON 배열 1개 + `manifest.json`(받는 사람 · 이유 · 컬렉션 · 가져오기 명령)
- 가져오기: `mongoimport --jsonArray --mode upsert` · 날짜는 확장 JSON `{"$date": …}` · 같은 `_id`는 덮어쓰기
- 모든 문서에 `_id` · `schemaVersion: 1` · `archiveId`
- **필드 추가**: `archive_export.py`의 `*_FIELDS`에 한 줄 + 아래 표에 한 줄 · 받는 쪽은 `schemaVersion`이 같으면 새 필드를 무시해도 됨

| 컬렉션 | 기본 | `_id` | 필드 |
|---|---|---|---|
| `QA_ARCHIVE_RUNS` | O | `runId` | `targetKind` · `status` · `startedAt` · `finishedAt` · `virtualUserCount` · `trafficMix` · `metrics`(합격 기준 지표) · `criterionResults` · `passedCriteriaCount` · `missedBotCount` · `falsePositiveCount` · `ruleHitCountByRuleId` · (정답표 · 봇 설정과 함께일 때만) `randomSeed` · `botVersionNumbers` |
| `QA_ARCHIVE_FINDINGS` | O | `{runId}:{bookingAttemptId}` | `runId` · `bookingAttemptId` · `findingType`(`MISSED_BOT` · `FALSE_POSITIVE`) · `actualActorType` |
| `QA_ARCHIVE_ANSWER_KEYS` | 직접 지정 | `{runId}:{bookingAttemptId}` | `runId` · `bookingAttemptId` · `actualActorType` |
| `QA_ARCHIVE_BOT_VERSIONS` | 직접 지정 | `{actorType}:v{versionNumber}` | `actorType` · `versionNumber` · `behavior`(행동 값) · `changeNote` |

- 시스템 판정 · 행동 수치는 복사하지 않아요. `bookingAttemptId`로 `SESSION_VERDICTS` · `SESSION_FEATURES`와 연결해요.
- 적발 목록은 QA 결과 화면 목록 길이(200건)까지 · `missedBotCount` · `falsePositiveCount`가 더 크면 목록이 잘린 것
- 시드는 VU 순서로 봇을 다시 계산할 수 있어서 정답표와 같은 등급으로 다뤄요.

## 4. Kafka

| 항목 | 값 |
|---|---|
| 토픽 | `ticketguard.events.v1` |
| 파티션 | 3 |
| 보관 기간 | 7일 (개발용 제안 · 확정 아님) |
| 순서 키 후보 | `bookingAttemptId` · 없으면 `userId` |
| 접속 | Docker 내부 `kafka:9092` (QA 컨테이너는 같은 compose 네트워크) |

- QA는 **전용 consumer group으로 읽기만** 해요. 토픽에 쓰지 않아요.

### 4-1. QA 소비자 규칙 (이벤트 전달 검증 · `system_targets/live_kafka_reader.py`)

| 항목 | 규칙 |
|---|---|
| 소비자 그룹 | `ticketguard-qa-{runId}` · 시스템 원본 적재 · Spark · `ticketguard-debug-*` 그룹과 공유 금지 |
| 읽은 위치 저장 | 안 함 (`enable.auto.commit=false` · commit 없음) · 시스템 소비자 위치에 영향 없음 |
| 읽는 범위 | Run 시작 직전 파티션별 끝 위치(high watermark) → 트래픽 종료 뒤 끝까지 · 끝 도달 뒤 5초 새 메시지 없으면 종료 · 최대 60초 |
| 메시지 해석 | value = 이벤트 JSON (v1 · v2) · 해석 실패 = 형식 오류 · key = `bookingAttemptId` → 없으면 `userId` |
| QA 메시지 식별 | `userId`가 `qa-user-*` · QA가 받은 예매 시도 번호 · QA가 만든 `eventId` |

**이벤트 전달 검증 항목**

| 항목 | 현업 용어 | 합격 |
|---|---|---|
| QA가 보낸 좌석 클릭 이벤트 전부 수신 | 완전성 | 누락 0 |
| 예매 시도마다 서버 이벤트 수신 · 예매 완료 = `queue_enter` · `queue_register` · `queue_admitted` · `captcha_success` · `booking_confirm_request` · `booking_confirm_success` · 매진 = 확정 성공 대신 `booking_confirm_fail` + `queue_cancel` | 흐름 완전성 | 누락 0 |
| 같은 `eventId` 한 번만 | 유일성 | 중복 0 |
| JSON 해석 가능 | 형식 유효성 | 오류 0 |
| 같은 예매 시도 = 같은 파티션 | 파티션 키 일관성 (순서 보장 조건) | 위반 0 |
| 메시지 생성 시각 − `occurredAt` | 적시성 · 전달 지연 p95 | 기록 (기준선 미정) |
| 스키마 v2 · `capture_chunk` | 관측 이벤트 수 | 기록 |

### 4-2. 원본 적재 검증 (`test_suites/raw_ingest.py` · `system_targets/live_raw_mongo_reader.py`)

| 항목 | 규칙 |
|---|---|
| 접속 | `TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI` · 원본 DB 읽기 전용 계정만 · `find`만 · 비우면 건너뜀 |
| 읽는 범위 | 4-1과 같은 트래픽 · 토픽에서 고른 QA 메시지의 위치(파티션 · 오프셋)만 · 위치 인덱스 `raw_kafka_position_v1` |
| 대기 | 전부 보일 때까지 1초마다 다시 조회 · 최대 30초 · 마지막에 전체 한 번 더 (늦게 생긴 중복 포함) |
| 읽는 필드 | `partition` · `offset` · `value`(원문 바이트) · `timestampMs` · `ingestedAt` · `routing.reason` |
| 분류표 | `raw-routing-v1` QA 사본 `domain/raw_event_routing.py` · 시스템 원본 `raw_consumer/router.py` · 시스템이 바꾸면 오분류로 드러남 |

| 컬렉션 | eventType |
|---|---|
| `behavior_events` | `page_enter` · `page_exit` · `search_change` · `genre_change` · `show_select` · `schedule_select` · `seat_select` · `seat_cancel` · `quantity_change` · `ui_interaction` · `page_lifecycle` |
| `booking_events` | `queue_*` · `connection_timeout` · `captcha_*` · `booking_confirm_*` · `booking_access_rejected` · `booking_not_open` |
| `auth_events` | `login_success` · `login_fail` |
| `http_events` | `browser_request_start` · `browser_request_body` · `browser_response_headers` · `browser_request` · `server_request` · `server_response_headers` |
| `performance_events` | `resource_timing` · `navigation_timing` · `performance_entry` |
| `browser_errors` | `browser_error` |
| `collector_events` | `collector_limitation` · `collector_failure` · `scenario_executed` |
| `raw_chunks` | `capture_chunk` |
| `unclassified_events` | 해석 실패 · 빈 값 · 미지원 `schemaVersion` · 미등록 `eventType` (`routing.reason`) |

**원본 적재 검증 항목**

| 항목 | 현업 용어 | 합격 |
|---|---|---|
| QA 메시지 위치마다 원본 문서 있음 | 완전성 | 적재 누락 0 |
| 같은 위치가 9개 컬렉션 전체에서 1건 | 유일성 | 중복 적재 0 |
| `eventType`별 기대 컬렉션에 보관 | 분류 정확성 | 오분류 0 · 미분류 0 |
| 저장된 `value` 해석 결과 = 토픽 메시지 | 원문 보존 | 원문 변형 0 |
| `ingestedAt` − `timestampMs` | 적재 지연 p95 | 기록 (기준선 미정) |
| 토픽에서 QA 메시지 0건 | 시험 성립 | FAIL (이벤트 전달 검증 먼저) |

## 5. 계약 시험 데이터

위치: `qa/case_data/event_contracts/` · db 팀도 자기 시험(Spark 등)에서 가져다 써요. Ground Truth · 봇 정보는 넣지 않아요.

### 5-1. 파일 모양

| 키 | 뜻 |
|---|---|
| `endpoint` | `events` = `POST /api/events/` · `action` = `POST /api/action/` · `kafka` = Django를 거치지 않고 토픽에 넣는 메시지 (db 팀 파이프라인 시험용 · QA HTTP 시험은 건너뜀) |
| `requests` | HTTP 요청 본문 목록 (`events` · `action`) |
| `kafka_messages` | 토픽 메시지 목록 · `key` · `value` (`kafka`) · `value`가 문자열이면 JSON이 아닌 원문 그대로 |
| `expected_status_codes` | HTTP 응답 코드 (`events` · `action`) · `"accepted"` = 200 또는 202 (Kafka 전달 완료 · 대기) |
| `expected_storage` | 파이프라인 처리 뒤 기대 결과 · `activity_event_count` (ACTIVITY_EVENTS 행 수) · `quarantine_reason_codes` (QUARANTINE_EVENTS 사유 목록) |

- Django가 400으로 거부한 요청은 Kafka로 가지 않아요. 그래서 `activity_event_count` 0 · 격리 없음이에요.
- 자리 표시는 실행할 때 값으로 바꿔요. 같은 파일 안에서는 같은 값이에요.

| 자리 표시 | 값 |
|---|---|
| `{{event_id}}` · `{{page_view_id}}` | 새 UUID |
| `{{now}}` | 지금 (UTC) |
| `{{now_without_timezone}}` · `{{now_kst}}` | 시간대 없는 지금 · 한국 시간(+09:00) 지금 |
| `{{now_minus_25_hours}}` · `{{now_plus_25_hours}}` | 25시간 전 · 뒤 |

- `kafka` 사례의 `value`는 Django가 토픽에 넣는 모양(스키마 v1 필드 18개 전부)과 같아요. 틀린 사례는 그중 한 곳만 틀려요.

### 5-2. 사례 목록

| 파일 | 내용 | HTTP | 저장 기대 |
|---|---|---|---|
| `valid_browser_event.json` | 올바른 브라우저 이벤트 | accepted | ACTIVITY 1 |
| `duplicate_event_id.json` | 같은 `eventId` · 같은 내용 두 번 | accepted · accepted(중복 응답) | ACTIVITY 1 |
| `event_id_payload_conflict.json` | 같은 `eventId` · 다른 내용 | accepted · 400 | ACTIVITY 1 |
| `missing_event_id.json` | `eventId` 없음 | 400 | 0 |
| `missing_page_instance_id.json` | `pageInstanceId` 없음 | 400 | 0 |
| `missing_page_view_id.json` | `pageViewId` 없음 | 400 | 0 |
| `naive_occurred_at.json` | 시간대 없는 시각 | 400 | 0 |
| `non_utc_occurred_at.json` | UTC가 아닌 시각(+09:00) | 400 | 0 |
| `stale_occurred_at.json` | 지금과 24시간 넘게 차이 (과거 · 미래) | 400 | 0 |
| `unknown_event_type.json` | 목록에 없는 종류 · 서버 전용 종류 | 400 | 0 |
| `unknown_show_id.json` | 없는 공연 | 400 | 0 |
| `invalid_schedule_id.json` | 공연과 맞지 않는 회차 | 400 | 0 |
| `missing_details.json` | `details` 없음 | 400 | 0 |
| `invalid_details.json` | `details` 허용 값 밖 (`pageName` 목록 외) | 400 | 0 |
| `extra_details_field.json` | `details` 목록 밖 항목 · 관측 필드 보존 (PR #12) | accepted | ACTIVITY 1 |
| `credential_in_details.json` | `details` 안 인증 정보 키(`password`) | 400 | 0 |
| `valid_telemetry_event.json` | 관측 이벤트 `navigation_timing` · 자유 형식 `details` | accepted | ACTIVITY 1 |
| `empty_telemetry_details.json` | 관측 이벤트 · 빈 `details` | 400 | 0 |
| `spoofed_user_id.json` | 브라우저가 `userId` · `receivedAt` 직접 전송 | 400 | 0 |
| `extra_fields.json` | 목록에 없는 필드(`seatPrice` · `schemaVersion`) | 400 | 0 |
| `stale_request_sequence.json` | 예매 확정에 이미 받은 순번 재전송 | 거부 | 확정 이벤트 중복 없음 |
| `kafka_valid_server_event.json` | 올바른 서버 이벤트 (`booking_confirm_success`) | - | ACTIVITY 1 |
| `kafka_duplicate_event_id.json` | 같은 `eventId` 메시지 두 번 (Producer 재전송) | - | ACTIVITY 1 · 격리 `DUPLICATE_EVENT_ID` |
| `kafka_malformed_json.json` | JSON이 아닌 메시지 | - | ACTIVITY 0 · 격리 `PARSE_ERROR` |
| `kafka_missing_event_type.json` | `eventType` 없음 | - | ACTIVITY 0 · 격리 `MISSING_FIELD` |
| `kafka_unsupported_schema_version.json` | `schemaVersion` 99 | - | ACTIVITY 0 · 격리 `UNSUPPORTED_SCHEMA` |

- MongoDB · 파이프라인이 붙기 전에는 HTTP 응답만 확인하고, 붙은 뒤에는 `expected_storage`까지 확인해요.
