"""Tests of the closing of the exe's splash screen."""

from __future__ import annotations

import sys
import types

import pytest

from ddviz.desktop import messages, splash


@pytest.fixture
def pyi_splash(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the bootloader's ``pyi_splash`` module; record its closes."""
    closes: list[str] = []
    fake = types.ModuleType("pyi_splash")
    fake.close = lambda: closes.append("close")
    monkeypatch.setitem(sys.modules, "pyi_splash", fake)
    monkeypatch.setattr(splash, "_closed", False)
    return closes


def test_without_the_bootloader_nothing_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``_PYI_SPLASH_IPC`` (development, a worker) pyi_splash is not imported."""
    monkeypatch.delenv("_PYI_SPLASH_IPC", raising=False)
    monkeypatch.delitem(sys.modules, "pyi_splash", raising=False)
    monkeypatch.setattr(splash, "_closed", False)
    splash.close_splash()
    assert "pyi_splash" not in sys.modules


def test_the_splash_is_closed_once(
    monkeypatch: pytest.MonkeyPatch, pyi_splash: list[str]
) -> None:
    """With the bootloader's variable, the first call closes; a second does nothing."""
    monkeypatch.setenv("_PYI_SPLASH_IPC", "12345")
    splash.close_splash()
    splash.close_splash()
    assert pyi_splash == ["close"]


def test_a_failure_to_close_is_not_raised(
    monkeypatch: pytest.MonkeyPatch, pyi_splash: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    """A close that raises is logged, and the app goes on."""
    monkeypatch.setenv("_PYI_SPLASH_IPC", "12345")

    def fail() -> None:
        raise ConnectionError("no splash")

    monkeypatch.setattr(sys.modules["pyi_splash"], "close", fail)
    splash.close_splash()
    assert "could not be closed" in caplog.text


def test_a_message_box_closes_the_splash_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The splash is closed before the message box, so that it does not cover it."""
    steps: list[str] = []
    monkeypatch.setattr(messages, "close_splash", lambda: steps.append("close"))
    monkeypatch.setattr(sys, "platform", "win32")
    user32 = types.SimpleNamespace(MessageBoxW=lambda *a: steps.append("box"))
    monkeypatch.setattr(messages.ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
    messages.show_warning("text")
    assert steps == ["close", "box"]
