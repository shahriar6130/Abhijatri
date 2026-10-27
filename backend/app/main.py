import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import get_settings
from app.destination_api import router as destination_router
from app.errors import ApiError, error_response, install_error_handlers
from app.guest_tag import DISPLAY_PATTERN
from app.limits import limiter
from app.ops import events
from app.ops.routes import router as ops_router

logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/openapi.json"})


RECEIPT_PATTERN = re.compile(r"abr1_[A-Za-z0-9_-]+")


class RedactIdentifiers(logging.Filter):
    """Backstop: guest tags and receipts never reach the logs (Guest-Identity-and-Visits 6, PF 26)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = RECEIPT_PATTERN.sub("[receipt]", DISPLAY_PATTERN.sub("[guest-tag]", message))
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def _install_log_filter() -> None:
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactIdentifiers) for f in handler.filters):
            handler.addFilter(RedactIdentifiers())


def _count_response(request: Request, status_code: int) -> None:
    events.count(f"http.{status_code // 100}xx")
    if status_code == 429:
        events.count("http.429")
    if getattr(request.state, "error_code", None) == "CHALLENGE_FAILED":
        events.count("challenge_failed")
    if status_code >= 500:
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "/(unmatched)"
        events.count(events.ROUTE_5XX_PREFIX + template)


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    flusher = events.Flusher()
    flusher.start()
    try:
        yield
    finally:
        flusher.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    _install_log_filter()
    docs = settings.docs_are_enabled
    application = FastAPI(
        title="Abhijatri API",
        version="0.1.0",
        description="Bangla-first, offline-ready travel platform API",
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    application.state.limiter = limiter
    install_error_handlers(application)

    @application.middleware("http")
    async def guardrails(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = request_id = str(uuid.uuid4())
        declared = request.headers.get("content-length", "")
        response: Response
        if declared.isdigit() and int(declared) > settings.max_request_body_bytes:
            response = error_response(request, "PAYLOAD_TOO_LARGE")
        else:
            try:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > settings.max_request_body_bytes:
                        raise ApiError("PAYLOAD_TOO_LARGE")

                # request.stream() consumes the ASGI body. Cache the validated body so
                # FastAPI can still parse JSON/form payloads in the downstream handler.
                request._body = bytes(body)
                response = await asyncio.wait_for(
                    call_next(request), timeout=settings.request_timeout_seconds
                )
            except ApiError as error:
                response = error_response(request, error.code)
            except TimeoutError:
                logger.error("request timed out: %s %s", request.method, request.url.path)
                response = error_response(request, "REQUEST_TIMEOUT")
        # Every response, success or early-return error, carries the same headers (audit F-06).
        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        # A JSON API never needs to run scripts or be framed (audit F-09). The interactive docs
        # (development only) load Swagger UI, so they are left without the CSP.
        if request.url.path not in DOCS_PATHS:
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @application.middleware("http")
    async def count_events(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Status classes and route templates only, never raw paths (Dashboard doc 6.3, PF 26).
        try:
            response = await call_next(request)
        except Exception:
            # An unhandled exception becomes a 500 in Starlette's outermost handler, after this
            # middleware; count it here or the dashboard's 5xx numbers would miss real failures.
            _count_response(request, 500)
            raise
        _count_response(request, response.status_code)
        return response

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["Content-Type", "Idempotency-Key", "Authorization"],
        allow_credentials=False,
        max_age=600,
    )
    application.include_router(router)
    application.include_router(destination_router)
    application.include_router(ops_router)
    return application


app = create_app()
