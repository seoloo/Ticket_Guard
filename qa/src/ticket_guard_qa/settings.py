"""설정 한 곳 · 환경 변수 TICKET_GUARD_QA_* → Settings"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from ticket_guard_qa.domain.enums import TargetKind

QA_ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TICKET_GUARD_QA_", env_file=".env", extra="ignore")

    target_kind: TargetKind = TargetKind.FAKE

    system_base_url: str = "http://127.0.0.1:8000"
    system_username: str = ""
    system_password: str = ""
    system_mongo_uri: str = ""  # 읽기 전용 계정만
    system_raw_mongo_uri: str = ""  # 원본 MongoDB ticketguard_raw · 읽기 전용 계정만 · 비우면 원본 적재 검증 건너뜀
    # 이벤트 토픽 읽기 전용 · QA 대시보드는 팀 compose 안에서만 실행 · 비우면 이벤트 전달 검증 건너뜀
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_events_topic: str = "ticketguard.events.v1"
    is_kafka_contract_injection_enabled: bool = False  # 토픽 계약 사례 · 시험 환경 토픽에 직접 주입 · 기본 꺼짐

    # 장애 복구 · Docker 소켓으로 정제 · 격리 저장 컨테이너 중지 · 시작 · 비우면 장애 복구 건너뜀
    pipeline_container_name: str = ""
    docker_socket_path: str = "/var/run/docker.sock"

    # 시스템 테스트 훅과 같은 값 · 저장소 .env의 QA_TEST_ACCOUNT_* · QA_CAPTCHA_FIXED_ANSWER (Issue #6)
    test_account_count: int = 0
    test_account_password: str = ""
    captcha_fixed_answer: str = ""
    # 트래픽 전 시험 데이터 초기화(/api/qa/reset/) · 시스템 관리자 계정 · 비어 있으면 건너뜀
    system_admin_username: str = ""
    system_admin_password: str = ""

    qa_database_url: str = "mongodb://127.0.0.1:27021/ticketguard_qa"  # 컨테이너 안은 qa/compose.qa-db.yml이 qa-mongo로 덮어씀
    report_output_dir: Path = Path("./qa_data/reports")
    case_data_dir: Path = QA_ROOT_DIR / "case_data"

    dashboard_base_path: str = "/qa"  # 팀 입구 127.0.0.1:8000/qa/ · AGENTS.md 4장

    rule_set_version: str = "mock-1"  # B2 룰 매칭 예측 · 실제 규칙 확정 시 domain/rule_sets.py 버전으로 교체

    random_seed: int = 20261103  # 같은 시드 = 같은 정답표
    fake_run_duration_sec: int = 10  # 가짜 대상 실행 흉내 시간 · 실제 QA 소요 시간에 맞춰 조정


def load_settings() -> Settings:
    return Settings()
