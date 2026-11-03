"""사람 · 봇 A · B · D 트래픽 · locust -f traffic_generators/locust_traffic.py · load 묶음 설치 필요"""
from locust import HttpUser, between, task

from ticket_guard_qa.domain.enums import ActorType


class HumanUser(HttpUser):
    actor_type = ActorType.HUMAN
    wait_time = between(1, 3)

    @task
    def browse_and_book(self) -> None:
        # TODO(시험 계정 여러 개 생긴 후): 로그인 → 공연 상세 → 대기열 → 좌석 선택 → 확정
        raise NotImplementedError("개발 계정 2개뿐 · AGENTS.md 5장")


class BotAUser(HumanUser):
    actor_type = ActorType.BOT_A
    wait_time = between(0.05, 0.1)  # 오픈 즉시형


class BotBUser(HumanUser):
    actor_type = ActorType.BOT_B
    wait_time = between(0.37, 0.43)  # 사람 흉내형 · 편차 작음


class BotDUser(HumanUser):
    actor_type = ActorType.BOT_D
    wait_time = between(0.13, 0.17)  # 다중 세션
