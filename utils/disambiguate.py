import asyncio
import functools
import random
import re
import weakref
from itertools import starmap

import discord
from discord.ext import commands

from .examples import get_example
from .colors import random_color

_ID_REGEX = re.compile(r'([0-9]{15,21})$')


async def disambiguate(ctx, matches, transform=str, *, tries=3):
    """Prompts the user to choose from a list of matches."""

    if not matches:
        raise commands.BadArgument('No results found.')

    num_matches = len(matches)
    if num_matches == 1:
        return matches[0]

    entries = '\n'.join(starmap('{0}: {1}'.format, enumerate(map(transform, matches), 1)))

    permissions = ctx.channel.permissions_for(ctx.me)
    if permissions.embed_links:
        # Build the embed as we go. And make it nice and pretty.
        embed = discord.Embed(color=random_color(), description=entries)
        embed.set_author(name=f"There were {num_matches} matches found. Which one did you mean?")

        index = random.randrange(len(matches))
        instructions = f'Just type the number.\nFor example, typing `{index + 1}` will return {matches[index]}'
        embed.add_field(name='Instructions:', value=instructions)

        message = await ctx.send(embed=embed)
    else:
        await ctx.send('There are too many matches. Which one did you mean? **Only say the number**.')
        message = await ctx.send(entries)

    def check(m):
        return (m.author.id == ctx.author.id
                and m.channel.id == ctx.channel.id
                and m.content.isdigit())

    await ctx.release()

    try:
        for i in range(tries):
            try:
                msg = await ctx.bot.wait_for('message', check=check, timeout=30.0)
            except asyncio.TimeoutError:
                raise commands.BadArgument('Took too long. Goodbye.')

            index = int(msg.content)
            try:
                return matches[index - 1]
            except IndexError:
                await ctx.send(f'Please give me a valid number. {tries - i - 1} tries remaining...')

        raise commands.BadArgument('Too many tries. Goodbye.')
    finally:
        await message.delete()
        await ctx.acquire()


class _DisambiguateExampleGenerator:
    def __get__(self, obj, cls):
        cls_name = cls.__name__.replace('Disambiguate', '')
        return functools.partial(get_example, getattr(discord, cls_name))


class Converter(commands.Converter):
    """This is the base class for all disambiguating converters.

    By default, if there is more than one thing with a given name, the ext converters will only pick the first results.
    These allow you to pick from multiple results.

    Especially important when the args become case-insensitive.
    """

    _transform = str
    __converters__ = weakref.WeakValueDictionary()
    random_example = _DisambiguateExampleGenerator()

    def __init__(self, *, ignore_case=True):
        self.ignore_case = ignore_case

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        Converter.__converters__[cls.__name__] = cls

    def _get_possible_entries(self, ctx):
        """Returns an iterable of possible entries to find matches with.

        Subclasses must provide this to allow disambiguating.
        """

        raise NotImplementedError

    def _exact_match(self, ctx, argument):
        """Returns an "exact" match given an argument.

        If this returns anything but None, that result will be returned without going through disambiguating.

        Subclasses may override this method to provide an "exact" functionality.
        """

        return None

    # The following predicates can be overridden if necessary

    def _predicate(self, obj, argument):
        """Standard predicate for filtering."""

        return obj.name == argument

    def _predicate_ignore_case(self, obj, argument):
        """Same thing like `predicate` but with case-insensitive filtering."""

        return obj.name.lower() == argument

    def _get_possible_results(self, ctx, argument):
        entries = self._get_possible_entries(ctx)

        if self.ignore_case:
            lowered = argument.lower()
            predicate = self._predicate_ignore_case
        else:
            lowered = argument
            predicate = self._predicate

        return [obj for obj in entries if predicate(obj, lowered)]

    async def convert(self, ctx, argument):
        exact_match = self._exact_match(ctx, argument)
        if exact_match:
            return exact_match

        matches = self._get_possible_results(ctx, argument)
        return await disambiguate(ctx, matches, transform=self._transform)


