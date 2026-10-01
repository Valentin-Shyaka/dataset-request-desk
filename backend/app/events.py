"""In-process pub/sub for Server-Sent Events.

Limitation (documented in NOTES): subscribers live in this process's memory, so this works
with a single API process. With several workers or replicas, publish through Postgres
LISTEN/NOTIFY or Redis pub/sub instead.
"""
import asyncio
import json
import threading


def format_sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"


class Broker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        """Safe to call from any thread. asyncio queues are not thread-safe, so we hand
        each put to the event loop with call_soon_threadsafe."""
        if self._loop is None:
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            self._loop.call_soon_threadsafe(self._offer, queue, event)

    @staticmethod
    def _offer(queue: asyncio.Queue, event: dict) -> None:
        if not queue.full():  # a stuck client must not grow memory forever; it refetches anyway
            queue.put_nowait(event)


broker = Broker()
