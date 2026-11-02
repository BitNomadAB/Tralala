from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value can be overridden with a TRALALA_* env var."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRALALA_", extra="ignore")

    data_dir: Path = Path("data")
    secret_key: str | None = None
    previous_secret_key: str | None = None
    session_ttl_seconds: int = 12 * 60 * 60
    password_min_length: int = 8
    credential_default_ttl_days: int = 90
    member_token_limit: int = 10
    member_token_default_days: int = 30
    member_token_max_days: int = 365
    invite_ttl_hours: int = 72
    trust_proxy_headers: bool = False
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_bytes: int = 8 * 1024 * 1024
    rate_limit_per_minute: int = 600
    board_idle_close_seconds: int = 300
    default_lists: str = "Backlog,Todo,In Progress,Review,Done"
    bootstrap_username: str = "admin"
    bootstrap_password: str = "admin"
    max_page_size: int = 200
    default_page_size: int = 50
    bulk_limit: int = 100
    idempotency_ttl_seconds: int = 24 * 60 * 60
    enable_docs: bool = True
    docs_require_auth: bool = True
    agents_allow_private_endpoints: bool = True
    attachment_max_bytes: int = 10 * 1024 * 1024
    board_attachment_max_bytes: int = 200 * 1024 * 1024

    @field_validator("data_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.sqlite"

    @property
    def boards_dir(self) -> Path:
        return self.data_dir / "boards"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def list_names(self) -> list[str]:
        return [name.strip() for name in self.default_lists.split(",") if name.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.boards_dir, self.backups_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
