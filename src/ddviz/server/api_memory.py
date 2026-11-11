"""Route of the memory shown in the footer (`ddviz.server.memory`)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ddviz.server.memory import MemoryMeter


def memory_router(meter: MemoryMeter) -> APIRouter:
    """Return the route ``GET /api/memory``.

    It answers ``{"backend_bytes": ..., "frontend_bytes": ...}``, each a
    number of bytes or null when it could not be measured, never cached.

    Parameters
    ----------
    meter : MemoryMeter
        Measures the working sets.

    Returns
    -------
    fastapi.APIRouter
        The route.
    """
    router = APIRouter()

    @router.get("/api/memory")
    async def memory() -> JSONResponse:
        """Return the working sets; the Win32 calls run off the event loop."""
        return JSONResponse(
            await run_in_threadpool(meter.measure),
            headers={"Cache-Control": "no-store"},
        )

    return router
