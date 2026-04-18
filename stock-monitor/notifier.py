import asyncio
from typing import Any


class Notifier:
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    async def publish(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            await q.put(payload)

    def subscriber_count(self) -> int:
        return len(self._subscribers)
