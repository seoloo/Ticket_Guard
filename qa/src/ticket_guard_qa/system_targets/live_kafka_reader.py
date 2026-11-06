"""이벤트 토픽 읽기 · QA 전용 소비자 그룹 · 읽은 위치 저장(commit) 없음 · 시스템 원본 적재 · Spark 소비자와 분리"""
import json
import time
from typing import Any

from ticket_guard_qa.system_targets.target_interfaces import StreamRecord

QA_CONSUMER_GROUP_PREFIX = "ticketguard-qa-"  # 시스템 소비자 그룹과 공유 금지 · docs/contracts.md 4장
METADATA_TIMEOUT_SEC = 5.0
POLL_TIMEOUT_SEC = 0.5
IDLE_FINISH_SEC = 5.0  # 끝까지 읽은 뒤 늦게 도착하는 메시지 대기
MAX_READ_SEC = 60.0


class EventStreamReadError(RuntimeError):
    pass


def decode_event(raw_value: bytes | None) -> dict[str, Any] | None:
    if raw_value is None:
        return None
    try:
        event = json.loads(raw_value)
    except (ValueError, UnicodeDecodeError):
        return None
    return event if isinstance(event, dict) else None


class KafkaEventStreamReader:
    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic

    def _create_consumer(self, run_id: str):
        from confluent_kafka import Consumer  # 실제 대상에서만 · 단위 테스트는 설치 불필요

        return Consumer({
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": f"{QA_CONSUMER_GROUP_PREFIX}{run_id}",
            "enable.auto.commit": False,
            "enable.partition.eof": True,
            "allow.auto.create.topics": False,
        })

    def snapshot_end_offsets(self) -> dict[int, int]:
        from confluent_kafka import KafkaException, TopicPartition

        consumer = self._create_consumer("offset-snapshot")
        try:
            topic_metadata = consumer.list_topics(self.topic, timeout=METADATA_TIMEOUT_SEC).topics.get(self.topic)
            if topic_metadata is None or topic_metadata.error is not None:
                raise EventStreamReadError(f"이벤트 토픽 없음 · {self.topic}")
            return {
                partition: consumer.get_watermark_offsets(TopicPartition(self.topic, partition), timeout=METADATA_TIMEOUT_SEC)[1]
                for partition in sorted(topic_metadata.partitions)
            }
        except KafkaException as error:
            raise EventStreamReadError(f"이벤트 스트림 접속 실패 · {self.bootstrap_servers} · {error}") from error
        finally:
            consumer.close()

    def read_since(self, start_offsets: dict[int, int], run_id: str) -> list[StreamRecord]:
        """start_offsets부터 끝까지 · 끝 도달 뒤 IDLE_FINISH_SEC 동안 새 메시지 없으면 종료"""
        from confluent_kafka import KafkaError, KafkaException, TopicPartition

        consumer = self._create_consumer(run_id)
        records: list[StreamRecord] = []
        reached_end: set[int] = set()
        started_at = last_message_at = time.monotonic()
        try:
            consumer.assign([TopicPartition(self.topic, partition, offset) for partition, offset in start_offsets.items()])
            while time.monotonic() - started_at < MAX_READ_SEC:
                message = consumer.poll(POLL_TIMEOUT_SEC)
                now = time.monotonic()
                if message is None:
                    if len(reached_end) == len(start_offsets) and now - last_message_at >= IDLE_FINISH_SEC:
                        break
                    continue
                if message.error():
                    if message.error().code() == KafkaError._PARTITION_EOF:
                        reached_end.add(message.partition())
                        continue
                    raise EventStreamReadError(f"이벤트 스트림 읽기 오류 · {message.error()}")
                reached_end.discard(message.partition())
                last_message_at = now
                timestamp_type, timestamp_ms = message.timestamp()
                key = message.key()
                records.append(StreamRecord(
                    partition=message.partition(), offset=message.offset(),
                    key=key.decode("utf-8", "replace") if key is not None else None,
                    timestamp_ms=timestamp_ms if timestamp_type else None,
                    event=decode_event(message.value()),
                ))
        except KafkaException as error:
            raise EventStreamReadError(f"이벤트 스트림 접속 실패 · {self.bootstrap_servers} · {error}") from error
        finally:
            consumer.close()
        return records
