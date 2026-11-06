"""Real isolated-topic regression. Only test-source documents are added."""
import json
import os
import subprocess
import sys
import time
import uuid
from confluent_kafka import Consumer, Producer, TopicPartition, OFFSET_INVALID
from confluent_kafka.admin import AdminClient, NewTopic
from pymongo.errors import DocumentTooLarge
from batching import Batch
from main import assign, mongo_client, kafka_config, flush, Ownership, Stop
from mongo_writer import write_batch
from router import COLLECTIONS, fingerprint
from settings import BatchSettings


def run():
    suffix=uuid.uuid4().hex
    topic='ticketguard.raw-routing-test.'+suffix
    group='ticketguard-raw-routing-test-'+suffix
    source=topic
    admin=AdminClient({'bootstrap.servers':os.environ['RAW_KAFKA_BOOTSTRAP_SERVERS']})
    admin.create_topics([NewTopic(topic,num_partitions=3,replication_factor=1,
        config={'retention.ms':'3600000'})])[topic].result(30)
    samples=[('page_enter','behavior_events'),('booking_confirm_success','booking_events'),
             ('login_success','auth_events'),('server_request','http_events'),
             ('performance_entry','performance_events'),('browser_error','browser_errors'),
             ('collector_failure','collector_events'),('capture_chunk','raw_chunks'),
             ('future_type','unclassified_events')]
    producer=Producer({'bootstrap.servers':os.environ['RAW_KAFKA_BOOTSTRAP_SERVERS']})
    expected=[]
    for index,(kind,target) in enumerate(samples):
        value=json.dumps({'schemaVersion':2,'eventType':kind,'details':{'sample':True}}).encode()
        producer.produce(topic,value=value,key=b'',partition=index%3,headers=[('x',b''),('x',None)])
        expected.append((value,target))
    for value in (None,b'',b'\xff\x00',b'[]'):
        producer.produce(topic,value=value,key=b'raw',partition=0)
        expected.append((value,'unclassified_events'))
    assert producer.flush(20)==0
    client=mongo_client();database=client[os.environ['RAW_MONGO_DATABASE']]
    def connect():
        c=Consumer(kafka_config(group));c.subscribe([topic],on_assign=assign);return c
    def collect(c,count):
        messages=[];deadline=time.monotonic()+30
        while len(messages)<count and time.monotonic()<deadline:
            m=c.poll(.2)
            if m is not None:
                if m.error():raise RuntimeError('Test poll failed')
                messages.append(m)
        assert len(messages)==count
        return messages
    c=connect();messages=collect(c,len(expected))
    batch=Batch(BatchSettings());[batch.add(m) for m in messages]
    own=Ownership(batch);own.owned={(topic,i) for i in range(3)}
    # First collection persists, second raises; the whole batch remains uncommitted.
    class PartialDB:
        def __init__(self):self.calls=0
        def get_collection(self,name,**kwargs):
            self.calls+=1
            if self.calls==2:raise DocumentTooLarge('Injected permanent failure')
            return database.get_collection(name,**kwargs)
    try:flush(c,PartialDB(),batch,source,own,Stop())
    except DocumentTooLarge:pass
    else:raise AssertionError('Expected injected write error')
    assert all(p.offset==OFFSET_INVALID for p in c.committed([TopicPartition(topic,i) for i in range(3)],timeout=10))
    before={}
    for name in COLLECTIONS:
        for item in database[name].find({'source':source}):before[item['_id']]=item['ingestedAt']
    assert before
    c.close()
    c=connect();replayed=collect(c,len(expected))
    assert {(m.partition(),m.offset()) for m in replayed}=={(m.partition(),m.offset()) for m in messages}
    batch=Batch(BatchSettings());[batch.add(m) for m in replayed]
    own=Ownership(batch);own.owned={(topic,i) for i in range(3)}
    flush(c,database,batch,source,own,Stop());c.close()
    all_items=[]
    for name in COLLECTIONS:
        for item in database[name].find({'source':source}):
            if item['_id'] in before:assert item['ingestedAt']==before[item['_id']]
            all_items.append((name,item))
    assert len(all_items)==len(expected)
    for value,target in expected:
        assert any(name==target and item['value']==value for name,item in all_items)
    first=next(item for name,item in all_items if name=='behavior_events')
    assert first['key']==b'' and [h['value'] for h in first['headers']]==[b'',None]
    # Launch the real main loop with already committed test group, produce one new record.
    env={**os.environ,'RAW_KAFKA_TOPIC':topic,'RAW_KAFKA_GROUP_ID':group,
         'RAW_SOURCE_ID':source,'RAW_ROUTING_FINGERPRINT':fingerprint()}
    child=subprocess.Popen([sys.executable,'main.py'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        producer.produce(topic,value=b'{"schemaVersion":1,"eventType":"login_fail"}',partition=1)
        assert producer.flush(20)==0
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if database.auth_events.count_documents({'source':source})==2:break
            if child.poll() is not None:raise RuntimeError('Main loop exited')
            time.sleep(.2)
        else:raise AssertionError('Timed low-traffic flush missing')
        child.terminate();out,_=child.communicate(timeout=50)
        assert child.returncode==0,out
    finally:
        if child.poll() is None:child.kill();child.wait()
    assert sum(database[n].count_documents({'source':source}) for n in COLLECTIONS)==len(expected)+1
    client.close()
    print('PASS routing=9 collections records=14 partial-write/replay/first-ingest/headers/low-traffic/SIGTERM')
    print('test_topic='+topic)


if __name__=='__main__':run()
