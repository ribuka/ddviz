"""Tests of reading the settings file."""

from __future__ import annotations

from pathlib import Path

from ddviz.settings import CacheSettings, load_settings, settings_path


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
