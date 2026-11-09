"""Run fail with dedicated DB stopped, then recover after starting that DB."""
import os
import sys
import time
from confluent_kafka import Consumer, Producer, OFFSET_INVALID
from confluent_kafka.admin import AdminClient, NewTopic
from pymongo import MongoClient
from pymongo.write_concern import WriteConcern
from main import assign, flush, Ownership, Stop
from batching import Batch
from settings import BatchSettings
from router import COLLECTIONS

suffix = os.environ['RAW_TEST_ID']
topic = 'ticketguard.raw-outage.' + suffix
group = 'ticketguard-raw-outage-' + suffix
bootstrap = os.environ['RAW_KAFKA_BOOTSTRAP_SERVERS']
if sys.argv[1] == 'fail':
    admin = AdminClient({'bootstrap.servers': bootstrap})
    admin.create_topics([
        NewTopic(topic, num_partitions=1, replication_factor=1,
                 config={'retention.ms': '3600000'})])[topic].result(30)
    p = Producer({'bootstrap.servers': bootstrap})
    p.produce(topic, value=b'outage-recovery')
    assert p.flush(20) == 0
c = Consumer({'bootstrap.servers': bootstrap, 'group.id': group,
              'enable.auto.commit': False, 'enable.auto.offset.store': False,
              'auto.offset.reset': 'error'})
c.subscribe([topic], on_assign=assign)
client = MongoClient(host='mongo-raw', port=int(os.environ.get('RAW_MONGO_PORT', '27017')),
                     username=os.environ['RAW_MONGO_WRITER_USERNAME'],
                     password=os.environ['RAW_MONGO_WRITER_PASSWORD'],
                     authSource=os.environ['RAW_MONGO_DATABASE'], directConnection=True,
                     serverSelectionTimeoutMS=1000, connectTimeoutMS=1000, socketTimeoutMS=1000)
col = client[os.environ['RAW_MONGO_DATABASE']].get_collection(
    'raw_events', write_concern=WriteConcern(w=1, j=True))
try:
    deadline = time.monotonic() + 30
    m = None
    while time.monotonic() < deadline:
        m = c.poll(1)
        if m is not None:
            if m.error(): raise RuntimeError('Poll failure')
            break
    assert m is not None and m.offset() == 0
    if sys.argv[1] == 'fail':
        try:
            batch=Batch(BatchSettings()); batch.add(m)
            ownership=Ownership(batch); ownership.owned={(topic,0)}
            flush(c, client[os.environ['RAW_MONGO_DATABASE']], batch, topic, ownership, Stop())
        except Exception:
            from confluent_kafka import TopicPartition
            assert c.committed([TopicPartition(topic, 0)], timeout=10)[0].offset == OFFSET_INVALID
            print('outage PASS: DB unavailable; offset not committed')
        else:
            raise AssertionError('Expected DB write failure')
    else:
        batch=Batch(BatchSettings()); batch.add(m)
        ownership=Ownership(batch); ownership.owned={(topic,0)}
        flush(c, client[os.environ['RAW_MONGO_DATABASE']], batch, topic, ownership, Stop())
        assert sum(client[os.environ['RAW_MONGO_DATABASE']][n].count_documents({'source':topic}) for n in COLLECTIONS) == 1
        print('recovery PASS: original offset replayed and saved')
finally:
    c.close()
    client.close()
