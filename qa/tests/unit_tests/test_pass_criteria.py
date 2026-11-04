from ticket_guard_qa.domain.pass_criteria import PASS_CRITERIA, evaluate_pass_criteria


def test_seven_pass_criteria():
    assert len(PASS_CRITERIA) == 7


def test_unmeasured_criteria_are_not_judged():
    results = {result.criterion_id: result for result in evaluate_pass_criteria({"api_latency_p95_sec": 3.0})}
    assert results["api_latency"].is_passed is True  # 3초 이하
    assert results["gold_latency"].is_passed is None


def test_at_least_and_at_most():
    results = {
        result.criterion_id: result
        for result in evaluate_pass_criteria({
            "bot_abd_detection_rate_percent": 89.9,
            "human_false_positive_rate_percent": 1.0,
        })
    }
    assert results["bot_abd_detection"].is_passed is False
    assert results["human_false_positive"].is_passed is True
