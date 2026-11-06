"""지연 · 오류율 계산"""
import math


def calculate_p95(values: list[float]) -> float:
    if not values:
        raise ValueError("p95 계산 값 없음")
    sorted_values = sorted(values)
    rank = math.ceil(0.95 * len(sorted_values))  # p95 = nearest-rank
    return sorted_values[rank - 1]


def calculate_error_rate_percent(total_request_count: int, failed_request_count: int) -> float:
    if total_request_count == 0:
        return 0.0
    return failed_request_count / total_request_count * 100
