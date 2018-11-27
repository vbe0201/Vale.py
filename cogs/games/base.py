import asyncio
import contextlib
import enum
import functools
import inspect
import random
import re

import discord
from discord.ext import commands

from .errors import NotEnoughMoney

from utils.colors import random_color
from utils.context_managers import temporary_item, temporary_message


async def money_required(ctx, amount: int):
    """A check that will be used as an extension to the Currency cog.

    Players need, depending on the game, a given amount of money to be able to join/create one.
    Creating games is more expensive than joining them. And the more big the games are, the higher the price to enjoy them.
    """

    cog = ctx.bot.get_cog('Currency')
    money = await cog.get_money(ctx.author.id)

    if money < amount:
        raise NotEnoughMoney(money, amount)

    await cog.add_money(ctx.author.id, -amount)


class Status(enum.Enum):
    PLAYING = enum.auto()
    END = enum.auto()
    TIMEOUT = enum.auto()
    QUIT = enum.auto()


class _TwoPlayerWaiter:
    def __init__(self, author, recipient):
        self._author = author
        self._recipient = recipient
        self._future = None
        self._closer = None
        self._event = asyncio.Event()

    def wait(self):
        future = self._future
        if not future:
            future = self._future = asyncio.ensure_future(asyncio.wait_for(self._event.wait(), timeout=300))

        return future

    def confirm(self, member):
        if self._author == member:
            raise RuntimeError('You can\'t join a game that you\'ve created. Are you really that lonely?')

        if not self._recipient:
            self._recipient = member

        elif member != self._recipient:
            raise RuntimeError('This game is not for you!')

        self._event.set()

    def decline(self, member):
        if self._recipient != member:
            return False

        self._closer = member
        return self._future.cancel()

    def cancel(self, member):
        if self._author != member:
            return False

        self._closer = member
        return self._future.cancel()

    def done(self):
        return bool(self._future and self._future.done())


class NoSelfArgument(commands.UserInputError):
    """Exception raised in CheckedMember when the author passes themselves as an argument."""


class _MemberConverter(commands.MemberConverter):
    async def convert(self, ctx, argument):
        member = await super().convert(ctx, argument)

        if member.status is discord.Status.offline:
            raise commands.BadArgument(f'{member} is offline.')

        if member.bot:
            raise commands.BadArgument(f'{member} is a bot. You can\'t use a bot here.')

        if member == ctx.author:
            raise NoSelfArgument('Please just don\'t try to use yourself lol.')

        return member

    @staticmethod
    def random_example(ctx):
        members = [
            member for member in ctx.guild.members
            if member.status is not discord.Status.offline
            and not member.bot
            and member != ctx.author
        ]

        member = random.choice(members) if members else 'This dude'
        return f'@{member}'


@contextlib.contextmanager
def _dummy_cm(*args, **kwargs):
    yield


