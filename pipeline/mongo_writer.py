import time
from datetime import datetime, timezone
from statistics import median
from functools import partial
from pymongo import MongoClient, UpdateOne
from pymongo.errors import AutoReconnect, BulkWriteError, NetworkTimeout, WTimeoutError
from pymongo.write_concern import WriteConcern
from records import document


def client_for(config):
    return MongoClient(
        host=config.mongo_host, port=config.mongo_port,
        username=config.username, password=config.password, authSource=config.database,
        directConnection=True, retryWrites=False, tz_aware=True,
        serverSelectionTimeoutMS=config.timeout_ms, connectTimeoutMS=config.timeout_ms,
        socketTimeoutMS=config.timeout_ms, maxPoolSize=2,
        appname='ticketguard-spark-raw',
    )


def flush(collection, operations, config):
    for attempt in range(config.retries):
        try:
            result = collection.bulk_write(operations, ordered=False)
            if not result.acknowledged:
                raise RuntimeError('Unacknowledged write')
            return
        except BulkWriteError as exc:
            # Concurrent idempotent upserts can race on the _id unique index.
            # Retry the entire bounded bulk only for duplicate-key races or WC
            # failures. Other document errors must fail the Spark task.
            details = exc.details or {}
            errors = details.get('writeErrors', [])
            if any(e.get('code') != 11000 for e in errors):
                raise RuntimeError('MongoDB document write failed') from None
            if not errors and not details.get('writeConcernErrors'):
                raise RuntimeError('MongoDB bulk failed') from None
        except (AutoReconnect, NetworkTimeout, WTimeoutError):
            pass
        if attempt + 1 == config.retries:
            raise RuntimeError('MongoDB write retries exhausted') from None
        time.sleep(min(2 ** attempt, 5))


def write_partition(rows, config):
    client = None
    try:
        clean_pending = []
        quarantine_pending = []
        clean = None
        quarantine = None
        for row in rows:
            if client is None:
                client = client_for(config)
                clean = client[config.database].get_collection(
                    'clean_events', write_concern=WriteConcern(w=1, j=True, wtimeout=config.timeout_ms))
                quarantine = client[config.database].get_collection(
                    'quarantine_events', write_concern=WriteConcern(w=1, j=True, wtimeout=config.timeout_ms))
            item = document(row)
            clean_item, quarantine_item = normalize(item['value'], item)
            if clean_item is not None:
                clean_pending.append(UpdateOne({'_id': clean_item['_id']}, {'$setOnInsert': clean_item}, upsert=True))
            else:
                quarantine_pending.append(UpdateOne({'_id': quarantine_item['_id']}, {'$setOnInsert': quarantine_item}, upsert=True))
            if len(clean_pending) + len(quarantine_pending) >= config.bulk_size:
                if clean_pending:
                    flush(clean, clean_pending, config)
                if quarantine_pending:
                    flush(quarantine, quarantine_pending, config)
                clean_pending = []
                quarantine_pending = []
        if clean_pending:
            flush(clean, clean_pending, config)
        if quarantine_pending:
            flush(quarantine, quarantine_pending, config)
    except Exception:
        # Never propagate driver exceptions containing operation payloads.
        raise RuntimeError('MongoDB partition write failed; batch will not commit') from None
    finally:
        if client is not None:
            client.close()


def write_batch(batch_df, batch_id, config):
    print(f'pipeline batch_start id={batch_id}', flush=True)
    batch_df.foreachPartition(partial(write_partition, config=config))
    refresh_metrics(config)
    print(f'pipeline batch_saved id={batch_id}', flush=True)


def refresh_metrics(config):
    """Rebuild small dashboard metrics from idempotent clean/quarantine data."""
    client = None
    try:
        client = client_for(config)
        db = client[config.database]
        grouped = db.clean_events.aggregate([
            {'$group': {
                '_id': {'eventType': '$eventType', 'result': '$result'},
                'count': {'$sum': 1},
                'lastOccurredAt': {'$max': '$occurredAt'},
            }},
        ])
        metrics = {}
        for row in grouped:
            event_type = row['_id']['eventType']
            result = row['_id']['result']
            item = metrics.setdefault(event_type, {
                '_id': f'event_type:{event_type}',
                'metricType': 'event_type',
                'eventType': event_type,
                'total': 0,
                'success': 0,
                'failure': 0,
                'rejected': 0,
                'lastOccurredAt': None,
            })
            item['total'] += row['count']
            item[result] = row['count']
            if row.get('lastOccurredAt') and (
                item['lastOccurredAt'] is None or row['lastOccurredAt'] > item['lastOccurredAt']
            ):
                item['lastOccurredAt'] = row['lastOccurredAt']
        quarantine_count = db.quarantine_events.count_documents({})
        summary = {
            '_id': 'summary',
            'metricType': 'summary',
            'totalCleanEvents': db.clean_events.count_documents({}),
            'totalQuarantineEvents': quarantine_count,
            'refreshedAt': datetime.now(timezone.utc),
        }
        collection = db.event_metrics
        collection.replace_one({'_id': 'summary'}, summary, upsert=True)
        for item in metrics.values():
            collection.replace_one({'_id': item['_id']}, item, upsert=True)
        _refresh_dashboard_collections(db)
        print(f'pipeline metrics_refreshed event_types={len(metrics)} quarantine={quarantine_count}', flush=True)
    finally:
        if client is not None:
            client.close()


