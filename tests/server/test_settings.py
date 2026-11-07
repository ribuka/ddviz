"""Tests of reading the settings file."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddviz.server.settings import (
    CacheSettings,
    ColumnsSettings,
    HoverSettings,
    LegendSettings,
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
    assert load_settings().hover == HoverSettings()
    assert load_settings().columns == ColumnsSettings()


def test_max_levels_is_read(tmp_path: Path) -> None:
    """``plot.max_levels`` sets the most levels; without it the default is 100."""
    path = tmp_path / "settings.toml"
    path.write_text("[plot]\nmax_levels = 80\n", encoding="utf-8")
    assert load_settings(path).plot.max_levels == 80
    assert PlotSettings().max_levels == 100


def test_max_axis_levels_is_read_apart_from_max_levels(tmp_path: Path) -> None:
    """``plot.max_axis_levels`` sets the most levels of a categorical x or y (a million by default) and leaves ``max_levels`` as it is."""
    path = tmp_path / "settings.toml"
    path.write_text("[plot]\nmax_axis_levels = 5000\n", encoding="utf-8")
    plot = load_settings(path).plot
    assert (plot.max_axis_levels, plot.max_levels) == (5000, 100)
    assert PlotSettings().max_axis_levels == 1_000_000
    assert load_settings().plot.max_axis_levels == 1_000_000


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "true", '"50"'])
def test_max_axis_levels_must_be_a_positive_integer(tmp_path: Path, value: str) -> None:
    """A max_axis_levels that is not a positive integer is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot]\nmax_axis_levels = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="plot.max_axis_levels"):
        load_settings(path)


@pytest.mark.parametrize("value", ["0", "2.5", "true", '"50"'])
def test_max_levels_must_be_a_positive_integer(tmp_path: Path, value: str) -> None:
    """A max_levels that is not a positive integer is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot]\nmax_levels = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_levels"):
        load_settings(path)


def test_max_listed_is_read(tmp_path: Path) -> None:
    """``columns.max_listed`` sets the most listed columns; without it the default is 1000."""
    path = tmp_path / "settings.toml"
    path.write_text("[columns]\nmax_listed = 5000\n", encoding="utf-8")
    assert load_settings(path).columns.max_listed == 5000
    assert ColumnsSettings().max_listed == 1000


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "true", '"1000"'])
def test_max_listed_must_be_a_positive_integer(tmp_path: Path, value: str) -> None:
    """A max_listed that is not a positive integer is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[columns]\nmax_listed = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns.max_listed"):
        load_settings(path)


def test_max_history_is_read(tmp_path: Path) -> None:
    """``columns.max_history`` sets the most kept keywords; without it the default is 20."""
    path = tmp_path / "settings.toml"
    path.write_text("[columns]\nmax_history = 5\n", encoding="utf-8")
    assert load_settings(path).columns.max_history == 5
    assert ColumnsSettings().max_history == 20


@pytest.mark.parametrize("value", ["0", "2.5", "true"])
def test_max_history_must_be_a_positive_integer(tmp_path: Path, value: str) -> None:
    """A max_history that is not a positive integer is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[columns]\nmax_history = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns.max_history"):
        load_settings(path)


def test_hover_limit_is_read_in_gigabytes(tmp_path: Path) -> None:
    """``hover.max_temp_gb`` becomes bytes; without it the default is 2GB."""
    path = tmp_path / "settings.toml"
    path.write_text("[hover]\nmax_temp_gb = 0.5\n", encoding="utf-8")
    assert load_settings(path).hover.max_temp_bytes == 2**29
    assert HoverSettings().max_temp_bytes == 2 * 2**30


@pytest.mark.parametrize("value", ["0", "-1", "true", '"2"', "inf", "nan"])
def test_hover_limit_must_be_a_positive_number(tmp_path: Path, value: str) -> None:
    """A max_temp_gb that is not a positive finite number is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[hover]\nmax_temp_gb = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_temp_gb"):
        load_settings(path)


@pytest.mark.parametrize("value", ["0", "0.0", "0.5", "1", "1.0"])
def test_inactive_opacity_is_read(tmp_path: Path, value: str) -> None:
    """``plot.legend.inactive_opacity`` from 0 to 1 is read; without it the default is 0.1."""
    path = tmp_path / "settings.toml"
    path.write_text(
        f"[plot]\nmax_levels = 80\n\n[plot.legend]\ninactive_opacity = {value}\n",
        encoding="utf-8",
    )
    plot = load_settings(path).plot
    assert plot.legend.inactive_opacity == float(value)
    assert plot.max_levels == 80
    assert LegendSettings().inactive_opacity == 0.1


@pytest.mark.parametrize("value", ["-0.1", "1.5", "true", '"0.5"', "nan", "inf"])
def test_inactive_opacity_must_be_from_0_to_1(tmp_path: Path, value: str) -> None:
    """An inactive_opacity that is not a number from 0 to 1 is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot.legend]\ninactive_opacity = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="plot.legend.inactive_opacity"):
        load_settings(path)
