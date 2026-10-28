<<<<<<< Updated upstream
import pytest
from pydantic import ValidationError

from app.config import Settings, normalize_database_url

GOOD_PEPPER = "x" * 40
SUPABASE = (
    "postgresql://postgres.ref:pw@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    "?sslmode=require"
)


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every case states its own configuration; no ambient CI or shell variable leaks in (audit F-03)."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def _prod(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "database_url": SUPABASE,
        "receipt_pepper": GOOD_PEPPER,
        "cors_allowed_origins": "https://app.example.com",
        "client_address_header": "X-Forwarded-For",
        "turnstile_enabled": True,
        "turnstile_secret": "0x4AAAAAAA-secret",
        "turnstile_hostname": "app.example.com",
        "redis_url": "rediss://default:pw@apn1-example.upstash.io:6379",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://"])
def test_provider_urls_use_psycopg_driver(prefix: str) -> None:
    assert normalize_database_url(prefix + "u:p@h/db").startswith("postgresql+psycopg://")


def test_explicit_driver_is_untouched() -> None:
    url = "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url(url) == url


def test_production_accepts_valid_configuration() -> None:
    settings = _prod()
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.docs_are_enabled is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"receipt_pepper": "development-only-change-me"},
        {"receipt_pepper": "y" * 26},
        {"cors_allowed_origins": "*"},
        {"database_url": SUPABASE.replace("?sslmode=require", "")},
        {"client_address_header": None},
        {"turnstile_enabled": False},
        {"turnstile_secret": None},
        {"turnstile_hostname": None},
        {"redis_url": None},
        {"redis_url": "redis://default:pw@apn1-example.upstash.io:6379"},  # TLS is required
        {"ops_dashboard_token": "too-short"},
        {"auth_skip_email_verification": True},  # every production account proves its email
    ],
)
def test_production_fails_closed(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        _prod(**overrides)


def test_production_accepts_a_long_ops_token() -> None:
    assert _prod(ops_dashboard_token="t" * 43).ops_dashboard_token == "t" * 43


def test_development_keeps_defaults() -> None:
    settings = Settings(_env_file=None, app_env="development")
    assert settings.docs_are_enabled is True
    assert settings.cors_origins == ["http://localhost:5173"]


def test_cors_origins_ignore_trailing_slashes() -> None:
    settings = Settings(_env_file=None, app_env="test", cors_allowed_origins="http://localhost:5173/, https://app.example.com//,")
    assert settings.cors_origins == ["http://localhost:5173", "https://app.example.com"]


def test_timezone_defaults() -> None:
    s = Settings(_env_file=None, app_env="test")
    assert s.app_timezone == "UTC"
    assert s.default_display_timezone == "Asia/Dhaka"
    assert s.display_tz.key == "Asia/Dhaka"


@pytest.mark.parametrize(
    "overrides",
    [{"app_timezone": "Asia/Dhaka"}, {"default_display_timezone": "Not/AZone"}],
)
def test_invalid_timezones_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", **overrides)


def test_unset_environment_fails_closed() -> None:
    with pytest.raises(ValidationError):  # unset APP_ENV is production, which needs the full set
        Settings(_env_file=None, receipt_pepper=GOOD_PEPPER)
    settings = Settings(
        _env_file=None,
        database_url=SUPABASE,
        receipt_pepper=GOOD_PEPPER,
        cors_allowed_origins="https://app.example.com",
        client_address_header="X-Forwarded-For",
        turnstile_enabled=True,
        turnstile_secret="s" * 20,
        turnstile_hostname="app.example.com",
        redis_url="rediss://default:pw@apn1-example.upstash.io:6379",
    )
    assert settings.is_production
    assert not settings.docs_are_enabled
    assert not settings.allow_test_staff_header
=======
import pytest
from pydantic import ValidationError

from app.config import Settings, normalize_database_url

GOOD_PEPPER = "x" * 40
SUPABASE = (
    "postgresql://postgres.ref:pw@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    "?sslmode=require"
)


def _prod(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "database_url": SUPABASE,
        "receipt_pepper": GOOD_PEPPER,
        "cors_allowed_origins": "https://app.example.com",
        "client_address_header": "X-Forwarded-For",
        "turnstile_enabled": True,
        "turnstile_secret": "0x4AAAAAAA-secret",
        "turnstile_hostname": "app.example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://"])
def test_provider_urls_use_psycopg_driver(prefix: str) -> None:
    assert normalize_database_url(prefix + "u:p@h/db").startswith("postgresql+psycopg://")


def test_explicit_driver_is_untouched() -> None:
    url = "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url(url) == url


def test_production_accepts_valid_configuration() -> None:
    settings = _prod()
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.docs_are_enabled is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"receipt_pepper": "development-only-change-me"},
        {"receipt_pepper": "y" * 26},
        {"cors_allowed_origins": "*"},
        {"database_url": SUPABASE.replace("?sslmode=require", "")},
        {"client_address_header": None},
        {"turnstile_enabled": False},
        {"turnstile_secret": None},
        {"turnstile_hostname": None},
    ],
)
def test_production_fails_closed(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        _prod(**overrides)


def test_development_keeps_defaults() -> None:
    # app_env is passed explicitly (like the other cases in this file) so the test is hermetic
    # and does not depend on an ambient APP_ENV that only CI happens to export.
    settings = Settings(_env_file=None, app_env="development")
    assert settings.docs_are_enabled is True
    assert settings.cors_origins == ["http://localhost:5173"]


def test_cors_origins_ignore_trailing_slashes() -> None:
    settings = Settings(_env_file=None, app_env="test", cors_allowed_origins="http://localhost:5173/, https://app.example.com//,")
    assert settings.cors_origins == ["http://localhost:5173", "https://app.example.com"]


def test_timezone_defaults() -> None:
    s = Settings(_env_file=None, app_env="test")
    assert s.app_timezone == "UTC"
    assert s.default_display_timezone == "Asia/Dhaka"
    assert s.display_tz.key == "Asia/Dhaka"


@pytest.mark.parametrize(
    "overrides",
    [{"app_timezone": "Asia/Dhaka"}, {"default_display_timezone": "Not/AZone"}],
)
def test_invalid_timezones_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", **overrides)


def test_unset_environment_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(ValidationError):  # unset APP_ENV is production, which needs the full set
        Settings(_env_file=None, receipt_pepper=GOOD_PEPPER)
    # The remaining production requirements are passed explicitly as init kwargs (which outrank
    # any ambient env var) so the build succeeds on a clean checkout, not only inside CI's env.
    settings = Settings(
        _env_file=None,
        database_url=SUPABASE,
        receipt_pepper=GOOD_PEPPER,
        cors_allowed_origins="https://app.example.com",
        client_address_header="X-Forwarded-For",
        turnstile_enabled=True,
        turnstile_secret="s" * 20,
        turnstile_hostname="app.example.com",
    )
    assert settings.is_production
    assert not settings.docs_are_enabled
    assert not settings.allow_test_staff_header
>>>>>>> Stashed changes
