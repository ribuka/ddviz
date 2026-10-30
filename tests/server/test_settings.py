"""Tests of reading the settings file."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddviz.server.settings import (
    CacheSettings,
    PlotSettings,
    load_settings,
    settings_path,
)


def test_missing_file_and_keys_take_defaults(tmp_path: Path) -> None:
    """Without a file, or with keys left out, the defaults apply."""
    assert load_settings(tmp_path / "none.toml").cache == CacheSettings()
    path = tmp_path / "settings.toml"
    path.write_text("[cache]\nmax_unused_days = 7\n", encoding="utf-8")
    cache = load_settings(path).cache
    assert cache.max_unused_days == 7
    assert cache.max_bytes == CacheSettings().max_bytes


def test_cache_size_is_read_in_gigabytes(tmp_path: Path) -> None:
    """``max_gb`` becomes bytes."""
    path = tmp_path / "settings.toml"
    path.write_text("[cache]\nmax_gb = 1.5\n", encoding="utf-8")
    assert load_settings(path).cache.max_bytes == int(1.5 * 2**30)


def test_the_repository_settings_load() -> None:
    """The settings file shipped in ``config/`` parses."""
    assert settings_path().exists()
    assert load_settings().cache == CacheSettings()
    assert load_settings().plot == PlotSettings()


def test_max_levels_is_read(tmp_path: Path) -> None:
    """``plot.max_levels`` sets the most levels; without it the default is 50."""
    path = tmp_path / "settings.toml"
    path.write_text("[plot]\nmax_levels = 80\n", encoding="utf-8")
    assert load_settings(path).plot.max_levels == 80
    assert PlotSettings().max_levels == 50


@pytest.mark.parametrize("value", ["0", "2.5", "true", '"50"'])
def test_max_levels_must_be_a_positive_integer(tmp_path: Path, value: str) -> None:
    """A max_levels that is not a positive integer is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot]\nmax_levels = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_levels"):
        load_settings(path)
