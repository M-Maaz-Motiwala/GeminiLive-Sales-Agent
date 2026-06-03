from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Gemini
    gemini_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://aura:aura@localhost:5432/aura"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_environment: str = ""
    pinecone_index_name: str = "aura-knowledge"

    # Asterisk ARI
    asterisk_host: str = "asterisk"
    asterisk_ari_port: int = 8088
    asterisk_ari_user: str = "aura"
    asterisk_ari_pass: str = "aura_secret"
    asterisk_ari_app: str = "gemini-agent"

    # RTP bridge
    rtp_listen_port: int = 5004
    rtp_listen_host: str = "0.0.0.0"
    rtp_external_host: str = "fastapi"  # hostname Asterisk uses to reach our RTP bridge

    # Frontend
    vite_api_url: str = "http://localhost:8000"

    # Bridge internal API (shared secret with gemini_bridge container)
    bridge_internal_token: str = "change-me-bridge-token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
