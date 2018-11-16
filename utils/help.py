import copy
import inspect
import itertools
import operator
import random
import sys

import discord
from discord.ext import commands
from more_itertools import chunked, flatten, run_length, sliced, spy

from .commands import all_names, command_category, walk_parents
from .converter import BotCommand
from .colors import random_color
from .deprecated import DeprecatedCommand
from .examples import command_example
from .misc import maybe_awaitable
from .paginator import Paginator, trigger


def _padded(string, width):
    return string + ' \u200b' * (width - len(string) + 1)


def _has_subcommands(command):
    return isinstance(command, commands.GroupMixin)


def _all_checks(command):
    yield from command.checks
    if not command.parent:
        return

    for parent in walk_parents(command.parent):
        if not parent.invoke_without_command:
            yield from parent.checks


def _build_command_requirements(command):
    requirements = []

    # All commands in this cog are owner-only anyways
    if command.cog_name == 'Owner':
        requirements.append('**Bot Owner only**')

    def make_pretty(p):
        return p.replace('_', ' ').title().replace('Guild', 'Server')

    for check in _all_checks(command):
        name = getattr(check, '__qualname__', '')

        if name.startswith('is_owner'):
            requirements.insert(0, '**Bot Owner only**')
        elif name.startswith('has_permissions'):
            permissions = inspect.getclosurevars(check).nonlocals['perms']
            pretty_permissions = [make_pretty(key) if value else f'~~{make_pretty(key)}~~'
                                  for key, value in permissions.items()]

            perm_names = ', '.join(pretty_permissions)
            requirements.append(f'{perm_names} permission{"s" * (len(pretty_permissions) != 1)}')

    return '\n'.join(requirements)


def _list_subcommands_and_descriptions(command):
    name_docs = sorted((str(sub), sub.short_doc) for sub in set(_visible_subcommands(command)))
    padding = max(len(name) for name, _ in name_docs)

    return '\n'.join(f'`{_padded(name, padding)}` \N{EM DASH} {doc}' for name, doc in name_docs)


def _visible_subcommands(command):
    return (c for c in command.walk_commands() if not c.hidden and c.enabled)


def _help_command_embed(ctx, command, func):
    clean_prefix = ctx.clean_prefix

    title = f'`{clean_prefix}{command.full_parent_name} {" / ".join(all_names(command))}`'
    description = (command.help or '').format(prefix=clean_prefix)
    if isinstance(command, DeprecatedCommand):
        description = f'*{command.warning}*\n\n{description}'

    embed = discord.Embed(title=func(title), description=func(description), color=random_color())

    requirements = _build_command_requirements(command)
    if requirements:
        embed.add_field(name=func('Requirements:'), value=func(requirements))

    usage = command_example(command, ctx)
    embed.add_field(name=func('Usage:'), value=func(usage), inline=False)

    if _has_subcommands(command):
        subs = _list_subcommands_and_descriptions(command)
        embed.add_field(name='See also:', value=subs, inline=False)

    category = command_category(command, 'Other')
    footer = f'Category: {category.title()}'
    return embed.set_footer(text=func(footer))


async def _can_run(command, ctx):
    try:
        return await command.can_run(ctx)
    except commands.CommandError:
        return False


async def _command_formatters(commands, ctx):
    for command in commands:
        yield command.name, await _can_run(command, ctx)


COMMAND_COLUMNS = 2


def _command_lines(command_can_run_pairs):
    if len(command_can_run_pairs) % 2:
        command_can_run_pairs = command_can_run_pairs + [('', '')]

    pairs = list(sliced(command_can_run_pairs, COMMAND_COLUMNS))
    widths = [max(len(c[0]) for c in column) for column in zip(*pairs)]

    def format_pair(pair, width):
        command, can_run = pair
        if not command:
            return ''

        formatted = f'`{_padded(command, width)}`'
        return formatted if can_run else f'~~{formatted}~~'

    return (' '.join(map(format_pair, pair, widths)) for pair in pairs)


