"""Lifecycle adapter for the existing localhost service's durable intake queue."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from starlette.concurrency import run_in_threadpool

from .intake import run_next, flush_pending_refreshes

LOG = logging.getLogger(__name__)


async def _loop(library, stop):
    while not stop.is_set():
        try:
            progressed = await run_in_threadpool(run_next, library)
        except Exception:
            # No provider body, source text, or credentials in server logs.
            LOG.error('The intake worker stopped a stage; its durable progress is retained.')
            progressed = False
        if not progressed:
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass


@contextlib.asynccontextmanager
async def worker_lifespan(library):
    """Only pre-authorized durable jobs run; a page view never creates one."""
    stop = asyncio.Event()
    task = asyncio.create_task(_loop(library, stop))
    try:
        yield
    finally:
        stop.set()
        # Requests already started have their existing bounded deadlines. A
        # process kill leaves a running attempt for explicit recovery, not replay.
        await task
        await run_in_threadpool(flush_pending_refreshes, library)
