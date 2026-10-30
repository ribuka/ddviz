"""Token authentication of the UI server.

On a shared RDP server every user can connect to a localhost port, so each
run makes a secret token and only a client that has it is served. The window
opens ``/?token=<token>`` once; the server moves the token into an HttpOnly,
SameSite=Strict cookie and redirects to ``/``, so the page and everything it
requests by relative URL (fetch, EventSource, the static files) carry the
cookie without the page ever seeing the token.
"""

from __future__ import annotations

import secrets

from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "ddviz-token"


def _same(given: str | None, token: str) -> bool:
    """Compare in constant time; bytes, since `compare_digest` refuses non-ASCII str."""
    return given is not None and secrets.compare_digest(given.encode(), token.encode())


class TokenAuth:
    """ASGI middleware that answers 403 to every request without the token.

    Parameters
    ----------
    app : ASGIApp
        The application to protect.
    token : str
        The secret of this run.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass on a request with the token, set the cookie from the first URL, refuse the rest."""
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        if _same(connection.cookies.get(COOKIE), self._token):
            await self._app(scope, receive, send)
            return
        if scope["path"] == "/" and _same(
            connection.query_params.get("token"), self._token
        ):
            # 303 drops the token from the address, so a reload uses the cookie.
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(COOKIE, self._token, httponly=True, samesite="strict")
        else:
            response = PlainTextResponse("forbidden", status_code=403)
        await response(scope, receive, send)
