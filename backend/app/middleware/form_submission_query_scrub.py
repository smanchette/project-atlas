from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any


ASGIApp = Callable[
    [dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]],
    Awaitable[None],
]


class FormSubmissionQueryScrubMiddleware:
    """Remove form-query bytes before routing, validation, or access observation."""

    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        self.app = app
        prefix = "/" + api_prefix.strip("/") if api_prefix.strip("/") else ""
        self._path = re.compile(
            rf"^{re.escape(prefix)}/websites/[^/]+/forms/[^/]+/submissions/?$"
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http" and self._path.fullmatch(
            str(scope.get("path", ""))
        ):
            query_was_present = bool(scope.get("query_string", b""))
            scope["query_string"] = b""
            if query_was_present:
                scope["atlas_form_query_was_present"] = True
        await self.app(scope, receive, send)
