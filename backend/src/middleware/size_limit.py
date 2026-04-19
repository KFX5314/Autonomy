"""
Request body size limit middleware.

Rejects any request whose Content-Length header exceeds config.MAX_BODY_BYTES
before Starlette buffers the body, which matters for the audio upload endpoint
where an attacker could otherwise submit a multi-gigabyte "audio" payload.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import config


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > config.MAX_BODY_BYTES:
                    return JSONResponse(
                        {"detail": "Payload too large"},
                        status_code=413,
                    )
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        return await call_next(request)
