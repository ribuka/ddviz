"""Routes of the file of the drawing settings: build it to save, hand the one opened to the page, tell the kinds of columns (Issue #287).

The page builds no file itself: it sends its drawing settings and the
columns they refer to, and the server adds the input and the kinds of those
columns (`ddviz.shared.drawfile.build`). A browser downloads the answer; the
window adds the paths from where the user saves it
(``ddviz.desktop.window._Api.save_draw_file``). A file opened on the
window's chooser comes back to the page of the input it loaded through
``/api/initial-draw``.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ddviz.server.models import ColumnKindsRequest, DrawFileRequest
from ddviz.server.source import Source
from ddviz.shared.drawfile import build, column_kind, default_name


async def _kinds(source: Source, names: list[str]) -> dict[str, str | None]:
    """Return the kind of each of `names` in the input (`column_kind`), None for a column it lacks."""
    schema = {c["name"]: c for c in await source.schema()}
    return {name: column_kind(schema[name]) if name in schema else None for name in names}


def _join(source: Source) -> dict | None:
    """Return the join the input took, as the file of the drawing settings keeps it (`build`), or None without one."""
    join = source.joined
    if join is None:
        return None
    return {
        "paths": [str(Path(p).absolute()) for p in join.right.paths],
        "recursive": join.right.recursive,
        "kind": join.kind,
        "keys": join.keys,
    }


def drawfile_router(source: Source, initial_draw: dict | None) -> APIRouter:
    """Return the routes of the file of the drawing settings.

    Parameters
    ----------
    source : Source
        The input loaded.
    initial_draw : dict or None
        The content of the file opened with the input on the window's
        chooser, which the page applies once loaded; None otherwise.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    @router.get("/api/initial-draw")
    async def initial() -> dict | None:
        """Return the file of the drawing settings opened with the input, or null."""
        return initial_draw

    @router.post("/api/column-kinds")
    async def column_kinds(request: ColumnKindsRequest) -> dict:
        """Return the kind of each column asked for (`ddviz.shared.drawfile.column_kind`), null for one the input lacks."""
        return await _kinds(source, request.names)

    @router.post("/api/draw-file")
    async def draw_file(request: DrawFileRequest) -> JSONResponse:
        """Return the file of the drawing settings sent, with the input and the kinds of the columns.

        ``source.relative`` is null, and so is ``source.join.relative``: the
        server does not know where it is saved. ``source.join`` is the join
        the input took, null without one. ``Content-Disposition`` names its
        default file.
        """
        kinds = await _kinds(source, request.columns)
        unknown = [name for name, kind in kinds.items() if kind is None]
        if unknown:
            raise HTTPException(400, f"データに無い列です：{', '.join(unknown)}")
        paths = [str(Path(p).absolute()) for p in source.paths]
        content = build(
            request.settings,
            kinds,
            paths,
            source.recursive,
            None,
            importlib.metadata.version("ddviz"),
            join=_join(source),
        )
        name = default_name(Path(paths[0]), Path(paths[0]).is_dir())
        return JSONResponse(
            content,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

    return router
