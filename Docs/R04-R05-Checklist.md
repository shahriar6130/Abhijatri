# R04 and R05: final checklist

**Status on 28 October 2026.** Gantt R04 (account service: register, email verification, sign-in/out, password reset) and R05 (account, verification and session screens) are **built and tested**. The items under "Before release" are configuration and deployment steps that only the owner can do; none of them is missing code.

Evidence is an automated test (`backend/tests/…`, run on PostgreSQL; `frontend/src/…test.ts`, vitest), a manual case of `Docs/Auth-and-Moderation-Test-Guide.md` (A1 to A17, C, D, N), or a check against the online Supabase project made on 27 and 28 October.

Totals: backend **481** tests passing, `ruff` and `mypy` clean; public app **59** vitest passing and the build succeeds; staff app **24** vitest passing and the build succeeds.

## R04: account service (backend, `backend/app/auth/`)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Register with email, display name, password; Supabase Auth is the identity provider | Done | `test_register_answers_the_same_for_new_and_existing_addresses`; guide A1 |
| 2 | Same answer for new and existing addresses (no account enumeration) | Done | same test; `test_app_mode_answers_the_same_for_existing_and_unknown_addresses`; A2 |
| 3 | Password rules, reserved and look-alike display names, unknown fields refused | Done | `test_register_rejects_invalid_input_with_field_errors`, `test_register_refuses_reserved_and_look_alike_names`, `test_register_rejects_unknown_fields`, `test_validators`; A3 to A5 |
| 4 | Email verification link; a used or wrong link is refused; verifying does not sign in | Done | `test_verify_email_confirms_without_creating_a_session`, `test_verify_email_rejects_a_used_or_wrong_link`; A7 |
| 5 | Resend the verification link without changing the password | Done | `test_app_mode_resend_keeps_the_password` |
| 6 | Account emails sent by this API through any provider (Mailpit, Brevo, SMTP, Resend), not Supabase's 2-per-hour mailer | Done | `test_app_mode_sends_the_verification_email_itself`, `test_smtp_provider.py` |
| 7 | Sign in sets HttpOnly `__Host-` cookies and never returns a token to the browser | Done | `test_login_sets_httponly_cookies_and_never_returns_a_token`; A11 |
| 8 | Sign-in failures look alike and are throttled per email and network | Done | `test_login_failures_look_alike_and_are_throttled`; A8 |
| 9 | Unverified email reported only after the right password | Done | `test_unverified_email_is_reported_only_after_the_right_password`; A6 |
| 10 | Disabled accounts cannot sign in or keep a session | Done | `test_a_disabled_account_cannot_sign_in_or_use_a_session`; D16 |
| 11 | Session endpoint: anonymous answer instead of 401, transparent refresh, tampered tokens refused | Done | `test_session_is_anonymous_without_cookies_and_never_a_401`, `test_session_refreshes_an_expired_access_token_once`, `test_a_tampered_or_foreign_token_is_not_a_session`, `test_token_verification_rejects_expiry_audience_and_algorithm_confusion` |
| 12 | CSRF token per session plus an Origin check on every cookie write; sign out | Done | `test_csrf_origin_and_logout`, `test_a_csrf_token_belongs_to_one_session`, `test_csrf_endpoint_needs_a_session`; A12 |
| 13 | Password reset: identical answer for unknown addresses, rate limit per address, password checked before the link is spent, all sessions end, security notice | Done | `test_reset_request_is_identical_for_known_and_unknown_addresses`, `test_reset_request_is_limited_per_address`, `test_reset_confirm_checks_the_password_before_spending_the_link`, `test_app_mode_reset_link_changes_the_password`, `test_notifications.py::test_a_password_change_sends_a_security_notice`; A13 to A15 |
| 14 | Register limited per network; Turnstile on register and reset when enabled | Done | `test_register_is_limited_per_network`; `app/turnstile.py` actions |
| 15 | Staff: role from the database, TOTP (AAL2) required, 404 for non-staff, re-authentication within 10 minutes, superadmin inactivity limit | Done | `test_staff_routes_hide_from_members_and_demand_totp`, `test_a_revoked_role_loses_access_even_with_a_valid_token`, `test_staff_writes_need_a_csrf_token`, `test_mfa_enroll_verify_and_reauth`, `test_recent_authentication_window`, `test_a_superadmin_session_ends_after_inactivity` |
| 16 | First superadmin by a one-time command | Done | `test_bootstrap_admin.py` (4 tests); run on the online project for `choturmatra@gmail.com` |
| 17 | Member visit counted once per Dhaka day | Done | `test_a_member_is_counted_once_per_dhaka_day`; A17 |
| 18 | Accounts and app profiles stored in the **online** Supabase project | Done | Online check 27 Oct: register, sign in, session and sign out against `sgoxsghtkmcikzyxoqgj`; rows in `auth.users` and `public.users`; migrations up to `0017` applied online |
| 19 | Clock drift handled safely (30 s leeway only) | Done | `CLOCK_SKEW_SECONDS` in `app/auth/tokens.py`; `test_token_verification_rejects_expiry_audience_and_algorithm_confusion` |
| 20 | Development switch to skip email verification, refused in production | Done | `test_skip_verification_creates_a_confirmed_account_without_email`, `test_config.py::test_production_fails_closed` |
| 21 | Every route answers 501 until Supabase is configured (no silent pass) | Done | `test_every_route_is_501_until_the_provider_is_configured` |