class TwoPlayerGameCog:
    def __init__(self, bot):
        self.bot = bot
        self.running_games = {}
        self._invited_games = {}

    def __init_subclass__(cls, *, game_cls, name=None, cmd=None, aliases=(), **kwargs):
        super().__init_subclass__(**kwargs)

        cls.name = name or cls.__name__
        cls.__game_class__ = game_cls
        cmd_name = cmd or cls.__name__.lower()

        group_help = inspect.getdoc(cls._game).format(name=cls.name)
        # We can't use the decorator because all the check decorator does is
        # add the predicate to an attribute called __commands_checks__, which
        # gets deleted after the first command.
        group = commands.group(
            name=cmd_name, aliases=aliases, help=group_help, invoke_without_command=True
        )
        group_command = group(commands.bot_has_permissions(embed_links=True)(cls._game))
        setattr(cls, f'{cmd_name}', group_command)

        gc = group_command.command
        for name, member in inspect.getmembers(cls):
            if not name.startswith('_game_'):
                continue

            name = name[6:]

            game_help = inspect.getdoc(member).format(name=cls.name, cmd=cmd_name)
            command = gc(name=name, help=game_help)(member)
            setattr(cls, f'{cmd_name}_{name}', command)

        setattr(cls, f'_{cls.__name__}__error', cls._error)

    async def _error(self, ctx, error):
        if isinstance(error, NoSelfArgument):
            message = random.choice((
                'Don\'t play with yourself.',
                'Mention someone.',
                "Self inviting, huh? :eyes:",
            ))

            await ctx.send(message)

    def _create_invite(self, ctx, member):
        command = f'{ctx.prefix}{ctx.command.root_parent or ctx.command}'
        if member:
            action = 'invited you to'
            description = (
                '**Do you accept?**\n'
                f'Yes: Type `` {command} join``\n'
                f'No: Type `` {command} decline``\n'
                'You have 5 minutes.'
            )
        else:
            action = 'created'
            description = (
                f'Type `{command} join` to join in!\n'
                'This will expire in 5 minutes.'
            )

        title = f'{ctx.author} has {action} a game of {self.__class__.name}!'
        return (discord.Embed(colour=0x00FF00, description=description)
                .set_author(name=title)
                .set_thumbnail(url=ctx.author.avatar_url)
                )

    async def _invite_member(self, ctx, member):
        invite_embed = self._create_invite(ctx, member)

        if member is None:
            await ctx.send(embed=invite_embed)
        else:
            await ctx.send(f'{member.mention}, you have a challenger!', embed=invite_embed)

    async def _game(self, ctx, *, member: _MemberConverter = None):
        """Starts a game of {name}.

        You can specify a user to invite them to play with
        you. Leaving out the user creates a game that anyone
        can join.
        """

        if ctx.channel.id in self.running_games:
            return await ctx.send(f"There's a {self.__class__.name} game already running in this channel...")

        if member is not None:
            pair = (ctx.author.id, member.id)
            channel_id = self._invited_games.get(pair)
            if channel_id:
                return await ctx.send(
                    'You\'ve already invited them in <#{channel_id}>, please don\'t spam them.'
                )

            cm = temporary_item(self._invited_games, pair, ctx.channel.id)
        else:
            cm = _dummy_cm()

        put_in_running = functools.partial(temporary_item, self.running_games, ctx.channel.id)

        await ctx.release()
        with cm:
            await self._invite_member(ctx, member)
            with put_in_running(_TwoPlayerWaiter(ctx.author, member)):
                waiter = self.running_games[ctx.channel.id]
                try:
                    await waiter.wait()
                except asyncio.TimeoutError:
                    if member:
                        return await ctx.send(f'{member.mention} couldn\'t join in time.')
                    return await ctx.send('No one joined in time.')
                except asyncio.CancelledError:
                    if waiter._closer == ctx.author:
                        msg = f'{ctx.author.mention} has closed the game. False alarm..'
                    else:
                        msg = f'{ctx.author.mention}, {member} declined your challenge.'
                    return await ctx.send(msg)

            with put_in_running(self.__game_class__(ctx, waiter._recipient)):
                inst = self.running_games[ctx.channel.id]
                await inst.run()

    async def _game_join(self, ctx):
        """Joins a {name} game.

        This either must be for you, or for everyone.
        """

        waiter = self.running_games.get(ctx.channel.id)
        if waiter is None:
            return await ctx.send(f'There\'s no {self.__class__.name} for you to join.')

        if not isinstance(waiter, _TwoPlayerWaiter):
            return await ctx.send('Sorry, you were late.')

        try:
            waiter.confirm(ctx.author)
        except RuntimeError as e:
            await ctx.send(e)
        else:
            await ctx.send(f'Alright {ctx.author.mention}, good luck!')

    async def _game_decline(self, ctx):
        """Declines a {name} game.

        This game must be for you. (i.e. through `{cmd} @user`)
        """

        waiter = self.running_games.get(ctx.channel.id)
        if waiter is None:
            return await ctx.send(f'There\'s no {self.__class__.name} for you to decline.')

        if isinstance(waiter, _TwoPlayerWaiter) and waiter.decline(ctx.author):
            with contextlib.suppress(discord.HTTPException):
                await ctx.message.add_reaction('\U00002705')

    async def _game_close(self, ctx):
        """Closes a {name} game, stopping anyone from joining.

        You must be the creator of the game.
        """
        waiter = self.running_games.get(ctx.channel.id)
        if waiter is None:
            return await ctx.send(f'There\'s no {self.__class__.name} for you to close.')

        if isinstance(waiter, _TwoPlayerWaiter) and waiter.cancel(ctx.author):
            with contextlib.suppress(discord.HTTPException):
                await ctx.message.add_reaction('\U00002705')


class TwoPlayerSession:
    def __init__(self, ctx, opponent):
        self._ctx = ctx
        self._status = Status.PLAYING
        self._display = discord.Embed(color=random_color())
        self._players = self._make_players(ctx, opponent)
        self._board = self._board_factory()

    def __init_subclass__(cls, *, board_factory, move_pattern=None, timeout=120):
        cls._timeout = timeout
        cls._move_pattern = move_pattern
        cls._board_factory = board_factory

    async def _update_display(self):
        raise NotImplementedError

    def current(self):
        """Returns the current player."""

        raise NotImplementedError

    def _push_move(self, move):
        raise NotImplementedError

    def _is_game_over(self):
        raise NotImplementedError

    def _translate_move(self, content):
        return re.match(self._move_pattern, content.lower())

    @staticmethod
    def _make_players(ctx, opponent):
        return random.sample((ctx.author, opponent), 2)

    def _check(self, message):
        if not (message.channel == self._ctx.channel and message.author == self.current()):
            return False

        if message.content.lower() in {'stop', 'quit', 'exit'}:
            self._status = Status.QUIT
            return True

        translated = self._translate_move(message.content)
        if not translated:
            return False

        try:
            self._push_move(translated)
        except NotImplementedError:
            # For the case I forgot to implement _push_move (and this will surely happen to me),
            # don't suppress this silently.
            raise
        except Exception:  # muh pycodestyle
            return False
        else:
            return True

    async def _make_move(self):
        wait_for = self._ctx.bot.wait_for
        try:
            await wait_for('message', timeout=self._timeout, check=self._check)
        except asyncio.TimeoutError:
            self._status = Status.TIMEOUT

    def _send_message(self):
        return temporary_message(self._ctx, embed=self._display)

    async def _loop(self):
        while not self._is_game_over():
            await self._update_display()

            async with self._send_message():
                await self._make_move()

            if self._status in [Status.QUIT, Status.TIMEOUT]:
                return

        self._status = Status.END

    async def _end(self):
        await self._update_display()
        await self._ctx.send(embed=self._display)

    async def run(self):
        await self._loop()
        await self._end()
