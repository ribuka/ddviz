"""Reading, merging and writing the TOML files of the settings (`ddviz.server.settings`)."""

from __future__ import annotations

import os
import tempfile
import tomllib
from collections.abc import Mapping, MutableMapping
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.toml_document import TOMLDocument


def read_text(path: Path) -> str | None:
    """Return the text of a settings file, or None when it does not exist.

    Raises
    ------
    ValueError
        When the file exists but cannot be read; the message names it.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{path}: cannot be read: {error}") from error


def read_table(path: Path) -> dict:
    """Return the table of a settings file; an empty one when it does not exist.

    Raises
    ------
    ValueError
        When the file cannot be read or is not TOML; the message names it.
    """
    text = read_text(path)
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from error


def merge_tables(base: Mapping, over: Mapping) -> dict:
    """Return `base` with the keys of `over` laid over it, table by table.

    A table in both is merged key by key; any other key of `over` replaces
    that of `base`.

    Parameters
    ----------
    base, over : Mapping
        Tables as `tomllib` reads them.

    Returns
    -------
    dict
        The merged table; the arguments are not changed.
    """
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = merge_tables(merged[key], value)
        else:
            merged[key] = value
    return merged


def updated_document(
    text: str | None, path: Path, changes: Mapping[str, object]
) -> TOMLDocument:
    """Return the document of `text` with the dotted keys of `changes` set, keeping its other keys and comments.

    Parameters
    ----------
    text : str or None
        The file's text; None for a file that does not exist yet.
    path : pathlib.Path
        The file, for the errors.
    changes : Mapping
        Value by dotted key, e.g. ``{"plot.legend.inactive_opacity": 0.2}``.

    Returns
    -------
    tomlkit.toml_document.TOMLDocument
        The document.

    Raises
    ------
    ValueError
        When `text` is not TOML, or a table of a key is another kind of value.
    """
    try:
        document = tomlkit.parse(text) if text is not None else tomlkit.document()
    except TOMLKitError as error:
        raise ValueError(f"{path}: {error}") from error
    for key, value in changes.items():
        *tables, name = key.split(".")
        table = document
        for part in tables:
            if part not in table:
                table[part] = tomlkit.table()
            table = table[part]
            if not isinstance(table, MutableMapping):
                raise ValueError(f"{path}: {part} of {key} is not a table")  # noqa: TRY004 - a wrong file, as the others
        table[name] = value
    return document


def replace_file(path: Path, text: str) -> None:
    """Write `text` to `path` through a temporary file of the same folder, which replaces it.

    On failure `path` is left as it was and the temporary file is removed.

    Raises
    ------
    OSError
        When the temporary file cannot be written or cannot replace `path`.
    """
    handle, name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        try:
            file = os.fdopen(handle, "w", encoding="utf-8", newline="")
        except BaseException:
            os.close(handle)
            raise
        with file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
