import asyncio
import collections
import contextlib
import functools
import itertools
import re

import discord
from discord.ext import commands
from more_itertools import chunked, consume, iter_except, unique_everseen

from .colors import random_color
from .misc import maybe_awaitable
from .queue import SimpleQueue

_Trigger = collections.namedtuple('_Trigger', 'emoji pattern blocking fallback')


def trigger(emoji, pattern=None, *, blocking=False, fallback=None):
    """Add a function that will be called with a certain reaction.

    If pattern is a string, it will be used as a regex pattern for messages to trigger that functions.

    If fallback is a string, it will be used as a regex pattern like pattern.
    But this will only be used if the bot can't add reactions.

    If blocking is True, reactions will be ignored for the duration of the execution.
    """

    def decorator(func):
        func.__trigger__ = _Trigger(emoji=emoji, pattern=pattern, blocking=blocking, fallback=fallback)
        return func

    return decorator


paginated = functools.partial(commands.bot_has_permissions, embed_links=True)
# Remove the predicate from the check
_validate_context = paginated()(lambda: 0).__commands_checks__[0]


class _TriggerCooldown(commands.CooldownMapping):
    def __init__(self):
        super().__init__(commands.Cooldown(rate=5, per=2, type=commands.BucketType.user))

    def _bucket_key(self, tup):
        return tup

    def is_rate_limited(self, message_id, user_id):
        bucket = self.get_bucket((message_id, user_id))
        return bucket.update_rate_limit() is not None


_trigger_cooldown = _TriggerCooldown()


class _Callback(collections.namedtuple('_Callback', 'func blocking')):
    """Wrapper class to store the resolved descriptor and the blocking attribute."""

    __slots__ = ()

    @property
    def __doc__(self):
        return self.func.__doc__