CROSSED_NOTE = '**Note:** You can\'t use commands\nthat are ~~crossed out~~.'


def _get_category_commands(bot, category):
    return {c for c in bot.all_commands.values() if command_category(c, 'Other') == category}


class CogPages(Paginator):
    goto = None

    @classmethod
    async def create(cls, ctx, category):
        command, commands = spy(
            c for c in _get_category_commands(ctx.bot, category) if not (c.hidden or ctx.bot.formatter.show_hidden)
        )

        pairs = [pair async for pair in _command_formatters(sorted(commands, key=str), ctx)]

        self = cls(ctx, _command_lines(pairs))
        pkg_name = command[0].module.rpartition('.')[0]
        module = sys.modules[pkg_name]

        self._cog_doc = inspect.getdoc(module) or 'No description yet.'
        self._cog_name = category.title() or 'Other'

        return self

    def create_embed(self, page):
        return (discord.Embed(description=self._cog_doc, color=self.color)
                .set_author(name=self._cog_name)
                .add_field(name='Commands:', value='\n'.join(page) + f'\n\n{CROSSED_NOTE}')
                .set_footer(text=f'Currently on page {self._index + 1}')
                )

    @trigger('\N{BLACK SQUARE FOR STOP}', fallback='exit')
    async def stop(self):
        """Exit."""

        await super().stop()


class GeneralHelpPaginator(Paginator):
    first = None
    last = None
    help_page = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    async def create(cls, ctx):
        def sort_key(c):
            return command_category(c), c.qualified_name

        entries = (cmd for cmd in sorted(ctx.bot.commands, key=sort_key) if not cmd.hidden)

        nested_pages = []
        per_page = 30

        for parent, cmds in itertools.groupby(entries, key=command_category):
            command, cmds = spy(cmds)
            command = next(iter(command))

            pkg_name = command.module.rpartition('.')[0]
            module = sys.modules[pkg_name]
            description = inspect.getdoc(module) or 'No description yet.'

            lines = [pair async for pair in _command_formatters(cmds, ctx)]
            nested_pages.extend((parent.title(), description, page) for page in sliced(lines, per_page))

        return cls(ctx, nested_pages, per_page=1)

    def create_embed(self, page):
        name, description, lines = page[0]
        random_command = random.choice(next(zip(*lines)))
        note = (
            f'For more help on a command,\ntype `{self.ctx.clean_prefix}help "command"`.\n'
            f'**Example:** `{self.ctx.clean_prefix}help {random_command}`'
        )
        formatted = '\n'.join(_command_lines(lines))
        commands = f'{formatted}\n{"-" * 30}\n{note}\n\u200b\n{CROSSED_NOTE}'

        return (discord.Embed(description=description, color=self.color)
                .set_author(name=name)
                .add_field(name='Commands:', value=commands)
                .set_footer(text=f'Page {self._index + 1} / {len(self._pages)}'))

    @trigger('\N{BLACK LEFT-POINTING TRIANGLE}', fallback=r'\<')
    def previous(self):
        """Back."""

        return super().previous() or (self.instructions() if self._index == 0 else None)

    @trigger('\N{BLACK RIGHT-POINTING TRIANGLE}', fallback=r'\>')
    def next(self):
        """Next."""

        return super().next()

    @trigger('\N{INPUT SYMBOL FOR NUMBERS}', blocking=True)
    async def goto(self):
        """Goto."""

        return await maybe_awaitable(super().goto)

    def instructions(self):
        """Table of Contents."""

        self._index = -1
        ctx = self.ctx
        bot = self.ctx.bot

        def cog_pages(iterable, start):
            for name, count in run_length.encode(map(operator.itemgetter(0), iterable)):
                if count == 1:
                    yield str(start), name
                else:
                    yield f'{start}-{start + count - 1}', name

                start += count

        pairs = list(cog_pages(flatten(self._pages), 1))
        padding = max(len(p[0]) for p in pairs)
        lines = [f'`\u200b{numbers:<{padding}}\u200b` - {name}' for numbers, name in pairs]

        if self.using_reactions():
            docs = ((emoji, func.__doc__) for emoji, func in self._reaction_map.items())
            controls = '\n'.join(f'{p1[0]} `{p1[1]}` | `{p2[1]}` {p2[0]}' for p1, p2 in chunked(docs, 2))
            footer_text = 'Click one of the reactions below.'
        else:
            controls = '\n'.join(
                f'`' + pattern.replace('\\', '') + f'` = `{func.__doc__}`'
                for pattern, func in self._message_fallbacks
            )
            footer_text = 'Type on of these things below because I don\'t have perms to give you the opportunity to react. **REEEEEEEE**'

        description = (f'For help on a command, type `{ctx.clean_prefix}help "command"`.\n\n'
                       f'To list the commands from one of the Categories below, type `{ctx.clean_prefix}commands "Category"`.\n')

        return (discord.Embed(description=description, color=self.color)
                .set_author(name='Vale.py Help', icon_url=bot.user.avatar_url)
                .add_field(name='Categories:', value='\n'.join(lines), inline=False)
                .add_field(name='Controls:', value=controls, inline=False)
                .set_footer(text=footer_text)
                )

    default = instructions

    @trigger('\N{BLACK SQUARE FOR STOP}', fallback='exit')
    async def stop(self):
        """Exit."""

        await super().stop()

    def check(self, reaction, user):
        if super().check(reaction, user):
            return True


