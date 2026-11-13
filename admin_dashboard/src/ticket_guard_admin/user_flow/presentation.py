"""
[홍석환] 공개 지표의 화면 표시 형식 변환
저장된 계산값을 유지하며 단위·한국 시각·최근 12시간 시계열을 구성한다.
"""
import json
from datetime import datetime, timedelta, timezone

from .contracts import moment

KST = timezone(timedelta(hours=9))


def korean_time(value):
    return moment(value).astimezone(KST).strftime('%Y.%m.%d %H:%M:%S KST')


def scope_label(value):
    if value == 'all':
        return '전체 공개 지표'
    simulation, show, schedule = json.loads(value)
    kind = '시뮬레이션' if simulation is True else '일반' if simulation is False else '구분 미확인'
    return f'{kind} · 공연 {show or "미기록"} · 회차 {schedule or "미기록"}'


def for_display(result, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=12)
    m = result['metrics']; h = result['history']
    nodes = [dict(id=n['id'], label=n['label'], order=n['order'], current=n['current'], entered=n['entered'],
                  ongoing=n['ongoing'], mean=n['dwell']['meanSeconds'], median=n['dwell']['medianSeconds'],
                  samples=n['dwell']['samples']) for n in sorted(m['nodes'], key=lambda n: n['order'])]
    def series(name):
        points = []
        for p in sorted(h[name], key=lambda point: moment(point['at'])):
            if not cutoff <= moment(p['at']) <= now:
                continue
            item = dict(at=moment(p['at']).isoformat(), observed=p['observed'])
            if name == 'presence':
                item['value'] = p.get('current')
            else:
                item.update(value=p['ratio'], numerator=p['numerator'], denominator=p['denominator'], ongoing=p.get('ongoing'))
            points.append(item)
        return points
    return dict(current=m['current'], starts=m['booking']['denominator'], completed=m['booking']['numerator'],
                ratio=m['booking']['ratio'], nodes=nodes, edges=[dict(e) for e in m['edges']], secondary=[],
                presence=series('presence'), booking=series('booking'), count_unit='개', counting_label='브라우저 세션',
                presence_note=f"브라우저 세션 단위 · 최근 {m['presenceTimeoutSeconds']}초 활동 신호 기준 추정",
                as_of_label=korean_time(m['asOf']), window_label=f"{korean_time(m['windowStart'])} ~ {korean_time(m['asOf'])}",
                published_label=korean_time(result['published_at']), version=result['version'],
                chart_range={'start': cutoff.isoformat(), 'end': now.isoformat()})