class InteractiveSession:
    """Base class for all interactive sessions.

    Subclasses must implement the 'default' method. If necessary, they can override 'start'.

    A page should either return a discord.Embed, or None to indicate the page was invalid somehow.
    e.g. the page number given was out of bounds, or there were side effects associated with it.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self._bot = ctx.bot
        self._channel = ctx.channel
        self._users = {ctx.author.id}
        self._message = None
        self._blocking = False

        self._current = None

        self._queue = SimpleQueue()

        self._using_reactions = False

    def __init_subclass__(cls, stop_emoji='\N{BLACK SQUARE FOR STOP}', stop_pattern=None, stop_fallback='exit', **kwargs):
        super().__init_subclass__(**kwargs)
        cls._reaction_map = callbacks = collections.OrderedDict()

        cls._message_callbacks = message_callbacks = []
        cls._message_fallbacks = message_fallbacks = []
        known_patterns = set()

        def trigger_iterator():
            name_members = itertools.chain.from_iterable(b.__dict__.items() for b in cls.__mro__)
            for name, member in unique_everseen(name_members, key=lambda p: p[0]):
                trigger = getattr(member, '__trigger__', None)
                if not trigger:
                    continue

                resolved = getattr(cls, name)
                callback = _Callback(resolved, trigger.blocking)
                yield trigger.emoji, trigger.pattern, trigger.fallback, callback

            if stop_emoji or stop_pattern or stop_fallback:
                yield stop_emoji, stop_pattern, stop_fallback, _Callback(cls.stop, False)

        for emoji, pattern, fallback, callback in trigger_iterator():
            if emoji not in callbacks:
                callbacks[emoji] = callback

            if pattern and pattern not in known_patterns:
                known_patterns.add(pattern)
                message_callbacks.append((pattern, callback))

            if fallback and fallback not in known_patterns:
                known_patterns.add(fallback)
                message_fallbacks.append((fallback, callback))

    def using_reactions(self):
        """Returns True if reactions are being used for the current session, False otherwise.

        This can return False if the session is not running.
        """

        return self._using_reactions

    def check(self, reaction, _):
        """Extra checks for reactions."""

        return reaction.emoji in self._reaction_map

    async def add_reactions(self):
        """Adds the reactions to the message."""

        for emoji in self._reaction_map:
            await self._message.add_reaction(emoji)

    def default(self):
        """Returns the first embed to start the controller."""

        raise NotImplementedError

    async def start(self):
        """First thing that gets called."""

        self._current = embed = await maybe_awaitable(self.default)
        self._message = await self._channel.send(embed=embed)

    async def stop(self):
        """Stops running the controller."""

        await self._queue.put(None)

    async def cleanup(self, *, delete_after):
        """Cleans up anything else after stopping."""

        method = self._message.delete if delete_after else self._message.clear_reactions()
        with contextlib.suppress(Exception):
            await method()

    async def run(self, *, timeout=120, delete_after=True):
        """Runs the interactive loop."""

        _validate_context(self.ctx)

        self._using_reactions = self._channel.permissions_for(self.ctx.me).add_reactions

        await self.start()
        if not self._message:
            raise RuntimeError('start() must be self._message.')

        message = self._message
        triggers = self._message_callbacks.copy()
        task = None
        listeners = []

        def listen(func):
            listeners.append(func)
            return self._bot.listen()(func)

        if self._using_reactions:
            task = self._bot.loop.create_task(self.add_reactions())

            @listen
            async def on_reaction_add(reaction, user):
                if (
                    not self._blocking
                    and reaction.message.id == message.id
                    and user.id in self._users
                    and self.check(reaction, user)
                    and not _trigger_cooldown.is_rate_limited(message.id, user.id)
                ):
                    callback, self._blocking = self._reaction_map[reaction.emoji]
                    cleanup = functools.partial(message.remove_reaction, reaction.emoji, user)
                    await self._queue.put((callback, cleanup))

        else:
            triggers.extend(self._message_fallbacks)

        if triggers:
            @listen
            async def on_message(msg):
                if (
                    self._blocking
                    or msg.channel != self._channel
                    or msg.author.id not in self._users
                ):
                    return

                patterns, callbacks = zip(*triggers)
                selectors = map(re.fullmatch, patterns, itertools.repeat(msg.content))
                callback = next(itertools.compress(callbacks, selectors), None)
                if not callback:
                    return

                if _trigger_cooldown.is_rate_limited(message.id, msg.author.id):
                    return

                callback, self._blocking = callback
                await self._queue.put((callback, msg.delete))

        try:
            while True:
                # Would async_timeout be better here?
                try:
                    job = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break

                if job is None:
                    break

                callback, after = job

                result = await maybe_awaitable(callback, self)

                with contextlib.suppress(discord.HTTPException):
                    await after()

                self._blocking = False

                if result is None:
                    continue

                self._current = result

                try:
                    await message.edit(embed=result)
                except discord.NotFound:
                    break

        finally:
            self._using_reactions = False

            for listener in listeners:
                self._bot.remove_listener(listener)

            if not (task is None or task.done()):
                task.cancel()

            consume(iter_except(self._queue.get_nowait, asyncio.QueueEmpty))
            await self.cleanup(delete_after=delete_after)

    interact = run

    @property
    def reaction_help(self):
        return '\n'.join(itertools.starmap('{0} => {1.__doc__}'.format, self._reaction_map.items()))


class Paginator(InteractiveSession):
    """A paginator takes an iterable of entries and paginates them."""

    def __init__(self, ctx, entries, *, per_page=15, title=discord.Embed.Empty, color=None):
        super().__init__(ctx)

        self._pages = tuple(chunked(entries, per_page))
        self._index = 0

        if not color:
            color = random_color()

        self.title = title
        self.color = color

    @property
    def single_page(self):
        """Returns whether there's just a single page or not."""

        return len(self._pages) == 1

    @property
    def small(self):
        """Returns whether there are five pages or less or not."""

        return len(self._pages) <= 5

    @property
    def total(self):
        """Returns the total number of entries in the list."""

        return sum(map(len, self._pages))

    async def start(self):
        """Starts paginating."""

        await super().start()
        if self.single_page:
            # If there's only one page, paginating is unnecessary
            await self.stop()

    async def cleanup(self, *, delete_after):
        if not self.single_page:
            await super().cleanup(delete_after=delete_after)

    async def add_reactions(self):
        if self.single_page:
            return

        fast_forwards = {'\U000023ed', '\U000023ee'}
        small = self.small

        for emoji in self._reaction_map:
            if not (small and emoji in fast_forwards):
                await self._message.add_reaction(emoji)

    def create_embed(self, page):
        """Creates an embed given a slice of entries."""

        return (discord.Embed(title=self.title, description='\n'.join(page), color=self.color)
                .set_footer(text=f'Page {self._index + 1}/{len(self._pages)} ({self.total} total)'))

    def page_at(self, index):
        """Returns the embed that would be created at a certain page. None if the index is out of bounds."""

        if not 0 <= index < len(self._pages):
            return None

        self._index = index
        return self.create_embed(self._pages[index])

    @trigger('\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}', fallback=r'\<\<')
    def default(self):
        """First page."""

        return self.page_at(0)

    @trigger('\N{BLACK LEFT-POINTING TRIANGLE}', fallback=r'\<')
    def previous(self):
        """Previous page."""

        return self.page_at(self._index - 1)

    @trigger('\N{BLACK RIGHT-POINTING TRIANGLE}', fallback=r'\>')
    def next(self):
        """Next page."""

        return self.page_at(self._index + 1)

    @trigger('\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}', fallback=r'\>\>')
    def last(self):
        """Last page."""

        return self.page_at(len(self._pages) - 1)

    def _goto_embed(self):
        ctx = self.ctx
        description = (
            f'Please enter a number from 1 to {len(self._pages)}.\n\n'
            'To cancel, click \N{INPUT SYMBOL FOR NUMBERS} again.'
        )

        return (discord.Embed(description=description, color=self.color)
                .set_author(name=f'What page do you want to go, {ctx.author.display_name}?'))

    def _goto_parse_input(self, content):
        try:
            index = int(content)
        except ValueError:
            return None

        return self.page_at(index - 1)

    @trigger('\N{INPUT SYMBOL FOR NUMBERS}', blocking=True)
    async def goto(self):
        """Go to a certain page."""

        ctx = self.ctx
        return_result = None
        user_message = None

        def check(m):
            nonlocal return_result, user_message
            if not (m.channel.id == self._channel.id and m.author.id == ctx.author.id):
                return False

            result = self._goto_parse_input(m.content)
            if not result:
                return False

            return_result = result
            user_message = m
            return True

        def remove_check(reaction, user):
            return (reaction.message.id == self._message.id
                    and user.id == ctx.author.id
                    and reaction.emoji == '\N{INPUT SYMBOL FOR NUMBERS}')

        to_wait = [
            self._bot.wait_for('message', check=check),
            self._bot.wait_for('reaction_remove', check=remove_check),
        ]

        try:
            embed = self._goto_embed()
            delete_always = await self._channel.send(embed=embed)

            done, pending = await asyncio.wait(to_wait, loop=self._bot.loop, timeout=60, return_when=asyncio.FIRST_COMPLETED)
            for fut in pending:
                fut.cancel()

            if not done:
                return None

            result = done.pop().result()

            if isinstance(result, discord.Message):
                return return_result

            return None

        finally:
            for m in [delete_always, user_message]:
                with contextlib.suppress(Exception):
                    await m.delete()


class FieldPaginator(Paginator):
    """Similar to Paginator, but uses the fields instead of the description."""

    def __init__(self, ctx, entries, *, inline=True, **kwargs):
        super().__init__(ctx, entries, **kwargs)

        self.inline = inline

        if len(self._pages) > 25:
            raise ValueError('Too many fields per page! The maximum is 25!')

    def create_embed(self, page):
        embed = (discord.Embed(title=self.title, color=self.color)
                 .set_footer(text=f'Page: {self._index + 1} / {len(self._pages)} ({self.total} total)'))

        add_field = functools.partial(embed.add_field, inline=self.inline)
        for name, value in page:
            add_field(name=name, value=value)

        return embed
