"""Tests of reading the settings files: the defaults, the shared file and the local file over it."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ddviz.server.settings import (
    CacheSettings,
    ColumnsSettings,
    HoverSettings,
    ImageCopySettings,
    LegendSettings,
    PlotSettings,
    Settings,
    load_settings,
    local_path,
    setting_keys,
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


def test_the_repository_settings_load(tmp_path: Path) -> None:
    """The settings file shipped in ``config/`` parses and holds the defaults (a copy, without the local file of this checkout)."""
    assert settings_path().exists()
    copy = tmp_path / "settings.toml"
    shutil.copy2(settings_path(), copy)
    assert load_settings(copy) == Settings()


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
    """``plot.legend.inactive_opacity`` from 0 to 1 is read; without it the default is 0.15."""
    path = tmp_path / "settings.toml"
    path.write_text(
        f"[plot]\nmax_levels = 80\n\n[plot.legend]\ninactive_opacity = {value}\n",
        encoding="utf-8",
    )
    plot = load_settings(path).plot
    assert plot.legend.inactive_opacity == float(value)
    assert plot.max_levels == 80
    assert LegendSettings().inactive_opacity == 0.15
    assert load_settings(tmp_path / "none.toml").plot.legend.inactive_opacity == 0.15


@pytest.mark.parametrize("value", ["-0.1", "1.5", "true", '"0.5"', "nan", "inf"])
def test_inactive_opacity_must_be_from_0_to_1(tmp_path: Path, value: str) -> None:
    """An inactive_opacity that is not a number from 0 to 1 is refused."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot.legend]\ninactive_opacity = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="plot.legend.inactive_opacity"):
        load_settings(path)


