"""
[홍석환] 원본 Kafka 전송 정보 보존
원본 식별자·토픽·파티션·오프셋과 키·본문·헤더를 저장용 BSON으로 변환한다.
"""
import hashlib
import json
from datetime import datetime, timezone
from bson.binary import Binary
from bson.int64 import Int64


def binary(value):
    return None if value is None else Binary(value)


def document(message, source):
    identity = [source, message.topic(), message.partition(), message.offset()]
    stamp_type, stamp_ms = message.timestamp()
    return {
        '_id': hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest(),
        'source': source, 'topic': message.topic(), 'partition': message.partition(),
        'offset': Int64(message.offset()), 'key': binary(message.key()),
        'value': binary(message.value()),
        'headers': [{'key': k, 'value': binary(v)} for k, v in (message.headers() or [])],
        'timestampMs': Int64(stamp_ms), 'timestampType': stamp_type,
        'ingestedAt': datetime.now(timezone.utc),
    }


def message_bytes(message):
    return (len(message.key() or b'') + len(message.value() or b'') +
            sum(len(k.encode('utf-8')) + len(v or b'') for k, v in (message.headers() or [])))
