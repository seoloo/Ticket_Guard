from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.answer_key.expected_verdicts import build_answer_key, plan_virtual_users
from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import SessionKey, TrafficMix


def test_plan_matches_traffic_mix():
    planned_users = plan_virtual_users(TrafficMix(), virtual_user_count=200, random_seed=1)
    human_count = sum(1 for user in planned_users if user.actor_type is ActorType.HUMAN)
    assert len(planned_users) == 200
    assert human_count == 160


def test_labels_do_not_reveal_bots():
    planned_users = plan_virtual_users(TrafficMix(), virtual_user_count=50, random_seed=1)
    assert all(user.virtual_user_label.startswith("qa-") for user in planned_users)
    assert all("bot" not in user.virtual_user_label.lower() for user in planned_users)


def test_same_seed_gives_same_plan():
    first_plan = plan_virtual_users(TrafficMix(), virtual_user_count=50, random_seed=7)
    second_plan = plan_virtual_users(TrafficMix(), virtual_user_count=50, random_seed=7)
    assert first_plan == second_plan


def test_answer_key_round_trip(qa_database):
    planned_users = plan_virtual_users(TrafficMix(), virtual_user_count=10, random_seed=1)
    session_key_by_label = {user.virtual_user_label: SessionKey(f"attempt-{index}") for index, user in enumerate(planned_users)}
    answer_key = build_answer_key(planned_users, session_key_by_label)

    repository = AnswerKeyRepository(qa_database)
    repository.save("run-test", answer_key)
    assert repository.load("run-test") == answer_key
