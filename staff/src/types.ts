/** Shapes returned by `/api/v1/auth/*` and `/api/v1/admin/*` (Docs/api/API.md 5.17 and 5.18). */

export type Lang = 'bn' | 'en';
export type Role = 'moderator' | 'superadmin';

export interface SessionUser {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
}

export type Session =
  | { authenticated: false }
  | {
      authenticated: true;
      user: SessionUser;
      role: Role | null;
      aal: 'aal1' | 'aal2';
      mfa_factors: { id: string; type: string }[];
      auth_time: string;
    };

export type SignedIn = Extract<Session, { authenticated: true }>;

export interface Enrollment {
  factor_id: string;
  secret: string;
  uri: string;
  qr_code: string;
}

export type TaskType = 'review_moderation' | 'report' | 'verification' | 'appeal' | 'enforcement';

export interface ReviewSubject {
  kind: 'review';
  review_id: string;
  status: string;
  version: number;
  overall_rating: number;
  title: string;
  body: string;
  author: 'member' | 'guest';
  guest_display_name: string | null;
  author_display_name?: string | null;
  /** Checked photos and video waiting for this decision (API.md 5.20). */
  media?: ReviewMedia[];
  created_at: string;
}

export interface ReviewMedia {
  id: string;
  kind: 'image' | 'video';
  content_type: string;
  alt_text: string;
  caption: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  size_bytes: number | null;
}

export interface ReportSubject {
  kind: 'report';
  report_id: string;
  state: 'open' | 'in_review' | 'actioned' | 'dismissed';
  version: number;
  reason_code: string;
  details: string | null;
  review_id: string;
  review_status: string | null;
  review_version: number | null;
  review_title: string | null;
  review_body: string | null;
  created_at: string;
}

export interface QueueItem {
  id: string;
  assigned_to?: string | null;
  task_type: TaskType;
  subject_id: string;
  status: string;
  required_role: Role;
  escalated: boolean;
  priority: number;
  claimed_by: string | null;
  lease_expires_at: string | null;
  lease_token?: string | null;
  version: number;
  created_at: string;
  claimable: boolean;
  lease_active: boolean;
  subject: ReviewSubject | ReportSubject | VerificationSubject | AppealSubject | EnforcementSubject | null;
}

export interface Task {
  id: string;
  assigned_to?: string | null;
  lease_token?: string | null;
  lease_expires_at: string | null;
  claimed_by: string | null;
  required_role: Role;
  escalated: boolean;
  status: string;
  version: number;
}

export interface AuditItem {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  actor_role: string | null;
  action: string;
  target_type: string;
  target_id: string;
  request_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
}

export interface StaffMember {
  user_id: string;
  display_name: string;
  email: string;
  role: Role;
  granted_at: string;
}

export interface UserHit {
  user_id: string;
  display_name: string;
  email: string;
  status: string;
  role: Role | null;
}

export interface Summary {
  generated_at: string;
  outbox_failed: number;
  oldest_pending_event_age_seconds: number | null;
  emails_failed_or_ambiguous: number;
  open_verification_cases: number;
  open_appeals: number;
  emergency_overdue: number;
  active_sanctions: number;
  queue_depth: number;
  oldest_open_task_age_seconds: number | null;
  escalated_open: number;
  expired_claims: number;
  open_reports: number;
  outbox_pending: number;
  denied_last_24h: number;
}

export interface DecisionInput {
  taskId: string;
  leaseToken: string;
  expectedVersion: number;
  decision: 'PUBLISH' | 'REJECT' | 'HIDE' | 'RESTORE';
  reasonCode: string;
  note?: string;
  /** PUBLISH only: photos or videos to reject; the others are approved with the review. */
  rejectedMediaIds?: string[];
}

export interface ReportTransitionInput {
  taskId: string;
  leaseToken: string;
  expectedVersion: number;
  to: 'in_review' | 'actioned' | 'dismissed';
  reasonCode: string;
  note?: string;
}

export interface VerificationSubject {
  kind: 'verification';
  case_id: string;
  state: 'submitted' | 'in_review' | 'needs_clarification' | 'approved' | 'rejected' | 'escalated' | 'withdrawn';
  version: number;
  statement: string | null;
  applicant: { display_name: string; email: string } | null;
  evidence: { id: string; content_type: string }[];
  created_at: string;
}

export interface AppealSubject {
  kind: 'appeal';
  appeal_id: string;
  reference: string;
  state: 'received' | 'in_review' | 'upheld' | 'overturned' | 'withdrawn';
  version: number;
  reason: string;
  target_type: string;
  target_id: string;
  original_decider_is_you: boolean;
  deadline_at: string;
  submitted_at: string;
}

export interface EnforcementCase {
  case_id: string;
  case_kind: 'takedown' | 'account';
  state: 'taken_down' | 'removed' | 'restored' | 'open' | 'closed';
  version: number;
  emergency: boolean;
  counts_toward_rating: boolean;
  follow_up_due_at: string | null;
  reason_code: string;
  note: string | null;
  review: { id: string; status: string; title: string | null } | null;
  user: { id: string; display_name: string; email: string; status: string } | null;
  sanctions: { id: string; kind: string; state: string; ends_at: string | null; review_on: string | null }[];
  created_at: string;
}

export interface EnforcementSubject extends EnforcementCase {
  kind: 'enforcement';
}
// ---- notifications (API.md 5.21) ----

export interface InboxItem {
  id: string;
  kind: string;
  category: string;
  priority: 'critical' | 'high' | 'normal' | 'low';
  critical: boolean;
  audience: 'member' | 'staff';
  title: { bn: string; en: string };
  body: { bn: string; en: string };
  link: string | null;
  created_at: string;
  read: boolean;
  archived: boolean;
}

export interface DeliveryRow {
  id: string;
  notification_id: string | null;
  digest_id: string | null;
  kind: string | null;
  channel: string;
  status: string;
  attempt_count: number;
  next_attempt_at: string | null;
  provider: string | null;
  destination_ref: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeliveryDetail extends DeliveryRow {
  provider_message_id: string | null;
  last_error_summary: string | null;
  attempts: { attempt_number: number; outcome: string; started_at: string; finished_at: string | null; error_class: string | null; error_code: string | null; redacted_error_summary: string | null }[];
}

export interface OutboxRow {
  id: string;
  event_type: string;
  aggregate_type: string | null;
  aggregate_id: string;
  status: string;
  attempts: number;
  next_attempt_at: string;
  last_error_code: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface SuppressionRow {
  id: string;
  destination_ref: string;
  channel: string;
  reason_code: string;
  created_by: string | null;
  created_at: string;
  removed_at: string | null;
  removal_reason: string | null;
}

export interface TemplateKey {
  template_key: string;
  variables: string[];
  audience: 'member' | 'staff' | null;
  priority: string | null;
  email: boolean | null;
  enabled: boolean;
  active_versions: Record<string, number>;
}

export interface TemplateVersion {
  id: string;
  template_key: string;
  channel: 'in_app' | 'email';
  locale: 'bn' | 'en';
  version: number;
  status: 'draft' | 'active' | 'retired';
  subject_template: string | null;
  title_template: string | null;
  body_template: string;
  created_at: string;
  activated_at: string | null;
}
