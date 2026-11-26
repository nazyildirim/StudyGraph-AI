"""Shared FastAPI route utilities."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class SanitizedValidationRoute(APIRoute):
    """APIRoute that strips raw `input` values from 422 validation errors.

    Prevents secrets, passwords, or sensitive request fields from ever being
    echoed back to clients in Pydantic/FastAPI validation error payloads.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()

        async def sanitized_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                sanitized_errors = [
                    {
                        "type": err.get("type"),
                        "loc": list(err.get("loc", ())),
                        "msg": err.get("msg"),
                    }
                    for err in exc.errors()
                ]
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"detail": sanitized_errors},
                )

        return sanitized_handler
