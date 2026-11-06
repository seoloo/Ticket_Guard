"""Idempotent collection bulks. The caller commits only after ALL bulks succeed."""
import time
from collections import defaultdict
import pymongo
from pymongo import UpdateOne
from pymongo.errors import AutoReconnect, NetworkTimeout, WTimeoutError, BulkWriteError
from pymongo.write_concern import WriteConcern
from records import document
from router import route


def write_batch(database, messages, source, deadline):
    grouped = defaultdict(list)
    for message in messages:
        if time.monotonic() >= deadline:
            raise TimeoutError('Batch deadline exceeded')
        target, metadata = route(message.value())
        item = document(message, source)
        item['routing'] = metadata
        grouped[target].append(UpdateOne({'_id': item['_id']}, {'$setOnInsert': item}, upsert=True))
    # One CSOT budget across all collections and attempts, not one per collection.
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Batch deadline exceeded')
    with pymongo.timeout(remaining):
        for name, operations in grouped.items():
            collection = database.get_collection(name, write_concern=WriteConcern(w=1, j=True))
            for attempt in range(3):
                try:
                    result = collection.bulk_write(operations, ordered=False)
                    if not result.acknowledged:
                        raise RuntimeError('Unacknowledged bulk')
                    break
                except BulkWriteError as exc:
                    # A rebalance can cause identical upserts to race on _id.
                    errors = (exc.details or {}).get('writeErrors', [])
                    if not errors or any(e.get('code') != 11000 for e in errors):
                        raise
                    if attempt == 2:
                        raise
                except (AutoReconnect, NetworkTimeout, WTimeoutError):
                    if attempt == 2:
                        raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Batch deadline exceeded')
                time.sleep(min(.25 * (attempt + 1), remaining))
    if time.monotonic() >= deadline:
        raise TimeoutError('Batch deadline exceeded; no commit')
    return {name: len(ops) for name, ops in grouped.items()}
