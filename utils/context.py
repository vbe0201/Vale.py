from discord.ext import commands


class _ContextAcquire:
    """Create an our own version of acquire for using it with
    the command context"""

    # __slots__ is used to explicitly state the instance attributes the object instance must have.
    __slots__ = ('ctx', 'timeout')

    def __init__(self, ctx, timeout):
        self.ctx = ctx
        self.timeout = timeout

    def __await__(self):
        return self.ctx._acquire(self.timeout).__await__()

    async def __aenter__(self):
        await self.ctx._acquire(self.timeout)
        return self.ctx.db

    async def __aexit__(self, *args):
        await self.ctx.release()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pool = self.bot.pool
        self.db = None

    @property
    def session(self):
        return self.bot.session

    async def _acquire(self, timeout):
        if self.db is None:
            self.db = await self.pool.acquire(timeout=timeout)
        return self.db

    def acquire(self, *, timeout=None):
        """
        This function is used to acquire a database connection from the pool through
        the command context.
        Example:
            async with ctx.acquire():
                await ctx.db.execute("Query here")

        :return:
            Instance of the class _ContextAcquire
        """

        return _ContextAcquire(self, timeout)

    async def release(self):
        """
        Releases the database connection from the pool
        """

        if self.db is not None:
            await self.bot.pool.release(self.db)
            self.db = None
