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

    # 시스템 테스트 훅과 같은 값 · 저장소 .env의 QA_TEST_ACCOUNT_* · QA_CAPTCHA_FIXED_ANSWER (Issue #6)
    test_account_count: int = 0
    test_account_password: str = ""
    captcha_fixed_answer: str = ""

    qa_database_url: str = "sqlite:///./qa_data/qa.db"
    report_output_dir: Path = Path("./qa_data/reports")
    case_data_dir: Path = QA_ROOT_DIR / "case_data"

    dashboard_base_path: str = "/qa"  # 팀 입구 127.0.0.1:8000/qa/ · AGENTS.md 4장

    random_seed: int = 20261103  # 같은 시드 = 같은 정답표
    fake_run_duration_sec: int = 10  # 가짜 대상 실행 흉내 시간 · 실제 QA 소요 시간에 맞춰 조정


def load_settings() -> Settings:
    return Settings()
