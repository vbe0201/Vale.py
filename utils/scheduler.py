import asyncio
import collections
import datetime
import json
import logging
import time

from .misc import maybe_awaitable
from . import db

logger = logging.getLogger(__name__)

MAX_SLEEP_TIME = 60 * 60 * 24
SHORT_TASK_DURATION = 60


class Scheduler(db.Table):
    id = db.Column(db.Serial, primary_key=True)
    expires = db.Column(db.Timestamp)

    event = db.Column(db.Text)
    created = db.Column(db.Timestamp, default="now() at time zone 'utc'")
    args_kwargs = db.Column(db.JSON, default="'{}'::jsonb")

    schedule_expires_index = db.Index(expires)


class _Entry(collections.namedtuple('_Entry', 'time event args kwargs created id')):
    __slots__ = ()

    def __new__(cls, time, event, args=None, kwargs=None, created=None, id=None):
        created = created or datetime.datetime.utcnow()
        args = args or ()
        kwargs = kwargs or {}

        return super().__new__(cls, time, event, args, kwargs, created, id)

    @classmethod
    def from_record(cls, record):
        """Returns an instance of this class from a database record. This is just for internal purposes."""

        # I swear I'm gonna kill someone for this line
        args_kwargs = json.loads(record['args_kwargs'])

        return cls(
            time=record['expires'],
            event=record['event'],
            args=args_kwargs['args'],
            kwargs=args_kwargs['kwargs'],
            created=record['created'],
            id=record['id'],
        )

    @property
    def utc(self):
        time = self.time
        if isinstance(time, datetime.datetime):
            return time

        return datetime.datetime.utcfromtimestamp(time)

    @property
    def seconds(self):
        delta = self.time - self.created
        if isinstance(delta, datetime.timedelta):
            delta = delta.total_seconds()

        return delta

    @property
    def short(self):
        """Returns True if the event is considered as "short".

        Short events are events that will be dispatched in under 1 minute. This gives an optimization opportunity as it doesn't
        have to be stored in the queue or database.
        """

        return self.seconds <= SHORT_TASK_DURATION


class BaseScheduler:
    """Manages timing-related things.

    This was made because of the issues with asyncio.sleep. Naively sleeping for timing will not work
    as it can only go up to 48 days reliably.

    Depending on the selector, the minimum it can go up to is 2 ** 22 -1, what makes ~48 days.
    """

    def __init__(self, *, loop=None, timefunc=time.monotonic):
        self.time_function = timefunc
        self._loop = loop or asyncio.get_event_loop()
        self._lock = asyncio.Lock()
        self._current = None
        self._runner = None
        self._callbacks = []

    def __del__(self):
        self.close()

    @staticmethod
    def _calculate_delta(time1, time2):
        return time1 - time2

    # The next 4 methods must be implemented in subclasses!

    async def _get(self):
        raise NotImplementedError

    async def _put(self, entry):
        raise NotImplementedError

    async def _remove(self, entry):
        raise NotImplementedError

    async def _cleanup(self):
        pass

    async def _update(self):
        while True:
            self._current = timer = await self._get()
            now = self.time_function()
            delta = self._calculate_delta(timer.time, now)

            logger.debug('Sleeping for %s seconds', delta)

            while delta > 0:
                await asyncio.sleep(min(MAX_SLEEP_TIME, delta))
                delta -= MAX_SLEEP_TIME

            logger.debug('Entry %r done, dispatching now.', timer)
            await self._dispatch(self._current)

    def _restart(self):
        self._runner.cancel()
        self._runner = self._loop.create_task(self._update())

    async def _short_task_optimization(self, event):
        # Maybe use self._loop.call_later?
        await asyncio.sleep(event.seconds)
        await self._dispatch(event)

    async def add_abs(self, when, action, args=(), kwargs=None, id=None):
        """Enter a new event in the queue at an absolute time.

        Returns an ID for the event which can be used to remove it, if necessary.
        """

        kwargs = kwargs or {}
        event = _Entry(when, action, args, kwargs, None, id)    # Remove id param
        if event.short:
            self._loop.create_task(self._short_task_optimization(event))
            return

        await self._put(event)

        if self._current and event.time <= self._current.time:
            self._restart()

    async def add(self, delay, action, args=(), kwargs=None, id=None):
        """A variant that specifies the time as a relative time.

        This is actually the more commonly used interface.
        """

        when = self.time_function() + delay
        return await self.add_abs(when, action, args, kwargs, id)

    async def remove(self, entry):
        """Removes an entry from the queue."""

        await self._remove(entry)
        self._restart()

    async def _dispatch(self, timer):
        for callback in self._callbacks:
            try:
                await maybe_awaitable(callback, timer)
            except Exception as e:
                logger.error('Callback %r raised %r', callback, e)
                raise

        logger.debug('All callbacks for %r have been called successfully.', timer)

    def add_callback(self, callback):
        self._callbacks.append(callback)

    def remove_callback(self, callback):
        callbacks = [cb for cb in self._callbacks if cb != callback]
        callbacks_removed = len(self._callbacks) - len(callbacks)
        self._callbacks[:] = callbacks

        return callbacks_removed

    def run(self):
        """Runs the scheduler.

        If the scheduler is already running, this does nothing.
        """

        if self.is_running():
            return

        self._runner = self._loop.create_task(self._update())

    def is_running(self):
        """Indicates whether the scheduler is currently running or not."""

        runner = self._runner
        return runner and not runner.done()

    def stop(self):
        """Stops the scheduler.

        This doesn't clear all the entries, use close() for that.
        """

        if not self.is_running():
            return

        runner = self._runner
        if not runner.done():
            runner.cancel()

    def close(self):
        """Closes the running task, and does any cleanup if necessary."""

        self.stop()
        self._loop.create_task(self._cleanup())
        del self._callbacks[:]
        self._current = None


class DatabaseScheduler(BaseScheduler):
    """An implementation of a Scheduler where a database is used.

    Only DBMSs that support JSON types are supported (basically just PostgreSQL but nvm).
    """

    def __init__(self, pool, *, safe_mode=True, **kwargs):
        super().__init__(**kwargs)
        self._pool = pool
        self._safe = safe_mode
        self._have_data = asyncio.Event()

    async def _dispatch(self, timer):
        await super()._dispatch(timer)

        if not getattr(timer, 'short', True):
            await self._remove(timer)

    @staticmethod
    def _calculate_delta(time1, time2):
        return (time1 - time2).total_seconds()

    async def _get_entry(self):
        query = 'SELECT * FROM scheduler ORDER BY expires LIMIT 1;'
        return await self._pool.fetchrow(query)

    async def _get(self):
        while True:
            entry = await self._get_entry()
            if entry:
                self._have_data.set()
                return _Entry.from_record(entry)

            self._have_data.clear()
            self._current = None
            await self._have_data.wait()

    async def _put(self, entry):
        query = """
            INSERT INTO scheduler (created, event, expires, args_kwargs)
            VALUES      ($1, $2, $3, $4::JSONB);
        """
        await self._pool.execute(
            query,
            entry.created,
            entry.event,
            entry.time,
            {'args': entry.args, 'kwargs': entry.kwargs},
        )
        self._have_data.set()

    async def _remove(self, entry):
        try:
            query = 'DELETE FROM scheduler WHERE id = $1;'
            await self._pool.execute(query, entry.id)
        except Exception as e:
            if self._safe:
                self.stop()

            logger.error('Removing %r failed due to %r', entry, e)
            raise
