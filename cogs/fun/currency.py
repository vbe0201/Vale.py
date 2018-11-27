import collections
import enum
import io
import math
import random

import discord
from discord.ext import commands
from PIL import Image

from utils import db
from utils.colors import random_color
from utils.examples import get_example, wrap_example
from utils.formats import pluralize
from utils.misc import run_in_executor
from utils.time import duration_units


class Money(db.Table, table_name='currency'):
    user_id = db.Column(db.BigInt, primary_key=True)
    amount = db.Column(db.Integer)


class Givelog(db.Table):
    id = db.Column(db.Serial, primary_key=True)
    giver = db.Column(db.BigInt)
    recipient = db.Column(db.BigInt)
    amount = db.Column(db.Integer)
    time = db.Column(db.Timestamp, default="now() at time zone 'utc'")


class DailyCashCooldowns(db.Table, table_name='daily_cash_cooldowns'):
    user_id = db.Column(db.BigInt, primary_key=True)
    latest_time = db.Column(db.Timestamp)


class DailyLog(db.Table):
    id = db.Column(db.Serial, primary_key=True)
    user_id = db.Column(db.BigInt)
    time = db.Column(db.Timestamp)
    amount = db.Column(db.Integer)


# Cooldown for `daily`
DAILY_CASH_COOLDOWN_TIME = 60 * 60 * 24
# minimum account age in days before one can use `daily` or `give`
MINIMUM_ACCOUNT_AGE = 7
MINIMUM_ACCOUNT_AGE_IN_SECONDS = MINIMUM_ACCOUNT_AGE * 24 * 60 * 60


class AccountTooYoung(commands.CheckFailure):
    """Will be raised when an account is less than 7 days old."""


def maybe_not_alt():
    def predicate(ctx):
        delta = ctx.message.created_at - ctx.author.created_at
        if delta.days > MINIMUM_ACCOUNT_AGE:
            return True

        retry_after = duration_units(MINIMUM_ACCOUNT_AGE_IN_SECONDS - delta.total_seconds())
        raise AccountTooYoung(
            f'Sorry, but your account is too young. Please wait for {retry_after} before you can use '
            f'`{ctx.clean_prefix}{ctx.command}`.'
        )

    return commands.check(predicate)


class Side(enum.Enum):
    heads = h = 'heads'
    tails = t = 'tails'

    # Probably implement these one day too?
    # edge = e = 'edge'
    # none = n = 'none'

    def __str__(self):
        return self.value

    @classmethod
    async def convert(cls, _, argument):
        try:
            return cls[argument.lower()]
        except KeyError:
            raise commands.BadArgument(f'{argument} is not a valid side.')

    @classmethod
    def random_example(cls, _):
        return random.choice(list(cls._member_map_))


SIDES = list(Side)[:2]
WEIGHTS = [0.4999, 0.4999, 0.0002][:2]


class _DummyUser(collections.namedtuple('_DummyUser', 'id')):
    @property
    def mention(self):
        return f'<Unknown User | ID: {self.id}>'


class NotNegative(commands.BadArgument):
    pass


class SideOrAmount(commands.Converter):
    __types = (Side, int)

    async def convert(self, ctx, argument):
        try:
            return await Side.convert(ctx, argument)
        except commands.BadArgument:
            pass

        try:
            return int(argument)
        except ValueError:
            raise commands.BadArgument(f'`{argument}` is not an amount or side.')

        return await self.__converter.convert(ctx, argument)

    @classmethod
    def random_example(cls, ctx):
        ctx.__sideoramount_flag__ = type_index = not getattr(ctx, '__sideoramount_flag__', False)
        return get_example(cls.__types[type_index], ctx)


def positive_int(argument):
    value = int(argument)
    if value > 0:
        return value

    raise NotNegative('Expected a positive value.')


class PositiveIntOnlyOnSide(commands.Converter):
    async def convert(self, ctx, argument):
        last_arg = ctx.args[-1]
        if isinstance(last_arg, int):
            raise commands.BadArgument(f'Hm, I thought you wanted to flip it {last_arg} times?')

        return positive_int(argument)


@wrap_example(positive_int)
@wrap_example(PositiveIntOnlyOnSide)
def _positive_int_example(ctx):
    if random.random() > 0.5:
        return random.choice([1, 5, 10])

    num = random.randint(2, 5)
    return random.choice(['9' * num, '1' + '0' * num])


class NonBlacklistedMember(commands.MemberConverter):
    async def convert(self, ctx, argument):
        member = await super().convert(ctx, argument)
        blacklist = ctx.bot.get_cog('Blacklists')

        if blacklist:
            if await blacklist.get_blacklist(member, connection=ctx.db):
                raise commands.BadArgument('This user is blacklisted.')

        return member

    @staticmethod
    def random_example(ctx):
        return get_example(discord.Member, ctx)


