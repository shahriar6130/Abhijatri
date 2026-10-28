"""Authentication endpoints (Docs/api/API.md section 4.1, Gantt R04).

Every response is ``no-store``. Sign-up, verification, sign-in and reset answer the same way for
known and unknown addresses. Tokens only ever travel in HttpOnly cookies; the body of a response
never contains one.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import abuse, visits
from app.admin.cases import is_verified_member
from app.auth import csrf, mail, validation
from app.auth.gotrue import GoTrueClient, GoTrueError, GoTrueUnavailable, TokenPair, get_gotrue
from app.auth.sessions import (
    MemberPrincipal,
    OptionalPrincipal,
    Principal,
    active_role,
    clear_session_cookies,
    provision_user,
    require_csrf,
    set_session_cookies,
)
from app.auth.tokens import InvalidToken, verify_access_token
from app.client_address import network_digest, trusted_client_address
from app.config import get_settings
from app.db import get_session
from app.destination_services import today_in_display_tz
from app.errors import ApiError
from app.models import User
from app.notify import events
from app.redis_client import RedisDep
from app.turnstile import ACTION_AUTH_REGISTER, ACTION_AUTH_RESET, TurnstileDep

logger = logging.getLogger(__name__)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _ready() -> None:
    if not get_settings().auth_configured:
        raise ApiError("AUTH_NOT_CONFIGURED")


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    dependencies=[Depends(_no_store), Depends(_ready), Depends(csrf.check_origin)],
)

GoTrue = Annotated[GoTrueClient, Depends(get_gotrue)]
DbSession = Annotated[Session, Depends(get_session)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RegisterRequest(_Body):
    email: str = Field(max_length=320)
    password: str = Field(max_length=validation.MAX_PASSWORD)
    display_name: str = Field(max_length=200)
    turnstile_token: str | None = Field(default=None, max_length=2048)


class VerifyEmailRequest(_Body):
    token_hash: str = Field(min_length=8, max_length=512)


class EmailRequest(_Body):
    email: str = Field(max_length=320)
    turnstile_token: str | None = Field(default=None, max_length=2048)


class LoginRequest(_Body):
    email: str = Field(max_length=320)
    password: str = Field(max_length=validation.MAX_PASSWORD)


class ResetConfirmRequest(_Body):
    token_hash: str = Field(min_length=8, max_length=512)
    new_password: str = Field(max_length=validation.MAX_PASSWORD)


class MfaVerifyRequest(_Body):
    factor_id: str = Field(min_length=8, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


class ReauthRequest(_Body):
    password: str = Field(max_length=validation.MAX_PASSWORD)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")


def _provider(call: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a GoTrue call; an outage is a 503 and never a pass."""
    try:
        return call(*args, **kwargs)
    except GoTrueUnavailable as error:
        raise ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"}) from error


def _app_mail() -> bool:
    """True when this API sends the account emails itself (AUTH_EMAIL_DELIVERY=app)."""
    return get_settings().auth_email_delivery == "app"


def _remote(request: Request) -> str | None:
    address = trusted_client_address(request)
    return str(address) if address else None


def _session_payload(principal: Principal, factors: list[dict[str, Any]], session: Session) -> dict[str, Any]:
    verified = [f for f in factors if f.get("status") == "verified"]
    return {
        "authenticated": True,
        "user": {
            "id": str(principal.user.id),
            "email": principal.user.email,
            "display_name": principal.user.display_name,
            "email_verified": principal.user.email_verified_at is not None,
        },
        "role": principal.role,
        "verified_member": is_verified_member(session, principal.user.id),
        "aal": principal.claims.aal,
        "mfa_factors": [{"id": f.get("id"), "type": f.get("factor_type")} for f in verified],
        "auth_time": principal.claims.auth_time.isoformat(),
    }


