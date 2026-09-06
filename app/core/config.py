"""Configuration applicative (variables d'environnement, cf. .env.example)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Sika"
    database_url: str = "sqlite:///./sika_dev.db"
    sika_secret_key: str = "dev-secret-key-change-me"
    sika_seed_pin: str = "1234"
    assemblyai_api_key: str = ""
    notif_provider: str = "console"  # console | http (WhatsApp/SMS agrégateur)
    notif_api_key: str = ""
    notif_sender: str = ""
    token_ttl_seconds: int = 12 * 3600
    cors_origins: str = "http://localhost:5173"


settings = Settings()