@pytest.mark.parametrize("value", [96, 300])
def test_image_copy_dpi_is_read(tmp_path: Path, value: int) -> None:
    """``plot.image_copy.dpi`` of 96 or 300 is read; without it the default is 300."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot.image_copy]\ndpi = {value}\n", encoding="utf-8")
    assert load_settings(path).plot.image_copy.dpi == value
    assert load_settings(tmp_path / "none.toml").plot.image_copy.dpi == 300
    path.write_text("[plot]\nmax_levels = 80\n", encoding="utf-8")
    assert load_settings(path).plot.image_copy == ImageCopySettings(dpi=300)


@pytest.mark.parametrize(
    "value", ["true", '"300"', "300.0", "96.0", "72", "0", "-96", "600"]
)
def test_image_copy_dpi_must_be_96_or_300(tmp_path: Path, value: str) -> None:
    """A dpi that is not the integer 96 or 300 is refused with the key and the allowed values."""
    path = tmp_path / "settings.toml"
    path.write_text(f"[plot.image_copy]\ndpi = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"plot\.image_copy\.dpi needs the integer 96 or 300"):
        load_settings(path)


def _files(tmp_path: Path, shared: str | None, local: str | None) -> Path:
    """Write the shared and the local file (None leaves one out); return the shared one."""
    path = tmp_path / "settings.toml"
    if shared is not None:
        path.write_text(shared, encoding="utf-8")
    if local is not None:
        local_path(path).write_text(local, encoding="utf-8")
    return path


def test_the_local_file_is_beside_the_shared_one(tmp_path: Path) -> None:
    """The local file is ``settings.local.toml`` in the folder of the shared file, also for a path given."""
    assert local_path(tmp_path / "a" / "settings.toml") == tmp_path / "a" / "settings.local.toml"
    assert local_path(settings_path()) == settings_path().parent / "settings.local.toml"


@pytest.mark.parametrize(
    ("shared", "local"),
    [(None, None), ("", None), (None, ""), ("", "")],
    ids=["neither", "shared-empty", "local-empty", "both-empty"],
)
def test_without_files_or_keys_the_defaults_apply(
    tmp_path: Path, shared: str | None, local: str | None
) -> None:
    """Without either file, or with empty ones, every setting takes its default (the opacity 0.15)."""
    settings = load_settings(_files(tmp_path, shared, local))
    assert settings == Settings()
    assert settings.plot.legend.inactive_opacity == 0.15


def test_the_shared_file_alone_sets_its_keys(tmp_path: Path) -> None:
    """With the shared file alone, its keys apply and the others take their defaults."""
    path = _files(tmp_path, "[plot.legend]\ninactive_opacity = 0.3\n", None)
    settings = load_settings(path)
    assert settings.plot.legend.inactive_opacity == 0.3
    assert settings.plot.max_levels == 100


def test_the_local_file_alone_sets_its_keys(tmp_path: Path) -> None:
    """With the local file alone, its keys apply and the others take their defaults."""
    path = _files(tmp_path, None, "[columns]\nmax_listed = 7\n")
    settings = load_settings(path)
    assert settings.columns.max_listed == 7
    assert settings.columns.max_history == 20


def test_the_local_file_wins_key_by_key_in_the_same_table(tmp_path: Path) -> None:
    """A key of the local file wins over the shared one; the other keys of the same table stay from the shared file."""
    shared = "[columns]\nmax_listed = 50\nmax_history = 9\n[cache]\nmax_gb = 3\n"
    local = "[columns]\nmax_listed = 7\n"
    settings = load_settings(_files(tmp_path, shared, local))
    assert settings.columns == ColumnsSettings(max_listed=7, max_history=9)
    assert settings.cache == CacheSettings(max_gb=3)


def test_the_local_file_wins_key_by_key_in_nested_tables(tmp_path: Path) -> None:
    """``[plot.legend]`` of the local file changes the opacity alone; ``plot.max_levels`` and ``plot.image_copy`` stay from the shared file."""
    shared = (
        "[plot]\nmax_levels = 80\n[plot.legend]\ninactive_opacity = 0.4\n"
        "[plot.image_copy]\ndpi = 96\n"
    )
    local = "[plot.legend]\ninactive_opacity = 0.05\n"
    plot = load_settings(_files(tmp_path, shared, local)).plot
    assert plot == PlotSettings(
        max_levels=80,
        legend=LegendSettings(inactive_opacity=0.05),
        image_copy=ImageCopySettings(dpi=96),
    )


def test_every_setting_is_read_from_the_local_file(tmp_path: Path) -> None:
    """All the settings, set in the local file over a shared file with others, take the local values."""
    shared = (
        "[cache]\nmax_gb = 1\nmax_unused_days = 1\n"
        "[plot]\nmax_levels = 1\nmax_axis_levels = 1\n"
        "[plot.legend]\ninactive_opacity = 1\n[plot.image_copy]\ndpi = 300\n"
        "[columns]\nmax_listed = 1\nmax_history = 1\n[hover]\nmax_temp_gb = 1\n"
    )
    local = (
        "[cache]\nmax_gb = 2.5\nmax_unused_days = 0.5\n"
        "[plot]\nmax_levels = 12\nmax_axis_levels = 34\n"
        "[plot.legend]\ninactive_opacity = 0.25\n[plot.image_copy]\ndpi = 96\n"
        "[columns]\nmax_listed = 56\nmax_history = 7\n[hover]\nmax_temp_gb = 0.25\n"
    )
    settings = load_settings(_files(tmp_path, shared, local))
    assert settings == Settings(
        cache=CacheSettings(max_gb=2.5, max_unused_days=0.5),
        plot=PlotSettings(
            max_levels=12,
            max_axis_levels=34,
            legend=LegendSettings(inactive_opacity=0.25),
            image_copy=ImageCopySettings(dpi=96),
        ),
        hover=HoverSettings(max_temp_gb=0.25),
        columns=ColumnsSettings(max_listed=56, max_history=7),
    )
    assert settings.cache.max_bytes == int(2.5 * 2**30)
    assert settings.hover.max_temp_bytes == 2**28
    assert len(setting_keys()) == 9


@pytest.mark.parametrize("value", ["0", "0.0", "1.5", "30"])
@pytest.mark.parametrize("key", ["max_gb", "max_unused_days"])
def test_cache_limits_take_0_and_more(tmp_path: Path, key: str, value: str) -> None:
    """The cache's size and days take finite numbers from 0, fractions too."""
    path = _files(tmp_path, None, f"[cache]\n{key} = {value}\n")
    assert getattr(load_settings(path).cache, key) == float(value)


