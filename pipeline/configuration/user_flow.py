"""사용자 흐름 전용 설정. 자격 증명은 출력하지 않는다."""
import os
from dataclasses import dataclass, field


@dataclass(repr=False)
class FlowConfig:
    kafka: str
    topic: str
    group: str
    raw_uri: str = field(repr=False)
    target_uri: str = field(repr=False)
    source: str
    checkpoint: str
    interval: int = 1
    presence: int = 30
    retention: int = 43200
    grace: int = 300
    max_offsets: int = 1000
    timeout_ms: int = 1000
    max_events: int = 250000

    @classmethod
    def load(cls):
        def required(name):
            value = os.environ.get(name, '')
            if not value:
                raise ValueError('필수 설정 누락: ' + name)
            return value
        def number(name, default, maximum):
            value = int(os.environ.get(name, default))
            if not 1 <= value <= maximum:
                raise ValueError('설정 범위 오류: ' + name)
            return value
        checkpoint = os.environ.get('FLOW_CHECKPOINT_DIR', '/checkpoints/flow-v1')
        if not checkpoint.startswith('/checkpoints/') or '..' in checkpoint.split('/'):
            raise ValueError('전용 체크포인트 경로 필요')
        return cls(os.environ.get('SPARK_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'),
                   os.environ.get('KAFKA_EVENTS_TOPIC', 'ticketguard.events.v1'),
                   os.environ.get('SPARK_KAFKA_GROUP_ID', 'ticketguard-spark-consumer'),
                   required('FLOW_RAW_MONGO_URI'), required('FLOW_TARGET_MONGO_URI'),
                   required('RAW_SOURCE_ID'), checkpoint,
                   number('FLOW_TRIGGER_SECONDS', 1, 1), number('FLOW_PRESENCE_SECONDS', 30, 3600),
                   43200, number('FLOW_GRACE_SECONDS', 300, 3600),
                   number('SPARK_MAX_OFFSETS_PER_TRIGGER', 1000, 10000),
                   number('FLOW_READ_TIMEOUT_MS', 1000, 10000), number('FLOW_MAX_EVENTS', 250000, 1000000))
