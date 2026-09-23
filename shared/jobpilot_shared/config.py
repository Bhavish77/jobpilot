"""Central settings, read once from the environment.

Both agent-core and job-worker import `settings` from here instead of each
calling os.environ separately — one source of truth for connection strings,
one place to add a new setting.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres
    database_url: str = "postgresql+asyncpg://jobpilot:jobpilot@localhost:5432/jobpilot"

    # MongoDB
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "jobpilot"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery / RabbitMQ
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM provider (managed-key mode; BYOK is a Phase 10 addition). Gemini
    # Flash — free tier — chosen to keep dev/learning cost at zero; swap
    # LLM_MODEL if Google ships a newer Flash version.
    llm_provider: str = "google"
    llm_api_key: str = "changeme"
    llm_model: str = "gemini-2.5-flash"

    # Rate limiting — sized to your actual provider RPM, not a guess
    llm_rate_limit_rpm: int = 60

    # Auth — Google is a primary login option alongside email+password.
    google_client_id: str = "changeme"
    google_client_secret: str = "changeme"
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # GitHub — optional, connected later from the profile screen purely to
    # grant Phase 3's RAG ingestion read access to the user's repos. Not a
    # login path.
    github_client_id: str = "changeme"
    github_client_secret: str = "changeme"
    github_redirect_uri: str = "http://localhost:8000/auth/github/callback"

    frontend_url: str = "http://localhost:3000"

    # Session JWT issued by us after a successful register/login/Google
    # sign-in — separate from any third-party token, which we never hand to
    # the frontend.
    jwt_secret: str = "changeme-dev-only"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    @property
    def sync_database_url(self) -> str:
        """Alembic needs a plain sync driver — asyncpg can't run outside an
        event loop, and migration tooling (autogenerate, offline mode) isn't
        built around async engines. Same database, a different driver for a
        different job: the app talks to Postgres async, migrations don't."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


settings = Settings()
