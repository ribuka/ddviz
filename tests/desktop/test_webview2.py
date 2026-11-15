"""Tests of reaching a window's WebView2, with fakes of pywebview's and WebView2's objects."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Self

import pytest

from ddviz.desktop.webview2 import on_ui, when_ready


class _Event:
    """A .NET event: handlers are added with ``+=``."""

    def __init__(self) -> None:
        self.handlers: list[Callable[..., None]] = []

    def __iadd__(self, handler: Callable[..., None]) -> Self:
        self.handlers.append(handler)
        return self

    def fire(self, *args: object) -> None:
        for handler in self.handlers:
            handler(*args)


class _Args:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


class _Control:
    def __init__(self, core: object | None) -> None:
        self.CoreWebView2 = core
        self.CoreWebView2InitializationCompleted = _Event()


class _Form:
    def Invoke(self, action: object) -> None:
        raise RuntimeError("no UI thread")


class _Window:
    def __init__(self) -> None:
        self.native = _Form()


def test_a_ready_control_is_handed_over_now() -> None:
    """A ready WebView2 is handed over at once, without subscribing."""
    core = object()
    control = _Control(core)
    calls: list[object] = []

    when_ready(control, calls.append)

    assert calls == [core]
    assert control.CoreWebView2InitializationCompleted.handlers == []


def test_a_control_is_handed_over_once_its_initialization_succeeds() -> None:
    """A WebView2 not ready yet is handed over once it is."""
    control = _Control(None)
    calls: list[object] = []

    when_ready(control, calls.append)
    assert calls == []

    core = object()
    control.CoreWebView2 = core
    control.CoreWebView2InitializationCompleted.fire(control, _Args(IsSuccess=True))

    assert calls == [core]


def test_a_failed_initialization_hands_over_nothing() -> None:
    """A failed start of WebView2 hands over nothing."""
    control = _Control(None)
    calls: list[object] = []

    when_ready(control, calls.append)
    control.CoreWebView2InitializationCompleted.fire(control, _Args(IsSuccess=False))

    assert calls == []


def test_a_failure_on_the_ui_thread_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A failure, also without pythonnet, is logged to the caller's logger."""
    log = logging.getLogger("ddviz.test_webview2")
    ran: list[bool] = []

    with caplog.at_level(logging.ERROR, logger=log.name):
        ok = on_ui(_Window(), lambda: ran.append(True), log, "cannot do it")

    assert ok is False
    assert ran == []
    assert [(r.name, r.levelno, r.getMessage()) for r in caplog.records] == [
        (log.name, logging.ERROR, "cannot do it")
    ]
