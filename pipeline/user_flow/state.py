"""단일 로컬 Spark 실행용 복구 상태. 원본 대신 검증된 최소 관측과 청크만 보존한다."""
import hashlib
import json
import sqlite3
from pathlib import Path
from user_flow.events import chunk_part, decode, project


class State:
    def __init__(self, path, max_events=250000, max_chunks=4096):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, time REAL, payload TEXT, batch INTEGER);
          CREATE INDEX IF NOT EXISTS events_time ON events(time);
          CREATE TABLE IF NOT EXISTS chunks(record TEXT, idx INTEGER, meta TEXT, data BLOB, seen REAL,
             PRIMARY KEY(record,idx));
          CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, complete INTEGER, ranges TEXT);
          CREATE TABLE IF NOT EXISTS assembled(record TEXT PRIMARY KEY, meta TEXT, seen REAL);
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        ''')
        self.db.commit()
        self.max_events = max_events; self.max_chunks = max_chunks

    def close(self):
        self.db.close()

    def begin(self, batch):
        self.db.execute('INSERT OR IGNORE INTO batches VALUES (?,0,?)', (batch, '[]'))
        self.db.commit()

    def feed(self, raw, batch, now, oldest, future_seconds=30):
        e = decode(raw)
        if e['eventType'] == 'capture_chunk':
            d, data = chunk_part(e)
            meta = json.dumps({k: d[k] for k in ('recordId', 'count', 'totalBytes', 'sha256')}, sort_keys=True)
            completed = self.db.execute('SELECT meta FROM assembled WHERE record=?', (d['recordId'],)).fetchone()
            if completed:
                if completed[0] != meta:
                    raise ValueError('완료된 청크 메타데이터 충돌')
                return None
            prior = self.db.execute('SELECT idx,meta,data FROM chunks WHERE record=?', (d['recordId'],)).fetchall()
            if any(m != meta or (i == d['index'] and bytes(v) != data) for i, m, v in prior):
                raise ValueError('청크 충돌')
            self.db.execute('INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?)', (d['recordId'], d['index'], meta, data, now))
            count = self.db.execute('SELECT count(*) FROM chunks').fetchone()[0]
            if count > self.max_chunks:
                raise ValueError('청크 상태 용량 초과')
            parts = self.db.execute('SELECT data FROM chunks WHERE record=? ORDER BY idx', (d['recordId'],)).fetchall()
            if len(parts) < d['count']:
                self.db.commit(); return None
            joined = b''.join(bytes(p[0]) for p in parts)
            if len(joined) != d['totalBytes'] or hashlib.sha256(joined).hexdigest() != d['sha256']:
                raise ValueError('청크 무결성 오류')
            e = decode(joined)
            if e['eventId'] != d['recordId'] or e['eventType'] == 'capture_chunk':
                raise ValueError('청크 식별자 오류')
            self.db.execute('DELETE FROM chunks WHERE record=?', (d['recordId'],))
            self.db.execute('INSERT INTO assembled VALUES (?,?,?)', (d['recordId'], meta, now))
        p = project(e)
        if p['time'] > now + future_seconds:
            raise ValueError('미래 시각 허용 범위 초과')
        if p['time'] < oldest:
            raise ValueError('상태 보존 범위를 넘은 이벤트: 별도 재계산 필요')
        previous = self.db.execute('SELECT payload FROM events WHERE id=?', (p['id'],)).fetchone()
        if previous and json.loads(previous[0])['fingerprint'] != p['fingerprint']:
            raise ValueError('동일 이벤트 식별자의 내용 충돌')
        self.db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?)', (p['id'], p['time'], json.dumps(p), batch))
        if self.db.execute('SELECT count(*) FROM events').fetchone()[0] > self.max_events:
            raise ValueError('계산 상태 용량 초과')
        self.db.commit()
        return p

    def finish(self, batch, ranges):
        self.db.execute('UPDATE batches SET complete=1,ranges=? WHERE id=?', (json.dumps(ranges), batch))
        previous = self.db.execute("SELECT value FROM meta WHERE key='ranges'").fetchone()
        merged = {(r['topic'], r['partition']): r for r in json.loads(previous[0])} if previous else {}
        for r in ranges:
            old = merged.setdefault((r['topic'], r['partition']), dict(r))
            old['start'] = min(old['start'], r['start']); old['end'] = max(old['end'], r['end'])
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('ranges',?)", (json.dumps(list(merged.values())),))
        self.db.commit()

    def ready(self):
        return not self.db.execute('SELECT 1 FROM batches WHERE complete=0 LIMIT 1').fetchone() and not self.db.execute('SELECT 1 FROM chunks LIMIT 1').fetchone()

    def observations(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM events ORDER BY time,id')]

    def ranges(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='ranges'").fetchone()
        return json.loads(row[0]) if row else []

    def prune(self, now, retention, grace, presence):
        # 진행 중 단계를 잃지 않도록 삭제 경계 이전의 대상별 마지막 관측은 유지한다.
        boundary = now - retention - grace
        self.db.execute('''DELETE FROM events WHERE time<?
            AND coalesce(json_extract(payload,'$.actor'),'') NOT IN (
              SELECT json_extract(payload,'$.actor') FROM events WHERE time>=?
              AND json_extract(payload,'$.actor') IS NOT NULL)''', (boundary, now - presence - grace))
        self.db.execute('DELETE FROM batches WHERE complete=1 AND id < (SELECT max(id)-10000 FROM batches)')
        self.db.execute('DELETE FROM assembled WHERE seen<?', (boundary,))
        self.db.commit()

    def pending_age(self, now):
        first = self.db.execute('SELECT min(seen) FROM chunks').fetchone()[0]
        return now - first if first is not None else 0