class IDConverter(Converter):
    MENTION_REGEX = None

    def _get_from_id(self, ctx, id):
        """Returns an object via a given ID."""

        raise NotImplementedError

    def __get_id_from_mention(self, argument):
        return re.match(self.MENTION_REGEX, argument) if self.MENTION_REGEX else None

    def _exact_match(self, ctx, argument):
        match = _ID_REGEX.match(argument) or self.__get_id_from_mention(argument)
        if not match:
            return None

        return self._get_from_id(ctx, int(match[1]))


class UserConverterMixin:
    MENTION_REGEX = r'<@!?([0-9]+)>$'

    def _exact_match(self, ctx, argument):
        result = super()._exact_match(ctx, argument)
        if result is not None:
            return result

        if not (len(argument) > 5 and argument[-5] == '#'):
            # No discriminator provided which makes an exact match impossible
            return None

        name, _, discriminator = argument.rpartition('#')
        return discord.utils.find(
            lambda u: u.name == name and u.discriminator == discriminator,
            self._get_possible_entries(ctx)
        )


class User(UserConverterMixin, IDConverter):
    def _get_from_id(self, ctx, id):
        return ctx.bot.get_user(id)

    def _get_possible_entries(self, ctx):
        return ctx._state._users.values()


class Member(UserConverterMixin, IDConverter):
    def _get_from_id(self, ctx, id):
        return ctx.guild.get_member(id)

    def _get_possible_entries(self, ctx):
        return ctx.guild._members.values()

    # Overriding these is necessary due to members having nicknames
    def _predicate(self, obj, argument):
        return super()._predicate(obj, argument) or (obj.nick and obj.nick == argument)

    def _predicate_ignore_case(self, obj, argument):
        return (
            super()._predicate_ignore_case(obj, argument)
            or (obj.nick and obj.nick.lower() == argument)
        )


class Role(IDConverter):
    MENTION_REGEX = r'<@&([0-9]+)>$'

    def _get_from_id(self, ctx, id):
        return discord.utils.get(self._get_possible_entries(ctx), id=id)

    def _get_possible_entries(self, ctx):
        return ctx.guild.roles


class TextChannel(IDConverter):
    MENTION_REGEX = r'<#([0-9]+)>$'

    def _get_from_id(self, ctx, id):
        return ctx.guild.get_channel(id)

    def _get_possible_entries(self, ctx):
        return ctx.guild.text_channels


class Guild(IDConverter):
    def _get_from_id(self, ctx, id):
        return ctx.bot.get_guild(id)

    def _get_possible_entries(self, ctx):
        return ctx._state._guilds.values()


def _is_discord_py_type(cls):
    module = getattr(cls, '__module__', '')
    return module.startswith('discord.') and not module.endswith('converter')


def _disambiguated(type_):
    """Return the corresponding disambiguating converter if one exists
    for that type.
    If no such converter exists, it returns the type.
    """
    if not _is_discord_py_type(type_):
        return type_

    return Converter.__converters__.get(type_.__name__, type_)


def _get_current_parameter(ctx):
    parameters = list(ctx.command.params.values())

    # Need to account for varargs and consume-rest kwarg only
    index = min(len(ctx.args) + len(ctx.kwargs), len(parameters) - 1)
    return parameters[index]


class Union(commands.Converter):
    _transform = '{0} ({0.__class__.__name__})'.format

    def __init__(self, *types, ignore_case=True):
        self.types = [
            type_(ignore_case=ignore_case)
            if isinstance(type_, type) and issubclass(type_, Converter)
            else type_
            for type_ in map(_disambiguated, types)
        ]

    async def convert(self, ctx, argument):
        param = _get_current_parameter(ctx)
        results = []
        for converter in self.types:
            if isinstance(converter, Converter):
                exact = converter._exact_match(ctx, argument)
                if exact is not None:
                    return exact

                results.extend(converter._get_possible_results(ctx, argument))
            else:
                # Standard type, so standard conversion
                try:
                    result = await ctx.command.do_conversion(ctx, converter, argument, param)
                except commands.BadArgument:
                    continue
                else:
                    results.append(result)
        return await disambiguate(ctx, results, transform=self._transform)

    def random_example(self, ctx):
        return get_example(random.choice(self.types), ctx)
