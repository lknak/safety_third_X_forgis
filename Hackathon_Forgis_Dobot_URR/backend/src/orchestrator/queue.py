"""FIFO task queue with bounded capacity for orchestrator runs."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Optional

from .schemas import OrchestratorTask


class OrchestratorTaskQueue:
    """In-memory FIFO task queue with max depth enforcement."""

    def __init__(self, max_size: int = 3):
        self._max_size = max_size
        self._queue: deque[OrchestratorTask] = deque()
        self._lock = asyncio.Lock()

    @property
    def max_size(self) -> int:
        return self._max_size

    async def enqueue(self, task: OrchestratorTask) -> tuple[bool, int]:
        """Enqueue task, returning (accepted, queue_position)."""
        async with self._lock:
            if len(self._queue) >= self._max_size:
                return False, len(self._queue)
            self._queue.append(task)
            return True, len(self._queue)

    async def pop_next(self) -> Optional[OrchestratorTask]:
        """Pop next task if available."""
        async with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()

    async def list_pending(self) -> list[OrchestratorTask]:
        """List pending tasks without mutation."""
        async with self._lock:
            return list(self._queue)

    async def depth(self) -> int:
        """Current queue depth."""
        async with self._lock:
            return len(self._queue)
