"""관리자 앱 전용 설정 · 루트 .env 또는 컨테이너 환경 변수 · QA 설정 사용 금지"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TICKET_GUARD_ADMIN_", env_file=".env", extra="ignore")
    mongo_uri: str = ""
    base_path: str = "/admin"