def _refresh_dashboard_collections(db):
    """Build dashboard read models only from clean_events; never touch raw_events."""
    clean = list(db.clean_events.find({}, {'_id': 0}))
    by_attempt = {}
    for event in clean:
        attempt = event.get('bookingAttemptId') or event.get('userId') or 'anonymous'
        by_attempt.setdefault(attempt, []).append(event)
    for events in by_attempt.values():
        events.sort(key=lambda item: item.get('occurredAt') or datetime.min.replace(tzinfo=timezone.utc))

    completed = sum(any(e.get('eventType') == 'booking_confirm_success' for e in events) for events in by_attempt.values())
    flow = {'_id': 'summary', 'startedAttempts': len(by_attempt), 'completedAttempts': completed,
            'conversionRate': completed / len(by_attempt) if by_attempt else 0,
            'incompleteAttempts': max(len(by_attempt) - completed, 0), 'refreshedAt': datetime.now(timezone.utc)}
    db.flow_metrics.replace_one({'_id': flow['_id']}, flow, upsert=True)
    stages = ('queue_enter', 'queue_admitted', 'captcha_success', 'seat_select', 'booking_confirm_success')
    db.funnel_metrics.replace_one({'_id': 'summary'}, {'_id': 'summary', 'stages': [
        {'stage': stage, 'count': sum(any(e.get('eventType') == stage for e in events) for events in by_attempt.values())}
        for stage in stages]}, upsert=True)
    failures = {}
    for event in clean:
        if event.get('result') in ('failure', 'rejected'):
            key = (event.get('eventType'), event.get('errorCode'), (event.get('details') or {}).get('action'), event.get('showId'), event.get('scheduleId'))
            failures[key] = failures.get(key, 0) + 1
    db.failure_reason_metrics.delete_many({})
    if failures:
        db.failure_reason_metrics.insert_many([
            {'eventType': key[0], 'errorCode': key[1], 'action': key[2], 'showId': key[3], 'scheduleId': key[4], 'count': count}
            for key, count in failures.items()
        ])
    users = {}
    for event in clean:
        user = event.get('userId')
        if not user:
            continue
        item = users.setdefault(user, {'_id': user, 'userId': user, 'signals': [], 'signalCount': 0,
                                      'lastActivityAt': event.get('occurredAt'), 'showId': event.get('showId'),
                                      'scheduleId': event.get('scheduleId'), 'reviewStatus': 'unreviewed'})
        if event.get('occurredAt') and event['occurredAt'] > item['lastActivityAt']:
            item['lastActivityAt'] = event['occurredAt']
        if event.get('result') == 'rejected':
            item['signals'].append('접근 거부 반복')
        if event.get('eventType') == 'captcha_wrong':
            item['signals'].append('보안문자 오답 반복')
        item['signalCount'] = len(item['signals'])
    db.suspicious_users.delete_many({})
    suspicious = [item for item in users.values() if item['signalCount']]
    if suspicious:
        db.suspicious_users.insert_many(suspicious)
    db.user_activity_metrics.delete_many({})
    if users:
        db.user_activity_metrics.insert_many([
            {'_id': user, 'userId': user, 'recentBookingAttempts': len({e.get('bookingAttemptId') for e in clean if e.get('userId') == user and e.get('bookingAttemptId')}),
             'accessDeniedCount': sum(e.get('result') == 'rejected' for e in clean if e.get('userId') == user),
             'lastActivityAt': item['lastActivityAt'], 'showIds': list({e.get('showId') for e in clean if e.get('userId') == user and e.get('showId')}),
             'scheduleIds': list({e.get('scheduleId') for e in clean if e.get('userId') == user and e.get('scheduleId')}),
             'timeline': [{'eventId': e.get('eventId'), 'eventType': e.get('eventType'), 'occurredAt': e.get('occurredAt'), 'errorCode': e.get('errorCode')} for e in clean if e.get('userId') == user]}
            for user, item in users.items()
        ])
    segment_pairs = (
        ('queue_enter', 'queue_admitted', 'queue_to_admitted'),
        ('queue_admitted', 'captcha_success', 'admitted_to_captcha'),
        ('captcha_success', 'seat_select', 'captcha_to_seat'),
        ('seat_select', 'booking_confirm_success', 'seat_to_confirm'),
    )
    segments = []
    for first, second, name in segment_pairs:
        values = []
        for events in by_attempt.values():
            starts = [e.get('occurredAt') for e in events if e.get('eventType') == first]
            ends = [e.get('occurredAt') for e in events if e.get('eventType') == second]
            if starts and ends:
                delta = (min(ends) - min(starts)).total_seconds() * 1000
                if delta >= 0:
                    values.append(delta)
        values.sort()
        p95 = values[min(len(values) - 1, max(0, int(len(values) * 0.95) - 1))] if values else None
        segments.append({'segment': name, 'medianMs': median(values) if values else None, 'p95Ms': p95, 'sampleCount': len(values)})
    db.stage_latency_metrics.replace_one({'_id': 'summary'}, {'_id': 'summary', 'segments': segments,
        'refreshedAt': datetime.now(timezone.utc)}, upsert=True)
