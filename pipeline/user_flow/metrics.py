"""검증된 최소 관측값으로 최근 12시간의 그래프와 수치를 계산한다."""
"""
[홍석환] 최근 한 시간 사용자 흐름 계산
기존 설명의 12시간은 이전 기준이며 기본 집계 범위는 현재 한 시간이다.
"""
from collections import defaultdict
from statistics import mean, median
from user_flow.events import STAGES, LABELS, iso


def ratio(n, d):
    return {'numerator': n, 'denominator': d, 'ratio': n / d if d else None}


def calculate(observations, now, presence_seconds=30, retention=3600, bucket=5):
    rows = sorted((r for r in observations if r['time'] <= now), key=lambda r: (r['time'], r['id']))
    cutoff = now - retention
    # 같은 브라우저의 시작 전 화면은 다음 시작 시도에만 연결한다. 브라우저 간 추정 연결은 하지 않는다.
    starts_by_actor = defaultdict(list)
    for r in rows:
        if r['actor'] and r['start'] and r['attempt']:
            if not any(a == r['attempt'] for _, a in starts_by_actor[r['actor']]):
                starts_by_actor[r['actor']].append((r['time'], r['attempt']))
    visits = defaultdict(list); attempts = {}; people = {}; samples = defaultdict(list)
    reached = defaultdict(set); transitions = defaultdict(set); pending = defaultdict(set)
    cancelled = set(); interrupted = set()
    for r in rows:
        a = r['attempt']
        if a:
            item = attempts.setdefault(a, {'start': None, 'success': None, 'last': r['time'], 'terminal': False})
            item['last'] = max(item['last'], r['time'])
            if r['start']:
                item['start'] = min(item['start'], r['time']) if item['start'] is not None else r['time']
            if r['success']:
                item['success'] = r['time']; item['terminal'] = True
            if r['cancel'] or r['timeout']:
                item['terminal'] = True
        actor = r['actor']
        if not actor:
            continue
        p = people.setdefault(actor, {'stage': 'other', 'last': r['time'], 'active': False, 'view': None})
        expired = r['time'] - p['last'] >= presence_seconds
        if expired and visits[actor] and visits[actor][-1]['end'] is None:
            visits[actor][-1]['interrupted'] = True
        p['last'] = r['time']
        # 늦게 도착한 이전 화면의 종료로 새 화면을 닫지 않는다.
        if r['exit'] and r['view'] and p['view'] and r['view'] != p['view']:
            continue
        if r['stage'] is not None:
            stage = r['stage']
            next_start = next((attempt for t, attempt in starts_by_actor[actor] if t >= r['time']), None)
            unit = a or next_start or actor
            history = visits[actor]
            changed = expired or not history or history[-1]['stage'] != stage or history[-1].get('interrupted') or (r['kind'] == 'page_enter' and r['view'] != history[-1]['view'])
            if changed:
                if history:
                    if history[-1]['end'] is None and not history[-1].get('interrupted'):
                        history[-1]['end'] = r['time']
                    previous = history[-1]
                    if previous['start'] >= cutoff and not previous.get('interrupted'):
                        transitions[(previous['stage'], stage)].add(previous['unit'])
                history.append({'stage': stage, 'start': r['time'], 'end': None, 'unit': unit, 'view': r['view']})
            p.update(stage=stage, view=r['view'] or p['view'])
        p['active'] = not (r['exit'] or r['cancel'] or r['timeout'])
        if r['exit'] or r['cancel']:
            if visits[actor] and visits[actor][-1]['end'] is None:
                visits[actor][-1]['end'] = r['time']
            if visits[actor] and r['cancel']:
                transitions[(visits[actor][-1]['stage'], 'cancelled')].add(visits[actor][-1]['unit'])
        if r['cancel']: cancelled.add(a or actor)
        if r['timeout']: interrupted.add(a or actor)
    for actor, history in visits.items():
        for v in history:
            if v['start'] < cutoff:
                continue
            reached[v['stage']].add(v['unit'])
            if v['end'] is not None:
                samples[v['stage']].append(max(0, v['end'] - v['start']))
            elif v is history[-1] and not v.get('interrupted') and people[actor]['active'] and now - people[actor]['last'] < presence_seconds:
                pending[v['stage']].add(v['unit'])
    active = [p for p in people.values() if p['active'] and now - p['last'] < presence_seconds]
    nodes = []
    for order, (stage, label) in enumerate(zip(STAGES, LABELS)):
        values = samples[stage]
        nodes.append({'id': stage, 'label': label, 'order': order,
                      'current': sum(p['stage'] == stage for p in active),
                      'dwell': {'meanSeconds': mean(values) if values else None,
                                'medianSeconds': median(values) if values else None, 'samples': len(values)},
                      'ongoing': len(pending[stage]), 'entered': len(reached[stage])})
    edge_keys = set(transitions) | set(zip(STAGES[:5], STAGES[1:6]))
    edges = []
    for src, dst in sorted(edge_keys):
        units = transitions[(src, dst)] & reached[src]
        kind = 'cancel' if dst == 'cancelled' else ('retry' if src == dst else ('forward' if STAGES.index(dst) > STAGES.index(src) else 'backward'))
        edges.append({'source': src, 'target': dst, 'kind': kind, 'moves': len(units),
                      **ratio(len(units), len(reached[src])), 'ongoing': len(pending[src])})
    cohort = [a for a in attempts.values() if a['start'] is not None and cutoff <= a['start'] <= now]
    buckets = defaultdict(list)
    for a in cohort:
        buckets[int(a['start'] // bucket) * bucket].append(a)
    series = [{'at': iso(t), **ratio(sum(a['success'] is not None for a in group), len(group)),
               'ongoing': sum(not a['terminal'] and now - a['last'] < presence_seconds for a in group),
               'observed': True} for t, group in sorted(buckets.items())]
    return {'contractVersion': 1, 'calculationVersion': 1, 'asOf': iso(now), 'windowStart': iso(cutoff),
            'countingUnit': 'browser_session', 'presenceTimeoutSeconds': presence_seconds,
            'nodes': nodes, 'edges': edges, 'current': len(active),
            'booking': ratio(sum(a['success'] is not None for a in cohort), len(cohort)),
            'bookingSeries': series, 'cancelled': len(cancelled), 'interrupted': len(interrupted)}
