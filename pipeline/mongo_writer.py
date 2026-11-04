import time
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
        pending = []
        for row in rows:
            if client is None:
                client = client_for(config)
                collection = client[config.database].get_collection(
                    'raw_events', write_concern=WriteConcern(w=1, j=True, wtimeout=config.timeout_ms))
            item = document(row)
            pending.append(UpdateOne({'_id': item['_id']}, {'$setOnInsert': item}, upsert=True))
            if len(pending) >= config.bulk_size:
                flush(collection, pending, config)
                pending = []
        if pending:
            flush(collection, pending, config)
    except Exception:
        # Never propagate driver exceptions containing operation payloads.
        raise RuntimeError('MongoDB partition write failed; batch will not commit') from None
    finally:
        if client is not None:
            client.close()


def write_batch(batch_df, batch_id, config):
    print(f'pipeline batch_start id={batch_id}', flush=True)
    batch_df.foreachPartition(partial(write_partition, config=config))
    print(f'pipeline batch_saved id={batch_id}', flush=True)
