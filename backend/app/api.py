import base64
import enum
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app import abuse, media, visits
from app import review_parameters as rp
from app.abuse import CounterSessions
from app.admin import cases
from app.admin.cases import ensure_not_restricted
from app.auth import csrf
from app.auth.sessions import MemberPrincipal, OptionalPrincipal, Principal
from app.auth.validation import public_author_name
from app.client_address import network_digest, trusted_client_address
from app.config import get_settings
from app.db import get_session
from app.destination_api import public_cache_headers
from app.errors import ApiError
from app.guest_tag import display_guest_tag
from app.limits import guest_submit_limit, guest_visit_limit, limiter, receipt_limit
from app.models import (
    DestinationRatingStats,
    ModerationDecision,
    PlatformRole,
    RatingAudience,
    Review,
    ReviewRevision,
    ReviewStatus,
    User,
    UserPlatformRole,
)
from app.ops import events
from app.redis_client import RedisDep
from app.schemas import (
    CategoryParameter,
    ChoiceOption,
    ConflictFlagRequest,
    GuestAppealCreated,
    GuestAppealRequest,
    GuestReviewCreate,
    GuestReviewCreated,
    GuestVisitRequest,
    HealthResponse,
    LocalizedText,
    ModerationQueueItem,
    ModerationRequest,
    ModerationResult,
    MyReviews,
    PublicReview,
    RatingParameter,
    RatingRules,
    ReceiptStatus,
    ReceiptStatusRequest,
    ReviewDetail,
    ReviewEdit,
    ReviewEdited,
    ReviewFeed,
    ReviewParameters,
    TextParameter,
    WithdrawRequest,
)
from app.services import (
    ReviewError,
    category_averages,
    edit_pending_review,
    encode_cursor,
    find_recoverable_draft,
    list_member_reviews,
    moderate_review,
    rejection_details,
    review_appeal_state,
    review_detail,
    revision_category_ratings,
    set_review_conflict,
    submit_guest_review,
    verify_receipt,
    withdraw_review,
)
from app.storage import StorageClient, get_storage
from app.turnstile import ACTION_GUEST_REVIEW, TurnstileDep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def _raise_service_error(error: Exception) -> NoReturn:
    if isinstance(error, ReviewError):
        raise ApiError(error.code) from error
    raise error


