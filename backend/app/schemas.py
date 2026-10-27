import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import review_parameters as rp
from app.config import get_settings
from app.models import (
    AdvisorySeverity,
    ComfortTier,
    ContactKind,
    GuideCategory,
    ReviewCategory,
    ReviewLanguage,
    ReviewStatus,
    SourceType,
    TravellerType,
)


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


CategoryScore = Annotated[int, Field(ge=rp.RATING_MIN, le=rp.RATING_MAX)]


class ReviewContent(StrictRequestModel):
    """What every review carries, from a guest or a signed-in member (Review.md 3.1)."""

    destination_id: uuid.UUID
    client_draft_id: uuid.UUID
    receipt_secret: str = Field(min_length=1, max_length=100, repr=False)
    language: ReviewLanguage
    traveller_type: TravellerType
    comfort_tier: ComfortTier
    visit_month: date
    title: str = Field(min_length=rp.TITLE_MIN, max_length=rp.TITLE_MAX)
    # The reviewer's free-text note: always required (Review.md 3.1, A2).
    body: str = Field(min_length=rp.NOTE_MIN, max_length=rp.NOTE_MAX)
    overall_rating: int = Field(ge=rp.RATING_MIN, le=rp.RATING_MAX)
    # Review.md 3.1, amendment A2: each category optional; a missing key means not applicable.
    category_ratings: dict[ReviewCategory, CategoryScore] | None = Field(default=None, max_length=7)
    consent_version: str = Field(min_length=1, max_length=40)

    @field_validator("category_ratings")
    @classmethod
    def empty_ratings_are_absent(
        cls, value: dict[ReviewCategory, int] | None
    ) -> dict[ReviewCategory, int] | None:
        return value or None

    @field_validator("visit_month")
    @classmethod
    def first_day_of_month(cls, value: date) -> date:
        if value.day != 1:
            raise ValueError("visit_month must use the first day of its month")
        display_tz = get_settings().display_tz
        current_month = datetime.now(display_tz).date().replace(day=1)
        if value > current_month:
            raise ValueError(f"visit_month cannot be in the future in {display_tz.key}")
        return value


class GuestReviewCreate(ReviewContent):
    guest_scope_secret: str = Field(min_length=43, max_length=200, repr=False)
    turnstile_token: str | None = Field(default=None, max_length=2048, repr=False)
    guest_display_name: str = Field(min_length=1, max_length=rp.DISPLAY_NAME_MAX)


class MemberReviewCreate(ReviewContent):
    """A signed-in member's review: the author and public name come from the session (Review.md 3.3)."""


class GuestReviewCreated(BaseModel):
    review_id: uuid.UUID
    status: ReviewStatus
    version: int
    duplicate_recovered: bool


class ModerationRequest(StrictRequestModel):
    expected_version: int = Field(ge=1)
    decision: Literal["PUBLISH", "REJECT", "HIDE", "RESTORE"]
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class ModerationResult(BaseModel):
    review_id: uuid.UUID
    status: ReviewStatus
    version: int
    counted_rating: int | None


class ModerationQueueItem(ModerationResult):
    """A queued review with the content a moderator has to read before deciding."""

    destination_id: uuid.UUID
    guest_display_name: str | None
    guest_tag: str | None = None
    overall_rating: int
    title: str
    body: str
    category_ratings: dict[ReviewCategory, int]
    created_at: datetime


class ConflictFlagRequest(StrictRequestModel):
    expected_version: int = Field(ge=1)
    conflict_declared: bool
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class ReceiptStatusRequest(StrictRequestModel):
    review_id: uuid.UUID
    receipt_secret: str = Field(min_length=1, max_length=100, repr=False)


class ReceiptStatus(BaseModel):
    review_id: uuid.UUID
    status: ReviewStatus
    version: int
    published_at: datetime | None
    decision_reason: str | None
    appeal_deadline: datetime | None


class WithdrawRequest(StrictRequestModel):
    expected_version: int = Field(ge=1)
    receipt_secret: str = Field(min_length=1, max_length=100, repr=False)


class PublicReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # A guest's typed name is never public (owner, 22 Oct 2026): a guest review is shown only as
    # "Anonymous guest · 1C669-J0TDY". The name stays visible to moderators in the queue.
    author_type: Literal["GUEST", "MEMBER"]
    # Null for member reviews and for guest reviews written before the tag existed.
    guest_tag: str | None = None
    status: ReviewStatus
    overall_rating: int
    published_at: datetime
    title: str
    body: str
    category_ratings: dict[ReviewCategory, int] = Field(default_factory=dict)
    # A member's public display name; null for guests (who stay anonymous).
    author_display_name: str | None = None
    media: list["PublicMedia"] = Field(default_factory=list)


class PublicMedia(BaseModel):
    """An approved photo or video. `url` is a signed link that works for about an hour."""

    id: uuid.UUID
    kind: Literal["image", "video"]
    content_type: str
    url: str
    alt_text: str
    caption: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


PublicReview.model_rebuild()


