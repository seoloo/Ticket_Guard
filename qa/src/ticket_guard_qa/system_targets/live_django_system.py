"""지금의 Django 시스템에 HTTP로 접속 · 시스템 코드 import 금지"""
from dataclasses import dataclass
from typing import Any

import httpx

from ticket_guard_qa.domain.models import (
    LiveMetrics,
    SessionBehavior,
    SessionKey,
    SessionVerdictRecord,
    SystemVerdicts,
    VirtualUserSessionResult,
)
from ticket_guard_qa.system_targets.live_booking_client import (
    BookingFlowError,
    LiveBookingClient,
    build_test_account_username,
)
from ticket_guard_qa.system_targets.target_interfaces import HttpResult

HEALTH_CHECK_TIMEOUT_SEC = 1.5  # 화면 헤더용 · 오래 기다리지 않음


@dataclass(frozen=True)
class VirtualUserAccountPool:
    """시스템 테스트 훅 시험 계정 · qa-user-0001 ~ · 꺼져 있으면 count 0"""
    count: int
    password: str
    captcha_answer: str


class AccountPoolExhaustedError(RuntimeError):
    pass


class LiveDjangoBookingApi:
    def __init__(self, base_url: str, username: str, password: str,
                 test_accounts: VirtualUserAccountPool | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.test_accounts = test_accounts or VirtualUserAccountPool(0, "", "")
        self.transport = transport
        self.contract_client: LiveBookingClient | None = None  # 계약 시험 · 개발 계정 한 개
        self.used_test_account_count = 0  # VU마다 다음 번호 · 계정당 진행 중 예매 1건

    def check_health(self) -> bool:
        try:
            with httpx.Client(base_url=self.base_url, transport=self.transport) as http_client:
                return http_client.get("/health/", timeout=HEALTH_CHECK_TIMEOUT_SEC).status_code == 200
        except httpx.HTTPError:
            return False

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult:
        if self.contract_client is None:
            contract_client = LiveBookingClient(self.base_url, self.transport)
            contract_client.login(self.username, self.password)
            self.contract_client = contract_client
        return self.contract_client.post_json("/api/events/", event)

    def start_virtual_user_session(self, behavior: SessionBehavior) -> VirtualUserSessionResult:
        """시험 계정 하나로 좌석 선택 단계까지 · 행동 값(진입 지연 · 클릭 간격) 적용은 1-c"""
        if self.used_test_account_count >= self.test_accounts.count:
            raise AccountPoolExhaustedError(
                f"시험 계정 부족 · {self.test_accounts.count}개 · 저장소 .env QA_TEST_ACCOUNT_COUNT 확인"
            )
        self.used_test_account_count += 1
        username = build_test_account_username(self.used_test_account_count)
        client = LiveBookingClient(self.base_url, self.transport)
        try:
            flow_result = client.run_until_seat_selection(username, self.test_accounts.password, self.test_accounts.captcha_answer)
        except (BookingFlowError, httpx.HTTPError):
            return VirtualUserSessionResult(SessionKey(f"failed-{username}"), latency_ms=0.0, is_error=True)
        finally:
            client.close()
        return VirtualUserSessionResult(SessionKey(flow_result.booking_attempt_id), flow_result.total_latency_ms, is_error=False)


class LiveDjangoVerdictReader:
    def read_session_verdicts(self, run_id: str) -> SystemVerdicts:
        # TODO(판정 구현 후): 시스템 판정 결과 읽기 · AGENTS.md 11장
        raise NotImplementedError("시스템 판정 없음 · AGENTS.md 5장")

    def read_verdict_records(self, run_id: str) -> list[SessionVerdictRecord]:
        raise NotImplementedError("시스템 판정 없음 · AGENTS.md 5장")


class LiveDjangoLiveMetricsReader:
    def read_live_metrics(self, run_id: str, elapsed_sec: float) -> LiveMetrics:
        # TODO(트래픽 생성기 · MongoDB 연결 후): Locust 통계 · Gold 반영 시각에서 계산
        raise NotImplementedError("실시간 수치 없음 · AGENTS.md 5장")


class LiveDockerProcessControl:
    def stop_service(self, service_name: str) -> None:
        # TODO(파이프라인 연결 후): Docker SDK로 컨테이너 중지
        raise NotImplementedError("복구할 파이프라인 없음 · AGENTS.md 5장")

    def start_service(self, service_name: str) -> None:
        # TODO(파이프라인 연결 후): Docker SDK로 컨테이너 시작
        raise NotImplementedError("복구할 파이프라인 없음 · AGENTS.md 5장")
