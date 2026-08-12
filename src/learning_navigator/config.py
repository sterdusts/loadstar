"""Central, environment-driven application configuration.

The desktop product must resolve its local files independently of the shell's
current working directory.  Otherwise launching the same installation from an
IDE or a shortcut can silently create a second, apparently empty database.
"""

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def _source_checkout_root(package_file: Path) -> Path | None:
    """Return the editable checkout root when running from a source tree."""

    for candidate in package_file.resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / ".env.example").is_file():
            return candidate
    return None


def runtime_root() -> Path:
    """Return the stable directory used for the environment file and local data."""

    configured = os.getenv("LN_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    checkout = _source_checkout_root(Path(__file__))
    if checkout is not None:
        return checkout
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / "Frame").resolve()
    return (Path.home() / ".frame").resolve()


RUNTIME_ROOT = runtime_root()
ENV_FILE = RUNTIME_ROOT / ".env"
DEFAULT_DATABASE_PATH = RUNTIME_ROOT / "learning_navigator.db"
STORAGE_SECRET_FILE = RUNTIME_ROOT / ".frame-storage-secret"


def resolve_database_url(value: str, *, base_dir: Path = RUNTIME_ROOT) -> str:
    """Resolve relative SQLite files against the stable application directory."""

    url = make_url(value)
    if not url.drivername.startswith("sqlite"):
        return value
    database = url.database
    if database is None or database in {"", ":memory:"} or database.startswith("file:"):
        return value
    path = Path(database).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return url.set(database=path.as_posix()).render_as_string(hide_password=False)


def ensure_runtime_root(path: Path = RUNTIME_ROOT) -> Path:
    """Create the stable local-data directory at application startup."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def persistent_storage_secret(path: Path | None = None) -> str:
    """Return a stable local UI secret without checking one into source control."""

    secret_path = path or STORAGE_SECRET_FILE
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if len(existing) >= 32 and existing not in {
        "development-only-change-me",
        "replace-with-a-long-random-value",
    }:
        return existing

    generated = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(
            secret_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        # An invalid pre-existing file is replaced atomically. This path is only
        # expected when upgrading an old development placeholder.
        temporary = secret_path.with_name(f"{secret_path.name}.{os.getpid()}.tmp")
        temporary.write_text(generated, encoding="utf-8")
        os.replace(temporary, secret_path)
        return generated
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(generated)
    return generated


class Settings(BaseSettings):
    """Runtime configuration loaded from ``LN_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_prefix="LN_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Learning Navigator"
    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    debug: bool = False
    auto_create_schema: bool = False
    ai_provider: str = "mock"
    ai_base_url: str = "http://localhost:11434/v1"
    ai_model: str = "mock-learning-map-v1"
    ai_api_key: SecretStr | None = None
    storage_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(persistent_storage_secret())
    )
    internal_api_url: str = "http://127.0.0.1:8000/api"
    allow_test_user_header: bool = False
    mastery_required_level: int = Field(default=3, ge=0, le=5)
    review_after_days: int = Field(default=30, ge=1, le=3650)
    algorithm_version: str = "path-rule-v1"
    mastery_algorithm_version: str = "mastery-rule-v1"

    @field_validator("database_url")
    @classmethod
    def make_database_location_stable(cls, value: str) -> str:
        return resolve_database_url(value)

    @field_validator("storage_secret", mode="before")
    @classmethod
    def replace_known_placeholder_secret(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value or "")
        if raw in {"development-only-change-me", "replace-with-a-long-random-value"}:
            return persistent_storage_secret()
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings object."""

    return Settings()
