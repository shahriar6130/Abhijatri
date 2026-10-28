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

    # Identity (R04). Supabase Auth is the identity provider; the browser only ever talks to this
    # API, which proxies Auth and keeps the tokens in HttpOnly cookies (Decisions.md, 27 Oct 2026).
    supabase_url: str | None = None  # e.g. http://127.0.0.1:54321 locally
    supabase_anon_key: str | None = Field(default=None, repr=False)
    supabase_service_role_key: str | None = Field(default=None, repr=False)  # server side only
    supabase_jwt_secret: str | None = Field(default=None, repr=False)  # HS256 tokens
    supabase_jwks_url: str | None = None  # ES256/RS256 tokens
    supabase_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    frontend_base_url: str = "http://localhost:5173"
    session_cookie_name: str = "__Host-abhijatri_session"
    refresh_cookie_name: str = "__Host-abhijatri_refresh"
    cookie_secure: bool = True  # __Host- cookies require Secure; browsers allow it on localhost
    member_session_days: int = Field(default=30, ge=1, le=90)  # absolute refresh-cookie lifetime
    superadmin_inactivity_hours: int = Field(default=8, ge=1, le=72)
    reauth_window_minutes: int = Field(default=10, ge=1, le=60)
    require_mfa_for_moderators: bool = True
    # Durable auth limits (API.md section 7, PF 14.3).
    login_failures_per_email_per_15m: int = Field(default=5, ge=1)
    login_attempts_per_network_per_hour: int = Field(default=100, ge=1)
    register_per_network_per_hour: int = Field(default=10, ge=1)
    reset_requests_per_email_per_hour: int = Field(default=3, ge=1)
    reset_requests_per_network_per_hour: int = Field(default=30, ge=1)
    token_confirms_per_network_per_hour: int = Field(default=30, ge=1)

    # Notifications (Moderation spec 11). `mailpit` is the local inbox, `resend` production, `none` off.
    email_provider: str = Field(default="none", pattern="^(none|mailpit|resend|smtp|brevo)$")
    brevo_api_key: str | None = Field(default=None, repr=False)
    # Who sends the verification and password-reset emails:
    # - "supabase": Supabase Auth mails them itself (its own rate limits apply);
    # - "app": the API asks Auth for the one-time token without any email, then sends it through
    #   EMAIL_PROVIDER. Only this API's own limits apply (API.md section 7).
    auth_email_delivery: str = Field(default="supabase", pattern="^(supabase|app)$")
    # Development only: registration creates an already-confirmed account and sends no email, so sign-in
    # works before an email provider is set up. Refused in production.
    auth_skip_email_verification: bool = False
    smtp_host: str | None = None  # e.g. smtp.gmail.com
    smtp_port: int = Field(default=587, ge=1, le=65535)  # 587 STARTTLS, 465 TLS
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)  # Gmail: an app password, never the account password
    mailpit_url: str = "http://127.0.0.1:54324"
    resend_api_key: str | None = Field(default=None, repr=False)
    email_from: str = "Abhijatri <no-reply@abhijatri.test>"
    notify_worker_enabled: bool = True
    notify_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    digest_hour: int = Field(default=8, ge=0, le=23)  # local hour of the daily digest
    # Notification spec v1.1 (Docs/Notification-Documentation.md).
    staff_base_url: str = "http://localhost:5175"  # links in staff notices and emails
    resend_webhook_secret: str | None = Field(default=None, repr=False)  # "whsec_..." from Resend
    brevo_webhook_token: str | None = Field(default=None, repr=False)  # bearer token configured on the Brevo webhook
    notify_scan_seconds: float = Field(default=60.0, gt=0, le=3600)  # alert and reminder scanners
    notify_failure_alert_per_hour: int = Field(default=5, ge=1)
    notify_backlog_alert_minutes: int = Field(default=10, ge=1)
    notify_webhook_anomaly_per_hour: int = Field(default=5, ge=1)
    notify_queue_overdue_hours: int = Field(default=24, ge=1)

    @property
    def email_from_address(self) -> str:
        return self.email_from.split("<")[-1].rstrip(">").strip()

    @property
    def email_from_name(self) -> str:
        return self.email_from.split("<")[0].strip() or "Abhijatri"

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
    def auth_configured(self) -> bool:
        return bool(
            self.supabase_url
            and self.supabase_anon_key
            and (self.supabase_jwt_secret or self.supabase_jwks_url)
        )

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
        if self.supabase_url and not self.supabase_url.startswith("https://"):
            raise ValueError("SUPABASE_URL must be https:// in production")
        if self.email_provider == "mailpit":
            raise ValueError("EMAIL_PROVIDER=mailpit is a development inbox; use resend in production")
        if self.email_provider == "smtp" and not (self.smtp_host and self.smtp_username and self.smtp_password):
            raise ValueError("SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD are required when EMAIL_PROVIDER=smtp")
        if self.email_provider == "brevo" and not self.brevo_api_key:
            raise ValueError("BREVO_API_KEY is required when EMAIL_PROVIDER=brevo")
        if self.auth_skip_email_verification:
            raise ValueError("AUTH_SKIP_EMAIL_VERIFICATION is for development only; email must be verified in production")
        if self.auth_email_delivery == "app" and self.email_provider == "none":
            raise ValueError("AUTH_EMAIL_DELIVERY=app needs an EMAIL_PROVIDER that sends mail")
        if self.email_provider == "resend" and not self.resend_api_key:
            raise ValueError("RESEND_API_KEY is required when EMAIL_PROVIDER=resend")
        if self.supabase_url and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must stay true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
