import time
from datetime import datetime, timezone
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
        print(f'pipeline metrics_refreshed event_types={len(metrics)} quarantine={quarantine_count}', flush=True)
    finally:
        if client is not None:
            client.close()
