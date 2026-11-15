"""Route of the progress events: the messages of the tasks (`TaskBroker.listen`), of the plots and of the exports of the plot's data, as server-sent events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ddviz.server.broker import TaskBroker


def events_router(broker: TaskBroker) -> APIRouter:
    """Return the route that streams the progress of the tasks (`TaskBroker.listen`) as server-sent events.

    Parameters
    ----------
    broker : TaskBroker
        Runs the tasks whose progress the route streams.

    Returns
    -------
    fastapi.APIRouter
        The route ``GET /api/events``.
    """
    router = APIRouter()

    @router.get("/api/events")
    async def events() -> StreamingResponse:
        """Stream the progress messages of the plot pool's tasks."""
        queue = broker.listen()

        async def stream() -> AsyncIterator[str]:
            try:
                while True:
                    message = await queue.get()
                    yield f"data: {json.dumps(message)}\n\n"
            finally:
                broker.unlisten(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
