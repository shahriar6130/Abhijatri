from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    DDL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class DestinationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    DELETED = "DELETED"


class RatingEligibility(str, enum.Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_GUEST = "INELIGIBLE_GUEST"
    INELIGIBLE_UNVERIFIED = "INELIGIBLE_UNVERIFIED"
    INELIGIBLE_DUPLICATE = "INELIGIBLE_DUPLICATE"
    INELIGIBLE_CONFLICT = "INELIGIBLE_CONFLICT"
    INELIGIBLE_REPORTED = "INELIGIBLE_REPORTED"
    INELIGIBLE_REMOVED = "INELIGIBLE_REMOVED"


class RevisionStatus(str, enum.Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    TOMBSTONED = "TOMBSTONED"
    # Replaced by a newer revision while the review was still unpublished (Review.md 5.2).
    SUPERSEDED = "SUPERSEDED"


class ReviewLanguage(str, enum.Enum):
    BN = "BN"
    EN = "EN"
    MIXED = "MIXED"


class TravellerType(str, enum.Enum):
    SOLO = "SOLO"
    STUDENT = "STUDENT"
    COUPLE = "COUPLE"
    FAMILY = "FAMILY"
    GROUP = "GROUP"


class ComfortTier(str, enum.Enum):
    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ReviewCategory(str, enum.Enum):
    """Review.md 3.1 and amendment A2: the seven frozen rating categories, in display order."""

    CLEANLINESS = "CLEANLINESS"
    ACCESSIBILITY = "ACCESSIBILITY"
    HOSPITALITY = "HOSPITALITY"
    FOOD = "FOOD"
    TRANSPORT = "TRANSPORT"
    SAFETY_PERCEPTION = "SAFETY_PERCEPTION"
    VALUE = "VALUE"


class RatingAudience(str, enum.Enum):
    """Which aggregate a counted rating belongs to (Review.md 6.1, 6.2); never merged."""

    GUEST = "GUEST"
    COMMUNITY = "COMMUNITY"


class ModerationDecision(str, enum.Enum):
    PUBLISH = "PUBLISH"
    REJECT = "REJECT"
    HIDE = "HIDE"
    RESTORE = "RESTORE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    SET_CONFLICT = "SET_CONFLICT"
    CLEAR_CONFLICT = "CLEAR_CONFLICT"


class SourceType(str, enum.Enum):
    OFFICIAL = "OFFICIAL"
    TEAM_RESEARCH = "TEAM_RESEARCH"
    OPEN_LICENCE = "OPEN_LICENCE"
    VENDOR_LICENSED = "VENDOR_LICENSED"
    OTHER = "OTHER"


class GuideCategory(str, enum.Enum):
    ATTRACTION = "ATTRACTION"
    ACCOMMODATION = "ACCOMMODATION"
    FOOD = "FOOD"
    TRANSPORT = "TRANSPORT"
    LOCAL_PRACTICE = "LOCAL_PRACTICE"


class AdvisorySeverity(str, enum.Enum):
    INFO = "INFO"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ContactKind(str, enum.Enum):
    POLICE = "POLICE"
    TOURIST_POLICE = "TOURIST_POLICE"
    AMBULANCE = "AMBULANCE"
    FIRE = "FIRE"
    HOSPITAL = "HOSPITAL"
    COAST_GUARD = "COAST_GUARD"
    FOREST_OFFICE = "FOREST_OFFICE"
    LOCAL_GUIDE = "LOCAL_GUIDE"
    OTHER = "OTHER"


class ProvenanceMixin:
    """Source, date and licence metadata required on every maintained record (PF 17)."""

    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    verified_on: Mapped[date] = mapped_column(Date, nullable=False)
    next_review_on: Mapped[date | None] = mapped_column(Date)
    licence: Mapped[str] = mapped_column(String(160), nullable=False)
    researcher: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(120))


class Destination(Base):
    __tablename__ = "destinations"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name="ck_destination_latitude_range"
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="ck_destination_longitude_range"
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="ck_destination_coordinates_pair"),
        Index(
            "ix_destinations_published_name",
            "name_en",
            "id",
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[DestinationStatus] = mapped_column(
        Enum(DestinationStatus, name="destination_status"),
        nullable=False,
        default=DestinationStatus.DRAFT,
    )
    name_bn: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    region_bn: Mapped[str | None] = mapped_column(String(160))
    region_en: Mapped[str | None] = mapped_column(String(160))
    summary_bn: Mapped[str | None] = mapped_column(Text)
    summary_en: Mapped[str | None] = mapped_column(Text)
    seasonality_bn: Mapped[str | None] = mapped_column(Text)
    seasonality_en: Mapped[str | None] = mapped_column(Text)
    restrictions_bn: Mapped[str | None] = mapped_column(Text)
    restrictions_en: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    content_licence: Mapped[str | None] = mapped_column(String(160))
    content_verified_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DestinationGuideItem(ProvenanceMixin, Base):
    __tablename__ = "destination_guide_items"
    __table_args__ = (
        Index("ix_guide_items_destination_category", "destination_id", "category", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[GuideCategory] = mapped_column(Enum(GuideCategory, name="guide_category"), nullable=False)
    title_bn: Mapped[str] = mapped_column(String(160), nullable=False)
    title_en: Mapped[str] = mapped_column(String(160), nullable=False)
    body_bn: Mapped[str] = mapped_column(Text, nullable=False)
    body_en: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DestinationAdvisory(ProvenanceMixin, Base):
    __tablename__ = "destination_advisories"
    __table_args__ = (
        CheckConstraint("valid_until >= effective_on", name="ck_advisory_validity_window"),
        Index("ix_advisories_destination_valid_until", "destination_id", "valid_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[AdvisorySeverity] = mapped_column(
        Enum(AdvisorySeverity, name="advisory_severity"), nullable=False
    )
    title_bn: Mapped[str] = mapped_column(String(160), nullable=False)
    title_en: Mapped[str] = mapped_column(String(160), nullable=False)
    text_bn: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DestinationContact(ProvenanceMixin, Base):
    __tablename__ = "destination_contacts"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name="ck_contact_latitude_range"
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="ck_contact_longitude_range"
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="ck_contact_coordinates_pair"),
        CheckConstraint(r"phone ~ '^\+?[0-9][0-9 -]{2,30}$'", name="ck_contact_phone_format"),
        Index("ix_contacts_destination_kind", "destination_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ContactKind] = mapped_column(Enum(ContactKind, name="contact_kind"), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    address_bn: Mapped[str | None] = mapped_column(String(300))
    address_en: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_team_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    # Member visit days (Guest-Identity-and-Visits 4.3): set by GET /auth/session once R04 exists.
    first_visit_on: Mapped[date | None] = mapped_column(Date)
    last_visit_on: Mapped[date | None] = mapped_column(Date)
    # Account state (Moderation spec 4.2): a disabled account fails closed even with a valid token.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),)


class UserRole(Base):
    """Staff role grants (Moderation spec 2.2): at most one active role per user, enforced by the index."""

    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint("role IN ('moderator', 'superadmin')", name="ck_user_roles_role"),
        Index("uq_user_roles_one_active", "user_id", unique=True, postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RoleAdminGuard(Base):
    """One row, locked ``FOR UPDATE`` to serialise superadmin grants and revocations (spec 6.1)."""

    __tablename__ = "role_admin_guard"
    __table_args__ = (CheckConstraint("id = 1", name="ck_role_admin_guard_single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)


class AuthSessionActivity(Base):
    """Last request per Supabase session, for the superadmin inactivity limit (spec 4.1)."""

    __tablename__ = "auth_session_activity"
    __table_args__ = (Index("ix_auth_session_activity_user", "user_id"),)

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PlatformRole(Base):
    __tablename__ = "platform_roles"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)


class UserPlatformRole(Base):
    __tablename__ = "user_platform_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_platform_role"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("platform_roles.id", ondelete="RESTRICT"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    verification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(240))


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("overall_rating BETWEEN 1 AND 5", name="ck_review_rating_range"),
        CheckConstraint(
            "counted_rating IS NULL OR counted_rating BETWEEN 1 AND 5",
            name="ck_review_counted_rating_range",
        ),
        CheckConstraint(
            "(author_user_id IS NOT NULL AND guest_display_name IS NULL AND guest_scope_hash IS NULL) OR "
            "(author_user_id IS NULL AND guest_display_name IS NOT NULL AND guest_scope_hash IS NOT NULL)",
            name="ck_review_author_shape",
        ),
        CheckConstraint(
            "(guest_scope_hash IS NULL) = (guest_scope_key_id IS NULL)",
            name="ck_review_scope_key_pair",
        ),
        CheckConstraint(
            "guest_tag IS NULL OR (author_user_id IS NULL AND guest_tag ~ '^[0-9A-HJKMNP-TV-Z]{10}$')",
            name="ck_review_guest_tag",
        ),
        Index(
            "uq_reviews_member_draft",
            "author_user_id",
            "client_draft_id",
            unique=True,
            postgresql_where=text("author_user_id IS NOT NULL"),
        ),
        Index(
            "uq_reviews_guest_draft",
            "guest_scope_hash",
            "client_draft_id",
            unique=True,
            postgresql_where=text("author_user_id IS NULL"),
        ),
        Index(
            "uq_reviews_member_active_visit",
            "author_user_id",
            "destination_id",
            "visit_month",
            unique=True,
            postgresql_where=text(
                "author_user_id IS NOT NULL AND duplicate_override = false AND "
                "status IN ('PENDING', 'UNDER_REVIEW', 'CHANGES_REQUESTED', 'PUBLISHED', 'HIDDEN')"
            ),
        ),
        Index(
            "ix_reviews_member_history",
            "author_user_id",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=text("author_user_id IS NOT NULL"),
        ),
        Index(
            "ix_reviews_published_feed",
            "destination_id",
            text("published_at DESC"),
            text("id DESC"),
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    guest_display_name: Mapped[str | None] = mapped_column(String(80))
    guest_scope_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    guest_scope_key_id: Mapped[str | None] = mapped_column(String(16))
    # Public pseudonym derived from the scope secret (Guest-Identity-and-Visits 3.1), no dash.
    guest_tag: Mapped[str | None] = mapped_column(CHAR(10))
    client_draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "review_revisions.id",
            name="fk_review_current_revision",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status"), nullable=False, default=ReviewStatus.PENDING
    )
    rating_eligibility: Mapped[RatingEligibility] = mapped_column(
        Enum(RatingEligibility, name="rating_eligibility"),
        nullable=False,
        default=RatingEligibility.NOT_EVALUATED,
    )
    conflict_declared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overall_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    counted_rating: Mapped[int | None] = mapped_column(SmallInteger)
    visit_month: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    current_revision: Mapped[ReviewRevision | None] = relationship(
        "ReviewRevision",
        primaryjoin="Review.current_revision_id == ReviewRevision.id",
        foreign_keys=[current_revision_id],
        post_update=True,
    )


class ReviewRevision(Base):
    __tablename__ = "review_revisions"
    __table_args__ = (
        UniqueConstraint("review_id", "sequence", name="uq_review_revision_sequence"),
        CheckConstraint("overall_rating BETWEEN 1 AND 5", name="ck_revision_rating_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RevisionStatus] = mapped_column(
        Enum(RevisionStatus, name="revision_status"), nullable=False, default=RevisionStatus.PENDING
    )
    language: Mapped[ReviewLanguage] = mapped_column(
        Enum(ReviewLanguage, name="review_language"), nullable=False
    )
    traveller_type: Mapped[TravellerType] = mapped_column(
        Enum(TravellerType, name="traveller_type"), nullable=False
    )
    comfort_tier: Mapped[ComfortTier] = mapped_column(
        Enum(ComfortTier, name="comfort_tier"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    overall_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ReviewCategoryRating(Base):
    """One optional category score of a revision; an absent row means not applicable."""

    __tablename__ = "review_category_ratings"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_category_rating_range"),)

    revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[ReviewCategory] = mapped_column(
        Enum(ReviewCategory, name="review_category"), primary_key=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ReviewReceipt(Base):
    """Keyed digest of a client-generated receipt. The raw receipt is never stored."""

    __tablename__ = "review_receipts"
    __table_args__ = (UniqueConstraint("key_id", "digest", name="uq_review_receipt_key_digest"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    key_id: Mapped[str] = mapped_column(String(16), nullable=False)
    digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DestinationRatingStats(Base):
    __tablename__ = "destination_rating_stats"
    __table_args__ = (
        CheckConstraint("community_rating_count >= 0", name="ck_community_count_nonnegative"),
        CheckConstraint("guest_rating_count >= 0", name="ck_guest_count_nonnegative"),
        CheckConstraint("community_rating_sum >= 0", name="ck_community_sum_nonnegative"),
        CheckConstraint("guest_rating_sum >= 0", name="ck_guest_sum_nonnegative"),
    )

    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), primary_key=True
    )
    community_rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    community_rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    guest_rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    guest_rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DestinationCategoryStats(Base):
    """O(1) per-category sum and count, moved in the same transaction as the overall aggregate."""

    __tablename__ = "destination_category_stats"
    __table_args__ = (
        CheckConstraint("rating_sum >= 0", name="ck_category_stats_sum_nonnegative"),
        CheckConstraint("rating_count >= 0", name="ck_category_stats_count_nonnegative"),
    )

    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[ReviewCategory] = mapped_column(
        Enum(ReviewCategory, name="review_category"), primary_key=True
    )
    audience: Mapped[RatingAudience] = mapped_column(
        Enum(RatingAudience, name="rating_audience"), primary_key=True
    )
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ModerationActionRecord(Base):
    __tablename__ = "moderation_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="RESTRICT"), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[ModerationDecision] = mapped_column(
        Enum(ModerationDecision, name="moderation_decision"), nullable=False
    )
    previous_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="moderation_previous_status"), nullable=False
    )
    new_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="moderation_new_status"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # the queue task this decision closed
    request_id: Mapped[str | None] = mapped_column(String(64))


class OutboxEvent(Base):
    """The shared outbox (Notification spec 7.1; Moderation spec 6.7). ``topic`` is the event type.

    ``available_at`` is the spec's ``next_attempt_at`` and ``lease_until`` its ``lease_expires_at``.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'processed', 'retry', 'dead_letter')", name="ck_outbox_events_status"),
        Index("ix_outbox_events_relay", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)  # the event type, e.g. review.state_changed
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Shared outbox contract (Moderation spec 6.7, migration 0014): status, lease, retries, errors.
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(String(300))
    # Notification spec 7.1 (migration 0017).
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, default=lambda: f"event:{uuid.uuid4()}")
    aggregate_type: Mapped[str | None] = mapped_column(String(40))
    aggregate_version: Mapped[int | None] = mapped_column(BigInteger)
    recipient_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    last_error_code: Mapped[str | None] = mapped_column(String(60))


class AuditEvent(Base):
    """Append-only record of privileged actions (Moderation spec 6.6). Triggers refuse UPDATE and DELETE.

    ``id`` is globally unique (the table is not partitioned), so ``GET /admin/audit-events/{id}`` is exact.
    ``metadata`` holds approved, non-secret facts only.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_actor", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # no FK: the log outlives accounts
    actor_role_snapshot: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(500))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


# Databases built from these models (tests) get the same append-only guard the migration installs.
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "CREATE OR REPLACE FUNCTION audit_events_are_append_only() RETURNS trigger SET search_path = '' AS $$ "
        "BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql"
    ),
)
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_are_append_only()"
    ),
)
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_are_append_only()"
    ),
)


