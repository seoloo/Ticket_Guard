import pytest

from ticket_guard_qa.scoring.latency_metrics import calculate_error_rate_percent, calculate_p95


def test_p95_uses_nearest_rank():
    assert calculate_p95([float(value) for value in range(1, 101)]) == 95.0
    assert calculate_p95([2.0, 3.5, 4.0, 6.5, 8.0]) == 8.0


def test_p95_without_values_is_error():
    with pytest.raises(ValueError):
        calculate_p95([])


def test_error_rate_percent():
    assert calculate_error_rate_percent(200, 1) == 0.5
    assert calculate_error_rate_percent(0, 0) == 0.0
