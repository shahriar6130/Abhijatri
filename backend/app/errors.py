"""The single API error contract (Docs/api/API.md section 2, Platform Foundation 12.3).

Every error body is ``{"error": {"code", "message", "request_id", "field_errors"}}``.
Clients branch on ``code``. ``message`` is Bangla by default and English when the
``Accept-Language`` header prefers it. Bodies never carry stack traces, SQL, secrets,
submitted values, internal paths, or whether an account exists.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# code -> (HTTP status, Bangla message, English message)
CATALOGUE: dict[str, tuple[int, str, str]] = {
    "AUTH_REQUIRED": (401, "অনুগ্রহ করে সাইন ইন করুন।", "Sign in is required."),
    "FORBIDDEN": (403, "এই কাজের অনুমতি আপনার নেই।", "You do not have permission to do this."),
    "SELF_MODERATION_FORBIDDEN": (
        403,
        "নিজের রিভিউ আপনি মডারেট করতে পারবেন না।",
        "You cannot moderate your own review.",
    ),
    "INVALID_CREDENTIALS": (401, "ইমেইল বা পাসওয়ার্ড সঠিক নয়।", "The email or password is not correct."),
    "EMAIL_NOT_VERIFIED": (403, "আগে আপনার ইমেইল যাচাই করুন।", "Verify your email address first."),
    "ACCOUNT_DISABLED": (403, "এই অ্যাকাউন্টটি বন্ধ করা হয়েছে।", "This account has been disabled."),
    "MFA_REQUIRED": (403, "দ্বি-স্তরের যাচাই (TOTP) প্রয়োজন।", "Two-step verification (TOTP) is required."),
    "REAUTH_REQUIRED": (403, "এই কাজের আগে আবার পাসওয়ার্ড দিয়ে যাচাই করুন।", "Confirm your identity again before this action."),
    "ACCOUNT_RESTRICTED": (403, "আপনার অ্যাকাউন্টে এই কাজটি সাময়িকভাবে সীমিত।", "Your account is temporarily restricted from doing this."),
    "APPEAL_REVIEWER_NOT_INDEPENDENT": (403, "যিনি মূল সিদ্ধান্ত দিয়েছেন তিনি আপিলের সিদ্ধান্ত দিতে পারবেন না।", "The person who made the original decision cannot decide its appeal."),
    "CSRF_INVALID": (403, "অনুরোধটি যাচাই করা যায়নি। পাতাটি রিফ্রেশ করুন।", "The request could not be verified. Refresh the page."),
    "CHALLENGE_FAILED": (403, "নিরাপত্তা যাচাই ব্যর্থ হয়েছে। আবার চেষ্টা করুন।", "The security check failed. Try again."),
    "NOT_FOUND": (404, "খুঁজে পাওয়া যায়নি।", "Not found."),
    "RECEIPT_NOT_FOUND": (404, "রিসিপ্টটি মেলেনি।", "The receipt does not match."),
    "METHOD_NOT_ALLOWED": (405, "এই পদ্ধতিটি অনুমোদিত নয়।", "This method is not allowed."),
    "REVIEW_VERSION_CONFLICT": (409, "এই রিভিউটি ইতিমধ্যে পরিবর্তিত হয়েছে।", "This review has already changed."),
    "LEASE_LOST": (409, "এই কাজের লিজ শেষ হয়েছে বা অন্যের হাতে গেছে। পাতাটি রিফ্রেশ করুন।", "Your claim on this task has ended. Reload to see the current state."),
    "TASK_NOT_AVAILABLE": (409, "কাজটি এখন নেওয়া যাবে না।", "This task cannot be claimed right now."),
    "VERIFICATION_ALREADY_OPEN": (409, "আপনার একটি যাচাই আবেদন ইতিমধ্যে চলছে।", "You already have a verification request in progress."),
    "ALREADY_VERIFIED": (409, "আপনি ইতিমধ্যে যাচাইকৃত সদস্য।", "You are already a Verified Member."),
    "DUPLICATE_APPEAL": (409, "এই সিদ্ধান্তের বিরুদ্ধে আপিল ইতিমধ্যে করা হয়েছে।", "This decision has already been appealed."),
    "LAST_SUPERADMIN": (409, "শেষ সুপারঅ্যাডমিনকে সরানো যাবে না।", "The last superadmin cannot be removed."),
    "INVALID_TRANSITION": (409, "বর্তমান অবস্থায় এই কাজটি করা যাবে না।", "This action is not allowed in the current state."),
    "DRAFT_ALREADY_SUBMITTED": (409, "এই খসড়াটি ইতিমধ্যে জমা দেওয়া হয়েছে।", "This draft was already submitted."),
    "MEMBER_REVIEW_EXISTS": (409, "এই গন্তব্যে এই মাসের জন্য আপনার একটি রিভিউ ইতিমধ্যে আছে।", "You already have a review of this destination for that month."),
    "RESERVED_DISPLAY_NAME": (409, "এই প্রদর্শন নামটি ব্যবহার করা যাবে না।", "This display name is reserved."),
    "IDEMPOTENCY_KEY_REUSED": (409, "একই কী ভিন্ন অনুরোধে ব্যবহার করা হয়েছে।", "This idempotency key was used with a different request."),
    "DUPLICATE_OPEN_REPORT": (409, "এই রিভিউয়ের জন্য আপনার একটি রিপোর্ট ইতিমধ্যে খোলা আছে।", "You already have an open report on this review."),
    "APPEAL_WINDOW_CLOSED": (409, "আপিলের সময় শেষ হয়ে গেছে।", "The appeal window has closed."),
    "PAYLOAD_TOO_LARGE": (413, "অনুরোধটি অনেক বড়।", "The request is too large."),
    "TOKEN_INVALID_OR_EXPIRED": (422, "লিংকটি সঠিক নয় বা মেয়াদ শেষ। নতুন লিংক চান।", "The link is not valid or has expired. Request a new one."),
    "EVIDENCE_REQUIRED": (422, "অনুমোদনের আগে অন্তত একটি প্রমাণ ফাইল লাগবে।", "At least one evidence file is needed before approval."),
    "TRANSITION_NOT_ALLOWED": (422, "বর্তমান অবস্থা থেকে এই পরিবর্তন অনুমোদিত নয়।", "This change is not allowed from the current state."),
    "VALIDATION_FAILED": (422, "প্রদত্ত তথ্য সঠিক নয়।", "The submitted data is not valid."),
    "INVALID_CURSOR": (422, "পৃষ্ঠার কার্সরটি সঠিক নয়।", "The page cursor is not valid."),
    "INVALID_RECEIPT_FORMAT": (422, "রিসিপ্টের ফরম্যাট সঠিক নয়।", "The receipt format is not valid."),
    "RATE_LIMITED": (429, "অনেক বেশি অনুরোধ। কিছুক্ষণ পরে আবার চেষ্টা করুন।", "Too many requests. Try again shortly."),
    "INTERNAL_ERROR": (500, "একটি অপ্রত্যাশিত ত্রুটি ঘটেছে।", "An unexpected error occurred."),
    "AUTH_NOT_CONFIGURED": (501, "সাইন-ইন সেবা এখনও চালু হয়নি।", "Sign-in is not configured."),
    "STAFF_AUTH_NOT_CONFIGURED": (501, "স্টাফ প্রমাণীকরণ এখনও চালু হয়নি।", "Staff authentication is not configured."),
    "GUEST_WRITES_PAUSED": (503, "অতিথি জমা সাময়িকভাবে বন্ধ আছে। পড়া চালু থাকবে।", "Guest submissions are paused. Reading continues."),
    "SERVICE_UNAVAILABLE": (503, "সেবাটি সাময়িকভাবে পাওয়া যাচ্ছে না। আবার চেষ্টা করুন।", "The service is temporarily unavailable. Try again."),
    "REQUEST_TIMEOUT": (504, "অনুরোধটির সময় শেষ হয়ে গেছে।", "The request timed out."),
}

_HTTP_STATUS_CODES = {
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    501: "STAFF_AUTH_NOT_CONFIGURED",
}

# Pydantic error type -> stable field-error code.
_FIELD_CODES = {
    "missing": "REQUIRED",
    "extra_forbidden": "UNKNOWN_FIELD",
    "string_too_short": "TOO_SHORT",
    "string_too_long": "TOO_LONG",
    "greater_than_equal": "TOO_SMALL",
    "greater_than": "TOO_SMALL",
    "less_than_equal": "TOO_LARGE",
    "less_than": "TOO_LARGE",
    "uuid_parsing": "INVALID_UUID",
    "uuid_type": "INVALID_UUID",
    "enum": "INVALID_VALUE",
    "literal_error": "INVALID_VALUE",
    "date_parsing": "INVALID_DATE",
    "date_from_datetime_parsing": "INVALID_DATE",
    "date_type": "INVALID_DATE",
    "json_invalid": "INVALID_JSON",
    "bool_parsing": "INVALID_VALUE",
    "int_parsing": "INVALID_VALUE",
    "string_type": "INVALID_VALUE",
}


class ApiError(Exception):
    """Raise anywhere in a request to produce the standard error body for ``code``."""

    def __init__(
        self,
        code: str,
        *,
        field_errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if code not in CATALOGUE:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(code)
        self.code = code
        self.status_code = CATALOGUE[code][0]
        self.field_errors = field_errors or []
        self.headers = headers or {}


def preferred_language(header: str | None) -> str:
    """Return ``"bn"`` or ``"en"``. Bangla is the default."""
    if not header:
        return "bn"
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate(header.split(",")):
        tag, *params = part.strip().split(";")
        weight = 1.0
        for param in params:
            name, _, value = param.strip().partition("=")
            if name == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        primary = tag.strip().lower().split("-")[0]
        if primary in {"bn", "en"} and weight > 0:
            ranked.append((-weight, position, primary))
    return min(ranked)[2] if ranked else "bn"


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def error_response(
    request: Request,
    code: str,
    *,
    field_errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    status_code, message_bn, message_en = CATALOGUE[code]
    language = preferred_language(request.headers.get("accept-language"))
    request_id = request_id_of(request)
    request.state.error_code = code  # read by the ops event middleware (app.main)
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message_en if language == "en" else message_bn,
                "request_id": request_id,
                "field_errors": field_errors or [],
            }
        },
        status_code=status_code,
        headers={**(headers or {}), "X-Request-ID": request_id},
    )


def _field_code(error: dict[str, Any]) -> str:
    kind = str(error.get("type", ""))
    if kind == "value_error":
        message = str(error.get("msg", "")).lower()
        if "future" in message:
            return "FUTURE_MONTH"
        if "first day" in message:
            return "NOT_FIRST_OF_MONTH"
        return "INVALID_VALUE"
    return _FIELD_CODES.get(kind, kind.upper() or "INVALID_VALUE")


def field_errors_from(exc: RequestValidationError) -> list[dict[str, str]]:
    """Field paths and codes only: submitted values are never echoed back."""
    result = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())[1:]]
        result.append({"field": ".".join(location) or "body", "code": _field_code(dict(error))})
    return result


def _retry_after(exc: RateLimitExceeded) -> str:
    try:
        return str(max(1, int(exc.limit.limit.get_expiry())))  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - the limit object shape is a library detail
        return "60"


def install_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request, error.code, field_errors=error.field_errors, headers=error.headers
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(error.status_code, "INTERNAL_ERROR")
        return error_response(request, code, headers=dict(error.headers or {}))

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(request, "VALIDATION_FAILED", field_errors=field_errors_from(error))

    @application.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, error: RateLimitExceeded) -> JSONResponse:
        return error_response(request, "RATE_LIMITED", headers={"Retry-After": _retry_after(error)})

    @application.exception_handler(DBAPIError)
    async def database_unavailable(request: Request, error: DBAPIError) -> JSONResponse:
        logger.error("database error on %s", request.url.path, exc_info=error)
        return error_response(request, "SERVICE_UNAVAILABLE", headers={"Retry-After": "5"})

    @application.exception_handler(PoolTimeoutError)
    async def pool_exhausted(request: Request, error: PoolTimeoutError) -> JSONResponse:
        logger.error("connection pool exhausted on %s", request.url.path, exc_info=error)
        return error_response(request, "SERVICE_UNAVAILABLE", headers={"Retry-After": "5"})

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("unhandled error on %s", request.url.path, exc_info=error)
        return error_response(request, "INTERNAL_ERROR")
