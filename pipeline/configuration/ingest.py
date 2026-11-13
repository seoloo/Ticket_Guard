"""
[홍석환] Spark 처리 환경 설정
Kafka·MongoDB·체크포인트·배치 설정을 읽고 허용 범위를 검사한다.
자격 증명이 포함된 설정은 로그에 출력하지 않는다.
"""
import os
import re
from dataclasses import dataclass, field


def positive(name, default, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
        if not 1 <= value <= maximum:
            raise ValueError()
        return value
    except ValueError:
        raise ValueError(f'Invalid positive integer setting: {name}') from None


def required(name):
    value = os.environ.get(name, '')
    if not value or value.startswith('CHANGE_ME'):
        raise ValueError(f'Required setting: {name}')
    return value


@dataclass(frozen=True, repr=False)
class Settings:
    kafka: str
    group_id: str
    topic: str
    mongo_host: str
    mongo_port: int
    database: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    checkpoint: str
    interval: int
    max_offsets: int
    bulk_size: int
    timeout_ms: int
    retries: int

    @classmethod
    def load(cls):
        kafka = os.environ.get('SPARK_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
        group_id = os.environ.get('SPARK_KAFKA_GROUP_ID', 'ticketguard-spark-consumer')
        topic = os.environ.get('KAFKA_EVENTS_TOPIC', 'ticketguard.events.v1')
        host = os.environ.get('SPARK_MONGO_HOST', 'ticket-guard-workspace-db-mongo-1')
        database = os.environ.get('MONGO_DATABASE', 'ticketguard')
        checkpoint = os.environ.get('SPARK_CHECKPOINT_DIR', '/checkpoints/spark-consumer')
        if not kafka or not re.fullmatch(r'[A-Za-z0-9._-]+', topic) or topic in ('.', '..'):
            raise ValueError('Invalid Kafka address or topic')
        if not re.fullmatch(r'[A-Za-z0-9._-]+', group_id) or group_id in ('.', '..'):
            raise ValueError('Invalid Kafka consumer group ID')
        if host == 'mongo' or not re.fullmatch(r'[A-Za-z0-9._-]+', host):
            raise ValueError('Invalid or ambiguous MongoDB hostname; use the workspace DB container name')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', database) or database in ('admin', 'config', 'local'):
            raise ValueError('Invalid application database')
        if not checkpoint.startswith('/checkpoints/') or '..' in checkpoint.split('/'):
            raise ValueError('Checkpoint must be a directory under /checkpoints')
        return cls(kafka, group_id, topic, host, positive('SPARK_MONGO_PORT', 27017, 65535),
                   database, required('MONGO_WRITER_USERNAME'), required('MONGO_WRITER_PASSWORD'),
                   checkpoint, positive('SPARK_TRIGGER_SECONDS', 5, 86400),
                   positive('SPARK_MAX_OFFSETS_PER_TRIGGER', 1000, 10000000),
                   positive('SPARK_MONGO_BULK_SIZE', 200, 10000),
                   positive('SPARK_MONGO_TIMEOUT_MS', 10000, 300000),
                   positive('SPARK_MONGO_WRITE_ATTEMPTS', 3, 10))
