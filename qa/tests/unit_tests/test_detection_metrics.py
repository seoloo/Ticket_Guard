from ticket_guard_qa.domain.enums import ActorType, VerdictStage
from ticket_guard_qa.domain.models import SessionKey
from ticket_guard_qa.scoring.confusion_matrix import build_confusion_matrix
from ticket_guard_qa.scoring.detection_metrics import (
    calculate_detection_metrics,
    find_false_positives,
    find_missed_bots,
)

HUMAN_SESSION = SessionKey("human-1")
CAUGHT_BOT_SESSION = SessionKey("bot-a-1")
MISSED_BOT_SESSION = SessionKey("bot-b-1")
UNJUDGED_BOT_SESSION = SessionKey("bot-d-1")

ANSWER_KEY = {
    HUMAN_SESSION: ActorType.HUMAN,
    CAUGHT_BOT_SESSION: ActorType.BOT_A,
    MISSED_BOT_SESSION: ActorType.BOT_B,
    UNJUDGED_BOT_SESSION: ActorType.BOT_D,
}
SYSTEM_VERDICTS = {
    HUMAN_SESSION: VerdictStage.CHALLENGE,
    CAUGHT_BOT_SESSION: VerdictStage.HOLD,
    MISSED_BOT_SESSION: VerdictStage.OBSERVE,
}


def test_challenge_or_higher_counts_as_detected():
    assert not VerdictStage.OBSERVE.is_detected
    assert VerdictStage.CHALLENGE.is_detected


def test_missing_verdict_counts_as_missed():
    assert set(find_missed_bots(ANSWER_KEY, SYSTEM_VERDICTS)) == {MISSED_BOT_SESSION, UNJUDGED_BOT_SESSION}
    assert find_false_positives(ANSWER_KEY, SYSTEM_VERDICTS) == [HUMAN_SESSION]


def test_detection_metrics_use_pass_criteria_names():
    metrics = calculate_detection_metrics(ANSWER_KEY, SYSTEM_VERDICTS)
    assert round(metrics["bot_abd_detection_rate_percent"], 2) == 33.33
    assert metrics["human_false_positive_rate_percent"] == 100.0
    assert "bot_c_detection_rate_percent" not in metrics  # 봇 C 없음 = 측정 안 됨


def test_confusion_matrix_puts_missing_verdict_in_normal():
    matrix = build_confusion_matrix(ANSWER_KEY, SYSTEM_VERDICTS)
    assert matrix[ActorType.BOT_D][VerdictStage.NORMAL] == 1
