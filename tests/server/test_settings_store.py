"""Tests of saving the settings into the local file and putting them in effect."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ddviz.server import settings_files
from ddviz.server.settings import Settings, load_settings, local_path
from ddviz.server.settings_store import SettingsStore

LOCAL = """# my settings
[plot]
max_levels = 30 # mine
mystery = "kept"

[plot.legend]
# how faint
inactive_opacity = 0.2

[other]
a = 1
"""


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    """Return a shared settings file in a folder of its own; the local file is beside it."""
    path = tmp_path / "config" / "settings.toml"
    path.parent.mkdir()
    path.write_text("[columns]\nmax_listed = 50\n", encoding="utf-8")
    return path


def _left(folder: Path) -> list[str]:
    """Return the names of the files of the folder."""
    return sorted(p.name for p in folder.iterdir())


def test_a_save_changes_the_keys_given_and_keeps_the_rest(shared: Path) -> None:
    """Only the keys saved change; the other keys, unknown keys and comments of the local file stay as they were."""
    local = local_path(shared)
    local.write_text(LOCAL, encoding="utf-8")
    store = SettingsStore.load(shared)
    store.save({"plot.legend.inactive_opacity": 0.35, "columns.max_history": 5})
    assert local.read_text(encoding="utf-8") == (
        LOCAL.replace("inactive_opacity = 0.2", "inactive_opacity = 0.35")
        + "\n[columns]\nmax_history = 5\n"
    )
    assert store.current == load_settings(shared)
    assert store.current.plot.legend.inactive_opacity == 0.35
    assert store.current.plot.max_levels == 30
    assert store.current.columns.max_listed == 50
    assert store.current.columns.max_history == 5


def test_a_save_without_a_local_file_creates_it(shared: Path) -> None:
    """Without a local file, a save creates one with the keys saved alone; the shared file is not changed."""
    before = shared.read_text(encoding="utf-8")
    store = SettingsStore.load(shared)
    store.save({"hover.max_temp_gb": 0.5})
    assert load_settings(shared).hover.max_temp_gb == 0.5
    assert local_path(shared).read_text(encoding="utf-8") == "[hover]\nmax_temp_gb = 0.5\n"
    assert shared.read_text(encoding="utf-8") == before
    assert _left(shared.parent) == ["settings.local.toml", "settings.toml"]


def test_a_save_without_changes_writes_nothing(shared: Path) -> None:
    """No change creates no local file, and leaves an existing one untouched."""
    store = SettingsStore.load(shared)
    store.save({})
    assert not local_path(shared).exists()
    local = local_path(shared)
    local.write_text(LOCAL, encoding="utf-8")
    os.utime(local, (1_000_000, 1_000_000))
    store.save({})
    assert local.stat().st_mtime == 1_000_000
    assert local.read_text(encoding="utf-8") == LOCAL


def test_a_save_keeps_what_changed_in_the_local_file_since_it_was_read(
    shared: Path,
) -> None:
    """A key that another hand wrote into the local file after the load stays; the key saved wins over the file."""
    local = local_path(shared)
    local.write_text("[columns]\nmax_history = 3\n", encoding="utf-8")
    store = SettingsStore.load(shared)
    local.write_text(
        "[columns]\nmax_history = 3\n[cache]\nmax_unused_days = 2\n"
        "[plot]\nmax_levels = 9\n",
        encoding="utf-8",
    )
    store.save({"plot.max_levels": 40})
    settings = load_settings(shared)
    assert (settings.cache.max_unused_days, settings.plot.max_levels) == (2, 40)
    assert settings.columns.max_history == 3
    assert store.current == settings


def test_zero_and_fractions_are_saved_as_given(shared: Path) -> None:
    """The opacity 0, a cache of 0 GB and fractional days are saved and read back as given."""
    store = SettingsStore.load(shared)
    store.save(
        {
            "plot.legend.inactive_opacity": 0,
            "cache.max_gb": 0,
            "cache.max_unused_days": 0.5,
        }
    )
    settings = load_settings(shared)
    assert settings.plot.legend.inactive_opacity == 0
    assert (settings.cache.max_gb, settings.cache.max_unused_days) == (0, 0.5)


@pytest.mark.parametrize(
    "changes",
    [
        {"plot.max_levels": 0},
        {"plot.max_levels": 2.5},
        {"plot.max_levels": True},
        {"plot.legend.inactive_opacity": 1.5},
        {"plot.legend.inactive_opacity": float("nan")},
        {"cache.max_gb": -1},
        {"cache.max_unused_days": float("inf")},
        {"hover.max_temp_gb": 0},
        {"columns.max_listed": "10"},
        {"plot.unknown": 1},
        {"plot.legend": 1},
    ],
)
def test_a_wrong_value_is_refused_and_writes_nothing(
    shared: Path, changes: dict
) -> None:
    """A value wrong for its key, or a key that is not a setting, fails before anything is written."""
    local = local_path(shared)
    local.write_text(LOCAL, encoding="utf-8")
    store = SettingsStore.load(shared)
    before = store.current
    with pytest.raises(ValueError, match=next(iter(changes))):
        store.save({"columns.max_history": 4, **changes})
    assert local.read_text(encoding="utf-8") == LOCAL
    assert store.current is before


@pytest.mark.parametrize(
    ("which", "text"),
    [
        ("local", "[plot\n"),
        ("local", "[columns]\nmax_history = 0\n"),
        ("local", "plot = 3\n"),
        ("shared", "[columns\n"),
    ],
    ids=["local-not-toml", "local-wrong-value", "local-plot-not-a-table", "shared-not-toml"],
)
def test_a_wrong_file_is_not_overwritten(shared: Path, which: str, text: str) -> None:
    """When a file turned wrong since the load, a save fails and leaves both files and the settings in effect as they were."""
    store = SettingsStore.load(shared)
    before = store.current
    target = shared if which == "shared" else local_path(shared)
    target.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        store.save({"plot.max_levels": 7})
    assert target.read_text(encoding="utf-8") == text
    assert store.current is before
    assert _left(shared.parent) == sorted({"settings.toml", target.name})


@pytest.mark.parametrize("step", ["write", "replace"])
def test_a_failed_write_leaves_the_file_and_the_settings(
    shared: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """When the temporary file cannot be written, or cannot replace the local file, the file and the settings in effect stay, and no temporary file is left."""
    local = local_path(shared)
    local.write_text(LOCAL, encoding="utf-8")
    store = SettingsStore.load(shared)
    before = store.current

    def fail(*args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    if step == "write":
        monkeypatch.setattr(settings_files.os, "fdopen", fail)
    else:
        monkeypatch.setattr(settings_files.os, "replace", fail)
    with pytest.raises(PermissionError):
        store.save({"plot.max_levels": 7})
    assert local.read_text(encoding="utf-8") == LOCAL
    assert store.current is before
    assert _left(shared.parent) == ["settings.local.toml", "settings.toml"]


def test_a_folder_that_cannot_be_written_leaves_the_settings(
    tmp_path: Path,
) -> None:
    """A local file whose folder does not exist (cannot be written) fails with OSError and changes nothing."""
    store = SettingsStore(Settings(), tmp_path / "gone" / "settings.toml")
    with pytest.raises(OSError):
        store.save({"plot.max_levels": 7})
    assert store.current == Settings()
    assert _left(tmp_path) == []


def test_settings_without_a_file_cannot_be_saved() -> None:
    """A store made of settings alone (as tests make) refuses to save."""
    store = SettingsStore(Settings())
    with pytest.raises(ValueError, match="no file"):
        store.save({"plot.max_levels": 7})


def test_a_save_replaces_the_snapshot_and_leaves_the_old_one(shared: Path) -> None:
    """A save puts a new snapshot in effect; the one a task took before stays as it was."""
    store = SettingsStore.load(shared)
    taken = store.current
    store.save({"plot.max_levels": 7})
    assert taken.plot.max_levels == 100
    assert store.current.plot.max_levels == 7
