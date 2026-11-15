"""The settings in effect, which the Preferences dialog saves and replaces as a whole.

One store lives for the whole run: the chooser and every UI server that `New`
builds again share it (`ddviz.__main__`). A task reads `current` once when it
starts and keeps that snapshot to its end; a save replaces the snapshot for
the tasks that start after it (`docs/spec.md`, "設定").
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path

import tomlkit

from ddviz.server.settings import (
    Settings,
    check_value,
    load_settings,
    local_path,
    settings_from,
    settings_path,
)
from ddviz.server.settings_files import (
    merge_tables,
    read_table,
    read_text,
    replace_file,
    updated_document,
)


class SettingsStore:
    """The settings in effect and the files they come from.

    Parameters
    ----------
    settings : Settings
        The settings in effect at first.
    path : pathlib.Path or None
        The shared settings file, beside which `save` writes the local one
        (`ddviz.server.settings.local_path`); None for settings that are not
        saved (tests), whose `save` fails.
    """

    def __init__(
        self, settings: Settings | None = None, path: Path | None = None
    ) -> None:
        self._settings = settings or Settings()
        self.path = path
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path | None = None) -> SettingsStore:
        """Return the store of the settings read from the files (`ddviz.server.settings.load_settings`).

        Parameters
        ----------
        path : pathlib.Path, optional
            Shared settings file; `settings_path` by default.

        Raises
        ------
        ValueError
            As `load_settings` does.
        """
        path = path or settings_path()
        return cls(load_settings(path), path)

    @property
    def current(self) -> Settings:
        """The settings in effect: a snapshot that a save replaces, never changes."""
        return self._settings

    def save(self, changes: Mapping[str, object]) -> Settings:
        """Write the changed keys into the local file and put the settings they give in effect.

        The local file is read again, so its other keys, unknown keys and
        comments stay, as do changes made to it since it was read. No
        change writes nothing. On failure the file and the settings in
        effect are left as they were.

        Parameters
        ----------
        changes : Mapping
            Value by dotted key (`ddviz.server.settings.setting_keys`).

        Returns
        -------
        Settings
            The settings now in effect.

        Raises
        ------
        ValueError
            When a key or value is not right, a file cannot be read or is
            not TOML, or the files with the changes give wrong settings.
        OSError
            When the local file cannot be written.
        """
        if self.path is None:
            raise ValueError("these settings have no file")
        checked = {key: check_value(key, value) for key, value in changes.items()}
        with self._lock:
            if not checked:
                return self._settings
            local = local_path(self.path)
            document = updated_document(read_text(local), local, checked)
            settings = _read(self.path, document.unwrap())
            replace_file(local, tomlkit.dumps(document))
            self._settings = settings
            return settings


def _read(path: Path, local: dict) -> Settings:
    """Return the settings of the shared file `path` with the table of the local file over it."""
    return settings_from(merge_tables(read_table(path), local))
