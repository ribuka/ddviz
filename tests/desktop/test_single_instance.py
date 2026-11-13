"""One window on the machine: the mutex, the window record, and the hand-over to the first run."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from ddviz.desktop import single_instance, window
from ddviz.desktop.single_instance import (
    MUTEX_NAME,
    Claim,
    Outcome,
    claim,
    record_window,
)

_ALREADY_EXISTS = 183
_ACCESS_DENIED = 5

_MINE = 1
_OTHER_SESSION = 2


class FakeWin32:
    """Win32 with a mutex, windows and sessions set by each test."""

    def __init__(self, mutex: tuple[int | None, int]) -> None:
        self.mutex = mutex
        self.names: list[str] = []
        self.closed: list[int] = []
        #: hwnd -> pid of the process that created it.
        self.windows: dict[int, int] = {}
        #: pid -> session.
        self.sessions: dict[int, int] = {100: _MINE}
        self.fronted: list[int] = []

    def create_mutex(self, name: str) -> tuple[int | None, int]:
        """Return the mutex set by the test."""
        self.names.append(name)
        return self.mutex

    def close_handle(self, handle: int) -> None:
        """Record a closed handle."""
        self.closed.append(handle)

    def is_window(self, hwnd: int) -> bool:
        """Return whether the window exists."""
        return hwnd in self.windows

    def window_pid(self, hwnd: int) -> int:
        """Return the process of the window, 0 when there is none."""
        return self.windows.get(hwnd, 0)

    def session_id(self, pid: int) -> int | None:
        """Return the session of the process."""
        return self.sessions.get(pid)

    def current_pid(self) -> int:
        """Return the id of this run."""
        return 100

    def bring_to_front(self, hwnd: int) -> None:
        """Record the window brought to the front."""
        self.fronted.append(hwnd)


class Clock:
    """Time that advances only by sleeping."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def __call__(self) -> float:
        """Return the time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the time."""
        self.sleeps += 1
        self.now += seconds


def _claim(api: FakeWin32, record: Path, clock: Clock | None = None) -> Claim:
    """Claim with the fakes and a 5-second wait."""
    clock = clock or Clock()
    return claim(api, record, wait=5.0, sleep=clock.sleep, clock=clock)


def test_without_the_mutex_the_run_takes_it_and_keeps_it(tmp_path: Path) -> None:
    """A run that creates the mutex goes on and keeps its handle open."""
    api = FakeWin32((42, 0))
    result = _claim(api, tmp_path / "window.json")
    assert result == Claim(Outcome.FIRST, 42)
    assert api.names == [MUTEX_NAME]
    assert api.closed == []


def test_the_first_run_records_its_window_and_pid(tmp_path: Path) -> None:
    """The first run writes its window's handle and its process id."""
    record = tmp_path / "ddviz" / "window.json"
    record_window(0x1234, 777, record)
    assert json.loads(record.read_text(encoding="utf-8")) == {
        "hwnd": 0x1234,
        "pid": 777,
    }
    record_window(0x99, record=record)
    assert json.loads(record.read_text(encoding="utf-8")) == {
        "hwnd": 0x99,
        "pid": os.getpid(),
    }


def test_a_mutex_of_another_user_is_in_use_at_once(tmp_path: Path) -> None:
    """ERROR_ACCESS_DENIED means another user: in use, without waiting."""
    api = FakeWin32((None, _ACCESS_DENIED))
    clock = Clock()
    result = _claim(api, tmp_path / "window.json", clock)
    assert result.outcome is Outcome.IN_USE
    assert clock.sleeps == 0
    assert api.fronted == []


def test_the_window_of_this_session_comes_to_the_front(tmp_path: Path) -> None:
    """A live window of a process in this session comes to the front."""
    record = tmp_path / "window.json"
    record_window(0x10, 500, record)
    api = FakeWin32((7, _ALREADY_EXISTS))
    api.windows[0x10] = 500
    api.sessions[500] = _MINE
    result = _claim(api, record)
    assert result.outcome is Outcome.FRONT
    assert api.fronted == [0x10]
    assert api.closed == [7]