def _record_member_visit(session: Session, redis_client: Any, principal: Principal) -> None:
    """Count the member once per Dhaka day (Guest-Identity-and-Visits 4.3). Best effort."""
    try:
        outcome = visits.record_member_visit(session, principal.user.id, today_in_display_tz())
        session.commit()
        if outcome is not None and get_settings().visit_counter_enabled:
            visits.record_visit(redis_client, "member", new=outcome)
    except Exception:  # noqa: BLE001 - counting must never break sign-in
        session.rollback()
        logger.warning("member visit was not counted")


# ---- registration and verification ----


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
def register(
    request: Request,
    payload: RegisterRequest,
    sessions: abuse.CounterSessions,
    verify_challenge: TurnstileDep,
    gotrue: GoTrue,
    background: BackgroundTasks,
) -> dict[str, str]:
    settings = get_settings()
    email = validation.normalize_email(payload.email)
    name = validation.normalize_display_name(payload.display_name)
    abuse.enforce(sessions, abuse.register_checks(settings, network_digest(request)))
    verify_challenge(payload.turnstile_token, action=ACTION_AUTH_REGISTER, remote_address=_remote(request))
    validation.validate_registration(email, payload.password, name)
    if settings.auth_skip_email_verification:
        try:
            _provider(gotrue.admin_create_confirmed_user, email, payload.password, {"display_name": name})
        except GoTrueError as error:
            if error.code in {"weak_password", "validation_failed"}:
                raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "password", "code": "WEAK"}]) from error
            logger.info("sign-up refused by the provider (%s)", error.code)  # an existing address looks the same
        return {"status": "registered"}
    try:
        if _app_mail():
            token = _provider(gotrue.admin_generate_link, "signup", email, payload.password, {"display_name": name})
            background.add_task(mail.deliver, mail.verification_email(email, token, name))
        else:
            _provider(gotrue.sign_up, email, payload.password, name)
    except GoTrueError as error:
        if error.code in {"weak_password", "validation_failed"}:
            raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "password", "code": "WEAK"}]) from error
        if "rate_limit" in error.code:
            raise ApiError("RATE_LIMITED", headers={"Retry-After": "60"}) from error
        logger.info("sign-up refused by the provider (%s)", error.code)  # an existing address looks the same
    return {"status": "verification_sent"}


@router.post("/verify-email")
def verify_email(request: Request, payload: VerifyEmailRequest, sessions: abuse.CounterSessions, gotrue: GoTrue) -> dict[str, str]:
    abuse.enforce(sessions, abuse.token_confirm_checks(get_settings(), network_digest(request)))
    try:
        tokens: TokenPair = _provider(gotrue.verify_token_hash, payload.token_hash, "signup")
    except GoTrueError as error:
        raise ApiError("TOKEN_INVALID_OR_EXPIRED") from error
    try:  # verification proves the address; signing in is a separate, deliberate step
        _provider(gotrue.sign_out, tokens.access_token)
    except (GoTrueError, ApiError):
        logger.info("could not revoke the verification session")
    return {"status": "verified"}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(request: Request, payload: EmailRequest, sessions: abuse.CounterSessions, gotrue: GoTrue, background: BackgroundTasks) -> dict[str, str]:
    settings = get_settings()
    email = validation.normalize_email(payload.email)
    abuse.enforce(sessions, abuse.reset_request_checks(settings, abuse.email_key(email), network_digest(request)))
    try:
        if _app_mail():  # no password: an unconfirmed account keeps the one it chose
            token = _provider(gotrue.admin_generate_link, "signup", email)
            background.add_task(mail.deliver, mail.verification_email(email, token, None))
        else:
            _provider(gotrue.resend_confirmation, email)
    except GoTrueError:
        logger.info("resend refused by the provider")
    return {"status": "verification_sent"}


# ---- sign-in and sign-out ----


