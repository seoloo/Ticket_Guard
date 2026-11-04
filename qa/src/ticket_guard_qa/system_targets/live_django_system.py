"""지금의 Django 시스템에 HTTP로 접속 · 시스템 코드 import 금지"""
import time
from typing import Any

import httpx

from ticket_guard_qa.domain.models import LiveMetrics, SessionBehavior, SessionVerdictRecord, SystemVerdicts, VirtualUserSessionResult
from ticket_guard_qa.system_targets.target_interfaces import HttpResult

CSRF_COOKIE_NAME = "csrftoken"
REQUEST_TIMEOUT_SEC = 5.0
HEALTH_CHECK_TIMEOUT_SEC = 1.5  # 화면 헤더용 · 오래 기다리지 않음


class LiveDjangoBookingApi:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.http_client = httpx.Client(base_url=self.base_url, timeout=REQUEST_TIMEOUT_SEC)
        self.is_logged_in = False

    def check_health(self) -> bool:
        try:
            return self.http_client.get("/health/", timeout=HEALTH_CHECK_TIMEOUT_SEC).status_code == 200
        except httpx.HTTPError:
            return False

    def submit_browser_event(self, event: dict[str, Any]) -> HttpResult:
        self._ensure_logged_in()
        return self._post_json("/api/events/", event)

    def start_virtual_user_session(self, behavior: SessionBehavior) -> VirtualUserSessionResult:
        # TODO(시험 계정 여러 개 생긴 후): 로그인 → 공연 상세 → 대기열 → 확정 · bookingAttemptId 받기
        raise NotImplementedError("개발 계정 2개뿐 · 트래픽 생성기 미구현 · AGENTS.md 5장")

    def _ensure_logged_in(self) -> None:
        if self.is_logged_in:
            return
        self.http_client.get("/login/")  # csrftoken 쿠키 받기
        login_result = self._post_json(
            "/api/action/", {"action": "login", "username": self.username, "password": self.password}
        )
        if login_result.status_code != 200:
            raise RuntimeError(f"시스템 로그인 실패 · HTTP {login_result.status_code}")
        self.is_logged_in = True

    def _post_json(self, path: str, payload: dict[str, Any]) -> HttpResult:
        headers = {"X-CSRFToken": self.http_client.cookies.get(CSRF_COOKIE_NAME, "")}
        started_at = time.perf_counter()
        response = self.http_client.post(path, json=payload, headers=headers)
        latency_ms = (time.perf_counter() - started_at) * 1000
        try:
            body = response.json()
        except ValueError:
            body = {}
        return HttpResult(response.status_code, body, latency_ms)


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
