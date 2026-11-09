"""Direct, batched Kafka raw routing. No post-ingestion classification stage."""
import logging
import os
import signal
import time
from confluent_kafka import Consumer, OFFSET_INVALID, TopicPartition
from pymongo import MongoClient
from batching import Batch
from settings import BatchSettings, required
from mongo_writer import write_batch
from router import fingerprint


def assign(consumer, partitions):
    committed = consumer.committed(partitions, timeout=10)
    for part in committed:
        if part.error:
            raise RuntimeError('Committed offset lookup failed')
        low, high = consumer.get_watermark_offsets(part, timeout=10, cached=False)
        if part.offset == OFFSET_INVALID:
            part.offset = low
        elif not low <= part.offset <= high:
            raise RuntimeError('Committed offset outside retained range')
        if part.offset < 0:
            raise RuntimeError('Unexpected offset')
    consumer.assign(committed)


def next_offsets(messages):
    positions = {}
    for m in messages:
        key = (m.topic(), m.partition())
        positions[key] = max(positions.get(key, 0), m.offset() + 1)
    return [TopicPartition(t, p, off) for (t, p), off in sorted(positions.items())]


class Ownership:
    def __init__(self, batch):
        self.batch, self.owned, self.generation = batch, set(), 0

    def on_assign(self, consumer, partitions):
        self.generation += 1
        assign(consumer, partitions)
        self.owned = {(p.topic, p.partition) for p in partitions}

    def on_revoke(self, consumer, partitions):
        self.generation += 1
        self.owned.clear()
        # Never flush or commit a revoked/lost assignment. Replay from committed offsets.
        if self.batch.messages:
            self.batch.clear()
            raise RuntimeError('Assignment changed with pending batch; restart required')

    on_lost = on_revoke


class Stop:
    def __init__(self):
        self.requested = False
        self.deadline = float('inf')

    def request(self, *_):
        if not self.requested:
            self.requested = True
            self.deadline = time.monotonic() + 45


def flush(consumer, database, batch, source, ownership, stop):
    if not batch.messages:
        return
    offsets = next_offsets(batch.messages)
    required_parts = {(p.topic, p.partition) for p in offsets}
    generation = ownership.generation
    if not required_parts <= ownership.owned:
        raise RuntimeError('Batch contains unowned partition')
    deadline = min(time.monotonic() + batch.config.write_seconds, stop.deadline)
    counts = write_batch(database, batch.messages, source, deadline)
    actual = {(p.topic, p.partition) for p in consumer.assignment()}
    if generation != ownership.generation or not required_parts <= ownership.owned & actual:
        raise RuntimeError('Assignment lost before commit')
    if time.monotonic() >= min(deadline, stop.deadline):
        raise TimeoutError('Deadline exceeded; no commit')
    committed = consumer.commit(offsets=offsets, asynchronous=False)
    if committed is None or len(committed) != len(offsets) or any(p.error for p in committed):
        raise RuntimeError('Offset commit failed')
    print('raw_consumer batch_saved records=%d collections=%s' %
          (len(batch.messages), ','.join('%s:%d' % pair for pair in sorted(counts.items()))), flush=True)
    batch.clear()


def consume_loop(consumer, database, config, source, stop, topic):
    batch = Batch(config)
    ownership = Ownership(batch)
    consumer.subscribe([topic], on_assign=ownership.on_assign,
                       on_revoke=ownership.on_revoke, on_lost=ownership.on_lost)
    while not stop.requested:
        if batch.due():
            flush(consumer, database, batch, source, ownership, stop)
        message = consumer.poll(batch.wait())
        if stop.requested:
            break
        if message is None:
            continue
        if message.error():
            raise RuntimeError('Kafka poll failed')
        if (message.topic(), message.partition()) not in ownership.owned:
            raise RuntimeError('Received unowned partition')
        if batch.would_exceed(message):
            flush(consumer, database, batch, source, ownership, stop)
        batch.add(message)
        if batch.due():
            flush(consumer, database, batch, source, ownership, stop)
    # Only graceful stop reaches here. Failures propagate without a finally-flush.
    flush(consumer, database, batch, source, ownership, stop)


def kafka_config(group=None):
    return {
        'bootstrap.servers': os.environ.get('RAW_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'),
        'group.id': group or os.environ.get('RAW_KAFKA_GROUP_ID', 'ticketguard-raw-db-v1'),
        'client.id': 'ticketguard-raw-' + os.environ.get('HOSTNAME', 'local'),
        'enable.auto.commit': False, 'enable.auto.offset.store': False,
        'auto.offset.reset': 'error', 'allow.auto.create.topics': False,
        'partition.assignment.strategy': 'range', 'max.poll.interval.ms': 300000,
        'socket.timeout.ms': 5000, 'session.timeout.ms': 45000,
        'queued.max.messages.kbytes': 8192,
        'fetch.message.max.bytes': 4194304,
        'fetch.max.bytes': 8388608,
    }


def mongo_client():
    return MongoClient(
        host=os.environ.get('RAW_MONGO_HOST', 'mongo-raw'), port=int(os.environ.get('RAW_MONGO_PORT', '27017')),
        username=required('RAW_MONGO_WRITER_USERNAME'),
        password=required('RAW_MONGO_WRITER_PASSWORD'),
        authSource=os.environ.get('RAW_MONGO_DATABASE', 'ticketguard_raw'),
        directConnection=True, retryWrites=False, tz_aware=True,
        serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=5000,
        appname='ticketguard-raw-consumer')


def main():
    consumer = client = None
    stop = Stop()
    signal.signal(signal.SIGTERM, stop.request)
    signal.signal(signal.SIGINT, stop.request)
    logging.getLogger('pymongo').setLevel(logging.CRITICAL)
    try:
        if fingerprint() != required('RAW_ROUTING_FINGERPRINT'):
            raise ValueError('Routing contract changed; explicit transition required')
        config = BatchSettings.load()
        source = required('RAW_SOURCE_ID')
        client = mongo_client()
        client.admin.command('ping')
        consumer = Consumer(kafka_config())
        print('raw_consumer started routing=raw-routing-v1 batch=%d/%ss/%dbytes' %
              (config.count, config.seconds, config.bytes), flush=True)
        consume_loop(consumer, client[os.environ.get('RAW_MONGO_DATABASE', 'ticketguard_raw')],
                     config, source, stop, os.environ.get('RAW_KAFKA_TOPIC', 'ticketguard.events.v1'))
        return 0
    except Exception as exc:
        print('raw_consumer failed error_class=' + type(exc).__name__, flush=True)
        return 1
    finally:
        try:
            if consumer is not None:
                consumer.close()
        finally:
            if client is not None:
                client.close()


if __name__ == '__main__':
    raise SystemExit(main())