class _HelpCommand(BotCommand):
    _choices = [
        'Help yourself.',
        'Gtfo, google it!',
        'https://www.50-best.com/images/memes_for_facebook_comments/just_google_it.jpg',
    ]

    async def convert(self, ctx, argument):
        try:
            return await super().convert(ctx, argument)
        except commands.BadArgument:
            if argument.lower() != 'me':
                raise commands.BadArgument(random.choice(self._choices))


def _help_error(ctx, missing_perms):
    old_send = ctx.send

    async def new_send(content, **kwargs):
        content += ' Turn on your DMs ffs.'
        await old_send(content, **kwargs)

    ctx.send = new_send
    raise commands.BotMissingPermissions(missing_perms)


async def _help_command(ctx, command, func):
    permissions = ctx.me.permissions_in(ctx.channel)
    if not permissions.send_messages:
        return

    if permissions.embed_links:
        return await ctx.send(embed=_help_command_embed(ctx, command, func))

    try:
        await ctx.author.send(embed=_help_command_embed(ctx, command, func))
    except discord.HTTPException:
        _help_error(ctx, ['embed_links'])


async def _help_general(ctx):
    if not ctx.me.permissions_in(ctx.channel).send_messages:
        return

    paginator = await GeneralHelpPaginator.create(ctx)
    try:
        await paginator.interact()
    except commands.BotMissingPermissions as e:
        missing_perms = e.missing_perms
    else:
        return

    new_ctx = copy.copy(ctx)
    new_ctx.channel = paginator._channel = await ctx.author.create_dm()
    paginator.ctx = new_ctx

    try:
        await paginator.interact()
    except discord.HTTPException:
        _help_error(ctx, missing_perms)


def help_command(func=lambda s: s, **kwargs):
    """Creates a help command with a given transformation function."""

    async def command(_, ctx, *, command: _HelpCommand = None):
        if command is None:
            await _help_general(ctx)
        else:
            await _help_command(ctx, command, func)

    try:
        module = sys._getframe(1).f_globals.get('__name__', '__main__')
    except (AttributeError, ValueError):
        pass

    if module is not None:
        command.__module__ = module

    return commands.command(help=func('Shows this message and other crap'), **kwargs)(command)
