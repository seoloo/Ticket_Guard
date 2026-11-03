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

    qa_database_url: str = "sqlite:///./qa_data/qa.db"
    report_output_dir: Path = Path("./qa_data/reports")
    case_data_dir: Path = QA_ROOT_DIR / "case_data"

    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8800

    random_seed: int = 20261103  # 같은 시드 = 같은 정답표


def load_settings() -> Settings:
    return Settings()