def require_staff(
    x_test_staff_id: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    settings = get_settings()
    if settings.is_production or not settings.allow_test_staff_header:
        raise ApiError("STAFF_AUTH_NOT_CONFIGURED")
    if x_test_staff_id is None:
        raise ApiError("AUTH_REQUIRED")
    try:
        user_id = uuid.UUID(x_test_staff_id)
    except ValueError as error:
        raise ApiError("AUTH_REQUIRED") from error

    now = datetime.now(UTC)
    user = session.scalar(
        select(User)
        .join(UserPlatformRole, UserPlatformRole.user_id == User.id)
        .join(PlatformRole, PlatformRole.id == UserPlatformRole.role_id)
        .where(
            User.id == user_id,
            PlatformRole.code.in_(["MODERATOR", "ADMINISTRATOR", "SUPER_ADMINISTRATOR"]),
            or_(UserPlatformRole.expires_at.is_(None), UserPlatformRole.expires_at > now),
        )
    )
    if user is None:
        raise ApiError("FORBIDDEN")
    return user


@router.get("/health", response_model=HealthResponse, operation_id="health_get")
@router.head("/health", response_model=HealthResponse, operation_id="health_head")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse, operation_id="health_ready_get")
@router.head("/health/ready", response_model=HealthResponse, operation_id="health_ready_head")
def health_ready(session: Session = Depends(get_session)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except Exception as error:
        logger.exception("readiness check failed")
        raise ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"}) from error
    return HealthResponse(status="ok")


@router.post(
    "/reviews/guest",
    response_model=GuestReviewCreated,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(guest_submit_limit)
def create_guest_review(
    request: Request,
    response: Response,
    payload: GuestReviewCreate,
    sessions: CounterSessions,
    verify_challenge: TurnstileDep,
    session: Session = Depends(get_session),
) -> GuestReviewCreated:
    """Order of checks (API.md 5.2, PF 14.4)."""
    settings = get_settings()
    try:
        # 1-2. Schema and receipt format are validated; a recoverable draft returns here,
        #      free of charge: no challenge, no counters.
        recovered = find_recoverable_draft(session, payload)
        if recovered is not None:
            response.status_code = status.HTTP_200_OK
            return GuestReviewCreated(
                review_id=recovered.id,
                status=recovered.status,
                version=recovered.version,
                duplicate_recovered=True,
            )
        # 3. Idempotency-Key replay: WP4.
        # Emergency switch: stop new Guest writes before spending a challenge.
        abuse.ensure_guest_writes_allowed(settings)
        # 4. Turnstile (hostname and action checked; single use).
        address = trusted_client_address(request)
        verify_challenge(
            payload.turnstile_token,
            action=ACTION_GUEST_REVIEW,
            remote_address=str(address) if address else None,
        )
        # 5-6. Durable counters commit on their own before the limits and ceilings are checked.
        abuse.enforce(
            sessions,
            abuse.guest_submit_checks(
                settings, abuse.scope_key(payload.guest_scope_secret), network_digest(request)
            ),
        )
        abuse.check_pending_ceilings(session, payload.destination_id)
        # 7. Business transaction.
        result = submit_guest_review(session, payload)
        session.commit()
        events.count("reviews.submitted")
    except ReviewError as error:
        session.rollback()
        _raise_service_error(error)
    if result.duplicate_recovered:
        response.status_code = status.HTTP_200_OK
    return GuestReviewCreated(
        review_id=result.review.id,
        status=result.review.status,
        version=result.review.version,
        duplicate_recovered=result.duplicate_recovered,
    )


def _text(pair: tuple[str, str]) -> LocalizedText:
    return LocalizedText(bn=pair[0], en=pair[1])


def _choices[E: enum.Enum](labels: Mapping[E, tuple[str, str]]) -> list[ChoiceOption]:
    return [ChoiceOption(value=str(member.value), label=_text(label)) for member, label in labels.items()]


@router.get("/review-parameters", response_model=ReviewParameters)
@limiter.limit("60/minute")
def review_parameters(request: Request, response: Response) -> ReviewParameters:
    """The review form and rating rules; `GuestReviewCreate` enforces the same limits."""
    response.headers.update(public_cache_headers())
    rating = RatingParameter(required=True, min=rp.RATING_MIN, max=rp.RATING_MAX)
    return ReviewParameters(
        version=rp.PARAMETERS_VERSION,
        overall_rating=rating,
        categories=[
            CategoryParameter(
                code=category,
                name=_text(name),
                prompt=_text(prompt),
                required=False,
                min=rp.RATING_MIN,
                max=rp.RATING_MAX,
            )
            for category, (name, prompt) in rp.CATEGORY_LABELS.items()
        ],
        note=TextParameter(field="body", required=True, min_length=rp.NOTE_MIN, max_length=rp.NOTE_MAX),
        title=TextParameter(field="title", required=True, min_length=rp.TITLE_MIN, max_length=rp.TITLE_MAX),
        display_name=TextParameter(
            field="guest_display_name", required=True, min_length=1, max_length=rp.DISPLAY_NAME_MAX
        ),
        traveller_types=_choices(rp.TRAVELLER_LABELS),
        comfort_tiers=_choices(rp.COMFORT_LABELS),
        languages=_choices(rp.LANGUAGE_LABELS),
        rating_rules=RatingRules(
            guest_feedback="Mean of the overall rating of published Guest reviews, shown with its count.",
            community_rating=(
                "Bayesian (sum + m * C) / (count + m) over eligible Verified Member reviews; "
                "shown only from community_min_reviews, otherwise Seeded Destination Selection."
            ),
            community_prior_mean=rp.COMMUNITY_PRIOR_MEAN,
            community_prior_weight=rp.COMMUNITY_PRIOR_WEIGHT,
            community_min_reviews=rp.COMMUNITY_MIN_REVIEWS,
            category_averages=(
                "Mean of each rated category per audience (Guest or Community), never merged; "
                "a category is left out until it has a rating."
            ),
        ),
    )


@router.post("/guest-visits", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(guest_visit_limit)
def create_guest_visit(
    request: Request,
    payload: GuestVisitRequest,
    sessions: CounterSessions,
    redis_client: RedisDep,
) -> Response:
    """Count one guest visit-day in Redis (Guest-Identity-and-Visits 4.2). Nothing identifies the guest.

    The browser sends this at most once per Dhaka day. Counting is best effort: a Redis failure is
    recorded in ``visits_dropped`` and the response is still 204.
    """
    abuse.enforce(sessions, abuse.guest_visit_checks(get_settings(), network_digest(request)))
    if get_settings().visit_counter_enabled:
        visits.record_visit(redis_client, "guest", new=payload.first_visit)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.get("/staff/moderation/reviews", response_model=list[ModerationQueueItem])
def moderation_queue(
    staff: User = Depends(require_staff),
    session: Session = Depends(get_session),
) -> list[ModerationQueueItem]:
    del staff
    rows = session.execute(
        select(Review, ReviewRevision)
        .join(ReviewRevision, ReviewRevision.id == Review.current_revision_id)
        .where(Review.status.in_([ReviewStatus.PENDING, ReviewStatus.UNDER_REVIEW]))
        .order_by(Review.created_at.asc(), Review.id.asc())
        .limit(100)
    ).all()
    categories = revision_category_ratings(session, [revision.id for _, revision in rows])
    return [
        ModerationQueueItem(
            review_id=review.id,
            status=review.status,
            version=review.version,
            counted_rating=review.counted_rating,
            destination_id=review.destination_id,
            guest_display_name=review.guest_display_name,
            guest_tag=display_guest_tag(review.guest_tag),
            overall_rating=review.overall_rating,
            title=revision.title,
            body=revision.body,
            category_ratings=categories[revision.id],
            created_at=review.created_at,
        )
        for review, revision in rows
    ]


@router.post(
    "/staff/moderation/reviews/{review_id}/decisions",
    response_model=ModerationResult,
)
def decide_review(
    review_id: uuid.UUID,
    payload: ModerationRequest,
    staff: User = Depends(require_staff),
    session: Session = Depends(get_session),
) -> ModerationResult:
    decision = ModerationDecision(payload.decision)
    try:
        review = moderate_review(
            session,
            review_id=review_id,
            actor_user_id=staff.id,
            expected_version=payload.expected_version,
            decision=decision,
            reason_code=payload.reason_code,
            note=payload.note,
        )
        session.commit()
        return ModerationResult(
            review_id=review.id,
            status=review.status,
            version=review.version,
            counted_rating=review.counted_rating,
        )
    except ReviewError as error:
        session.rollback()
        _raise_service_error(error)


@router.put(
    "/staff/moderation/reviews/{review_id}/conflict",
    response_model=ModerationResult,
)
def change_review_conflict(
    review_id: uuid.UUID,
    payload: ConflictFlagRequest,
    staff: User = Depends(require_staff),
    session: Session = Depends(get_session),
) -> ModerationResult:
    try:
        review = set_review_conflict(
            session,
            review_id=review_id,
            actor_user_id=staff.id,
            expected_version=payload.expected_version,
            conflict_declared=payload.conflict_declared,
            reason_code=payload.reason_code,
            note=payload.note,
        )
        session.commit()
        return ModerationResult(
            review_id=review.id,
            status=review.status,
            version=review.version,
            counted_rating=review.counted_rating,
        )
    except ReviewError as error:
        session.rollback()
        _raise_service_error(error)


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded).decode("utf-8")
        timestamp, review_id = raw.rsplit("|", 1)
        moment = datetime.fromisoformat(timestamp)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment, uuid.UUID(review_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise ApiError("INVALID_CURSOR") from error


@router.get("/destinations/{destination_id}/reviews", response_model=ReviewFeed)
@limiter.limit("60/minute")
def public_reviews(
    request: Request,
    response: Response,
    destination_id: uuid.UUID,
    after: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_session),
    storage: StorageClient = Depends(get_storage),
) -> ReviewFeed:
    statement = (
        select(Review, ReviewRevision)
        .join(ReviewRevision, ReviewRevision.id == Review.current_revision_id)
        .where(
            Review.destination_id == destination_id,
            Review.status == ReviewStatus.PUBLISHED,
            Review.published_at.is_not(None),
        )
        .order_by(Review.published_at.desc(), Review.id.desc())
        .limit(limit + 1)
    )
    if after:
        published_at, review_id = _decode_cursor(after)
        statement = statement.where(
            or_(
                Review.published_at < published_at,
                and_(Review.published_at == published_at, Review.id < review_id),
            )
        )
    rows = session.execute(statement).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    categories = revision_category_ratings(session, [revision.id for _, revision in rows])
    attached = media.published_media(session, storage, [review.id for review, _ in rows])
    author_ids = {review.author_user_id for review, _ in rows if review.author_user_id}
    authors = dict(session.execute(select(User.id, User.display_name).where(User.id.in_(author_ids))).all()) if author_ids else {}
    items = [
        PublicReview(
            id=review.id,
            author_type="MEMBER" if review.author_user_id else "GUEST",
            guest_tag=display_guest_tag(review.guest_tag),
            status=review.status,
            overall_rating=review.overall_rating,
            published_at=review.published_at,
            title=revision.title,
            body=revision.body,
            category_ratings=categories[revision.id],
            author_display_name=public_author_name(authors.get(review.author_user_id)) if review.author_user_id else None,
            media=attached.get(review.id, []),
        )
        for review, revision in rows
        if review.published_at is not None
    ]
    next_cursor = None
    if has_more and rows:
        last_review = rows[-1][0]
        if last_review.published_at is not None:
            next_cursor = encode_cursor(last_review.published_at, last_review.id)
    stats = session.get(DestinationRatingStats, destination_id)
    guest_count = stats.guest_rating_count if stats else 0
    guest_average = (
        stats.guest_rating_sum / guest_count if stats is not None and guest_count else None
    )
    response.headers.update(public_cache_headers())
    return ReviewFeed(
        items=items,
        next_cursor=next_cursor,
        guest_rating_average=guest_average,
        guest_rating_count=guest_count,
        guest_category_averages=category_averages(session, [destination_id]).get(
            (destination_id, RatingAudience.GUEST), []
        ),
    )


_RECEIPT_FAILURE_CODES = {"RECEIPT_NOT_FOUND", "INVALID_RECEIPT_FORMAT"}


def _receipt_status(session: Session, review: Review) -> ReceiptStatus:
    details = rejection_details(session, review)
    return ReceiptStatus(
        review_id=review.id,
        status=review.status,
        version=review.version,
        published_at=review.published_at,
        decision_reason=details.decision_reason,
        appeal_deadline=details.appeal_deadline,
        appeal_state=review_appeal_state(session, review.id),
    )


def _guard_receipt_operation(
    request: Request, sessions: CounterSessions, receipt_secret: str
) -> tuple[bytes, bytes]:
    """Progressive delay after repeated failures, then the per-receipt and per-network limits."""
    settings = get_settings()
    receipt, network = abuse.receipt_key(receipt_secret), network_digest(request)
    abuse.guard_receipt_failures(sessions, receipt, network)
    abuse.enforce(sessions, abuse.receipt_op_checks(settings, receipt, network))
    return receipt, network


@router.post("/review-receipts/status", response_model=ReceiptStatus)
@limiter.limit(receipt_limit)
def receipt_status(
    request: Request,
    payload: ReceiptStatusRequest,
    sessions: CounterSessions,
    session: Session = Depends(get_session),
) -> ReceiptStatus:
    receipt, network = _guard_receipt_operation(request, sessions, payload.receipt_secret)
    try:
        review = verify_receipt(session, payload.review_id, payload.receipt_secret)
        result = _receipt_status(session, review)
        session.commit()  # persists a re-digest under the current key after rotation
    except ReviewError as error:
        session.rollback()
        if error.code in _RECEIPT_FAILURE_CODES:
            abuse.record_receipt_failure(sessions, receipt, network)
        _raise_service_error(error)
    return result


def _owner_session(request: Request, principal: Principal | None) -> Principal:
    """A signed-in member acting on their own review: session and CSRF token, never a receipt."""
    if principal is None:
        raise ApiError("AUTH_REQUIRED")
    csrf.check_origin(request)
    csrf.require_valid(request, principal.csrf_binding)
    return principal


@router.post("/reviews/{review_id}/withdraw", response_model=ReceiptStatus)
@limiter.limit(receipt_limit)
def withdraw_guest_review(
    request: Request,
    review_id: uuid.UUID,
    payload: WithdrawRequest,
    sessions: CounterSessions,
    principal: OptionalPrincipal,
    session: Session = Depends(get_session),
) -> ReceiptStatus:
    """A Guest sends the receipt; a signed-in member omits it and uses the session (API.md 5.4)."""
    if payload.receipt_secret is None:
        owner = _owner_session(request, principal)
        try:
            review = withdraw_review(session, review_id, payload.expected_version, author_id=owner.user.id)
            result = _receipt_status(session, review)
            session.commit()
        except ReviewError as error:
            session.rollback()
            _raise_service_error(error)
        return result
    receipt, network = _guard_receipt_operation(request, sessions, payload.receipt_secret)
    try:
        verify_receipt(session, review_id, payload.receipt_secret)
        review = withdraw_review(session, review_id, payload.expected_version)
        result = _receipt_status(session, review)
        session.commit()
    except ReviewError as error:
        session.rollback()
        if error.code in _RECEIPT_FAILURE_CODES:
            abuse.record_receipt_failure(sessions, receipt, network)
        _raise_service_error(error)
    return result


@router.patch("/reviews/{review_id}/pending", response_model=ReviewEdited)
@limiter.limit(receipt_limit)
def edit_unpublished_review(
    request: Request,
    review_id: uuid.UUID,
    payload: ReviewEdit,
    sessions: CounterSessions,
    principal: OptionalPrincipal,
    session: Session = Depends(get_session),
) -> ReviewEdited:
    """Edit a review that is still PENDING or CHANGES_REQUESTED as a new revision (API.md 5.5)."""
    if payload.receipt_secret is None:
        owner = _owner_session(request, principal)
        ensure_not_restricted(session, owner.user.id)  # a restricted or suspended member cannot post (spec 6.4)
        try:
            outcome = edit_pending_review(session, review_id, payload, author_id=owner.user.id)
            session.commit()
        except ReviewError as error:
            session.rollback()
            _raise_service_error(error)
    else:
        receipt, network = _guard_receipt_operation(request, sessions, payload.receipt_secret)
        try:
            verify_receipt(session, review_id, payload.receipt_secret)
            outcome = edit_pending_review(session, review_id, payload)
            session.commit()
        except ReviewError as error:
            session.rollback()
            if error.code in _RECEIPT_FAILURE_CODES:
                abuse.record_receipt_failure(sessions, receipt, network)
            _raise_service_error(error)
    return ReviewEdited(
        review_id=outcome.review.id, status=outcome.review.status, version=outcome.review.version, revision=outcome.revision
    )


@router.post("/review-receipts/appeals", response_model=GuestAppealCreated, status_code=status.HTTP_201_CREATED)
@limiter.limit(receipt_limit)
def appeal_rejected_review(
    request: Request,
    payload: GuestAppealRequest,
    sessions: CounterSessions,
    session: Session = Depends(get_session),
) -> GuestAppealCreated:
    """A Guest appeals the rejection of their review with the receipt (API.md 5.6)."""
    receipt, network = _guard_receipt_operation(request, sessions, payload.receipt_secret)
    try:
        verify_receipt(session, payload.review_id, payload.receipt_secret)
        appeal = cases.create_guest_appeal(session, payload.review_id, statement=payload.statement)
        session.commit()
    except ReviewError as error:
        session.rollback()
        if error.code in _RECEIPT_FAILURE_CODES:
            abuse.record_receipt_failure(sessions, receipt, network)
        _raise_service_error(error)
    except ApiError:
        session.rollback()
        raise
    return GuestAppealCreated(appeal_id=appeal.id, status="OPEN", deadline_at=appeal.deadline_at)


@router.get("/reviews/mine", response_model=MyReviews)
def my_reviews(
    response: Response,
    principal: MemberPrincipal,
    status_filter: ReviewStatus | None = Query(default=None, alias="status"),
    destination_id: uuid.UUID | None = None,
    after: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_session),
) -> MyReviews:
    """The signed-in member's own reviews, newest first, with an opaque cursor (Review.md 9.3)."""
    try:
        items, next_cursor = list_member_reviews(
            session, principal.user.id, status=status_filter, destination_id=destination_id, after=after, limit=limit
        )
    except ReviewError as error:
        _raise_service_error(error)
    response.headers["Cache-Control"] = "no-store"
    return MyReviews(items=items, next_cursor=next_cursor)


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(
    response: Response,
    review_id: uuid.UUID,
    principal: MemberPrincipal,
    session: Session = Depends(get_session),
) -> ReviewDetail:
    """The owner's full view, or a moderator's. Anyone else sees 404, so existence is not disclosed."""
    settings = get_settings()
    staff = principal.role in ("moderator", "superadmin")
    if staff and (principal.role == "superadmin" or settings.require_mfa_for_moderators) and not principal.claims.mfa_verified:
        raise ApiError("MFA_REQUIRED")
    review = session.get(Review, review_id)
    if review is None or (not staff and review.author_user_id != principal.user.id):
        raise ApiError("NOT_FOUND")
    response.headers["Cache-Control"] = "no-store"
    try:
        return review_detail(session, review, staff=staff)
    except ReviewError as error:
        _raise_service_error(error)
