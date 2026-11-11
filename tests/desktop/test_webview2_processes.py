"""Tests of following the window's WebView2 processes, with fakes of WebView2's objects."""

from __future__ import annotations

from collections.abc import Callable
from typing import Self

from ddviz.desktop.webview2_processes import FrontendProcesses


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


class _Info:
    def __init__(self, pid: int) -> None:
        self.ProcessId = pid


class _Environment:
    def __init__(self, pids: list[int]) -> None:
        self.pids = pids
        self.ProcessInfosChanged = _Event()
        self.fail = False

    def GetProcessInfos(self) -> list[_Info]:
        if self.fail:
            raise RuntimeError("gone")
        return [_Info(p) for p in self.pids]

    def change(self, pids: list[int]) -> None:
        self.pids = pids
        self.ProcessInfosChanged.fire(self, None)


class _Core:
    def __init__(self, environment: _Environment) -> None:
        self.Environment = environment
        self.ProcessFailed = _Event()


class _Args:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


class _Control:
    def __init__(self, core: _Core | None) -> None:
        self.CoreWebView2 = core
        self.CoreWebView2InitializationCompleted = _Event()


def test_the_processes_follow_the_environment() -> None:
    """A ready WebView2 is listed at once, and again on each change."""
    environment = _Environment([10, 11])
    frontend = FrontendProcesses()
    assert frontend.pids() is None
    frontend.hook(_Control(_Core(environment)))
    assert frontend.pids() == [10, 11]
    environment.change([10, 11, 12])
    assert frontend.pids() == [10, 11, 12]


def test_a_webview2_not_ready_yet_is_listed_once_ready() -> None:
    """Before WebView2 is ready nothing is known; a failed start stays unknown."""
    environment = _Environment([20])
    control = _Control(None)
    frontend = FrontendProcesses()
    frontend.hook(control)
    assert frontend.pids() is None
    control.CoreWebView2 = _Core(environment)
    control.CoreWebView2InitializationCompleted.fire(control, _Args(IsSuccess=True))
    assert frontend.pids() == [20]

    failed = FrontendProcesses()
    other = _Control(None)
    failed.hook(other)
    other.CoreWebView2InitializationCompleted.fire(other, _Args(IsSuccess=False))
    assert failed.pids() is None


def test_the_processes_are_forgotten_when_webview2_or_the_window_ends() -> None:
    """The browser process exiting, or the window closing, ends the list for good."""
    environment = _Environment([30, 31])
    core = _Core(environment)
    frontend = FrontendProcesses()
    frontend.hook(_Control(core))
    core.ProcessFailed.fire(core, _Args(ProcessFailedKind="RenderProcessExited"))
    assert frontend.pids() == [30, 31]
    core.ProcessFailed.fire(core, _Args(ProcessFailedKind="BrowserProcessExited"))
    assert frontend.pids() is None
    environment.change([32])
    assert frontend.pids() is None

    closed = FrontendProcesses()
    closed.hook(_Control(_Core(_Environment([40]))))
    closed.end()
    assert closed.pids() is None


def test_a_failed_listing_makes_the_processes_unknown() -> None:
    """When listing fails the list is unknown until a change lists again."""
    environment = _Environment([50])
    environment.fail = True
    frontend = FrontendProcesses()
    frontend.hook(_Control(_Core(environment)))
    assert frontend.pids() is None
    environment.fail = False
    environment.change([50, 51])
    assert frontend.pids() == [50, 51]
    environment.fail = True
    environment.change([52])
    assert frontend.pids() is None
