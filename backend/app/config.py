import json
import re
from functools import lru_cache
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PEPPER = "development-only-change-me"
DEFAULT_DATABASE_URL = "postgresql+psycopg://abhijatri:abhijatri_dev@localhost:5432/abhijatri"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}


def normalize_database_url(value: str) -> str:
    """Make provider URLs (postgres://, postgresql://) use the psycopg3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix) :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"  # fail closed: dev/test must be requested explicitly
    database_url: str = DEFAULT_DATABASE_URL
    migration_database_url: str | None = None
    receipt_pepper: str = Field(default=DEFAULT_PEPPER, min_length=24, repr=False)
    receipt_session_minutes: int = 15
    receipt_keys: str | None = Field(default=None, repr=False)  # JSON {"v1": "<secret>", ...}
    receipt_key_current: str = "v1"
    cors_allowed_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    app_timezone: str = "UTC"
    default_display_timezone: str = "Asia/Dhaka"
    docs_enabled: bool | None = None
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=2, ge=0, le=20)
    db_pool_recycle: int = Field(default=1800, ge=30)
    db_pool_timeout: int = Field(default=5, ge=1, le=60)
    db_connect_timeout: int = Field(default=5, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    db_lock_timeout_ms: int = Field(default=3000, ge=100, le=60000)
    db_idle_in_transaction_timeout_ms: int = Field(default=15000, ge=1000, le=120000)
    request_timeout_seconds: int = Field(default=15, ge=1, le=120)
    max_request_body_bytes: int = Field(default=65536, ge=1024, le=1048576)
    advisory_stale_after_days: int = Field(default=30, ge=1, le=365)
    public_cache_max_age_seconds: int = Field(default=60, ge=0, le=3600)
    allow_test_staff_header: bool = False
    rate_limit_enabled: bool = True
    # Storage for the in-memory-style burst pre-filter. The default is per-process memory; Upstash
    # (REDIS_URL) is used for the visit counters only, not for this limiter (Decisions.md, 22 Oct 2026).
    rate_limit_storage_uri: str = Field(default="memory://", min_length=1)
    rate_limit_guest_submit: str = "5/minute"  # in-memory burst pre-filter only (PF 14.5)
    rate_limit_receipt: str = "10/minute"  # in-memory burst pre-filter only (PF 14.5)
    rate_limit_guest_visit: str = "20/minute"  # in-memory burst pre-filter only (PF 14.5)

    # Trusted client address (PF 14.2): the one provider-appended header entry, never a guess.
    client_address_header: str | None = None
    client_address_position: int = Field(default=-1, ge=-5, le=5)

    # Durable abuse limits (API.md section 7, PF 14.3). All are hard limits.
    guest_submit_per_scope_per_day: int = Field(default=3, ge=1)
    guest_submit_per_network_per_hour: int = Field(default=30, ge=1)
    guest_submit_per_network_per_day: int = Field(default=100, ge=1)
    receipt_ops_per_receipt_per_hour: int = Field(default=20, ge=1)
    receipt_ops_per_network_per_hour: int = Field(default=100, ge=1)
    guest_visits_per_network_per_hour: int = Field(default=60, ge=1)
    receipt_failures_short_limit: int = Field(default=5, ge=1)  # per 15 minutes
    receipt_failures_long_limit: int = Field(default=20, ge=1)  # per 24 hours
    guest_pending_per_destination: int = Field(default=50, ge=1)
    guest_pending_total: int = Field(default=500, ge=1)
    guest_pending_alert_ratio: float = Field(default=0.8, gt=0, le=1)
    guest_writes_paused: bool = False  # emergency switch: guest writes only, reads continue

    # Cloudflare Turnstile (PF 14.1). Disabled only in development and test.
    turnstile_enabled: bool = False
    turnstile_secret: str | None = Field(default=None, repr=False)
    turnstile_hostname: str | None = None
    turnstile_verify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    turnstile_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    # Visit counters and ops event counters (Guest-Identity-and-Visits 7). Upstash in shared
    # environments (rediss://), a local container or fakeredis in development and tests.
    redis_url: str | None = Field(default=None, repr=False)
    redis_timeout_ms: int = Field(default=300, ge=50, le=5000)
    visit_counter_enabled: bool = True  # kill switch for counting visits
    metrics_flush_seconds: int = Field(default=60, ge=5, le=3600)

    # System Monitoring Dashboard, phase 1 (System-Monitoring-Dashboard 3.1). Unset: /ops is 404.
    ops_dashboard_token: str | None = Field(default=None, repr=False)
    ops_auth_failures_per_network_per_hour: int = Field(default=10, ge=1)

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _normalize_url(cls, value: str | None) -> str | None:
        return normalize_database_url(value) if value else value

    @field_validator("receipt_keys")
    @classmethod
    def _keyring_is_valid(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            ring = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("RECEIPT_KEYS must be a JSON object") from error
        if not isinstance(ring, dict) or not ring:
            raise ValueError("RECEIPT_KEYS must be a non-empty JSON object")
        for key_id, secret in ring.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", str(key_id)):
                raise ValueError("RECEIPT_KEYS ids must be 1 to 16 letters, digits, '-' or '_'")
            if not isinstance(secret, str) or len(secret) < 24:
                raise ValueError("every RECEIPT_KEYS secret must be a string of at least 24 characters")
        return value

    @field_validator("app_timezone")
    @classmethod
    def _storage_zone_is_utc(cls, value: str) -> str:
        if value != "UTC":
            raise ValueError("APP_TIMEZONE must be UTC; timestamps are stored and computed in UTC")
        return value

    @field_validator("default_display_timezone")
    @classmethod
    def _display_zone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"DEFAULT_DISPLAY_TIMEZONE {value!r} is not a valid IANA zone") from error
        return value

    @property
    def hmac_keyring(self) -> dict[str, str]:
        """Versioned HMAC keys shared by receipt, guest-scope and network digests.

        Without ``RECEIPT_KEYS`` the single ``RECEIPT_PEPPER`` is key ``v1``. Old keys stay in
        the ring until no stored digest references them (Platform Foundation 13.4).
        """
        if self.receipt_keys:
            ring = json.loads(self.receipt_keys)
            return {str(key_id): str(secret) for key_id, secret in ring.items()}
        return {"v1": self.receipt_pepper}

    @property
    def display_tz(self) -> ZoneInfo:
        return ZoneInfo(self.default_display_timezone)

    @property
    def is_production(self) -> bool:
        return self.app_env not in {"development", "test"}

    @property
    def cors_origins(self) -> list[str]:
        # Browsers send an Origin without a path, so "http://localhost:5173/" would never match.
        return [o.strip().rstrip("/") for o in self.cors_allowed_origins.split(",") if o.strip().rstrip("/")]

    @property
    def docs_are_enabled(self) -> bool:
        return self.docs_enabled if self.docs_enabled is not None else not self.is_production

    @property
    def effective_migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    @model_validator(mode="after")
    def _current_key_exists(self) -> "Settings":
        if self.receipt_key_current not in self.hmac_keyring:
            raise ValueError("RECEIPT_KEY_CURRENT must name a key in the keyring")
        return self

    @model_validator(mode="after")
    def _production_guard(self) -> "Settings":
        if not self.is_production:
            return self
        if self.database_url == DEFAULT_DATABASE_URL:
            raise ValueError("DATABASE_URL must be explicitly configured in production")
        if self.receipt_pepper == DEFAULT_PEPPER or len(self.receipt_pepper) < 32:
            raise ValueError("RECEIPT_PEPPER must be a unique value of at least 32 characters")
        if any(len(secret) < 32 or secret == DEFAULT_PEPPER for secret in self.hmac_keyring.values()):
            raise ValueError("every RECEIPT_KEYS secret must be unique and at least 32 characters")
        if not self.client_address_header:
            raise ValueError(
                "CLIENT_ADDRESS_HEADER must name the provider-appended header proven by the "
                "forged-header test (Platform Foundation 14.2)"
            )
        if not (self.turnstile_enabled and self.turnstile_secret and self.turnstile_hostname):
            raise ValueError("TURNSTILE_ENABLED, TURNSTILE_SECRET and TURNSTILE_HOSTNAME are required")
        if "*" in self.cors_origins or not self.cors_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must list explicit origins, never '*'")
        host = urlparse(self.database_url.replace("+psycopg", "", 1)).hostname or ""
        if host not in LOCAL_HOSTS and "sslmode=require" not in self.database_url:
            raise ValueError("DATABASE_URL must include sslmode=require outside local hosts")
        if not (self.redis_url and self.redis_url.startswith("rediss://")):
            raise ValueError("REDIS_URL must be set to this environment's rediss:// (TLS) Upstash URL")
        if self.ops_dashboard_token is not None and len(self.ops_dashboard_token) < 32:
            raise ValueError("OPS_DASHBOARD_TOKEN must be at least 32 characters, or unset")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
