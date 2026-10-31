"""Session cookies and the request principal (Platform Foundation 8.5, Moderation spec 4).

The access token and the refresh token live in HttpOnly ``__Host-`` cookies. A request with an
expired access token is refreshed transparently once; every failure ends in ``AUTH_REQUIRED``.
Account state and staff role are read from the database on every request, never from the token.
"""

import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import csrf
from app.auth.gotrue import GoTrueClient, GoTrueError, GoTrueUnavailable, TokenPair, get_gotrue
from app.auth.tokens import Claims, InvalidToken, verify_access_token
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import AuthSessionActivity, User, UserRole

logger = logging.getLogger(__name__)

STAFF_ROLES = ("moderator", "superadmin")


@dataclass
class Principal:
    user: User
    claims: Claims
    role: str | None  # active staff role, from the database
    access_token: str = ""  # the current token: refreshed during this request if it had expired

    @property
    def csrf_binding(self) -> str:
        return str(self.claims.session_id or self.user.id)


def set_session_cookies(response: Response, tokens: TokenPair) -> None:
    settings = get_settings()
    common = {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}
    response.set_cookie(settings.session_cookie_name, tokens.access_token, max_age=tokens.expires_in, **common)  # type: ignore[arg-type]
    response.set_cookie(
        settings.refresh_cookie_name,
        tokens.refresh_token,
        max_age=settings.member_session_days * 86400,
        **common,  # type: ignore[arg-type]
    )


def clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    for name in (settings.session_cookie_name, settings.refresh_cookie_name):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


def active_role(session: Session, user_id: uuid.UUID) -> str | None:
    return session.scalar(select(UserRole.role).where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None)))


def provision_user(session: Session, claims: Claims) -> User:
    """Create the application row for an Auth identity on first sight (same id)."""
    user = session.get(User, claims.user_id)
    if user is not None:
        return user
    name = claims.display_name or (claims.email.split("@")[0] if claims.email else "Member")
    user = User(
        id=claims.user_id,
        email=claims.email,
        display_name=name[:80],
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:  # the same email already belongs to another application row
        session.rollback()
        logger.warning("could not provision a user: email already linked to another identity")
        raise ApiError("ACCOUNT_DISABLED") from error
    return user


def _touch_activity(session: Session, claims: Claims, now: datetime) -> datetime | None:
    """Record the request time for the session; return the previous time (for the inactivity limit)."""
    if claims.session_id is None:
        return None
    previous = session.scalar(
        select(AuthSessionActivity.last_seen_at).where(AuthSessionActivity.session_id == claims.session_id)
    )
    statement = insert(AuthSessionActivity).values(
        session_id=claims.session_id, user_id=claims.user_id, last_seen_at=now
    )
    session.execute(
        statement.on_conflict_do_update(index_elements=[AuthSessionActivity.session_id], set_={"last_seen_at": now})
    )
    return previous


def _read_claims(request: Request, response: Response, gotrue: GoTrueClient) -> tuple[Claims, str] | None:
    settings = get_settings()
    access = request.cookies.get(settings.session_cookie_name)
    refresh = request.cookies.get(settings.refresh_cookie_name)
    if access:
        try:
            return verify_access_token(access), access
        except InvalidToken:
            pass
    if not refresh:
        return None
    try:
        tokens = gotrue.refresh(refresh)
        claims = verify_access_token(tokens.access_token)
    except (GoTrueError, InvalidToken):
        clear_session_cookies(response)
        return None
    except GoTrueUnavailable as error:
        raise ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"}) from error
    set_session_cookies(response, tokens)
    return claims, tokens.access_token


def optional_principal(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    gotrue: Annotated[GoTrueClient, Depends(get_gotrue)],
) -> Principal | None:
    if not get_settings().auth_configured:
        return None
    found = _read_claims(request, response, gotrue)
    if found is None:
        return None
    claims, access_token = found
    user = provision_user(session, claims)
    if user.status != "active":
        from app.admin import cases  # noqa: PLC0415 - cases imports this module

        # A suspension whose time has passed ends now, so expiry does not wait for the daily job (P-01).
        if cases.expire_due_sanctions(session, user.id):
            session.flush()
            session.refresh(user)
    if user.status != "active":
        session.commit()
        raise ApiError("ACCOUNT_DISABLED")
    role = active_role(session, user.id)
    now = datetime.now(UTC)
    previous = _touch_activity(session, claims, now)
    limit = timedelta(hours=get_settings().superadmin_inactivity_hours)
    if role == "superadmin" and previous is not None and now - previous > limit:
        session.commit()
        with contextlib.suppress(GoTrueError, GoTrueUnavailable):
            gotrue.sign_out(access_token)
        clear_session_cookies(response)
        return None
    session.commit()
    return Principal(user=user, claims=claims, role=role, access_token=access_token)


OptionalPrincipal = Annotated[Principal | None, Depends(optional_principal)]


def require_member(principal: OptionalPrincipal) -> Principal:
    if principal is None:
        raise ApiError("AUTH_REQUIRED")
    return principal


MemberPrincipal = Annotated[Principal, Depends(require_member)]


def require_csrf(request: Request, principal: MemberPrincipal) -> Principal:
    csrf.check_origin(request)
    csrf.require_valid(request, principal.csrf_binding)
    return principal


def _record_role_denial(session: Session, principal: Principal, request: Request, required: tuple[str, ...]) -> None:
    """A staff member asked for something their role does not allow: write `denied.role` in its own committed
    transaction (the request is failing anyway) and let repeated denials raise the security alert. A non-staff
    caller gets 404 and is not recorded, so the log cannot be filled by strangers probing the routes."""
    from app.models import AuditEvent  # noqa: PLC0415
    from app.notify import alerts  # noqa: PLC0415

    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    try:
        session.rollback()
        session.add(
            AuditEvent(
                actor_user_id=principal.user.id, actor_role_snapshot=principal.role, action="denied.role", target_type="route",
                target_id=f"{request.method} {path}"[:64], reason=f"needs {' or '.join(required)}",
                event_metadata={"required": list(required), "method": request.method, "route": path},
            )
        )
        session.commit()
        if alerts.check_denials(session, principal.user.id):
            session.commit()
    except Exception:  # noqa: BLE001 - the 403 is what the caller needs
        session.rollback()
        logger.warning("could not record a denied attempt")


def staff_principal(*roles: str):  # type: ignore[no-untyped-def]
    """Dependency factory. Non-staff get 404 (the existence of staff routes is not disclosed, spec 2.4);
    staff of another role get 403. Staff must have passed TOTP (AAL2) as the policy requires."""

    def dependency(request: Request, principal: MemberPrincipal, session: Annotated[Session, Depends(get_session)]) -> Principal:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            csrf.check_origin(request)
            csrf.require_valid(request, principal.csrf_binding)
        if principal.role is None:
            raise ApiError("NOT_FOUND")
        if principal.role not in roles:
            _record_role_denial(session, principal, request, roles)
            raise ApiError("FORBIDDEN")
        settings = get_settings()
        needs_mfa = principal.role == "superadmin" or settings.require_mfa_for_moderators
        if needs_mfa and not principal.claims.mfa_verified:
            raise ApiError("MFA_REQUIRED")
        return principal

    return dependency


def require_recent_auth(principal: Principal) -> None:
    window = timedelta(minutes=get_settings().reauth_window_minutes)
    if datetime.now(UTC) - principal.claims.auth_time > window:
        raise ApiError("REAUTH_REQUIRED")