@pytest.mark.parametrize("value", ["-1", "-0.5", "inf", "nan", "true", '"10"'])
@pytest.mark.parametrize("key", ["max_gb", "max_unused_days"])
def test_cache_limits_must_be_finite_and_not_negative(
    tmp_path: Path, key: str, value: str
) -> None:
    """A cache's size or days below 0, infinite, NaN, a bool or a string is refused with its key."""
    path = _files(tmp_path, f"[cache]\n{key} = {value}\n", None)
    with pytest.raises(ValueError, match=f"cache.{key}"):
        load_settings(path)


@pytest.mark.parametrize("value", ["1", "1000000000"])
def test_positive_integers_take_1_and_have_no_upper_bound(
    tmp_path: Path, value: str
) -> None:
    """The least value of an integer setting is 1; no upper bound is added."""
    path = _files(tmp_path, None, f"[columns]\nmax_history = {value}\n")
    assert load_settings(path).columns.max_history == int(value)


def test_a_wrong_value_of_the_local_file_is_refused_with_its_key(tmp_path: Path) -> None:
    """A wrong value in the local file fails with its key, even when the shared file is right: no fallback to the shared value."""
    path = _files(tmp_path, "[plot]\nmax_levels = 50\n", "[plot]\nmax_levels = 0\n")
    with pytest.raises(ValueError, match="plot.max_levels"):
        load_settings(path)


def test_a_wrong_value_hidden_by_the_local_file_is_not_an_error(tmp_path: Path) -> None:
    """The merged values are checked: a wrong shared value that the local file replaces does not fail."""
    path = _files(tmp_path, "[plot]\nmax_levels = 0\n", "[plot]\nmax_levels = 5\n")
    assert load_settings(path).plot.max_levels == 5


@pytest.mark.parametrize("which", ["shared", "local"])
def test_a_file_that_is_not_toml_is_refused_with_its_name(tmp_path: Path, which: str) -> None:
    """A syntax error of either file fails with the file's name, without falling back to the other file."""
    good, bad = "[columns]\nmax_listed = 5\n", "[columns\nmax_listed = \n"
    path = _files(
        tmp_path, bad if which == "shared" else good, bad if which == "local" else good
    )
    name = r"settings\.toml" if which == "shared" else r"settings\.local\.toml"
    with pytest.raises(ValueError, match=name):
        load_settings(path)


@pytest.mark.parametrize("which", ["shared", "local"])
def test_a_file_that_cannot_be_read_is_refused_with_its_name(
    tmp_path: Path, which: str
) -> None:
    """A file that exists but cannot be read (a folder of the name, bytes not UTF-8) fails with its name."""
    path = tmp_path / "settings.toml"
    target = path if which == "shared" else local_path(path)
    target.mkdir()
    name = target.name.replace(".", r"\.")
    with pytest.raises(ValueError, match=name):
        load_settings(path)
    target.rmdir()
    target.write_bytes(b"\xff\xfe[cache]")
    with pytest.raises(ValueError, match=name):
        load_settings(path)


@pytest.mark.parametrize("text", ["plot = 3\n", "[plot]\nlegend = 0.5\n"])
def test_a_table_that_is_not_a_table_is_refused_with_its_key(
    tmp_path: Path, text: str
) -> None:
    """A table of the settings given as another value fails with its name."""
    with pytest.raises(ValueError, match="plot"):
        load_settings(_files(tmp_path, None, text))


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    """Keys that are not settings, in either file, are ignored."""
    path = _files(tmp_path, "[other]\na = 1\n", "top = 2\n[plot]\nmystery = 3\n")
    assert load_settings(path) == Settings()
