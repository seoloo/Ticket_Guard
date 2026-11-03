# Ticket Guard: phase 1 boundaries and required next steps

## Data paths

```text
Booking: browser → Django validation → booking/inventory repository → MongoDB
Analytics: browser/server → Django event validation → Kafka → PySpark Structured Streaming → MongoDB
```

Booking confirmation must not wait for Spark analytics. Kafka is now implemented in phase 2; see [Kafka implementation](kafka.md). Spark and MongoDB remain mandatory follow-up deliverables. The sections below retain the persistence/analytics target design. Separate domain writes and analytics ingestion; do not let Spark become the authority for seats.

## Version selection before implementation

Python 3.13.15 is the agreed baseline across development and CI. Verify the chosen stable Spark, Python, Java, Scala binary version and Kafka/MongoDB connectors together before phase 3. Match driver and executor Python environments. Pin actual working image tags and dependency versions. Do not use `latest` or silently downgrade Python. Kafka client is not required to be PyKafka; evaluate a supported Python 3.13 client such as confluent-kafka against the selected broker version, wheels, delivery/error APIs, licensing and operational needs before choosing. Kafka 4.1.2 and confluent-kafka 2.16.1 were selected and tested on Python 3.13.15 in phase 2. Spark/Java/MongoDB connector compatibility remains to be validated.

## MongoDB integration choice

Compare the official Django MongoDB Backend and direct PyMongo repository adapters against pinned Django/Python/MongoDB versions. The official backend permits supported ORM behavior but feature and authentication/session support must be checked in its compatibility documentation. Direct PyMongo fits the current repository boundary but requires explicit user/session persistence and atomic domain operations. Phase 1 uses neither and does not assume a relational DB. Decide and document before implementing persistence.

## Event schema v1

All events carry schemaVersion, eventId (UUID), eventType, occurredAt (UTC ISO timestamp), receivedAt (server UTC timestamp), userId, bookingAttemptId, pageInstanceId, showId, scheduleId, requestSequence, result, errorCode, plus source (`browser`/`server`). Optional context is null outside a booking. Server identity and receipt time are never accepted from the browser. Browser time is validated as timezone-aware and within 24 hours in the mock receiver. Invalid events return 400. No arbitrary browser payload fields are stored.

Browser allowlist: page_enter, page_exit, search_change, genre_change, show_select, schedule_select, seat_select, seat_cancel, quantity_change. Browser events are untrusted observations, not confirmed domain facts. The server generates login_success/login_fail, queue_enter/queue_register/queue_cancel, connection_timeout, captcha_success/captcha_wrong, booking_confirm_request/success/fail. Passwords, captcha answers and raw session tokens are excluded. A failed login has no verified userId and is not exposed to other users' log viewers.

The mock receiver deduplicates (userId,eventId) within a bounded in-memory window. Later use a persistent unique eventId key/index or durable dedup design; browser retry must retain the same eventId. Generate authoritative server events once per committed domain result. Record every rejection where meaningful without logging sensitive request bodies. page_exit can be lost and does not itself cancel an attempt.

## Kafka and reliability

- Candidate ordering key: bookingAttemptId, falling back to userId (anonymous events need a non-sensitive session key). Ordering is within one partition, not across the cluster. Document hot-key and repartition consequences.
- Define topic names, partition counts, replication factor and retention before deploy. A local single broker is development only.
- Bounded producer buffering/timeouts, delivery callbacks, retries, backpressure and an observable failure counter are needed.
- For domain events, design transactional outbox or equivalent durable publish recovery with the MongoDB write. Simply swallowing errors, which the mock intentionally does, is not production delivery assurance.
- A timeout after committing a booking must be resolved with bookingAttemptId/idempotency lookup, not blindly repeated booking creation.
- Do not claim end-to-end exactly-once from retries alone.

## Spark job

Read Kafka via Structured Streaming. Validate schemaVersion and required fields; send invalid records to a dedicated quarantine topic/collection without secrets. Normalize UTC types and distinguish event time/receipt time. Deduplicate with an explicit event-time watermark/window; explain how events outside the window are handled. Aggregate counts/latency by showId/scheduleId and time window.

Persist checkpointLocation to a named Docker volume. Agree on startingOffsets, replay policy and recovery from a missing or incompatible checkpoint. Use idempotent MongoDB upserts keyed by eventId (and aggregate deterministic window keys) in foreachBatch or a compatible connector. Batch re-execution must not double-count. Test restart after partial sink writes. Monitor lag, rejected/late records and sink errors. Use explicit schema evolution/migration policies.

## MongoDB collections and indexes

- users/sessions: real authentication and revocable server sessions; no raw passwords/tokens.
- shows/schedules: canonical schedule, seat type, open time and server price.
- bookings: unique bookingAttemptId/idempotency key, user ownership index, immutable confirmed result.
- inventory: atomic conditional reserve/confirm. General admission decrements only when remaining >= requested quantity. Reserved seat updates validate all requested seats. Decide whether one inventory document per schedule (single atomic operation) or multiple documents with transactions is appropriate. A process lock is not sufficient.
- events: unique eventId, indexes for user/show/time and TTL on receivedAt of 86,400 seconds. TTL removal is asynchronous; exact deletion at the 24-hour instant is not guaranteed.
- aggregates: deterministic keys for show/schedule/window; separate retention from raw events.

Booking history is separate from events and has no event-log TTL. If transactions cover multiple documents or an outbox, configure a supported replica set/sharded deployment. A replica set inside one local host is not host-failure high availability.

## Admission, multiple tabs and requests

Move active attempt ownership, heartbeat expiry, queue sequence and captcha count to shared authoritative server storage. Define atomic claim/cancel, server-generated capabilities, TTL and fencing so a late request cannot resurrect an expired admission. A Redis addition is optional and requires a design decision; do not add it silently or replace mandatory MongoDB/Kafka/Spark.

Current single-process service uses a lock and monotonic time. For unconfirmed attempts it rejects sequences <= last accepted sequence; for already confirmed attempts it returns the stored result before sequence processing. Client ignores old confirm responses. Transactions/fencing are required to retain this policy across workers. Browser draft seats are presentation state only.

## Integration acceptance checklist

Actual web action produces identifiable event → broker contains event → Spark consumes/processes → MongoDB stores corresponding event/aggregate. Verify no duplicate booking/event on retries, wrong-user access denial, producer outage, broker restart, Spark restart/checkpoint recovery, sink outage and replay. Run container health checks and document resource requirements. Validate local Docker integration separately from multi-node distribution, replication and failover.