@router.post("/login")
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    sessions: abuse.CounterSessions,
    session: DbSession,
    redis_client: RedisDep,
    gotrue: GoTrue,
) -> dict[str, Any]:
    email = validation.normalize_email(payload.email)
    email_digest, network = abuse.email_key(email), network_digest(request)
    abuse.guard_login(sessions, email_digest, network)
    try:
        tokens: TokenPair = _provider(gotrue.sign_in, email, payload.password)
    except GoTrueError as error:
        if error.code == "email_not_confirmed":
            raise ApiError("EMAIL_NOT_VERIFIED") from error
        abuse.record_login_failure(sessions, email_digest, network)
        raise ApiError("INVALID_CREDENTIALS") from error
    try:
        claims = verify_access_token(tokens.access_token)
    except InvalidToken as error:
        raise ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"}) from error
    user = provision_user(session, claims)
    if user.status != "active":
        session.commit()
        raise ApiError("ACCOUNT_DISABLED")
    session.commit()
    set_session_cookies(response, tokens)
    principal = Principal(user=user, claims=claims, role=active_role(session, user.id), access_token=tokens.access_token)
    _record_member_visit(session, redis_client, principal)
    return _session_payload(principal, _provider(gotrue.list_factors, tokens.access_token), session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, principal: OptionalPrincipal, gotrue: GoTrue) -> Response:
    if principal is not None:
        csrf.require_valid(request, principal.csrf_binding)
        try:
            gotrue.sign_out(principal.access_token)
        except (GoTrueError, GoTrueUnavailable):
            logger.info("provider sign-out failed; cookies are cleared anyway")
    empty = Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
    clear_session_cookies(empty)
    return empty


# ---- password reset ----


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def password_reset_request(
    request: Request,
    payload: EmailRequest,
    sessions: abuse.CounterSessions,
    verify_challenge: TurnstileDep,
    gotrue: GoTrue,
    background: BackgroundTasks,
) -> dict[str, str]:
    settings = get_settings()
    email = validation.normalize_email(payload.email)
    abuse.enforce(sessions, abuse.reset_request_checks(settings, abuse.email_key(email), network_digest(request)))
    verify_challenge(payload.turnstile_token, action=ACTION_AUTH_RESET, remote_address=_remote(request))
    try:
        if _app_mail():
            token = _provider(gotrue.admin_generate_link, "recovery", email)
            background.add_task(mail.deliver, mail.reset_email(email, token))
        else:
            _provider(gotrue.request_recovery, email)
    except GoTrueError:
        logger.info("recovery refused by the provider")
    return {"status": "reset_sent"}  # identical for known and unknown addresses


@router.post("/password-reset/confirm")
def password_reset_confirm(
    request: Request, payload: ResetConfirmRequest, sessions: abuse.CounterSessions, gotrue: GoTrue, session: DbSession
) -> dict[str, str]:
    abuse.enforce(sessions, abuse.token_confirm_checks(get_settings(), network_digest(request)))
    validation.validate_new_password(payload.new_password)  # before the one-time token is spent
    try:
        tokens: TokenPair = _provider(gotrue.verify_token_hash, payload.token_hash, "recovery")
        _provider(gotrue.update_password, tokens.access_token, payload.new_password)
    except GoTrueError as error:
        if error.code in {"weak_password", "same_password"}:
            raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "password", "code": "WEAK"}]) from error
        raise ApiError("TOKEN_INVALID_OR_EXPIRED") from error
    try:  # every session of the account ends, including the one this link created
        _provider(gotrue.sign_out, tokens.access_token)
    except (GoTrueError, ApiError):
        logger.info("could not revoke sessions after a password reset")
    _security_notice(session, tokens.access_token)
    return {"status": "password_changed"}


def _security_notice(session: Session, access_token: str) -> None:
    """Tell the account holder their password changed (Notification spec 3, security notice). Best effort."""
    try:
        user_id = verify_access_token(access_token).user_id
        if session.get(User, user_id) is None:
            return  # never signed in here yet: no inbox to write to
        events.emit(session, "security.password_changed", user_id, {"user_id": str(user_id)}, aggregate_type="user")
        session.commit()
    except Exception:  # noqa: BLE001 - the password change itself already succeeded
        session.rollback()
        logger.warning("password-change notice was not queued")


