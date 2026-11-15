"""The items of the Preferences dialog, and what the dialog reads and saves through the window.

The dialog itself is ``static/js/preferences.js``; it draws the items of
`ITEMS` in their order and checks the inputs by their ``input``. Every
setting (`ddviz.server.settings.setting_keys`) is an item, or is in
`EXCLUDED` with the reason; ``config/settings.toml`` has every setting
(tests/server/test_preference_items.py checks the three agree).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from ddviz.server.settings import IMAGE_COPY_DPIS, values_of
from ddviz.server.settings_store import SettingsStore

#: The groups of the dialog, in their order.
GROUPS = ("グラフ表示", "列リスト", "キャッシュ", "ホバー")

#: The message of a save that failed, before its reason.
SAVE_FAILED = "設定を保存できませんでした："


@dataclass(frozen=True)
class PreferenceItem:
    """An item of the Preferences dialog.

    Parameters
    ----------
    key : str
        Dotted key of the setting.
    group : str
        One of `GROUPS`.
    label : str
        Name shown.
    input : {"percent", "integer", "number", "choice"}
        ``"percent"``: a slider and a number from 0 to 100 % in steps of 1,
        saved divided by 100; ``"integer"``: a positive integer;
        ``"number"``: a finite number, fractions allowed, from `minimum`;
        ``"choice"``: one of `choices`.
    timing : str
        When the value takes effect, always shown.
    unit : str
        Unit shown after the input; empty for none.
    minimum : float
        Least value of a ``"number"``.
    above_minimum : bool
        A ``"number"`` must be above `minimum`, not equal to it.
    note : str
        Explanation shown under the item; empty for none.
    choices : tuple of int
        The values of a ``"choice"``, in the order shown.
    """

    key: str
    group: str
    label: str
    input: Literal["percent", "integer", "number", "choice"]
    timing: str
    unit: str = ""
    minimum: float = 0
    above_minimum: bool = False
    note: str = ""
    choices: tuple[int, ...] = ()


#: The items, in the order of the dialog (`docs/spec.md`, "Preferences").
ITEMS = (
    PreferenceItem(
        "plot.legend.inactive_opacity",
        "グラフ表示",
        "非アクティブ系列の濃さ",
        "percent",
        "適用後すぐに反映",
        unit="%",
        note="0% で非表示、100% で通常と同じ濃さ",
    ),
    PreferenceItem(
        "plot.max_levels",
        "グラフ表示",
        "色・形・グループの水準上限",
        "integer",
        "次のグラフ作成から反映。Colorの区間数の入力上限は適用後すぐ",
        note="Color / Symbol / Group X / Group Y / Wrap に適用",
    ),
    PreferenceItem(
        "plot.max_axis_levels",
        "グラフ表示",
        "X・Yカテゴリ軸の水準上限",
        "integer",
        "次のグラフ作成から反映",
    ),
    PreferenceItem(
        "plot.image_copy.dpi",
        "グラフ表示",
        "グラフ画像のコピーの解像度",
        "choice",
        "次の画像コピーから反映",
        unit="DPI",
        note="96 は画面と同じ大きさ、300 は印刷向け",
        choices=tuple(sorted(IMAGE_COPY_DPIS)),
    ),
    PreferenceItem(
        "columns.max_listed",
        "列リスト",
        "一覧に表示する列数の上限",
        "integer",
        "適用後すぐに一覧を更新",
    ),
    PreferenceItem(
        "columns.max_history",
        "列リスト",
        "検索履歴の件数",
        "integer",
        "次の履歴表示・追加から反映",
    ),
    PreferenceItem(
        "cache.max_gb",
        "キャッシュ",
        "列キャッシュ容量の上限",
        "number",
        "次のキャッシュ整理から反映",
        unit="GB",
    ),
    PreferenceItem(
        "cache.max_unused_days",
        "キャッシュ",
        "未使用キャッシュの保持日数",
        "number",
        "次のキャッシュ整理から反映",
        unit="日",
    ),
    PreferenceItem(
        "hover.max_temp_gb",
        "ホバー",
        "ホバー用一時ファイルの容量上限",
        "number",
        "次の描画計算から反映。作成済みのファイルは保持",
        unit="GB",
        above_minimum=True,
    ),
)

#: Settings the dialog does not edit, with the reason.
EXCLUDED: dict[str, str] = {}


class Preferences:
    """What the Preferences dialog calls through the window (`ddviz.desktop.window._Api`).

    Parameters
    ----------
    store : SettingsStore
        The settings in effect, which the UI servers read too.
    """

    def __init__(self, store: SettingsStore) -> None:
        self.store = store

    def state(self) -> dict:
        """Return the items of the dialog and the values in effect.

        Returns
        -------
        dict
            ``{"groups", "items", "values"}``: `GROUPS`, `ITEMS` as dicts
            and the value of each item by its key.
        """
        return {
            "groups": list(GROUPS),
            "items": [asdict(item) for item in ITEMS],
            "values": self._values(),
        }

    def save(self, changes: dict) -> dict:
        """Save the changed values (`SettingsStore.save`).

        Parameters
        ----------
        changes : dict
            Value by key, of the items changed only.

        Returns
        -------
        dict
            ``{"values"}``, the values now in effect; or ``{"error"}`` with
            the message of a save that failed, which changed nothing.
        """
        if not isinstance(changes, dict):
            return {"error": f"{SAVE_FAILED}{changes!r}"}
        unknown = sorted(set(changes) - {item.key for item in ITEMS})
        if unknown:
            return {"error": f"{SAVE_FAILED}編集できない項目です：{unknown}"}
        try:
            self.store.save(changes)
        except (OSError, ValueError) as error:
            return {"error": f"{SAVE_FAILED}{error}"}
        return {"values": self._values()}

    def _values(self) -> dict:
        """Return the value in effect of each item by its key."""
        values = values_of(self.store.current)
        return {item.key: values[item.key] for item in ITEMS}
