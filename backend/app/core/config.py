from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
PUBLIC_URL_SCHEMES = ("http", "https")


def _public_url_problem(address: str) -> str | None:
    """What keeps ``address`` from being the base of every link, or None when nothing does."""
    if any(char.isspace() or not char.isprintable() for char in address):
        return "must not contain spaces or control characters"
    try:
        parts = urlsplit(address)
    except ValueError:  # an unclosed IPv6 bracket, say
        return "is not a URL"
    if parts.scheme not in PUBLIC_URL_SCHEMES:
        return "must start with http:// or https://"
    if "@" in parts.netloc:
        return "must not carry a user name or password"
    try:
        _ = parts.port  # urlsplit checks the port only when it is read
    except ValueError:
        return "has a port that is not a number from 0 to 65535"
    if not parts.hostname:
        return "must name a host, as https://tralala.example.com does"
    if "?" in address:
        return "must not have a query (?...)"
    if "#" in address:
        return "must not have a fragment (#...)"
    return None


def checked_public_url(value: str | None) -> str | None:
    """``public_url`` as links are built on it: None when unset or empty, else the address
    without its trailing slash.

    Only an http or https address with a host name is accepted; a user name or password, a query
    or a fragment would end up in every link, so each is refused. The error names the setting and
    what is wrong with it, and it stops ``Settings()``, so the server does not start with an
    address it cannot build a link on.
    """
    address = (value or "").strip()
    if not address:
        return None
    problem = _public_url_problem(address)
    if problem is not None:
        raise ValueError(f"public_url (TRALALA_PUBLIC_URL) {problem}")
    return address.rstrip("/")


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
    # The address people open Tralala at (https://tralala.example.com), which makes the link to a
    # decision that waits for a person absolute. The server never learns it from a request's Host
    # or X-Forwarded-* headers; unset (or empty), such a link is a path inside Tralala.
    public_url: str | None = None
    # Deciding in the editor (TRALALA_EDITOR_DECISIONS), off unless the operator turns it on. Only
    # while it is on may a person give a key of their own the right ``loops:decide``; with it off,
    # or on a key without that right, every decision is a signed-in person's in Tralala.
    editor_decisions: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_bytes: int = 8 * 1024 * 1024
    rate_limit_per_minute: int = 600
    board_idle_close_seconds: int = 300
    # How long a measured set of board counters is reused before it is measured again. A write to a
    # board drops its row immediately; this only bounds a file changed outside the app. 0 disables
    # the cache and measures on every list.
    board_counts_cache_seconds: int = 60
    default_lists: str = "Backlog,Todo,In Progress,Review,Done"
    # The area labels a board created without a template starts with (a template brings its own);
    # a board created before this setting keeps the labels it has. Empty for none.
    default_labels: str = (
        "Development,Architecture,UX,QA,Security,Operations,Documentation,Data,Product,"
        "Business,Economy,Legal,Support,Communication,Research"
    )
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
    # What one generation run sends the model, documents and repository snapshot together, in
    # characters (about 100 k tokens by default). The documents come first; the snapshot gets the
    # rest, cut to fit.
    generation_context_chars: int = 400_000
    # A model that takes tools reads the repositories itself (list_files, read_file, search):
    # at most this many tool calls per run, after which it is asked for its answer.
    generation_tool_steps: int = 60
    # The most characters one tool answer sends the model; a longer file comes in parts.
    generation_tool_result_chars: int = 60_000
    # Git over HTTPS (the repository provider ``git_https``): the host names a mirror may fetch
    # from, comma-separated. A repository on any other host is refused when it is added and again
    # before every fetch.
    repository_hosts: str = "github.com"
    # A mirror still larger than this after its hygiene is removed; the next run clones it again.
    repository_mirror_max_bytes: int = 1024 * 1024 * 1024
    # How long one git command (ls-remote, clone, fetch, archive or a hygiene step) may take.
    repository_fetch_timeout_seconds: int = 120
    # The git program the mirror runs; a bare name is looked up on PATH.
    repository_git_binary: str = "git"
    # GitHub archives kept per repository and commit, all together at most this many bytes; the
    # oldest go first. 0 keeps none.
    repository_archive_cache_max_bytes: int = 256 * 1024 * 1024
    # The largest repository archive one run downloads or a mirror writes, held in memory
    # while the run reads it.
    repository_archive_max_bytes: int = 128 * 1024 * 1024
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

    @field_validator("public_url", mode="after")
    @classmethod
    def _public_address(cls, value: str | None) -> str | None:
        return checked_public_url(value)

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
    def repos_dir(self) -> Path:
        """Where the Git mirrors are: a cache that backups leave out and a run rebuilds."""
        return self.data_dir / "repos"

    @property
    def allowed_repository_hosts(self) -> frozenset[str]:
        """``repository_hosts`` as lower-case host names, without blanks."""
        return frozenset(
            host.strip().lower() for host in self.repository_hosts.split(",") if host.strip()
        )

    @property
    def list_names(self) -> list[str]:
        return [name.strip() for name in self.default_lists.split(",") if name.strip()]

    @property
    def label_names(self) -> list[str]:
        return [name.strip() for name in self.default_labels.split(",") if name.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.boards_dir, self.backups_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