## R05: screens (public app `frontend/`, staff app `staff/`)

| # | Screen or behaviour | Status | Evidence |
|---|---|---|---|
| 1 | `/register` with bilingual validation, "Check your email" and resend; "Account created" when verification is skipped | Done | `RegisterPage.tsx`; `utils/authValidation.test.ts`; A1 to A5 |
| 2 | `/verify-email` (link from the email, expired state) | Done | `VerifyEmailPage.tsx`; A7 |
| 3 | `/login` with the specific error messages and the resend button | Done | `SignInPage.tsx`; `api/auth.test.ts`; A6, A8, A9 |
| 4 | Server-backed session: sidebar name, survives reload, sign out returns to the same guest | Done | `context/SessionContext.tsx`; A10, A12 |
| 5 | `/forgot-password` and `/reset-password` | Done | `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`; A13 to A15 |
| 6 | Guests still write reviews without an account | Done | `api/guests.test.ts`, `api/reviews.test.ts`; A16 |
| 7 | `/account/verification` (request, evidence upload, answer a question) and the Verified Member badge | Done | `VerificationPage.tsx`; D1 to D8 |
| 8 | `/account/appeals` with deadlines | Done | `AppealsPage.tsx`; D10 to D13 |
| 9 | Notification bell (live, reconnect state) and `/account/notifications` (inbox, archive, email preferences) | Done | `NotificationBell.tsx`, `NotificationsPage.tsx`, `utils/notifications.test.ts`; N1 to N6 |
| 10 | Members review under their own name with photos and one video | Done | `GuestReviewForm.tsx`, `ReviewPhotos.tsx`, `utils/reviewPhotos.test.ts`; `test_media.py` |
| 11 | Staff dashboard: sign in, TOTP enrolment, queue, media, enforcement, audit, staff roles, monitoring, inbox, notification operations | Done | `staff/src/*`, `staff/src/api.test.ts`, `staff/src/logic.test.ts`; guide sections 4, 5, 5b, 5d |

## Before release (owner actions, not code)

| # | Action | Why |
|---|---|---|
| 1 | Set `AUTH_SKIP_EMAIL_VERIFICATION=false` (or delete the line) in `backend/.env` | It is on locally only while Brevo is not ready; production refuses to start with it on |
| 2 | Finish Brevo: verified sender, then `EMAIL_PROVIDER=brevo` + `BREVO_API_KEY` (or the SMTP key) | Real verification and reset emails; until then they go to Mailpit locally |
| 3 | Roll the Supabase service role key that was pasted in chat, and put the new one in `backend/.env` and Railway yourself | The old key is exposed |
| 4 | ~~Apply migration `0017_notification_system` online~~ | Done 28 Oct 2026 |
| 5 | Commit and push to `backend-dev`, merge into `main` | Railway deploys `main`; it still runs commit `a337d5c` without accounts |
| 6 | Railway variables: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWKS_URL`, `SUPABASE_SERVICE_ROLE_KEY` (you), the email settings, and the staff site in `CORS_ALLOWED_ORIGINS` | The deployed API needs them |
| 7 | Deploy the staff dashboard under the choturmatra30 Vercel account (`vercel login`, then ask Claude) | It calls the API through its own `/api` path so cookies stay first-party |
| 8 | Same-site domain for the public app and API (PF 5.5), or the same `/api` forwarding for the public app | Browsers do not send `SameSite=Lax` cookies across sites |
