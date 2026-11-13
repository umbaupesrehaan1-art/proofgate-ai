"""FastAPI application factory and versioned ProofGate endpoints."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from proofgate import __version__
from proofgate.analyzer import AnalyzerError
from proofgate.github import GitHubIntegrationError, inspect_github
from proofgate.models import (
    AnalysisRequest,
    ErrorResponse,
    GitHubInspectionRequest,
    VerificationRequest,
)
from proofgate.runner import analyze_request, run_verification

logger = logging.getLogger("proofgate.api")
MAX_REQUEST_BYTES = 512_000


class RequestSizeLimitMiddleware:
    """Bound request bodies, including chunked requests without Content-Length."""

    def __init__(self, app: Any, *, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._send_too_large(scope, send)
                    return
            except ValueError:
                await self._send_error(scope, send, 400, "invalid_request", "Invalid request.")
                return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._send_too_large(scope, send)
                return
            more_body = message.get("more_body", False)

        sent = False

        async def replay_body() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)

    async def _send_too_large(self, scope: dict[str, Any], send: Any) -> None:
        await self._send_error(
            scope, send, 413, "request_too_large", "Request body exceeds the size limit."
        )

    @staticmethod
    async def _send_error(
        scope: dict[str, Any], send: Any, status: int, code: str, message: str
    ) -> None:
        payload = json.dumps(
            ErrorResponse(error=code, message=message, request_id=uuid4().hex).model_dump()
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


def _error_response(status_code: int, code: str, message: str, request: Request) -> JSONResponse:
    request_id = request.headers.get("x-request-id", uuid4().hex)[:100]
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=code, message=message, request_id=request_id).model_dump(),
    )


def _analyzer_status(error: AnalyzerError) -> tuple[int, str]:
    if error.code == "not_found":
        return 404, error.code
    if error.code == "root_not_configured":
        return 503, error.code
    if error.code in ("invalid_root", "unreadable_path"):
        return 503, error.code
    if error.code in ("diff_too_large",):
        return 413, error.code
    return 400, error.code


def create_app(repository_root: Path | None = None) -> FastAPI:
    """Create an application; repository access is restricted to this configured root."""
    configured_root = repository_root
    if configured_root is None:
        configured = os.getenv("PROOFGATE_REPOSITORY_ROOT")
        configured_root = Path(configured) if configured else None

    application = FastAPI(
        title="ProofGate AI",
        version=__version__,
        description="Evidence-first analysis of AI-generated code changes.",
        docs_url="/docs",
        redoc_url=None,
    )
    application.state.repository_root = configured_root
    application.add_middleware(RequestSizeLimitMiddleware)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields: list[str] = []
        for error in exc.errors()[:10]:
            location = error.get("loc", ())
            if location and location[0] == "body":
                location = location[1:]
            field = ".".join(str(part) for part in location)[:120] or "request"
            if field not in fields:
                fields.append(field)
        request_id = request.headers.get("x-request-id", uuid4().hex)[:100]
        return JSONResponse(
            status_code=422,
            content={
                **ErrorResponse(
                    error="validation_error",
                    message="Request validation failed.",
                    request_id=request_id,
                ).model_dump(),
                "fields": fields,
            },
        )

    @application.exception_handler(ValidationError)
    async def model_validation_error_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        del exc
        return _error_response(422, "validation_error", "Request validation failed.", request)

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled request error (%s)", type(exc).__name__)
        return _error_response(
            500, "internal_error", "The request could not be completed.", request
        )

    @application.get("/")
    def service_root() -> dict[str, str]:
        return {
            "service": "ProofGate AI",
            "description": "Evidence-first verification for AI-generated code changes.",
            "version": __version__,
        }

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/v1")
    def api_index() -> dict[str, Any]:
        return {
            "version": "v1",
            "endpoints": {
                "analyze": {
                    "method": "POST",
                    "path": "/api/v1/analyze",
                    "description": "Read-only Python source analysis.",
                },
                "verify": {
                    "method": "POST",
                    "path": "/api/v1/verify",
                    "description": "Safe evidence collection and policy decision.",
                },
                "github_inspect": {
                    "method": "POST",
                    "path": "/api/v1/github/inspect",
                    "description": "Bounded, read-only inspection of public GitHub content.",
                },
            },
        }

    @application.post("/api/v1/analyze")
    def analyze(payload: AnalysisRequest, request: Request) -> Any:
        root = application.state.repository_root
        if root is None:
            return _error_response(
                503,
                "root_not_configured",
                "Repository analysis is unavailable because no permitted root is configured.",
                request,
            )
        try:
            return analyze_request(root, payload.repository_path, max_files=payload.max_files)
        except AnalyzerError as exc:
            status, code = _analyzer_status(exc)
            return _error_response(status, code, exc.message, request)

    @application.post("/api/v1/verify")
    def verify(payload: VerificationRequest, request: Request) -> Any:
        try:
            result = run_verification(payload, repository_root=application.state.repository_root)
            return result
        except AnalyzerError as exc:
            status, code = _analyzer_status(exc)
            return _error_response(status, code, exc.message, request)

    @application.post("/api/v1/github/inspect")
    def github_inspect(payload: GitHubInspectionRequest, request: Request) -> Any:
        try:
            return inspect_github(payload)
        except GitHubIntegrationError as exc:
            return _error_response(exc.status_code, exc.code, exc.message, request)

    return application


app = create_app()