class Currency:
    def __init__(self, bot):
        self.bot = bot

        with open('data/images/coins/heads.png', 'rb') as heads, \
                open('data/images/coins/tails.png', 'rb') as tails:

            self._heads_image = Image.open(heads).convert('RGBA')
            self._tails_image = Image.open(tails).convert('RGBA')

        if len({*self._heads_image.size, *self._tails_image.size}) != 1:
            raise RuntimeError('Images must be the same size.')

    def __unload(self):
        self._heads_image.close()
        self._tails_image.close()

    async def __error(self, ctx, error):
        if isinstance(error, NotNegative):
            await ctx.send('Fuck off. You\'re not going to mess up my economy!')
        elif isinstance(error, AccountTooYoung):
            await ctx.send(error)

    @property
    def image_size(self):
        return self._heads_image.size[0]

    async def get_money(self, user_id, *, connection=None):
        connection = connection or self.bot.pool

        query = 'SELECT amount FROM currency WHERE user_id = $1;'
        row = await connection.fetchrow(query, user_id)
        return row['amount'] if row else 0

    async def add_money(self, user_id, amount, *, connection=None):
        connection = connection or self.bot.pool

        query = """
            INSERT INTO   currency
            VALUES        ($1, $2)
            ON CONFLICT   (user_id)
            DO UPDATE SET amount = currency.amount + $2;
        """
        await connection.execute(query, user_id, amount)

    @commands.command(name='cash', aliases=['money', 'coins'])
    async def _cash(self, ctx, user: discord.Member = None):
        """Shows how much money you have."""

        user = user or ctx.author
        amount = await self.get_money(user.id, connection=ctx.db)
        if not amount:
            return await ctx.send(f'{user} has nothing.')

        await ctx.send(f'{user} has **{amount}** \N{MONEY WITH WINGS}.')

    @commands.command(name='leaderboard')
    async def _leaderboard(self, ctx):
        """Shows the 10 richest people."""

        query = """
            SELECT     user_id, amount FROM currency
            WHERE      amount > 0
            ORDER BY   amount
            DESC LIMIT 10;
        """

        get_user = self.bot.get_user
        fields = (
            f'{(get_user(user_id) or _DummyUser(user_id)).mention} with **{amount}**'
            for user_id, amount in await ctx.db.fetch(query)
        )

        # Probably paginate this?
        embed = discord.Embed(title='Top 10 richest people', description='\n'.join(fields), color=random_color())
        await ctx.send(embed=embed)

    @commands.command(name='give')
    @maybe_not_alt()
    async def _give(self, ctx, amount: positive_int, user: NonBlacklistedMember):
        """Gives some of your money to another user.

        You must have at least the amount you are trying to give.
        """

        if ctx.author == user:
            return await ctx.send('Wait...Did you really try to give money to yourself?!')

        money = await self.get_money(ctx.author.id, connection=ctx.db)
        if money < amount:
            return await ctx.send('You don\'t have enough to give it away.')

        query = 'UPDATE currency SET amount = amount - $2 WHERE user_id = $1;'
        await ctx.db.execute(query, ctx.author.id, amount)

        await self.add_money(user.id, amount, connection=ctx.db)

        query = 'INSERT INTO givelog (giver, recipient, amount) VALUES ($1, $2, $3);'
        await ctx.db.execute(query, ctx.author.id, user.id, amount)
        await ctx.message.add_reaction('\N{OK HAND SIGN}')

    @commands.command(name='award')
    @commands.is_owner()
    async def _award(self, ctx, amount: int, *, user: discord.User):
        """Awards some money to a user."""

        await self.add_money(user.id, amount, connection=ctx.db)
        await ctx.message.add_reaction('\N{OK HAND SIGN}')

    @commands.command(name='take')
    @commands.is_owner()
    async def _take(self, ctx, amount: int, *, user: discord.User):
        """Takes some money away from an user."""

        money = await self.get_money(user.id, connection=ctx.db)
        if not money:
            return await ctx.send(f'{user.mention} has no money left...yeah..')

        amount = min(money, amount)
        await self.add_money(user.id, -amount, connection=ctx.db)
        await ctx.message.add_reaction('\N{OK HAND SIGN}')

    @staticmethod
    async def _default_flip(ctx):
        """Flip called with no arguments."""

        side = random.choices(SIDES, WEIGHTS)[0]
        file = discord.File(f'data/images/coins/{side}.png', 'coin.png')

        embed = (discord.Embed(title=f'...Flipped {side}!', color=random_color())
                 .set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar_url)
                 .set_image(url='attachment://coin.png'))

        await ctx.send(file=file, embed=embed)

    @run_in_executor
    def _flip_image(self, num_sides):
        images = {
            Side.heads: self._heads_image,
            Side.tails: self._tails_image,
        }
        stats = collections.Counter()

        root = num_sides ** 0.5
        height, width = round(root), int(math.ceil(root))

        sides = (random.choices(SIDES, WEIGHTS)[0] for _ in range(num_sides))

        size = self.image_size
        image = Image.new('RGBA', (width * size, height * size))

        for index, side in enumerate(sides):
            y, x = divmod(index, width)
            image.paste(images[side], (x * size, y * size))
            stats[side] += 1

        message = ' and '.join(pluralize(**{str(side)[:-1]: n}) for side, n in stats.items())

        f = io.BytesIO()
        image.save(f, 'png')
        f.seek(0)

        return message, discord.File(f, 'flipcoins.png')

    async def _numbered_flip(self, ctx, number):
        if number == 1:
            await self._default_flip(ctx)
        elif number > 100:
            await ctx.send('I am not going to flip that many coins for you.')
        elif number <= 0:
            await ctx.send('Wtf, how is that supposed to work?')
        else:
            message, file = await self._flip_image(number)

            embed = (discord.Embed(title=f'...Flipped {message}', color=random_color())
                     .set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar_url)
                     .set_image(url='attachment://flipcoins.png'))

            await ctx.send(file=file, embed=embed)

    @commands.command(name='flip')
    @commands.bot_has_permissions(embed_links=True, attach_files=True)
    async def _flip(self, ctx, side_or_number: SideOrAmount = None, amount: PositiveIntOnlyOnSide = None):
        """Flips a coin.

        The first argument can either be the side (heads or tails) or the number of coins you want to flip.
        If you don't type anything, it will flip one coin.

        If you specify a side for the first argument, you can
        also type the amount of money you wish to bet on for this flip.
        Getting it right gives you 2.0x the money you've bet.
        """

        if not side_or_number:
            return await self._default_flip(ctx)
        if isinstance(side_or_number, int):
            return await self._numbered_flip(ctx, side_or_number)

        side = side_or_number
        is_betting = amount is not None

        if is_betting:
            money = await self.get_money(ctx.author.id, connection=ctx.db)
            if money < amount:
                return await ctx.send('You don\'t have enough.')

            new_amount = -amount

        actual = random.choices(SIDES, WEIGHTS)[0]
        won = actual == side

        if won:
            message = 'You won!'
            color = 0x4CAF50
            if is_betting:
                new_amount += amount * 2
                message += f'\nYou won **{new_amount}** \N{MONEY WITH WINGS}.'

        else:
            message = 'You lost!'
            color = 0xF44336
            if is_betting:
                lost = '**everything**' if amount == money else f'**{amount}** \N{MONEY WITH WINGS}'
                message += f'\nYou lost {lost} \N{MONEY WITH WINGS}.'

        if is_betting:
            query = 'UPDATE currency SET amount = amount + $2 WHERE user_id = $1;'
            await ctx.db.execute(query, ctx.author.id, new_amount)

        file = discord.File(f'data/images/coins/{actual}.png', 'coin.png')

        embed = (discord.Embed(description=message, color=color)
                 .set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar_url)
                 .set_image(url='attachment://coin.png'))

        await ctx.send(file=file, embed=embed)

    @commands.command(name='daily')
    @maybe_not_alt()
    async def _daily_cash(self, ctx):
        """Command to give you daily cash (between 10 and 200).

        As the name suggests, you can only use this command every 24 hours.
        """

        author_id = ctx.author.id
        now = ctx.message.created_at

        query = 'SELECT latest_time FROM daily_cash_cooldowns WHERE user_id = $1;'
        row = await ctx.db.fetchrow(query, author_id)

        if row:
            delta = (now - row['latest_time']).total_seconds()
            retry_after = DAILY_CASH_COOLDOWN_TIME - delta

            if retry_after > 0:
                return await ctx.send(f'Don\'t be greedy. Wait at least {duration_units(retry_after)} before using this command again.')

        query = """
            INSERT INTO   daily_cash_cooldowns
            VALUES        ($1, $2)
            ON CONFLICT   (user_id)
            DO UPDATE SET latest_time = $2;
        """
        await ctx.db.execute(query, author_id, now)

        amount = random.randint(10, 200)
        await self.add_money(author_id, amount, connection=ctx.db)

        query = 'INSERT INTO dailylog (user_id, time, amount) VALUES ($1, $2, $3);'
        await ctx.db.execute(query, author_id, now, amount)

        await ctx.send(f'{ctx.author.mention}, for your daily hope you will receive **{amount}** \N{MONEY WITH WINGS}.')


def setup(bot):
    bot.add_cog(Currency(bot))
