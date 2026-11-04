"""Lossless Kafka transport record to BSON; no JSON parsing or filtering."""
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
