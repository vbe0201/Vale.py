import asyncio
import collections
import itertools
import random


class SimpleQueue:
    """A simple, unbounded FIFO queue.

    Strongly inspired by queue.SimpleQueue and asyncio.Queue
    """

    def __init__(self, *, maxsize=0):
        self._queue = collections.deque(maxlen=maxsize) if maxsize > 0 else collections.deque()
        self._count = asyncio.Semaphore(0)

    def empty(self):
        """Return True if the queue is empty, False otherwise."""

        return not self._queue

    def qsize(self):
        """Number of elements in the queue."""

        return len(self._queue)

    def clear(self):
        """Clears the queue."""

        self._queue.clear()

    def shuffle(self):
        """Shuffles the queue."""

        random.shuffle(self._queue)

    async def put(self, item):
        """Puts an item into the queue.

        This is only a coroutine for compatibility with asyncio.Queue.
        """

        self.put_nowait(item)

    def put_nowait(self, item):
        """Puts an item into the queue without blocking."""

        self._queue.append(item)
        self._count.release()

    async def get(self):
        """Removes and returns an item from the queue.

        If queue is empty, wait until an item is available.
        """

        await self._count.acquire()
        return self.get_nowait()

    def get_nowait(self):
        """Removes and returns an item from the queue.

        Returns an item if one is immediately available, else raise QueueEmpty.
        """

        if self.empty():
            raise asyncio.QueueEmpty

        return self._queue.popleft()

    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return len(self._queue)
