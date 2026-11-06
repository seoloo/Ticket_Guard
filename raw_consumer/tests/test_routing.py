import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from bson import BSON
from confluent_kafka import OFFSET_INVALID, TopicPartition
from pymongo.errors import BulkWriteError, DocumentTooLarge
from router import route, GROUPS
from records import document
from batching import Batch
from settings import BatchSettings
from main import flush, Stop, Ownership, assign, next_offsets, consume_loop
from mongo_writer import write_batch


def message(value=b'bad', partition=0, offset=0):
    m = Mock()
    for name, value in {'topic':'test', 'partition':partition, 'offset':offset,
                        'value':value, 'key':b'', 'headers':[('x', b''), ('x', None), ('x', b'\xff')],
                        'timestamp':(1, 123), 'error':None}.items():
        getattr(m, name).return_value = value
    return m


class RoutingTests(unittest.TestCase):
    def test_all_explicit_routes_both_versions(self):
        for version in (1, 2):
            for target, kinds in GROUPS.items():
                for kind in kinds:
                    self.assertEqual(route(json.dumps({'schemaVersion':version, 'eventType':kind}).encode())[0], target)

    def test_fallback_reasons(self):
        for value, reason in [(None,'null_payload'), (b'','empty_payload'), (b'\xff','parse_failed'),
            (b'{','parse_failed'), (b'NaN','parse_failed'), (b'[]','non_object_json'),
            (b'{"schemaVersion":true}','unsupported_schema'),
            (b'{"schemaVersion":3}','unsupported_schema'),
            (b'{"schemaVersion":1}','invalid_event_type'),
            (b'{"schemaVersion":2,"eventType":"booking_future"}','unknown_event_type')]:
            target, metadata = route(value)
            self.assertEqual((target, metadata['reason']), ('unclassified_events', reason))

    def test_binary_null_headers_and_identity(self):
        m = message(b'\xff\x00')
        item = BSON(BSON.encode(document(m,'s'))).decode()
        self.assertEqual(item['value'], b'\xff\x00')
        self.assertEqual(item['key'], b'')
        self.assertEqual([h['value'] for h in item['headers']], [b'', None, b'\xff'])
        self.assertEqual(document(m,'s')['_id'], item['_id'])
        self.assertNotEqual(document(message(b'\xff\x00',offset=1),'s')['_id'],item['_id'])
        self.assertIsNone(document(message(None),'s')['value'])

    def test_count_time_and_bytes(self):
        clock = Mock(return_value=0)
        batch = Batch(BatchSettings(count=2, bytes=1000), clock)
        batch.add(message()); self.assertFalse(batch.due())
        clock.return_value=1; self.assertTrue(batch.due())
        batch.clear(); batch.add(message());batch.add(message()); self.assertTrue(batch.due())
        batch=Batch(BatchSettings(bytes=4),clock)
        batch.add(message(b'x'*20)); self.assertTrue(batch.due())
        self.assertTrue(batch.would_exceed(message()))

    def test_offsets(self):
        result = next_offsets([message(offset=2),message(partition=1,offset=9),message(offset=7)])
        self.assertEqual([(p.partition,p.offset) for p in result],[(0,8),(1,10)])

    def context(self):
        batch=Batch(BatchSettings()); batch.add(message())
        own=Ownership(batch); own.owned={('test',0)}
        c=Mock();c.assignment.return_value=[TopicPartition('test',0)]
        c.commit.return_value=[TopicPartition('test',0,1)]
        return batch,own,c

    def test_partial_bulk_failure_no_commit(self):
        batch,own,c=self.context()
        batch.add(message(b'{"schemaVersion":1,"eventType":"login_success"}',offset=1))
        db=Mock(); first=Mock();first.bulk_write.return_value.acknowledged=True
        second=Mock();second.bulk_write.side_effect=DocumentTooLarge('test')
        db.get_collection.side_effect=[first,second]
        with self.assertRaises(DocumentTooLarge):flush(c,db,batch,'s',own,Stop())
        first.bulk_write.assert_called_once();c.commit.assert_not_called()
        self.assertEqual(len(batch.messages),2)

    def test_commit_failure_retains_batch(self):
        batch,own,c=self.context();c.commit.side_effect=RuntimeError()
        with patch('main.write_batch',return_value={'unclassified_events':1}):
            with self.assertRaises(RuntimeError):flush(c,Mock(),batch,'s',own,Stop())
        self.assertEqual(len(batch.messages),1)

    def test_commit_error_result(self):
        batch,own,c=self.context();c.commit.return_value=[SimpleNamespace(error='failed')]
        with patch('main.write_batch',return_value={}):
            with self.assertRaises(RuntimeError):flush(c,Mock(),batch,'s',own,Stop())

    def test_ownership_lost_before_commit(self):
        batch,own,c=self.context();c.assignment.return_value=[]
        with patch('main.write_batch',return_value={}):
            with self.assertRaises(RuntimeError):flush(c,Mock(),batch,'s',own,Stop())
        c.commit.assert_not_called()

    def test_revoke_and_lost_never_flush(self):
        for method in ('on_revoke','on_lost'):
            batch,own,c=self.context()
            with self.assertRaises(RuntimeError):getattr(own,method)(c,[TopicPartition('test',0)])
            self.assertEqual(batch.messages,[]);self.assertEqual(own.owned,set())
            c.commit.assert_not_called()

    def test_expired_shutdown_no_commit(self):
        batch,own,c=self.context();stop=Stop();stop.deadline=time.monotonic()-1
        with self.assertRaises(TimeoutError):flush(c,Mock(),batch,'s',own,stop)
        c.commit.assert_not_called()

    def test_graceful_stop_flushes_pending(self):
        c=Mock();stop=Stop()
        def subscribe(topics,**callbacks):
            c.committed.return_value=[TopicPartition('test',0,-1001)]
            c.get_watermark_offsets.return_value=(0,1)
            callbacks['on_assign'](c,[TopicPartition('test',0)])
        c.subscribe.side_effect=subscribe
        calls=[0]
        def poll(_):
            calls[0]+=1
            if calls[0]==1:return message()
            stop.request();return None
        c.poll.side_effect=poll;c.assignment.return_value=[TopicPartition('test',0)]
        c.commit.return_value=[TopicPartition('test',0,1)]
        with patch('main.write_batch',return_value={'unclassified_events':1}) as written:
            consume_loop(c,Mock(),BatchSettings(),'s',stop,'test')
        written.assert_called_once();c.commit.assert_called_once()

    def test_assign_new_resume_expired(self):
        for off,expected in [(OFFSET_INVALID,5),(8,8)]:
            c=Mock();p=TopicPartition('test',0,off);c.committed.return_value=[p]
            c.get_watermark_offsets.return_value=(5,10)
            assign(c,[p]);self.assertEqual(p.offset,expected)
        c=Mock();p=TopicPartition('test',0,4);c.committed.return_value=[p]
        c.get_watermark_offsets.return_value=(5,10)
        with self.assertRaises(RuntimeError):assign(c,[p])

    def test_writer_set_on_insert(self):
        db=Mock();db.get_collection.return_value.bulk_write.return_value.acknowledged=True
        write_batch(db,[message()], 's', time.monotonic()+5)
        args=db.get_collection.return_value.bulk_write.call_args
        operation=args.args[0][0]
        self.assertIn('$setOnInsert',operation._doc)
        self.assertTrue(operation._upsert)
        self.assertFalse(args.kwargs['ordered'])


if __name__=='__main__':unittest.main()
