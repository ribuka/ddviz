"""Tests of the Preferences items: every setting is an item or excluded, and the shipped file has every setting."""

from __future__ import annotations

import tomllib
from dataclasses import fields
from pathlib import Path

import pytest

from ddviz.server.preferences import EXCLUDED, GROUPS, ITEMS, SAVE_FAILED, Preferences
from ddviz.server.settings import load_settings, local_path, setting_keys, settings_path
from ddviz.server.settings_store import SettingsStore


def _toml_keys(table: dict, prefix: str = "") -> list[str]:
    """Return the dotted keys of the values of a TOML table."""
    keys = []
    for name, value in table.items():
        if isinstance(value, dict):
            keys += _toml_keys(value, f"{prefix}{name}.")
        else:
            keys.append(f"{prefix}{name}")
    return keys


def gaps(  # noqa: C901
    defined: list[str], items: list[str], excluded: dict[str, str], shipped: list[str]
) -> list[str]:
    """Return what is missing where, among the settings, the dialog's items and the shipped file.

    Parameters
    ----------
    defined : list of str
        Keys of the settings' definition (`ddviz.server.settings`).
    items : list of str
        Keys of the Preferences items.
    excluded : dict
        Settings the dialog leaves out, with the reason.
    shipped : list of str
        Keys of ``config/settings.toml``.

    Returns
    -------
    list of str
        One message per key missing somewhere; none when they agree.
    """
    messages = []
    for key in defined:
        if key not in items and key not in excluded:
            messages.append(f"{key}: in the settings, missing from the Preferences items and EXCLUDED")
        if key not in shipped:
            messages.append(f"{key}: in the settings, missing from config/settings.toml")
    for key in items:
        if key not in defined:
            messages.append(f"{key}: a Preferences item, missing from the settings")
        if key in excluded:
            messages.append(f"{key}: a Preferences item, also in EXCLUDED")
    for key, reason in excluded.items():
        if key not in defined:
            messages.append(f"{key}: in EXCLUDED, missing from the settings")
        if not reason.strip():
            messages.append(f"{key}: in EXCLUDED without a reason")
    for key in shipped:
        if key not in defined:
            messages.append(f"{key}: in config/settings.toml, missing from the settings")
    return messages


def _current() -> tuple[list[str], list[str], dict[str, str], list[str]]:
    """Return the keys of the settings, the items, the excluded settings and the shipped file."""
    shipped = tomllib.loads(settings_path().read_text(encoding="utf-8"))
    return setting_keys(), [i.key for i in ITEMS], dict(EXCLUDED), _toml_keys(shipped)


def test_the_settings_the_items_and_the_shipped_file_agree() -> None:
    """Every setting is a Preferences item (none is excluded now) and in config/settings.toml, and neither has others."""
    defined, items, excluded, shipped = _current()
    assert gaps(defined, items, excluded, shipped) == []
    assert excluded == {}
    assert len(items) == len(set(items)) == 9


def test_a_new_setting_left_out_of_the_dialog_fails() -> None:
    """A setting added to the definition and the shipped file but not to the items fails, naming the key and where it is missing."""
    defined, items, excluded, shipped = _current()
    assert gaps([*defined, "plot.new"], items, excluded, [*shipped, "plot.new"]) == [
        "plot.new: in the settings, missing from the Preferences items and EXCLUDED"
    ]


def test_an_item_without_a_setting_fails() -> None:
    """An item that is not a setting fails, naming the key."""
    defined, items, excluded, shipped = _current()
    assert gaps(defined, [*items, "plot.new"], excluded, shipped) == [
        "plot.new: a Preferences item, missing from the settings"
    ]


def test_a_key_of_the_shipped_file_alone_fails() -> None:
    """A key in config/settings.toml that is not a setting fails, naming the key."""
    defined, items, excluded, shipped = _current()
    assert gaps(defined, items, excluded, [*shipped, "plot.new"]) == [
        "plot.new: in config/settings.toml, missing from the settings"
    ]