class MediaIntentRequest(StrictRequestModel):
    content_type: str = Field(max_length=40)
    size_bytes: int = Field(ge=1)
    alt_text: str = Field(min_length=1, max_length=250)
    caption: str | None = Field(default=None, max_length=300)
    # The uploader confirms they made the photo or video and may publish it (Review.md 8).
    ownership_declared: Literal[True]


class MediaIntent(BaseModel):
    media_id: uuid.UUID
    kind: Literal["image", "video"]
    upload_url: str
    max_bytes: int


class MediaStatus(BaseModel):
    id: uuid.UUID
    kind: Literal["image", "video"]
    state: str
    content_type: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    size_bytes: int | None = None


class CategoryAverage(BaseModel):
    category: ReviewCategory
    average: float
    count: int


class ReviewFeed(BaseModel):
    items: list[PublicReview]
    next_cursor: str | None
    guest_rating_average: float | None
    guest_rating_count: int
    guest_category_averages: list[CategoryAverage] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str


class LocalizedText(BaseModel):
    bn: str
    en: str


class RatingParameter(BaseModel):
    required: bool
    min: int
    max: int


class CategoryParameter(BaseModel):
    code: ReviewCategory
    name: LocalizedText
    prompt: LocalizedText
    required: bool
    min: int
    max: int


class TextParameter(BaseModel):
    field: str
    required: bool
    min_length: int
    max_length: int


class ChoiceOption(BaseModel):
    value: str
    label: LocalizedText


class RatingRules(BaseModel):
    guest_feedback: str
    community_rating: str
    community_prior_mean: float
    community_prior_weight: int
    community_min_reviews: int
    category_averages: str


class ReviewParameters(BaseModel):
    """Everything a client needs to render the review form and explain the scores."""

    version: str
    overall_rating: RatingParameter
    categories: list[CategoryParameter]
    note: TextParameter
    title: TextParameter
    display_name: TextParameter
    traveller_types: list[ChoiceOption]
    comfort_tiers: list[ChoiceOption]
    languages: list[ChoiceOption]
    rating_rules: RatingRules


class GuestVisitRequest(StrictRequestModel):
    """Exactly one boolean (Guest-Identity-and-Visits 4.2). Any other field, such as a name, tag,
    secret or device id, is a 422 ``UNKNOWN_FIELD``."""

    first_visit: bool


AdvisoryState = Literal["NOT_YET_EFFECTIVE", "CURRENT", "STALE", "EXPIRED"]


class Provenance(BaseModel):
    """Public source metadata. Researcher and reviewer names stay internal."""

    model_config = ConfigDict(from_attributes=True)

    source_type: SourceType
    source_ref: str
    publisher: str
    effective_on: date
    verified_on: date
    next_review_on: date | None
    licence: str


class CommunityRatingSummary(BaseModel):
    average: float | None
    count: int
    category_averages: list[CategoryAverage] = Field(default_factory=list)
    # Bayesian score (Review.md 6.1); null until five eligible reviews (6.4).
    score: float | None = None
    seeded_selection: bool = True


class GuestFeedbackSummary(BaseModel):
    average: float | None
    count: int
    category_averages: list[CategoryAverage] = Field(default_factory=list)


class DestinationSummary(BaseModel):
    id: uuid.UUID
    name_bn: str
    name_en: str
    region_bn: str | None
    region_en: str | None
    summary_bn: str | None
    summary_en: str | None
    latitude: float | None
    longitude: float | None
    community_rating: CommunityRatingSummary
    guest_feedback: GuestFeedbackSummary
    active_advisory_count: int
    last_updated: datetime


class DestinationList(BaseModel):
    items: list[DestinationSummary]
    next_cursor: str | None


class GuideItem(BaseModel):
    id: uuid.UUID
    category: GuideCategory
    title_bn: str
    title_en: str
    body_bn: str
    body_en: str
    sort_order: int
    provenance: Provenance


class Advisory(BaseModel):
    id: uuid.UUID
    severity: AdvisorySeverity
    title_bn: str
    title_en: str
    text_bn: str
    text_en: str
    effective_on: date
    valid_until: date
    state: AdvisoryState
    provenance: Provenance


class Contact(BaseModel):
    id: uuid.UUID
    kind: ContactKind
    name_bn: str
    name_en: str
    phone: str
    address_bn: str | None
    address_en: str | None
    latitude: float | None
    longitude: float | None
    provenance: Provenance


class DestinationProfile(BaseModel):
    id: uuid.UUID
    name_bn: str
    name_en: str
    region_bn: str | None
    region_en: str | None
    summary_bn: str | None
    summary_en: str | None
    seasonality_bn: str | None
    seasonality_en: str | None
    restrictions_bn: str | None
    restrictions_en: str | None
    latitude: float | None
    longitude: float | None
    community_rating: CommunityRatingSummary
    guest_feedback: GuestFeedbackSummary
    guide_items: list[GuideItem]
    advisories: list[Advisory]
    contacts: list[Contact]
    content_licence: str | None
    content_verified_on: date | None
    as_of: date
    stale_after_days: int
    last_updated: datetime
