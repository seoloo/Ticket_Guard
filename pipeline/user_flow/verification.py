"""읽기 전용 원본 구간 대조. 원본 본문은 비교 후 반환하며 저장하지 않는다."""
import hashlib

COLLECTIONS = ('behavior_events', 'booking_events', 'auth_events', 'http_events',
               'performance_events', 'browser_errors', 'collector_events', 'raw_chunks', 'unclassified_events')


class VerificationPending(RuntimeError):
    pass


def verified_record(database, source, topic, partition, offset, value, timeout_ms=1000):
    query = {'source': source, 'topic': topic, 'partition': partition, 'offset': offset}
    found = []
    for name in COLLECTIONS:
        found.extend(database[name].find(query, {'value': 1, '_id': 0}).limit(2).max_time_ms(timeout_ms))
        if len(found) > 1:
            raise VerificationPending('원본 위치 중복')
    if len(found) != 1:
        raise VerificationPending('원본 적재 대기')
    original = found[0].get('value')
    if original is None or value is None or hashlib.sha256(bytes(original)).digest() != hashlib.sha256(bytes(value)).digest():
        raise VerificationPending('원본 내용 불일치')
    return bytes(original)


def verified_records(database, source, rows, timeout_ms=1000):
    """최대 100개씩 인덱스 조회하여 레코드별 아홉 번 조회하는 비용을 줄인다."""
    groups = {}
    for row in rows:
        groups.setdefault((row.topic, row.partition), []).append(row.offset)
    found = {}
    for (topic, partition), offsets in groups.items():
        query = {'source': source, 'topic': topic, 'partition': partition, 'offset': {'$in': offsets}}
        for name in COLLECTIONS:
            for item in database[name].find(query, {'topic': 1, 'partition': 1, 'offset': 1, 'value': 1}).max_time_ms(timeout_ms):
                key = (topic, partition, item['offset'])
                if key in found:
                    raise VerificationPending('원본 위치 중복')
                found[key] = item.get('value')
    verified = []
    for row in rows:
        original = found.get((row.topic, row.partition, row.offset))
        if original is None:
            raise VerificationPending('원본 적재 대기')
        if row.value is None or bytes(original) != bytes(row.value):
            raise VerificationPending('원본 내용 불일치')
        verified.append(bytes(original))
    return verified
