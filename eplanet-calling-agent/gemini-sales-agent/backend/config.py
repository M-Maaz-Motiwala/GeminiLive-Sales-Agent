from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Gemini
    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-2.5-flash"

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
    vite_api_url: str = "http://localhost:8080"

    # Bridge internal API (shared secret with gemini_bridge container)
    bridge_internal_token: str = "change-me-bridge-token"
    bridge_url: str = "http://bridge:8000"

    # Outbound: lab (PJSIP/100x) | trunk (PJSIP/+E164@trunk) — trunk creds in Asterisk
    outbound_mode: str = "lab"
    outbound_lab_endpoint: str = "PJSIP/1001"
    outbound_default_caller_id: str = "1000"
    outbound_default_country_code: str = "1"
    outbound_trunk_name: str = ""
    outbound_trunk_caller_id: str = ""
    max_concurrent_outbound: int = 5

    # CRM-generated Asterisk dialplan (mounted volume in docker-compose)
    asterisk_generated_dir: str = "/app/asterisk/generated"
    asterisk_container_name: str = "asterisk"

    # Call window (local timezone); disabled by default — set outbound_call_window_enabled=true to enforce
    outbound_call_window_enabled: bool = False
    outbound_call_timezone: str = "UTC"
    outbound_call_hour_start: int = 0
    outbound_call_hour_end: int = 24

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Google Calendar OAuth (per-user consent)
    calendar_redirect_uri: str = "http://localhost:8000/api/calendar/callback"
    calendar_encryption_key: str = ""  # Fernet key (base64-encoded 32 bytes)


@lru_cache
def get_settings() -> Settings:
    return Settings()
