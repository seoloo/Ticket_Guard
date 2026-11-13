"""
[홍석환] 사용자 흐름 공개 계약 검사
버전·필드·수치·식별자·시각을 검사하고 오류를 안전한 상태로 구분한다.
"""
import json
import math
from datetime import datetime


class FlowError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def invalid():
    raise FlowError('invalid_contract', '공개 지표 형식 오류 · 저장 계약과 필수 필드·단위를 확인해 주세요.')


def scope_key(value):
    if value == 'all':
        return value
    try:
        decoded = json.loads(value)
        if not isinstance(decoded, list) or len(decoded) != 3:
            raise ValueError()
        if decoded[0] is not None and type(decoded[0]) is not bool:
            raise ValueError()
        if any(v is not None and (not isinstance(v, str) or not 1 <= len(v) <= 100) for v in decoded[1:]):
            raise ValueError()
        return json.dumps(decoded, separators=(',', ':'))
    except (ValueError, TypeError):
        raise FlowError('unsupported_filter', '지원하지 않는 조회 범위 · 전체 또는 공개된 시뮬레이션·공연·회차 조합을 선택해 주세요.') from None


def moment(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError()
        return dt
    except (ValueError, TypeError, AttributeError, OverflowError):
        invalid()


def count(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2**53-1:
        invalid()
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        invalid()
    return value


def text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        invalid()
    return value


def proportion(item, allow_unobserved=False):
    if not isinstance(item, dict):
        invalid()
    if not {'numerator', 'denominator', 'ratio'} <= item.keys():
        invalid()
    if allow_unobserved and item.get('observed') is False:
        if any(item.get(key) is not None for key in ('numerator', 'denominator', 'ratio')):
            invalid()
        return
    n = count(item['numerator']); d = count(item['denominator']); r = item['ratio']
    if n > d or (d == 0 and r is not None):
        invalid()
    if d:
        number(r)
        if r > 1 or not math.isclose(r, n/d, rel_tol=1e-8, abs_tol=1e-10):
            invalid()


def validate(current, series, scope):
    try:
        for wrapper in (current, series):
            if wrapper['_id'] != scope or wrapper['status'] != 'verified':
                invalid()
            text(wrapper['version']); moment(wrapper['asOf'])
        published = current['result']; history = series['result']; metrics = published['metrics']
        if published['_id'] != current['version'] or published['scope'] != scope or published['status'] != 'verified':
            invalid()
        if history['version'] != current['version'] or history['scope'] != scope:
            invalid()
        moment(published['verifiedAt']); moment(published['publishedAt'])
        if moment(history['publishedAt']) != moment(published['publishedAt']):
            invalid()
        if type(metrics['contractVersion']) is not int or metrics['contractVersion'] != 1:
            invalid()
        if type(metrics['calculationVersion']) is not int or metrics['calculationVersion'] != 1:
            invalid()
        if metrics['countingUnit'] != 'browser_session':
            invalid()
        if moment(metrics['windowStart']) > moment(metrics['asOf']):
            invalid()
        count(metrics['presenceTimeoutSeconds']); count(metrics['current']); proportion(metrics['booking'])
        nodes = metrics['nodes']; edges = metrics['edges']
        if not isinstance(nodes, list) or len(nodes) > 32 or not isinstance(edges, list) or len(edges) > 256:
            invalid()
        ids = {}; orders = set()
        for node in nodes:
            id_ = text(node['id']); text(node['label']); order = count(node['order'])
            if id_ in ids or order in orders:
                invalid()
            ids[id_] = node; orders.add(order)
            for key in ('current', 'entered', 'ongoing'):
                count(node[key])
            dwell = node['dwell']; samples = count(dwell['samples'])
            for key in ('meanSeconds', 'medianSeconds'):
                if samples == 0:
                    if dwell[key] is not None:
                        invalid()
                else:
                    number(dwell[key])
        if sum(n['current'] for n in nodes) != metrics['current']:
            invalid()
        seen = set()
        for edge in edges:
            if edge['kind'] not in ('forward', 'backward', 'retry', 'cancel'):
                invalid()
            if edge['source'] not in ids or (edge['target'] not in ids and not (edge['kind'] == 'cancel' and edge['target'] == 'cancelled')):
                invalid()
            key = (edge['source'], edge['target'], edge['kind'])
            if key in seen:
                invalid()
            seen.add(key); proportion(edge); count(edge['moves']); count(edge['ongoing'])
            if edge['moves'] != edge['numerator'] or edge['denominator'] != ids[edge['source']]['entered']:
                invalid()
        for name in ('presence', 'booking'):
            points = history[name]
            if not isinstance(points, list) or len(points) > 10000:
                invalid()
            observed_times = set()
            for point in points:
                dt = moment(point['at'])
                if dt in observed_times or type(point['observed']) is not bool:
                    invalid()
                observed_times.add(dt)
                if name == 'presence':
                    if 'current' not in point:
                        invalid()
                    if point['observed']:
                        count(point['current'])
                    elif point.get('current') is not None:
                        invalid()
                else:
                    proportion(point, allow_unobserved=True)
                    if point['observed']:
                        count(point['ongoing'])
                    elif point.get('ongoing') is not None:
                        invalid()
        return metrics, history
    except (KeyError, TypeError, AttributeError, OverflowError):
        invalid()
