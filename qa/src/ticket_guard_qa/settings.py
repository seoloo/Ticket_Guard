"""설정 한 곳 · 환경 변수 TICKET_GUARD_QA_* → Settings"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from ticket_guard_qa.domain.enums import AdminCheckMode, TargetKind

QA_ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TICKET_GUARD_QA_", env_file=".env", extra="ignore")

    target_kind: TargetKind = TargetKind.FAKE

    system_base_url: str = "http://127.0.0.1:8000"
    system_username: str = ""
    system_password: str = ""
    system_mongo_uri: str = ""  # 읽기 전용 계정만

    qa_database_url: str = "sqlite:///./qa_data/qa.db"
    report_output_dir: Path = Path("./qa_data/reports")
    case_data_dir: Path = QA_ROOT_DIR / "case_data"

    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8800  # 안쪽 전용 · 밖은 팀 입구 8000 · AGENTS.md 4장
    dashboard_base_path: str = ""  # 팀 입구 뒤에서는 "/qa"
    admin_check_mode: AdminCheckMode = AdminCheckMode.LOCAL_ONLY

    random_seed: int = 20261103  # 같은 시드 = 같은 정답표
    fake_run_duration_sec: int = 10  # 가짜 대상 실행 흉내 시간 · 실제 QA 소요 시간에 맞춰 조정


def load_settings() -> Settings:
    return Settings()
