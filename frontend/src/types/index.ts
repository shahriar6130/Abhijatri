export type Language = 'bn' | 'en';
export type Theme = 'light' | 'dark';

// ---------------------------------------------------------------------------
// API contract types (Docs/api/API.md sections 2, 5 and 8; backend app/schemas.py)
// ---------------------------------------------------------------------------

export interface FieldError {
  field: string;
  code: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    field_errors: FieldError[];
  };
}

export type SourceType = 'OFFICIAL' | 'TEAM_RESEARCH' | 'OPEN_LICENCE' | 'VENDOR_LICENSED' | 'OTHER';
export type GuideCategory = 'ATTRACTION' | 'ACCOMMODATION' | 'FOOD' | 'TRANSPORT' | 'LOCAL_PRACTICE';
export type AdvisorySeverity = 'INFO' | 'CAUTION' | 'WARNING' | 'CRITICAL';
export type AdvisoryState = 'NOT_YET_EFFECTIVE' | 'CURRENT' | 'STALE' | 'EXPIRED';
export type ContactKind =
  | 'POLICE'
  | 'TOURIST_POLICE'
  | 'AMBULANCE'
  | 'FIRE'
  | 'HOSPITAL'
  | 'COAST_GUARD'
  | 'FOREST_OFFICE'
  | 'LOCAL_GUIDE'
  | 'OTHER';

export interface Provenance {
  source_type: SourceType;
  source_ref: string;
  publisher: string;
  effective_on: string;
  verified_on: string;
  next_review_on: string | null;
  licence: string;
}

/** Mean of one category's ratings for one audience (API.md 5.8, 5.12). */
export interface CategoryAverage {
  category: ReviewCategory;
  average: number;
  count: number;
}

export interface RatingSummary {
  average: number | null;
  count: number;
  /** Counted categories only, in Review.md order. Absent from older API builds. */
  category_averages?: CategoryAverage[];
  /** Community Rating only: server Bayesian score, null below five reviews (Review.md 6.1, 6.4). */
  score?: number | null;
  seeded_selection?: boolean;
}

export interface DestinationSummary {
  id: string;
  name_bn: string;
  name_en: string;
  region_bn: string | null;
  region_en: string | null;
  summary_bn: string | null;
  summary_en: string | null;
  latitude: number | null;
  longitude: number | null;
  community_rating: RatingSummary;
  guest_feedback: RatingSummary;
  active_advisory_count: number;
  last_updated: string;
}

export interface DestinationList {
  items: DestinationSummary[];
  next_cursor: string | null;
}

export interface GuideItem {
  id: string;
  category: GuideCategory;
  title_bn: string;
  title_en: string;
  body_bn: string;
  body_en: string;
  sort_order: number;
  provenance: Provenance;
}

export interface Advisory {
  id: string;
  severity: AdvisorySeverity;
  title_bn: string;
  title_en: string;
  text_bn: string;
  text_en: string;
  effective_on: string;
  valid_until: string;
  state: AdvisoryState;
  provenance: Provenance;
}

export interface Contact {
  id: string;
  kind: ContactKind;
  name_bn: string;
  name_en: string;
  phone: string;
  address_bn: string | null;
  address_en: string | null;
  latitude: number | null;
  longitude: number | null;
  provenance: Provenance;
}

export interface DestinationProfile {
  id: string;
  name_bn: string;
  name_en: string;
  region_bn: string | null;
  region_en: string | null;
  summary_bn: string | null;
  summary_en: string | null;
  seasonality_bn: string | null;
  seasonality_en: string | null;
  restrictions_bn: string | null;
  restrictions_en: string | null;
  latitude: number | null;
  longitude: number | null;
  community_rating: RatingSummary;
  guest_feedback: RatingSummary;
  guide_items: GuideItem[];
  advisories: Advisory[];
  contacts: Contact[];
  content_licence: string | null;
  content_verified_on: string | null;
  as_of: string;
  stale_after_days: number;
  last_updated: string;
}

export type ReviewStatus =
  | 'PENDING'
  | 'UNDER_REVIEW'
  | 'CHANGES_REQUESTED'
  | 'PUBLISHED'
  | 'HIDDEN'
  | 'REJECTED'
  | 'WITHDRAWN'
  | 'DELETED';
export type ReviewLanguage = 'BN' | 'EN' | 'MIXED';
export type TravellerType = 'SOLO' | 'STUDENT' | 'COUPLE' | 'FAMILY' | 'GROUP';
export type ComfortTier = 'ECONOMY' | 'STANDARD' | 'PREMIUM';
/** Review.md 3.1: the seven frozen rating categories. */
export type ReviewCategory =
  | 'CLEANLINESS'
  | 'ACCESSIBILITY'
  | 'HOSPITALITY'
  | 'FOOD'
  | 'TRANSPORT'
  | 'SAFETY_PERCEPTION'
  | 'VALUE';
/** Each category is optional (not applicable) or an integer from 1 to 5. */
export type CategoryRatings = Partial<Record<ReviewCategory, number>>;

export interface PublicReview {
  id: string;
  /** A guest's typed name is never public; a guest review shows only "Anonymous guest · tag". */
  author_type: 'GUEST' | 'MEMBER';
  /** "1C669-J0TDY"; null for member reviews and guest reviews written before the tag existed. */
  guest_tag: string | null;
  status: ReviewStatus;
  overall_rating: number;
  published_at: string;
  title: string;
  body: string;
  category_ratings?: CategoryRatings;
  /** A member's public display name; null for guests. */
  author_display_name?: string | null;
  /** Approved photos and video only. `url` is a signed link that works for about an hour. */
  media?: PublicMedia[];
}

