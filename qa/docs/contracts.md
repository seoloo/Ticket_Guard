# 시스템과 맞춘 데이터 형식

QA가 시스템 데이터를 읽거나 db 브랜치와 형식을 맞출 때 보는 문서예요. 규칙 전체는 [`../AGENTS.md`](../AGENTS.md).

- **원본**: 시스템 저장소의 `docs/architecture.md` (develop `d323060` 기준, 2026-11-03)
- 이 문서는 원본을 **QA 쪽에서 쓰기 좋게 옮긴 것**이에요. 서로 다르면 원본이 맞고, 이 문서를 고쳐요.
- 고치는 절차는 AGENTS.md 7장 "형식이 바뀔 때"를 따라요.

---

## 1. 이벤트 스키마 v1

| 시스템 필드 | QA 코드 이름 | 뜻 · 규칙 |
|---|---|---|
| `schemaVersion` | `schema_version` | 지금은 `1` |
| `eventId` | `event_id` | UUID · 같은 사용자 안에서 중복이면 한 번만 저장 |
| `eventType` | `event_type` | 아래 2장 목록만 허용 |
| `occurredAt` | `occurred_at` | ISO 시각 · 시간대 없으면 거부 · 지금과 24시간 넘게 차이 나면 거부(미래 포함) · UTC로 바꿔 저장 |
| `receivedAt` | `received_at` | 서버가 넣는 시각 · 브라우저 값은 받지 않음 |
| `userId` | `user_id` | 서버가 넣는 사용자 · 브라우저 값은 받지 않음 |
| `bookingAttemptId` | `booking_attempt_id` | 예매 시도 하나 · 예매 밖이면 `null` |
| `pageInstanceId` | `page_instance_id` | 화면(탭) 하나 · 브라우저 이벤트는 필수(80자 이하) |
| `showId` · `scheduleId` | `show_id` · `schedule_id` | 공연 · 회차 · 없는 공연이면 거부 · 예매 밖이면 `null` |
| `requestSequence` | `request_sequence` | 확정 요청 순번 · 이미 받은 번호 이하면 거부 |
| `result` · `errorCode` | `result` · `error_code` | 결과 · 실패 이유 |
| `source` | `source` | `browser` · `server` |

- 브라우저 이벤트는 `POST /api/events/`로 받아요. 로그인 안 했으면 **401**, 형식이 틀리면 **400**을 돌려줘요.
- 목록에 없는 필드는 저장하지 않아요.
- 비밀번호 · 보안문자 답 · 세션 토큰은 이벤트에 들어가지 않아요.

## 2. 이벤트 종류

| 보내는 쪽 | 종류 |
|---|---|
| 브라우저 (믿지 않는 관찰 값) | `page_enter` · `page_exit` · `search_change` · `genre_change` · `show_select` · `schedule_select` · `seat_select` · `seat_cancel` · `quantity_change` |
| 서버 (확정된 사실) | `login_success` · `login_fail` · `queue_enter` · `queue_register` · `queue_cancel` · `connection_timeout` · `captcha_success` · `captcha_wrong` · `booking_confirm_request` · `booking_confirm_success` · `booking_confirm_fail` |

- `page_exit`는 유실될 수 있어요. QA는 이 이벤트가 없다고 실패로 보지 않아요.

## 3. 컬렉션 (MongoDB 연결 후 · 예정)

| 컬렉션 | 내용 | QA가 확인하는 것 |
|---|---|---|
| `users` · `sessions` | 실제 인증 · 서버 세션 | 다른 사용자 데이터 접근 거부 |
| `shows` · `schedules` | 공연 · 회차 · 오픈 시간 · 가격 | 오픈 전 예매 거부 · 서버 가격 사용 |
| `bookings` | 예매 결과 · `bookingAttemptId` 유일 | 같은 확정 요청을 다시 보내도 예매 1건 |
| `inventory` | 재고 · 조건부 차감 | 동시 확정 시 초과 판매 0건 |
| `events` | 이벤트 원본 · `eventId` 유일 · `receivedAt` TTL 86,400초 | 중복 0건 · 24시간 뒤 삭제(바로 지워지지 않을 수 있음) |
| `aggregates` | 공연 · 회차 · 시간 구간별 집계 | Spark 재시작 뒤에도 두 번 세지 않음 |
| 격리(quarantine) | 형식이 틀린 이벤트 | 틀린 이벤트가 전부 격리로 감 · 비밀 값 없음 |
| 판정 결과 | **미정** (AGENTS.md 11장) | 정답표와 비교 |

## 4. Kafka (예정)

- 순서 키 후보: `bookingAttemptId` · 없으면 `userId`
- 토픽 이름 · 파티션 수 · 보관 기간: **미정** · 정해지면 이 표에 추가

## 5. 계약 시험 데이터

위치: `qa/case_data/event_contracts/` · db 팀도 자기 시험에서 가져다 써요. 정답표 · 봇 정보는 넣지 않아요.

| 파일 | 내용 | 기대 결과 |
|---|---|---|
| `valid_browser_event.json` | 올바른 브라우저 이벤트 | 저장 1건 |
| `duplicate_event_id.json` | 같은 `eventId` 두 번 | 저장 1건 · 두 번째는 중복 응답 |
| `missing_event_id.json` | `eventId` 없음 | 400 · 저장 0건 |
| `naive_occurred_at.json` | 시간대 없는 시각 | 400 |
| `stale_occurred_at.json` | 지금과 24시간 넘게 차이 나는 시각 (과거 · 미래) | 400 |
| `unknown_event_type.json` | 목록에 없는 종류 · 서버 전용 종류 | 400 |
| `missing_page_instance_id.json` | `pageInstanceId` 없음 | 400 |
| `unknown_show_id.json` | 없는 공연 | 400 |
| `spoofed_user_id.json` | 브라우저가 `userId` · `receivedAt`을 직접 보냄 | 서버 값으로 덮어씀 |
| `extra_fields.json` | 목록에 없는 필드 추가 | 그 필드는 저장 안 됨 |
| `stale_request_sequence.json` | 예매 확정(`/api/action/`)에 이미 받은 순번 재전송 | 거부 · 이미 확정된 시도면 같은 예매를 돌려줌 |

- MongoDB · Kafka가 붙기 전에는 HTTP 응답만 확인하고, 붙은 뒤에는 저장 결과까지 확인해요.
