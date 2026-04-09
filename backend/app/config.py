from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Polyfacts"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/polyfacts"

    @model_validator(mode="after")
    def _fix_database_url(self):
        """Ensure database_url uses asyncpg driver for SQLAlchemy async engine."""
        url = self.database_url
        if url.startswith("postgres://"):
            self.database_url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            self.database_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self

    # Redis
    redis_url: str = "redis://localhost:6379"

    # API Keys
    api_key: str = "dev-key-change-me"
    deepgram_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    brave_search_api_key: str = ""
    jwt_secret: str = "change-me-in-production"
    access_token_expire_minutes: int = 1440

    # Government APIs
    bls_api_key: str = ""
    fred_api_key: str = ""
    congress_api_key: str = ""

    # Processing
    claim_worthiness_threshold: float = 0.5
    max_upload_size_mb: int = 500
    max_evidence_sources: int = 10

    # Storage
    upload_dir: str = "uploads"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
