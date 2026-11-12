"""불변 결과를 먼저 기록하고 단일 공개 포인터를 마지막에 교체한다."""
import hashlib
import json
from bson import BSON
from datetime import datetime, timezone, timedelta


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


def indexes(db):
    for name in ('flow_versions', 'flow_series'):
        db[name].create_index('expiresAt', expireAfterSeconds=0)
    db.flow_series.create_index([('scope', 1), ('at', 1), ('publishedAt', 1)])
    db.flow_versions.create_index([('scope', 1), ('publishedAt', -1)])


def publish(db, metrics, ranges, now, scope='all', retention=43200, grace=300):
    content = {'metrics': metrics, 'ranges': ranges, 'scope': scope}
    version = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    # 현재 결과는 TTL 없이 유지한다. 이전 공개 버전만 포인터 교체 후 만료시킨다.
    compact = {k: v for k, v in metrics.items() if k not in ('presenceSeries', 'bookingSeries')}
    document = {'_id': version, 'metrics': compact, 'ranges': ranges, 'scope': scope,
                'status': 'verified', 'verifiedAt': utc(now), 'publishedAt': utc(now)}
    series_id = f'{scope}:{version}'
    series = {'_id': series_id, 'scope': scope, 'version': version,
              'at': utc(int(now // 5) * 5), 'publishedAt': utc(now),
              'presence': metrics.get('presenceSeries', []), 'booking': metrics['bookingSeries']}
    if len(BSON.encode(series)) > 8*1024*1024 or len(BSON.encode(document)) > 8*1024*1024:
        raise RuntimeError('공개 문서 용량 제한 초과')
    db.flow_versions.update_one({'_id': version}, {'$setOnInsert': document}, upsert=True)
    db.flow_series.update_one({'_id': series_id}, {'$setOnInsert': series}, upsert=True)
    old = db.flow_public.find_one({'_id': scope})
    db.flow_public.replace_one({'_id': scope}, {'_id': scope, 'version': version, 'asOf': utc(now),
                               'status': 'verified', 'seriesCutoff': utc(now - retention)}, upsert=True)
    if old and old['version'] != version:
        db.flow_versions.update_one({'_id': old['version']}, {'$set': {'expiresAt': utc(now + grace)}})
        db.flow_series.update_one({'_id': f"{scope}:{old['version']}"}, {'$set': {'expiresAt': utc(now + grace)}})
    return version


def cleanup_unpublished(db, now, grace=30):
    """공개 포인터가 참조하는 문서는 만료시키지 않고 실패 잔여물만 정리한다."""
    current = [p['version'] for p in db.flow_public.find({}, {'version': 1})]
    for name, identity in (('flow_versions', '_id'), ('flow_series', 'version')):
        db[name].update_many({identity: {'$nin': current}, 'expiresAt': {'$exists': False},
                              'publishedAt': {'$lt': utc(now - grace)}},
                             {'$set': {'expiresAt': utc(now + grace)}})


def read_public(db, scope='all', now=None):
    pointer = db.flow_public.find_one({'_id': scope})
    if not pointer:
        return None
    version = db.flow_versions.find_one({'_id': pointer['version'], 'status': 'verified'})
    if not version:
        raise RuntimeError('공개 결과 조회 실패')
    # 단일 버전의 이력만 읽어 부분 저장 실패의 미공개 이력이 섞이지 않게 한다.
    series = db.flow_series.find_one({'_id': f"{scope}:{pointer['version']}"})
    if not series:
        raise RuntimeError('공개 시계열 조회 실패')
    if now is not None:
        from user_flow.events import stamp
        for name in ('presence', 'booking'):
            series[name] = [p for p in series[name] if stamp(p['at']) >= now - 43200]
    return version, series
