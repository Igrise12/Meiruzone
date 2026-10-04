"""FastAPI composition, loopback access policy, and sanitized errors."""

import logging
import re
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .api import router
from .config import Settings
from .database import Repository
from .demo import demo_emails
from .models import ErrorDetail, ErrorResponse, FieldError
from .services import ApiError, InboxService


logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 4096
LOOPBACK_HOST = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?$", re.I)


def error_response(status: int, code: str, message: str, fields=(), headers=None):
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, fields=list(fields)))
    return JSONResponse(status_code=status, content=body.model_dump(by_alias=True), headers=headers)


class SanitizedCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code >= 400:
            return error_response(400, "cors_forbidden", "Preflight request is not allowed.")
        return response


class LocalAccessMiddleware:
    def __init__(self, app, origins: tuple[str, ...]):
        self.app = app
        self.origins = origins

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        origin = headers.get("origin")

        async def reject(status, code, message):
            response_headers = None
            if origin in self.origins:
                response_headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
            await error_response(status, code, message, headers=response_headers)(scope, receive, send)

        if len(headers.getlist("host")) != 1 or len(headers.getlist("origin")) > 1:
            return await reject(400, "invalid_headers", "Request access headers are invalid.")
        if not LOOPBACK_HOST.fullmatch(headers.get("host", "")):
            return await reject(400, "invalid_host", "Only loopback hosts are allowed.")
        if origin is not None and origin not in self.origins:
            return await reject(403, "origin_forbidden", "Request origin is not allowed.")
        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            if headers.get("x-meiruzone-request") != "1":
                return await reject(403, "write_header_required", "The local write header is required.")
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                return await reject(415, "json_required", "State-changing requests require JSON.")
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    return await reject(413, "request_too_large", "Request body exceeds 4096 bytes.")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            original_receive = receive
            replayed = False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = replay
        response_started = False

        async def safe_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            # Contain failures here so the HTTP server cannot log private exception details.
            logger.error("Unexpected backend operation failure.")
            if not response_started:
                return await reject(500, "internal_error", "The operation could not be completed.")


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        try:
            settings = Settings.from_env()
        except ValueError:
            raise RuntimeError("Invalid backend configuration. Check the documented settings.") from None
    repository = Repository(settings.database_path)

    @asynccontextmanager
    async def lifespan(application):
        try:
            repository.initialize()
            if settings.demo:
                repository.seed_demo(demo_emails())
        except (OSError, sqlite3.Error, ValueError):
            raise RuntimeError("Local storage could not be initialized.") from None
        yield

    application = FastAPI(
        title="Meiruzone local API", version="0.1.0", lifespan=lifespan,
        docs_url=None, redoc_url=None,
    )
    application.state.inbox = InboxService(repository, settings)
    application.add_middleware(
        SanitizedCORSMiddleware, allow_origins=list(settings.frontend_origins),
        allow_credentials=False, allow_methods=["GET", "PATCH", "POST"],
        allow_headers=["Content-Type", "X-Meiruzone-Request"],
    )
    application.add_middleware(LocalAccessMiddleware, origins=settings.frontend_origins)

    @application.exception_handler(ApiError)
    async def api_error(request, error):
        return error_response(error.status, error.code, error.message)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        known_fields = {
            "body", "path", "query", "header", "email_id", "q", "category", "priority",
            "needsReview", "needs_review", "limit", "offset", "source", "mode", "X-Meiruzone-Request",
        }
        fields = []
        for item in error.errors():
            location = ".".join(str(part) for part in item["loc"] if part in known_fields)
            fields.append(FieldError(
                field=location or "request", code=item["type"], message="Invalid or missing value.",
            ))
        return error_response(422, "validation_error", "Request validation failed.", fields)

    @application.exception_handler(HTTPException)
    async def http_error(request, error):
        messages = {404: "Resource not found.", 405: "Method not allowed."}
        return error_response(error.status_code, "http_error", messages.get(error.status_code, "Request failed."))

    @application.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        logger.warning("Local storage operation failed.")
        return error_response(503, "storage_unavailable", "Local storage is unavailable. Try again.")

    application.include_router(router)
    return application


app = create_app()
