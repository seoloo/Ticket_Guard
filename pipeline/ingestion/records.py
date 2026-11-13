"""
[홍석환] Kafka 전송 레코드의 BSON 변환
토픽·파티션·오프셋과 원문 바이트를 저장 가능한 전송 정보로 변환한다.
"""
from datetime import timezone
from bson.binary import Binary
from bson.int64 import Int64


def document(row):
    stamp = row.timestamp
    if stamp is not None:
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    return {
        '_id': f'{row.topic}:{row.partition}:{row.offset}',
        'topic': row.topic,
        'partition': int(row.partition),
        'offset': Int64(row.offset),
        'key': None if row.key is None else Binary(bytes(row.key)),
        'value': None if row.value is None else Binary(bytes(row.value)),
        'timestamp': stamp,
        'timestampType': int(row.timestampType),
    }
