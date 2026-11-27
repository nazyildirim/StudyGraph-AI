"""Bounded ASGI request body size guard for multipart material uploads (HIGH-1).

Enforces an early byte limit BEFORE Starlette / python-multipart spools an
oversized upload to RAM or disk:
1. Checks `Content-Length` immediately if present (fast-reject 413).
2. Counts actual streamed bytes in `receive()` to catch missing, chunked, or
   forged `Content-Length` headers without buffering the body in memory.
3. Applies strictly to `POST .../materials/upload` paths so other endpoints
   are unaffected.
"""

from __future__ import annotations

import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 512 * 1024


class _BodyTooLargeError(Exception):
    """Internal signal to abort downstream multipart parsing cleanly."""


def _configured_upload_limit_bytes() -> int:
    raw = os.environ.get("UPLOAD_MAX_BYTES", "").strip()
    if raw:
        try:
            parsed = int(raw)
            if parsed >= 1024:
                return parsed + MULTIPART_OVERHEAD_BYTES
        except ValueError:
            pass
    return DEFAULT_UPLOAD_MAX_BYTES + MULTIPART_OVERHEAD_BYTES


class UploadBodyLimitMiddleware:
    """ASGI middleware rejecting oversized multipart upload streams with 413."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int | None = None,
    ) -> None:
        self._app = app
        self._explicit_limit = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        if method != "POST" or not path.rstrip("/").endswith("/materials/upload"):
            await self._app(scope, receive, send)
            return

        limit = (
            self._explicit_limit
            if self._explicit_limit is not None
            else _configured_upload_limit_bytes()
        )

        # 1. Fast-reject based on Content-Length header before reading any bytes.
        for header_name, header_value in scope.get("headers", ()):
            if header_name.lower() == b"content-length":
                try:
                    declared = int(header_value.decode("ascii").strip())
                except (ValueError, UnicodeDecodeError):
                    response = JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid Content-Length header."},
                    )
                    await response(scope, receive, send)
                    return
                if declared < 0:
                    response = JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid Content-Length header."},
                    )
                    await response(scope, receive, send)
                    return
                if declared > limit:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "detail": "Uploaded request body exceeds maximum allowed size."
                        },
                    )
                    await response(scope, receive, send)
                    return

        # 2. Stream-count actual received bytes (handles chunked or forged Content-Length).
        total_received = 0
        response_started = False

        async def guarded_receive() -> Message:
            nonlocal total_received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                total_received += len(body)
                if total_received > limit:
                    raise _BodyTooLargeError()
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, guarded_receive, tracked_send)
        except _BodyTooLargeError:
            if not response_started:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Uploaded request body exceeds maximum allowed size."
                    },
                )
                await response(scope, receive, send)
            else:
                raise