# ---- session, CSRF, MFA, re-authentication ----


@router.get("/csrf")
def csrf_token(principal: MemberPrincipal) -> dict[str, str]:
    return {"csrf_token": csrf.issue(principal.csrf_binding)}


@router.get("/session")
def current_session(
    request: Request,
    principal: OptionalPrincipal,
    session: DbSession,
    redis_client: RedisDep,
    gotrue: GoTrue,
) -> dict[str, Any]:
    if principal is None:
        return {"authenticated": False}
    _record_member_visit(session, redis_client, principal)
    try:
        factors = gotrue.list_factors(principal.access_token)
    except (GoTrueError, GoTrueUnavailable):
        factors = []
    return _session_payload(principal, factors, session)


@router.post("/mfa/enroll")
def mfa_enroll(request: Request, principal: Annotated[Principal, Depends(require_csrf)], gotrue: GoTrue) -> dict[str, Any]:
    access = principal.access_token
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    try:
        body = _provider(gotrue.mfa_enroll, access, f"{principal.user.display_name[:40]}-{stamp}")
    except GoTrueError as error:
        raise ApiError("VALIDATION_FAILED") from error
    totp = body.get("totp") or {}
    return {"factor_id": body.get("id"), "secret": totp.get("secret"), "uri": totp.get("uri"), "qr_code": totp.get("qr_code")}


@router.post("/mfa/verify")
def mfa_verify(
    request: Request,
    response: Response,
    payload: MfaVerifyRequest,
    principal: Annotated[Principal, Depends(require_csrf)],
    gotrue: GoTrue,
) -> dict[str, Any]:
    access = principal.access_token
    try:
        challenge = _provider(gotrue.mfa_challenge, access, payload.factor_id)
        tokens: TokenPair = _provider(gotrue.mfa_verify, access, payload.factor_id, challenge, payload.code)
    except GoTrueError as error:
        raise ApiError("INVALID_CREDENTIALS") from error
    set_session_cookies(response, tokens)
    claims = verify_access_token(tokens.access_token)
    return {"aal": claims.aal, "auth_time": claims.auth_time.isoformat(), "csrf_token": csrf.issue(str(claims.session_id or principal.user.id))}


@router.post("/reauth")
def reauthenticate(
    request: Request,
    response: Response,
    payload: ReauthRequest,
    sessions: abuse.CounterSessions,
    principal: Annotated[Principal, Depends(require_csrf)],
    gotrue: GoTrue,
) -> dict[str, Any]:
    """Confirm the password (and the TOTP code for staff) again before a high-impact action."""
    email_digest, network = abuse.email_key(principal.user.email), network_digest(request)
    abuse.guard_login(sessions, email_digest, network)
    try:
        tokens: TokenPair = _provider(gotrue.sign_in, principal.user.email, payload.password)
    except GoTrueError as error:
        abuse.record_login_failure(sessions, email_digest, network)
        raise ApiError("INVALID_CREDENTIALS") from error
    factors = [f for f in _provider(gotrue.list_factors, tokens.access_token) if f.get("status") == "verified"]
    if factors:
        if not payload.code:
            raise ApiError("MFA_REQUIRED")
        factor_id = str(factors[0]["id"])
        try:
            challenge = _provider(gotrue.mfa_challenge, tokens.access_token, factor_id)
            tokens = _provider(gotrue.mfa_verify, tokens.access_token, factor_id, challenge, payload.code)
        except GoTrueError as error:
            abuse.record_login_failure(sessions, email_digest, network)
            raise ApiError("INVALID_CREDENTIALS") from error
    set_session_cookies(response, tokens)
    claims = verify_access_token(tokens.access_token)
    return {
        "aal": claims.aal,
        "auth_time": claims.auth_time.isoformat(),
        "csrf_token": csrf.issue(str(claims.session_id or principal.user.id)),
    }