def test_the_window_of_another_session_is_in_use(tmp_path: Path) -> None:
    """A live window in another session is not brought to the front."""
    record = tmp_path / "window.json"
    record_window(0x10, 500, record)
    api = FakeWin32((7, _ALREADY_EXISTS))
    api.windows[0x10] = 500
    api.sessions[500] = _OTHER_SESSION
    result = _claim(api, record)
    assert result.outcome is Outcome.IN_USE
    assert api.fronted == []


@pytest.mark.parametrize("case", ["no file", "no window", "other pid", "broken file"])
def test_without_a_live_window_after_waiting_it_is_in_use(
    tmp_path: Path, case: str
) -> None:
    """Without a live window of the recorded process, it is in use after waiting."""
    record = tmp_path / "window.json"
    api = FakeWin32((7, _ALREADY_EXISTS))
    api.sessions[500] = _MINE
    if case == "no window":
        record_window(0x10, 500, record)
    elif case == "other pid":
        record_window(0x10, 500, record)
        api.windows[0x10] = 600
        api.sessions[600] = _MINE
    elif case == "broken file":
        record.write_text("{", encoding="utf-8")
    clock = Clock()
    result = _claim(api, record, clock)
    assert result.outcome is Outcome.IN_USE
    assert api.fronted == []
    assert clock.now >= 5.0
    assert clock.sleeps > 1


def test_a_window_recorded_while_waiting_comes_to_the_front(tmp_path: Path) -> None:
    """A first run still starting records its window while the second waits."""
    record = tmp_path / "window.json"
    api = FakeWin32((7, _ALREADY_EXISTS))
    clock = Clock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.sleeps == 3:  # the first run shows its window
            record_window(0x10, 500, record)
            api.windows[0x10] = 500
            api.sessions[500] = _MINE

    result = claim(api, record, wait=5.0, sleep=sleep, clock=clock)
    assert result.outcome is Outcome.FRONT
    assert api.fronted == [0x10]


def test_off_windows_nothing_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off Windows the run goes on."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert claim() == Claim(Outcome.FIRST)


@pytest.fixture
def no_window(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Replace what `run_window` opens, and record what it would show."""
    calls: dict[str, list] = {"runs": [], "warnings": []}
    monkeypatch.setattr(window, "_choose_runtime", lambda: "a runtime")
    monkeypatch.setattr(window, "_run", lambda *a: calls["runs"].append(a) or True)
    monkeypatch.setattr(window, "show_warning", calls["warnings"].append)
    monkeypatch.setattr(window, "RunLog", _NoLog)
    return calls


class _NoLog:
    """A run log that writes nothing."""

    def start(self) -> bool:
        return False

    def finish(self) -> None:
        pass

    def close(self) -> None:
        pass


def _run_window(paths: list[str] | None) -> int:
    """Run the window path with a dummy app."""
    return window.run_window(paths, False, lambda *a: None, lambda p: "x")


def test_the_first_run_opens_the_window(
    monkeypatch: pytest.MonkeyPatch, no_window: dict[str, list]
) -> None:
    """The run that owns the mutex opens the window."""
    monkeypatch.setattr(window, "claim", lambda: Claim(Outcome.FIRST, 42))
    assert _run_window(["a.parquet"]) == 0
    assert len(no_window["runs"]) == 1
    assert no_window["warnings"] == []


def test_in_use_is_told_and_opens_no_window(
    monkeypatch: pytest.MonkeyPatch, no_window: dict[str, list]
) -> None:
    """In use: the message, no window, a non-zero exit code."""
    monkeypatch.setattr(window, "claim", lambda: Claim(Outcome.IN_USE))
    assert _run_window(None) != 0
    assert no_window["runs"] == []
    assert no_window["warnings"] == [single_instance.IN_USE_MESSAGE]
    assert "他のユーザーが使用中です" in single_instance.IN_USE_MESSAGE


def test_a_second_run_with_a_path_only_brings_the_window_to_the_front(
    monkeypatch: pytest.MonkeyPatch, no_window: dict[str, list]
) -> None:
    """A second run ignores its input and ends normally without a message."""
    monkeypatch.setattr(window, "claim", lambda: Claim(Outcome.FRONT))
    assert _run_window(["other.parquet"]) == 0
    assert no_window["runs"] == []
    assert no_window["warnings"] == []
