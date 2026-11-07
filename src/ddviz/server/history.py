r"""The search history of the column list, kept per input across runs.

A keyword goes in when a column it found is placed on a role or the filter
pane (`docs/spec.md`, "列リスト"). Each input has its own file in
``%LOCALAPPDATA%\ddviz\history``, named from its paths, so that windows on
different inputs never write the same file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)


def default_history_root() -> Path:
    r"""Return the per-user directory of the search histories, ``%LOCALAPPDATA%\ddviz\history``.

    Returns
    -------
    pathlib.Path
        The directory, which may not exist.
    """
    base = os.environ.get("LOCALAPPDATA")
    local = Path(base) if base else Path.home() / ".cache"
    return local / "ddviz" / "history"


def history_file(root: Path, paths: list[str]) -> Path:
    """Return the history file of the input of `paths` under `root`.

    Parameters
    ----------
    root : pathlib.Path
        Directory of the histories.
    paths : list of str
        Absolute paths of the input; their order counts, as it does for the
        rows of several files.

    Returns
    -------
    pathlib.Path
        The file, which may not exist.
    """
    key = "\n".join(os.path.normcase(p) for p in paths)
    return root / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"


def normalize(word: str) -> str:
    """Return `word` with its blanks trimmed and runs of them made one space; the search reads both the same."""
    return " ".join(word.split())


class SearchHistory:
    """The keywords searched in the column list of one input, newest first.

    Parameters
    ----------
    path : pathlib.Path
        File of the history (`history_file`). It is read on each call, so
        that two windows on the same input see each other's keywords.
    paths : list of str
        Paths of the input, written into the file to tell what it is for.
    limit : int
        Most keywords kept (``columns.max_history`` of the settings).
    """

    def __init__(self, path: Path, paths: list[str], limit: int) -> None:
        self.path = path
        self.paths = paths
        self.limit = limit

    def words(self) -> list[str]:
        """Return the keywords, newest first.

        Returns
        -------
        list of str
            Up to `limit` keywords; none when the file is missing or broken.
        """
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            _log.warning("search history unreadable: %s: %s", self.path, error)
            return []
        words = data.get("words") if isinstance(data, dict) else None
        if not isinstance(words, list):
            return []
        return [w for w in words if isinstance(w, str)][: self.limit]

    def add(self, word: str) -> list[str]:
        """Put `word` first; the same keyword, in any case, moves rather than repeats.

        Parameters
        ----------
        word : str
            Keyword of the search box; a blank one is not kept.

        Returns
        -------
        list of str
            The keywords after the change.
        """
        word = normalize(word)
        words = self.words()
        if not word:
            return words
        key = word.casefold()
        return self._write([word, *(w for w in words if w.casefold() != key)])

    def remove(self, word: str) -> list[str]:
        """Remove `word`.

        Returns
        -------
        list of str
            The keywords after the change.
        """
        return self._write([w for w in self.words() if w != word])

    def clear(self) -> list[str]:
        """Remove every keyword.

        Returns
        -------
        list of str
            No keywords.
        """
        self.path.unlink(missing_ok=True)
        return []

    def _write(self, words: list[str]) -> list[str]:
        """Write `words`, cut to `limit`, through a temporary file; return them."""
        words = words[: self.limit]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"paths": self.paths, "words": words}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return words