class IdempotencyKey(Base):
    """Stored result of a retried decision (Moderation spec 8.2), scoped by actor and operation."""

    __tablename__ = "idempotency_keys"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    operation: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ModerationTask(Base):
    """Queue and claim state, kept apart from content lifecycle (Moderation spec 5 and 7.2)."""

    __tablename__ = "moderation_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done', 'cancelled')", name="ck_moderation_tasks_status"),
        CheckConstraint("required_role IN ('moderator', 'superadmin')", name="ck_moderation_tasks_role"),
        CheckConstraint(
            "task_type IN ('review_moderation', 'report', 'verification', 'appeal', 'enforcement')",
            name="ck_moderation_tasks_type",
        ),
        Index(
            "uq_moderation_tasks_open_subject",
            "task_type",
            "subject_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_moderation_tasks_queue", "status", "priority", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    required_role: Mapped[str] = mapped_column(String(20), nullable=False, default="moderator", server_default="moderator")
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Report(Base):
    """A member's report on a review (Gantt R11). One open report per reporter and review."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("state IN ('open', 'in_review', 'actioned', 'dismissed')", name="ck_reports_state"),
        Index(
            "uq_reports_one_open_per_reporter",
            "reporter_user_id",
            "review_id",
            unique=True,
            postgresql_where=text("state IN ('open', 'in_review')"),
        ),
        Index("ix_reports_review", "review_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str | None] = mapped_column(String(1000))
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


OPEN_CASE_STATES = "('submitted', 'in_review', 'needs_clarification', 'escalated')"


class VerificationCase(Base):
    """A member's request to become a Verified Member (Moderation spec 6.2, 7.1). One open case per member."""

    __tablename__ = "verification_cases"
    __table_args__ = (
        CheckConstraint(
            "state IN ('submitted', 'in_review', 'needs_clarification', 'approved', 'rejected', 'escalated', 'withdrawn')",
            name="ck_verification_cases_state",
        ),
        Index("uq_verification_cases_one_open", "applicant_user_id", unique=True, postgresql_where=text(f"state IN {OPEN_CASE_STATES}")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    applicant_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    statement: Mapped[str | None] = mapped_column(String(1000))
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="submitted", server_default="submitted")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(60))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class VerificationEvidence(Base):
    """Metadata of a private evidence file; the bytes live in a private Storage bucket (spec 3.3)."""

    __tablename__ = "verification_evidence"
    __table_args__ = (CheckConstraint("status IN ('pending', 'uploaded', 'deleted')", name="ck_verification_evidence_status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", server_default="pending")
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnforcementCase(Base):
    """A takedown or removal, kept apart from the content itself (spec 6.4). Rating eligibility is its own field."""

    __tablename__ = "enforcement_cases"
    __table_args__ = (
        CheckConstraint("kind IN ('takedown', 'account')", name="ck_enforcement_cases_kind"),
        CheckConstraint("state IN ('taken_down', 'removed', 'restored', 'open', 'closed')", name="ck_enforcement_cases_state"),
        CheckConstraint("num_nonnulls(review_id, subject_user_id) = 1", name="ck_enforcement_cases_one_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"))
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(12), nullable=False)
    emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    counts_toward_rating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    follow_up_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Sanction(Base):
    """An account-level restriction with a scope and an end or review date (spec 6.4, 7.3)."""

    __tablename__ = "sanctions"
    __table_args__ = (
        CheckConstraint("kind IN ('warning', 'posting_restriction', 'suspension')", name="ck_sanctions_kind"),
        CheckConstraint("state IN ('active', 'expired', 'reversed')", name="ck_sanctions_state"),
        CheckConstraint("ends_at IS NOT NULL OR review_on IS NOT NULL", name="ck_sanctions_has_end"),
        Index("ix_sanctions_user_active", "user_id", postgresql_where=text("state = 'active'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    enforcement_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enforcement_cases.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[str] = mapped_column(String(60), nullable=False, default="reviews", server_default="reviews")
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="active", server_default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_on: Mapped[date | None] = mapped_column(Date)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Appeal(Base):
    """An appeal against one decision (spec 6.5). Typed targets keep real foreign keys; exactly one is set."""

    __tablename__ = "appeals"
    __table_args__ = (
        CheckConstraint("state IN ('received', 'in_review', 'upheld', 'overturned', 'withdrawn')", name="ck_appeals_state"),
        CheckConstraint(
            "num_nonnulls(moderation_action_id, enforcement_case_id, verification_case_id) = 1", name="ck_appeals_one_target"
        ),
        # a guest appeal (no account) is always against a moderation action, reached through the receipt
        CheckConstraint("appellant_user_id IS NOT NULL OR moderation_action_id IS NOT NULL", name="ck_appeals_guest_target"),
        # one appeal per decision: a decided appeal cannot be filed again; a withdrawn one can
        Index("uq_appeals_moderation", "moderation_action_id", unique=True, postgresql_where=text("moderation_action_id IS NOT NULL AND state <> 'withdrawn'")),
        Index("uq_appeals_enforcement", "enforcement_case_id", unique=True, postgresql_where=text("enforcement_case_id IS NOT NULL AND state <> 'withdrawn'")),
        Index("uq_appeals_verification", "verification_case_id", unique=True, postgresql_where=text("verification_case_id IS NOT NULL AND state <> 'withdrawn'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null for a guest appeal filed with a receipt (Review.md 4.2); the review's receipt proves standing.
    appellant_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    moderation_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("moderation_actions.id", ondelete="CASCADE"))
    enforcement_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enforcement_cases.id", ondelete="CASCADE"))
    verification_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("verification_cases.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="received", server_default="received")
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    original_decider_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class Notification(Base):
    """One durable in-app item per recipient and notification kind (Notification spec 7.2).

    ``(event_id, recipient_user_id, kind)`` is unique, so re-processing an event never duplicates it.
    Texts are stored in both languages. ``audience = 'staff'`` items are shown only while the
    recipient still holds a staff role (spec 5). ``delivery_mode`` says how email follows it.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_id", "recipient_user_id", "kind", name="uq_notifications_identity"),
        CheckConstraint("priority IN ('critical', 'high', 'normal', 'low')", name="ck_notifications_priority"),
        CheckConstraint("audience IN ('member', 'staff')", name="ck_notifications_audience"),
        CheckConstraint("delivery_mode IN ('immediate', 'digest', 'none')", name="ck_notifications_delivery_mode"),
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
        Index("ix_notifications_expires_at", "expires_at"),
        Index("ix_notifications_digest_queue", "delivery_mode", "digest_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="normal", server_default="normal")
    audience: Mapped[str] = mapped_column(String(8), nullable=False, default="member", server_default="member")
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    title_bn: Mapped[str] = mapped_column(String(160), nullable=False)
    title_en: Mapped[str] = mapped_column(String(160), nullable=False)
    body_bn: Mapped[str] = mapped_column(String(600), nullable=False)
    body_en: Mapped[str] = mapped_column(String(600), nullable=False)
    link: Mapped[str | None] = mapped_column(String(300))  # an allowlisted internal route, never a free URL
    appeal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # kept while that appeal is open (spec 10)
    delivery_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="none", server_default="none")
    digest_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_digests.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def critical(self) -> bool:
        return self.priority == "critical"


class NotificationDigest(Base):
    """One daily summary per recipient and local day (spec 7.10); its items point back with ``digest_id``."""

    __tablename__ = "notification_digests"
    __table_args__ = (
        UniqueConstraint("recipient_user_id", "window_date", name="uq_notification_digests_window"),
        CheckConstraint("status IN ('queued', 'sending', 'accepted', 'failed', 'ambiguous')", name="ck_notification_digests_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    window_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued", server_default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class NotificationDelivery(Base):
    """One external (email) delivery of a notification or of a digest (spec 7.3).

    "accepted" means the provider took the message, not that it reached the inbox. ``destination_ref``
    is an HMAC of the address used, never the address itself.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'sending', 'accepted', 'delivered', 'bounced', 'failed_permanently', 'skipped', 'ambiguous')",
            name="ck_notification_deliveries_status",
        ),
        CheckConstraint("num_nonnulls(notification_id, digest_id) = 1", name="ck_notification_deliveries_subject"),
        UniqueConstraint("notification_id", "channel", name="uq_notification_deliveries_notification"),
        UniqueConstraint("digest_id", "channel", name="uq_notification_deliveries_digest"),
        Index("ix_notification_deliveries_due", "status", "next_attempt_at"),
        Index("ix_notification_deliveries_message", "provider_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"))
    digest_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_digests.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="email", server_default="email")
    destination_ref: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    last_error_code: Mapped[str | None] = mapped_column(String(60))
    last_error_summary: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class NotificationDeliveryAttempt(Base):
    """Append-only history of every send attempt (spec 7.4)."""

    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("delivery_id", "attempt_number", name="uq_notification_delivery_attempts_number"),
        CheckConstraint(
            "outcome IN ('accepted', 'transient_failure', 'permanent_failure', 'ambiguous', 'skipped')",
            name="ck_notification_delivery_attempts_outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notification_deliveries.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error_class: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(60))
    redacted_error_summary: Mapped[str | None] = mapped_column(String(300))


class NotificationProviderEvent(Base):
    """A provider callback, stored once per ``(provider, provider_event_id)`` (spec 7.5)."""

    __tablename__ = "notification_provider_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_notification_provider_events"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_deliveries.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class NotificationTemplate(Base):
    """A versioned text for one template key, channel and language (spec 7.6). Active versions are immutable."""

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "channel", "locale", "version", name="uq_notification_templates_version"),
        CheckConstraint("channel IN ('in_app', 'email')", name="ck_notification_templates_channel"),
        CheckConstraint("locale IN ('bn', 'en')", name="ck_notification_templates_locale"),
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_notification_templates_status"),
        Index(
            "uq_notification_templates_active", "template_key", "channel", "locale", unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_template: Mapped[str | None] = mapped_column(String(200))
    title_template: Mapped[str | None] = mapped_column(String(160))
    body_template: Mapped[str] = mapped_column(String(600), nullable=False)
    variable_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", server_default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # null: shipped with the code
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationRule(Base):
    """Live configuration of one catalogue rule (spec 7.7): priority, channels and on/off.

    Which events and recipient resolvers exist is fixed in code (``app/notify/registry.py``); this
    table only tunes allowlisted fields of those rules.
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        CheckConstraint("priority IN ('critical', 'high', 'normal', 'low')", name="ck_notification_rules_priority"),
    )

    template_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class NotificationPreference(Base):
    """How a person wants standard (non-critical) email (spec 7.8)."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint("standard_email_mode IN ('immediate', 'digest', 'off')", name="ck_notification_preferences_mode"),
    )

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    standard_email_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="digest", server_default="digest")
    digest_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Dhaka", server_default="Asia/Dhaka")
    digest_local_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(8, 0), server_default="08:00")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class NotificationSuppression(Base):
    """An address that must not be emailed (bounce, complaint, or by hand), kept as an HMAC (spec 7.9)."""

    __tablename__ = "notification_suppressions"
    __table_args__ = (
        Index(
            "uq_notification_suppressions_active", "destination_hmac", "channel", unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    destination_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="email")
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    removed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_reason: Mapped[str | None] = mapped_column(String(300))


class RateLimitBucket(Base):
    """Fixed-window attempt counter keyed by a keyed digest; never holds raw identifiers."""

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("count >= 0", name="ck_rate_limit_count_nonnegative"),
        Index("ix_rate_limit_buckets_window_start", "window_start"),
    )

    rule: Mapped[str] = mapped_column(String(60), primary_key=True)
    key_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class VisitDailyStats(Base):
    """Four visit totals per Asia/Dhaka day, rolled up from Redis (Guest-Identity-and-Visits 4.5).

    Numbers only: no guest tag, secret, address or user reference. The split columns are NULL only
    for legacy days migrated from ``guest_visits``, whose totals sit in ``guest_total_legacy``.
    """

    __tablename__ = "visit_daily_stats"
    __table_args__ = tuple(
        CheckConstraint(f"{column} IS NULL OR {column} >= 0", name=f"ck_visit_daily_stats_{column}")
        for column in ("guest_new", "guest_returning", "member_new", "member_returning", "guest_total_legacy")
    )

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    guest_new: Mapped[int | None] = mapped_column(Integer)
    guest_returning: Mapped[int | None] = mapped_column(Integer)
    member_new: Mapped[int | None] = mapped_column(Integer)
    member_returning: Mapped[int | None] = mapped_column(Integer)
    guest_total_legacy: Mapped[int | None] = mapped_column(Integer)
    rolled_up_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )


class ReviewMedia(Base):
    """A photo or video attached to a member review (Review.md 8, amendment A4).

    The upload lands in a private quarantine object; the server checks it (and re-encodes images
    without metadata) into ``processed_key``. Only ``approved`` media of a published review are shown.
    """

    __tablename__ = "review_media"
    __table_args__ = (
        CheckConstraint("kind IN ('image', 'video')", name="ck_review_media_kind"),
        CheckConstraint(
            "state IN ('awaiting_upload', 'pending', 'approved', 'rejected', 'removed')", name="ck_review_media_state"
        ),
        CheckConstraint("ownership_declared", name="ck_review_media_ownership"),
        CheckConstraint("state IN ('awaiting_upload', 'removed') OR processed_key IS NOT NULL", name="ck_review_media_processed"),
        Index("ix_review_media_review", "review_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    uploader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="awaiting_upload", server_default="awaiting_upload")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    quarantine_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    processed_key: Mapped[str | None] = mapped_column(String(300), unique=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    alt_text: Mapped[str] = mapped_column(String(250), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(300))
    ownership_declared: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
