"""로컬 Spark용 검증 우선 배치 처리와 무이벤트 시간 갱신."""
import json
import threading
import time
from itertools import islice
from pathlib import Path
from pymongo import MongoClient
from user_flow.events import iso
from user_flow.metrics import calculate
from user_flow.state import State
from user_flow.store import indexes, publish, cleanup_unpublished
from user_flow.verification import verified_records, VerificationPending


def connection(uri, timeout):
    return MongoClient(uri, serverSelectionTimeoutMS=timeout, connectTimeoutMS=timeout,
                       socketTimeoutMS=timeout, tz_aware=True, appname='ticketguard-flow')


class Processor:
    def __init__(self, config, raw_database, target_database, clock=time.time):
        self.config = config; self.raw = raw_database; self.target = target_database; self.clock = clock
        self.lock = threading.RLock()
        self.path = Path(config.checkpoint) / 'derived-state.sqlite'
        self.reference_path = Path(config.checkpoint) / 'reference-state.sqlite'
        self.failed = False

    def state(self):
        return State(str(self.path), max_events=self.config.max_events)

    def verified_rows(self, dataframe):
        iterator = dataframe.toLocalIterator(prefetchPartitions=False)
        while True:
            rows = list(islice(iterator, 100))
            if not rows:
                return
            for attempt in range(5):
                try:
                    originals = verified_records(self.raw, self.config.source, rows, self.config.timeout_ms)
                    break
                except VerificationPending:
                    if attempt == 4:
                        raise
                    time.sleep(.25)
            yield from zip(rows, originals)

    def batch(self, dataframe, batch_id):
        with self.lock:
            state = self.state(); reference = State(str(self.reference_path), max_events=self.config.max_events)
            now = self.clock(); ranges = {}
            state.begin(batch_id)
            reference.begin(batch_id)
            try:
                # 원본 전체를 모으지 않고 한 파티션씩 순회한다. 적재 전 바이트를 대조한다.
                for row, verified in self.verified_rows(dataframe):
                    raw = bytes(row.value) if row.value is not None else None
                    # 서로 독립적으로 파싱·추출해 원본과 소비 결과의 최소 관측도 비교한다.
                    from user_flow.events import decode, project
                    event = decode(raw)
                    if event['eventType'] != 'capture_chunk' and project(event) != project(decode(verified)):
                        raise VerificationPending('원본 관측 재계산 불일치')
                    state.feed(raw, batch_id, now, now - self.config.retention - self.config.grace)
                    reference.feed(verified, batch_id, now, now - self.config.retention - self.config.grace)
                    key = (row.topic, row.partition)
                    r = ranges.setdefault(key, {'topic': row.topic, 'partition': row.partition, 'start': row.offset, 'end': row.offset + 1})
                    r['start'] = min(r['start'], row.offset); r['end'] = max(r['end'], row.offset + 1)
                state.finish(batch_id, list(ranges.values()))
                reference.finish(batch_id, list(ranges.values()))
                state.db.execute("INSERT OR IGNORE INTO meta VALUES ('coverageStart',?)", (json.dumps(now),))
                state.db.commit()
                self.failed = False
                self._publish(state)
            except Exception as exc:
                self.failed = True
                self.target.flow_health.replace_one({'_id': 'pipeline'}, {'_id': 'pipeline', 'status': 'blocked',
                    'checkedAt': iso(self.clock()), 'errorClass': type(exc).__name__}, upsert=True)
                raise RuntimeError('사용자 흐름 검증 실패: 공개 보류, 체크포인트 재시작 필요') from None
            finally:
                reference.close()
                state.close()

    def tick(self):
        with self.lock:
            if self.failed:
                return
            state = self.state()
            try:
                self._publish(state)
            finally:
                state.close()

    def _publish(self, state):
        now = self.clock()
        if not state.ready():
            self.target.flow_health.replace_one({'_id': 'pipeline'}, {'_id': 'pipeline', 'status': 'waiting_chunks',
                'checkedAt': iso(now), 'pendingSeconds': state.pending_age(now)}, upsert=True)
            return
        if not state.db.execute('SELECT 1 FROM batches WHERE complete=1 LIMIT 1').fetchone():
            return
        state.prune(now, self.config.retention, self.config.grace, self.config.presence)
        rows = state.observations()
        reference = State(str(self.reference_path), max_events=self.config.max_events)
        try:
            if not reference.ready():
                raise VerificationPending('원본 재계산 상태 미완료')
            reference.prune(now, self.config.retention, self.config.grace, self.config.presence)
            expected = calculate(reference.observations(), now, self.config.presence, self.config.retention)
            if calculate(rows, now, self.config.presence, self.config.retention) != expected:
                raise VerificationPending('원본 재계산 지표 불일치')
        finally:
            reference.close()
        contexts = {r['attempt']: (r['simulation'], r['show'], r['schedule']) for r in rows
                    if r['attempt'] and r['simulation'] is not None}
        for row in rows:
            if row['attempt'] in contexts:
                row['simulation'], row['show'], row['schedule'] = contexts[row['attempt']]
        # 관측된 차원만 제공한다. all 외에 완전 일치 차원을 제공하며 임의 조합은 생성하지 않는다.
        scopes = {'all': rows}
        dimensions = {(r['simulation'], r['show'], r['schedule']) for r in rows}
        for (key,) in state.db.execute("SELECT key FROM meta WHERE key LIKE 'history:%'"):
            prior_scope = key[len('history:'):]
            if prior_scope != 'all':
                dimensions.add(tuple(json.loads(prior_scope)))
        for simulation, show, schedule in dimensions:
            key = json.dumps([simulation, show, schedule], separators=(',', ':'))
            scopes[key] = [r for r in rows if (r['simulation'], r['show'], r['schedule']) == (simulation, show, schedule)]
        if len(scopes) > 100:
            raise RuntimeError('차원 수 제한 초과')
        for scope, values in scopes.items():
            calculated_at = self.clock()
            metrics = calculate(values, now, self.config.presence, self.config.retention)
            metrics['calculatedAt'] = iso(calculated_at)
            metrics['latestReceivedAt'] = iso(max(r['received'] for r in values)) if values else None
            coverage = state.db.execute("SELECT value FROM meta WHERE key='coverageStart'").fetchone()
            coverage_start = json.loads(coverage[0]) if coverage else now
            metrics['liveCoverageStart'] = iso(coverage_start)
            key = 'history:' + scope
            prior = state.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            history = json.loads(prior[0]) if prior else []
            at = int(now // 5) * 5
            history = [h for h in history if now - self.config.retention <= h['epoch'] and h['epoch'] != at]
            history.append({'epoch': at, 'at': iso(at), 'asOf': iso(now), 'current': metrics['current'], 'observed': True})
            # 중단 구간을 0으로 채우지 않는다. 12시간 격자에서 명시적 미관측값으로 제공한다.
            from user_flow.events import stamp
            first = (int((now-self.config.retention)//5)+1)*5
            grid = range(first, at+1, 5)
            known_presence = {h['epoch']: h for h in history}
            metrics['presenceSeries'] = [known_presence.get(t, {'at': iso(t), 'current': None, 'observed': False}) for t in grid]
            known_booking = {int(stamp(h['at'])): h for h in metrics['bookingSeries']}
            metrics['bookingSeries'] = [known_booking.get(t, {'at': iso(t), 'numerator': 0 if t >= coverage_start else None,
                'denominator': 0 if t >= coverage_start else None, 'ratio': None,
                'ongoing': 0 if t >= coverage_start else None, 'observed': t >= coverage_start}) for t in grid]
            metrics['scope'] = scope
            metrics['verifiedAt'] = iso(self.clock())
            # 공개 시각은 기준 시각과 달리 실제 저장 직전의 시각이다.
            publish(self.target, metrics, state.ranges(), self.clock(), scope, self.config.retention, 30)
            state.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(history)))
            state.db.commit()
        self.target.flow_health.replace_one({'_id': 'pipeline'}, {'_id': 'pipeline', 'status': 'verified',
            'checkedAt': iso(self.clock()), 'processingSeconds': self.clock() - now}, upsert=True)
        cleanup_unpublished(self.target, self.clock())


def run():
    from configuration.user_flow import FlowConfig
    from pyspark.sql import SparkSession
    config = FlowConfig.load()
    spark = SparkSession.builder.appName('ticketguard-user-flow').config('spark.sql.session.timeZone', 'UTC').getOrCreate()
    if not spark.sparkContext.master.startswith('local['):
        raise ValueError('현재 상태 저장 구현은 단일 로컬 Spark만 지원한다')
    raw = connection(config.raw_uri, config.timeout_ms); target = connection(config.target_uri, config.timeout_ms)
    processor = Processor(config, raw.get_default_database(), target.get_default_database())
    indexes(target.get_default_database())
    stop = threading.Event()
    def ticker():
        while not stop.wait(config.interval):
            try:
                processor.tick()
            except Exception as exc:
                processor.failed = True
                try:
                    processor.target.flow_health.replace_one({'_id': 'pipeline'}, {'_id': 'pipeline',
                        'status': 'blocked', 'errorClass': type(exc).__name__, 'checkedAt': iso(time.time())}, upsert=True)
                except Exception:
                    pass
                print('flow tick_failed error_class=' + type(exc).__name__, flush=True)
    thread = threading.Thread(target=ticker, daemon=True); query = None
    try:
        source = (spark.readStream.format('kafka').option('kafka.bootstrap.servers', config.kafka)
                  .option('kafka.group.id', config.group).option('subscribe', config.topic)
                  .option('startingOffsets', 'earliest').option('failOnDataLoss', 'true')
                  .option('maxOffsetsPerTrigger', config.max_offsets).load())
        query = (source.writeStream.foreachBatch(processor.batch).option('checkpointLocation', str(Path(config.checkpoint) / 'spark'))
                 .trigger(processingTime=f'{config.interval} seconds').start())
        thread.start(); query.awaitTermination()
    finally:
        stop.set()
        if query is not None: query.stop()
        if thread.is_alive(): thread.join(timeout=10)
        raw.close(); target.close(); spark.stop()