export interface PublicMedia {
  id: string;
  kind: 'image' | 'video';
  content_type: string;
  url: string;
  alt_text: string;
  caption: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
}

export interface ReviewFeed {
  items: PublicReview[];
  next_cursor: string | null;
  guest_rating_average: number | null;
  guest_rating_count: number;
  guest_category_averages?: CategoryAverage[];
}

export interface LocalizedText {
  bn: string;
  en: string;
}

export interface TextParameter {
  field: string;
  required: boolean;
  min_length: number;
  max_length: number;
}

/** `GET /review-parameters` (API.md 5.15): the form and rating rules, defined by the server. */
export interface ReviewParameters {
  version: string;
  overall_rating: { required: boolean; min: number; max: number };
  categories: {
    code: ReviewCategory;
    name: LocalizedText;
    prompt: LocalizedText;
    required: boolean;
    min: number;
    max: number;
  }[];
  note: TextParameter;
  title: TextParameter;
  display_name: TextParameter;
  traveller_types: { value: TravellerType; label: LocalizedText }[];
  comfort_tiers: { value: ComfortTier; label: LocalizedText }[];
  languages: { value: ReviewLanguage; label: LocalizedText }[];
  rating_rules: {
    guest_feedback: string;
    community_rating: string;
    category_averages: string;
    community_prior_mean: number;
    community_prior_weight: number;
    community_min_reviews: number;
  };
}

/** `POST /guest-visits` (API.md 5.14). Nothing about the guest is sent or stored. */
export interface GuestReviewCreate {
  destination_id: string;
  client_draft_id: string;
  guest_scope_secret: string;
  receipt_secret: string;
  turnstile_token?: string | null;
  guest_display_name: string;
  language: ReviewLanguage;
  traveller_type: TravellerType;
  comfort_tier: ComfortTier;
  visit_month: string;
  title: string;
  body: string;
  overall_rating: number;
  /** API.md 5.2: optional; sent when VITE_REVIEW_CATEGORY_RATINGS is true. */
  category_ratings?: CategoryRatings;
  consent_version: string;
}

export interface GuestReviewCreated {
  review_id: string;
  status: ReviewStatus;
  version: number;
  duplicate_recovered: boolean;
}

export interface ReceiptStatus {
  review_id: string;
  status: ReviewStatus;
  version: number;
  published_at: string | null;
  decision_reason: string | null;
  appeal_deadline: string | null;
}

// ---------------------------------------------------------------------------
// Prototype-only shapes (pages not yet backed by the API: planner, packs, trips)
// ---------------------------------------------------------------------------

export interface Destination {
  id: string;
  nameBn: string;
  nameEn: string;
  regionBn: string;
  regionEn: string;
  coverImage: string;
  rating: number;
  reviewCount: number;
  descriptionBn: string;
  descriptionEn: string;
  seasonalityBn: string;
  seasonalityEn: string;
  activeAdvisoriesCount: number;
  offlinePackSizeMb: number;
  highlightsBn: string[];
  highlightsEn: string[];
}

export interface CostEstimateItem {
  category: string;
  unit: string;
  quantity: number;
  low: number;
  expected: number;
  high: number;
  confidence: number;
}

export interface CostEstimateResult {
  destination: string;
  partySize: number;
  durationDays: number;
  durationNights: number;
  comfortTier: 'economy' | 'standard' | 'premium';
  items: CostEstimateItem[];
  totalExpected: number;
  perPersonExpected: number;
  sharedTotal: number;
  individualTotal: number;
  overallConfidence: 'High' | 'Medium' | 'Low';
}

export interface HealthStatus {
  status: string;
  database?: string;
  latencyMs?: number;
  timestamp?: string;
  urlChecked?: string;
  error?: string;
}

/** API.md 5.17: the signed-in member as the server describes them. */
export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
}

export type StaffRole = 'moderator' | 'superadmin';

export type AuthSession =
  | { authenticated: false }
  | {
      authenticated: true;
      user: AuthUser;
      role: StaffRole | null;
      verified_member: boolean;
      aal: 'aal1' | 'aal2';
      mfa_factors: { id: string; type: string }[];
      auth_time: string;
    };

/** API.md 5.19: in-app notifications. */
export interface AppNotification {
  id: string;
  kind: string;
  critical: boolean;
  title: { bn: string; en: string };
  body: { bn: string; en: string };
  link: string | null;
  created_at: string;
  read: boolean;
}

export interface VerificationCaseView {
  id: string;
  state: 'submitted' | 'in_review' | 'needs_clarification' | 'approved' | 'rejected' | 'escalated' | 'withdrawn';
  version: number;
  statement: string | null;
  decision_note: string | null;
  decision_reason: string | null;
  created_at: string;
  decided_at: string | null;
  evidence: { id: string; status: string; content_type: string }[];
}

export interface AppealView {
  id: string;
  reference: string;
  state: 'received' | 'in_review' | 'upheld' | 'overturned' | 'withdrawn';
  target_type: string | null;
  target_id: string | null;
  reason: string;
  submitted_at: string;
  deadline_at: string;
  decided_at: string | null;
  decision_note: string | null;
}

export interface AppealableDecision {
  target_type: 'moderation_action' | 'enforcement_case' | 'verification_case';
  target_id: string;
  label: string;
  decided_at: string;
  deadline_at: string;
  open: boolean;
  appeal_state: string | null;
}