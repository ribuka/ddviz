"""Tests of keeping the window's WebView2 from reaching outside ddviz (Issue #377).

WebView2 is replaced by fakes with the members that `OfflineGuard` uses.
"""

from __future__ import annotations

from typing import Self

import pytest

from ddviz.desktop.offline import OfflineGuard, allowed

PORT = 50123
#: How pywebview's ``NavigateToString`` page starts (``html=``, ``load_html``).
OWN_PAGE = "data:text/html;charset=utf-8;base64,PGh0bWw+"


class _Event:
    """A .NET event: handlers come and go with ``+=`` and ``-=``."""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler: object) -> Self:
        self.handlers.append(handler)
        return self

    def __isub__(self, handler: object) -> Self:
        self.handlers.remove(handler)
        return self


class _Settings:
    """``CoreWebView2Settings``; `old` raises on the setting, as a runtime without it would."""

    def __init__(self, old: bool = False) -> None:
        self._old = old
        self.reputation = True

    @property
    def IsReputationCheckingRequired(self) -> bool:
        return self.reputation

    @IsReputationCheckingRequired.setter
    def IsReputationCheckingRequired(self, value: bool) -> None:
        if self._old:
            raise AttributeError("IsReputationCheckingRequired")
        self.reputation = value


class _Core:
    """``CoreWebView2``: its events and settings."""

    def __init__(self, settings: _Settings) -> None:
        self.NavigationStarting = _Event()
        self.NewWindowRequested = _Event()
        self.Settings = settings


class _Args:
    """The arguments of ``NavigationStarting`` and ``NewWindowRequested``."""

    def __init__(self, uri: str) -> None:
        self.Uri = uri
        self.Cancel = False
        self.Handled = False


def _pywebview(sender: object, args: object) -> None:
    raise AssertionError("the default browser")


def _guarded(port: int | None = PORT, settings: _Settings | None = None) -> tuple[OfflineGuard, _Core]:
    core = _Core(settings or _Settings())
    core.NewWindowRequested += _pywebview
    guard = OfflineGuard(lambda: port)
    guard.guard(core, _pywebview)
    return guard, core


@pytest.mark.parametrize(
    "uri",
    [
        f"http://127.0.0.1:{PORT}/?token=abc",
        f"http://127.0.0.1:{PORT}/static/js/app.js",
        OWN_PAGE,
    ],
)
def test_the_server_and_the_windows_own_pages_are_allowed(uri: str) -> None:
    """The UI server of the open input and pywebview's ``NavigateToString`` pages are ddviz's."""
    assert allowed(uri, PORT)


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/",
        "http://example.com/",
        f"http://127.0.0.1:{PORT + 1}/",
        f"https://127.0.0.1:{PORT}/",
        f"http://localhost:{PORT}/",
        f"http://127.0.0.1:{PORT}@example.com/",
        "http://127.0.0.1:notaport/",
        "file:///C:/Windows/win.ini",
        "about:blank",
        "data:image/svg+xml,<svg/>",
        "data:text/html,<script>fetch('https://example.com/')</script>",
    ],
)
def test_other_uris_are_refused(uri: str) -> None:
    """Another host, port or scheme is refused, also when it only looks like the server."""
    assert not allowed(uri, PORT)


def test_without_a_server_only_the_windows_own_pages_are_allowed() -> None:
    """On the chooser and during `New` no port is allowed."""
    assert allowed(OWN_PAGE, None)
    assert not allowed(f"http://127.0.0.1:{PORT}/", None)


def test_a_refused_navigation_is_cancelled_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    """``Cancel`` is set for a refused URI and not for the server's."""
    guard, core = _guarded()
    assert core.NavigationStarting.handlers == [guard.starting]
    outside = _Args("https://example.com/")
    guard.starting(core, outside)
    assert outside.Cancel
    assert "cancelled a navigation to https://example.com/" in caplog.text
    inside = _Args(f"http://127.0.0.1:{PORT}/")
    guard.starting(core, inside)
    assert not inside.Cancel


def test_the_allowed_port_follows_the_open_input() -> None:
    """The port is asked at each navigation: the next input's server takes the place of the last."""
    ports = [PORT]
    guard = OfflineGuard(lambda: ports[-1])
    ports.append(PORT + 1)
    old, new = _Args(f"http://127.0.0.1:{PORT}/"), _Args(f"http://127.0.0.1:{PORT + 1}/")
    guard.starting(None, old)
    guard.starting(None, new)
    assert old.Cancel
    assert not new.Cancel


def test_new_windows_open_nothing_in_place_of_pywebviews_handler() -> None:
    """The handler of pywebview, which opens the default browser, leaves; a request is handled with nothing opened."""
    guard, core = _guarded()
    assert core.NewWindowRequested.handlers == [guard.new_window]
    args = _Args("https://example.com/")
    guard.new_window(core, args)
    assert args.Handled


def test_smartscreen_is_turned_off() -> None:
    """``IsReputationCheckingRequired`` becomes False."""
    settings = _Settings()
    _guarded(settings=settings)
    assert settings.reputation is False


def test_a_runtime_without_the_setting_still_guards_the_navigation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure is logged, and the navigation and new windows stay guarded."""
    guard, core = _guarded(settings=_Settings(old=True))
    assert "cannot turn off SmartScreen" in caplog.text
    assert core.NavigationStarting.handlers == [guard.starting]
    assert core.NewWindowRequested.handlers == [guard.new_window]
