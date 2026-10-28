"""Regression tests from the Security & QA audit of 21 Oct 2026 (section 6) and its fixes F-06, F-09.

All are deterministic and need no database.
"""

import base64
import ipaddress
import secrets

import pytest
from fastapi.testclient import TestClient

from app import crypto
from app.client_address import _parse, normalise
from app.config import get_settings
from app.db import get_session
from app.errors import preferred_language
from app.main import API_CSP, SECURITY_HEADERS, create_app

# ---- crypto.receipt_format_problem: the receipt anti-forgery gate ----


def _receipt(raw: bytes) -> str:
    return crypto.RECEIPT_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_well_formed_random_receipts_are_accepted() -> None:
    for _ in range(50):
        assert crypto.receipt_format_problem(_receipt(secrets.token_bytes(32))) is None


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("abr2_" + "A" * 43, "prefix"),
        ("ABR1_" + "A" * 43, "prefix"),
        ("abr1_" + "A" * 42, "length_or_alphabet"),
        ("abr1_" + "A" * 44, "length_or_alphabet"),
        ("abr1_" + "A" * 42 + "+", "length_or_alphabet"),
        ("abr1_" + "A" * 42 + "B", "encoding"),  # non-canonical trailing bits
        (_receipt(bytes(32)), "weak"),  # 32 identical bytes
    ],
)
def test_malformed_or_weak_receipts_are_rejected(value: str, problem: str) -> None:
    assert crypto.receipt_format_problem(value) == problem


# ---- errors.preferred_language: parses a fully attacker-controlled header ----


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "bn"),
        ("", "bn"),
        ("en", "en"),
        ("en-GB,en;q=0.9", "en"),
        ("bn;q=0.4, en;q=0.8", "en"),
        ("en;q=0, bn", "bn"),
        ("en;q=abc", "bn"),  # malformed q fails safe to Bangla
        ("fr, de;q=0.9", "bn"),
        ("BN-bd", "bn"),
        ("en-US;q=1;foo=bar", "en"),
    ],
)
def test_language_negotiation_fails_safe_to_bangla(header: str | None, expected: str) -> None:
    assert preferred_language(header) == expected


# ---- client_address: the value that keys every durable rate-limit counter ----


def test_ipv6_addresses_in_one_64_share_a_key() -> None:
    first = ipaddress.ip_address("2001:db8:1:2:aaaa::1")
    second = ipaddress.ip_address("2001:db8:1:2:ffff::9")
    assert normalise(first) == normalise(second) == "2001:db8:1:2::/64"
    assert normalise(ipaddress.ip_address("2001:db8:1:3::1")) != normalise(first)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("203.0.113.7:4711", "203.0.113.7"),
        (" [2001:db8::1] ", "2001:db8::1"),
        ("not-an-address", None),
        ("", None),
    ],
)
def test_address_parsing(value: str, expected: str | None) -> None:
    parsed = _parse(value)
    assert (str(parsed) if parsed else None) == expected
    assert normalise(None) == "unknown"


# ---- F-06 / F-09: every response carries the security headers ----


def _client() -> TestClient:
    application = create_app()
    application.dependency_overrides[get_session] = lambda: None
    return TestClient(application)


def _assert_hardened(response, *, csp: bool = True) -> None:  # type: ignore[no-untyped-def]
    assert response.headers.get("x-request-id")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name
    if csp:
        assert response.headers.get("content-security-policy") == API_CSP


def test_oversized_content_length_413_carries_every_header() -> None:
    limit = get_settings().max_request_body_bytes
    response = _client().post(
        "/api/v1/guest-visits",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(limit + 1)},
    )
    assert response.status_code == 413
    _assert_hardened(response)


def test_oversized_streamed_body_413_carries_every_header() -> None:
    limit = get_settings().max_request_body_bytes

    def chunks():  # type: ignore[no-untyped-def]
        yield b"x" * (limit + 10)

    response = _client().post("/api/v1/guest-visits", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    _assert_hardened(response)


def test_normal_and_not_found_responses_carry_the_csp() -> None:
    client = _client()
    _assert_hardened(client.get("/api/v1/health"))
    _assert_hardened(client.get("/api/v1/does-not-exist"))


def test_interactive_docs_are_left_without_the_csp() -> None:
    response = _client().get("/docs")
    if response.status_code == 200:  # docs are off in production settings
        assert "content-security-policy" not in response.headers
