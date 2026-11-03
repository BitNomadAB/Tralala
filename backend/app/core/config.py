from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


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
    backup_interval_hours: int = 24
    backup_keep: int = 10
    invite_ttl_hours: int = 72
    trust_proxy_headers: bool = False
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_bytes: int = 8 * 1024 * 1024
    rate_limit_per_minute: int = 600
    board_idle_close_seconds: int = 300
    # How long a measured set of board counters is reused before it is measured again. A write to a
    # board drops its row immediately; this only bounds a file changed outside the app. 0 disables
    # the cache and measures on every list.
    board_counts_cache_seconds: int = 60
    default_lists: str = "Backlog,Todo,In Progress,Review,Done"
    bootstrap_username: str = "admin"
    bootstrap_password: str = "admin"  # noqa: S105 - a placeholder bootstrap_admin replaces
    max_page_size: int = 200
    default_page_size: int = 50
    bulk_limit: int = 100
    idempotency_ttl_seconds: int = 24 * 60 * 60
    enable_docs: bool = True
    docs_require_auth: bool = True
    agents_allow_private_endpoints: bool = True
    discussion_max_rounds: int = 4
    discussion_token_budget: int = 200_000
    discussion_time_budget_seconds: int = 900
    # A file cannot exceed the request body that carries it, so this tracks max_request_bytes
    # rather than promising a size the request ceiling would refuse.
    attachment_max_bytes: int = 8 * 1024 * 1024
    board_attachment_max_bytes: int = 200 * 1024 * 1024
    board_import_max_bytes: int = 256 * 1024 * 1024
    # How the host filesystem behaves: auto (the real OS), windows, posix, or network for a board
    # directory on NFS/SMB. It selects retry policy, never the locking mechanism.
    platform_profile: str = "auto"
    # The lowest level the backend log writes: DEBUG, INFO, WARNING or ERROR.
    log_level: str = "INFO"

    @field_validator("log_level", mode="after")
    @classmethod
    def _known_level(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned not in LOG_LEVELS:
            raise ValueError(f"log_level must be one of {', '.join(LOG_LEVELS)}")
        return cleaned

    @field_validator("platform_profile", mode="after")
    @classmethod
    def _known_profile(cls, value: str) -> str:
        from .platform import PROFILES, resolve_profile

        cleaned = (value or "auto").strip().lower()
        if cleaned not in PROFILES:
            raise ValueError(f"platform_profile must be one of {', '.join(PROFILES)}")
        return resolve_profile(cleaned)

    @property
    def file_profile(self) -> str:
        """The profile every file operation uses; already resolved by the validator."""
        return self.platform_profile

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