def test_a_setting_missing_from_the_shipped_file_fails() -> None:
    """A setting and item that config/settings.toml lacks fails, naming the key."""
    defined, items, excluded, shipped = _current()
    assert gaps([*defined, "plot.new"], [*items, "plot.new"], excluded, shipped) == [
        "plot.new: in the settings, missing from config/settings.toml"
    ]


def test_an_excluded_setting_passes_and_an_excluded_item_fails() -> None:
    """A setting in EXCLUDED with a reason needs no item; one also an item, without a reason or without a setting fails."""
    defined, items, excluded, shipped = _current()
    new = [*defined, "plot.new"]
    shipped_new = [*shipped, "plot.new"]
    reason = {**excluded, "plot.new": "理由"}
    assert gaps(new, items, reason, shipped_new) == []
    assert gaps(new, [*items, "plot.new"], reason, shipped_new) == [
        "plot.new: a Preferences item, also in EXCLUDED"
    ]
    assert gaps(new, items, {**excluded, "plot.new": " "}, shipped_new) == [
        "plot.new: in EXCLUDED without a reason"
    ]
    assert gaps(defined, items, reason, shipped) == [
        "plot.new: in EXCLUDED, missing from the settings"
    ]


def test_every_item_has_a_group_a_label_and_a_timing() -> None:
    """Each item is in one of the four groups, in the order of the groups, with a label and when it takes effect."""
    assert GROUPS == ("グラフ表示", "列リスト", "キャッシュ", "ホバー")
    order = [GROUPS.index(i.group) for i in ITEMS]
    assert order == sorted(order)
    for item in ITEMS:
        assert item.label and item.timing
        assert item.input in {"percent", "integer", "number", "choice"}
        assert bool(item.choices) == (item.input == "choice")
    assert {f.name for f in fields(ITEMS[0])} >= {"key", "label", "unit", "timing"}


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    """Return the settings of an empty shared file in a folder of its own."""
    path = tmp_path / "settings.toml"
    path.write_text("", encoding="utf-8")
    return SettingsStore.load(path)


def test_the_state_has_the_items_and_the_values(store: SettingsStore) -> None:
    """The dialog gets the groups, every item and the value in effect of each, as the files hold them (GB, 0 to 1)."""
    state = Preferences(store).state()
    assert state["groups"] == list(GROUPS)
    assert [i["key"] for i in state["items"]] == [i.key for i in ITEMS]
    assert state["values"] == {
        "plot.legend.inactive_opacity": 0.15,
        "plot.max_levels": 100,
        "plot.max_axis_levels": 1_000_000,
        "plot.image_copy.dpi": 300,
        "columns.max_listed": 1000,
        "columns.max_history": 20,
        "cache.max_gb": 10,
        "cache.max_unused_days": 30,
        "hover.max_temp_gb": 2,
    }


def test_a_save_returns_the_values_in_effect(store: SettingsStore) -> None:
    """A save writes the local file and returns the new values."""
    found = Preferences(store).save({"plot.legend.inactive_opacity": 0.4})
    assert found["values"]["plot.legend.inactive_opacity"] == 0.4
    assert load_settings(store.path).plot.legend.inactive_opacity == 0.4


@pytest.mark.parametrize(
    "changes",
    [{"plot.max_levels": 0}, {"plot.image_copy.dpi": 72}, {"plot.nothing": 1}, [1]],
)
def test_a_save_that_fails_returns_the_error(store: SettingsStore, changes: object) -> None:
    """A wrong value, a key that is not an item or changes that are not a dict return the error and write nothing."""
    found = Preferences(store).save(changes)
    assert found["error"].startswith(SAVE_FAILED)
    assert not local_path(store.path).exists()


def test_a_save_that_cannot_write_returns_the_error(tmp_path: Path) -> None:
    """A local file that cannot be written returns the error with its reason."""
    store = SettingsStore.load(tmp_path / "gone" / "settings.toml")
    found = Preferences(store).save({"plot.max_levels": 5})
    assert found["error"].startswith(SAVE_FAILED)
    assert store.current.plot.max_levels == 100
