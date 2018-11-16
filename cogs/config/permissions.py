import itertools
import random
from collections import defaultdict, namedtuple

import asyncpg
import discord
from discord.ext import commands
from more_itertools import partition

from utils import cache, db, disambiguate, formats
from utils.commands import command_category, walk_parents
from utils.converter import BotCommand, Category
from utils.misc import emoji_url, truncate, unique
from utils.paginator import Paginator


class CommandPermissions(db.Table, table_name='permissions'):
    id = db.Column(db.Serial, primary_key=True)
    name = db.Column(db.Text)
    guild_id = db.Column(db.BigInt)
    snowflake = db.Column(db.BigInt, nullable=True)
    whitelist = db.Column(db.Boolean)


class Ignored(db.Table, table_name='plonks'):
    guild_id = db.Column(db.BigInt)
    entity_id = db.Column(db.BigInt)

    plonks_index = db.Index(guild_id, entity_id)
    __create_extra__ = ['PRIMARY KEY (guild_id, entity_id)']


ALL_COMMANDS_KEY = '*'


def _extract_from_node(node):
    return node.partition('.')


def _get_class_name(obj):
    return obj.__class__.__name__.replace('Text', '')


class _PermissionFormattingMixin:
    def _get_header(self):
        if self.command:
            return f'Command **{self.command}** is'

        if self.cog == ALL_COMMANDS_KEY:
            return 'All commands are'

        category, _, cog = self.cog.partition('/')
        if cog:
            return f'Module **{cog}** is'

        return f'Category **{category.title()}** is'


class PermissionDenied(_PermissionFormattingMixin, commands.CheckFailure):
    def __init__(self, message, *args):
        name, obj, *_ = args
        self.object = obj
        self.cog, _, self.command = _extract_from_node(name)

        super().__init__(message, *args)

    def __str__(self):
        return (
            f'{self._get_header()} disabled for the {_get_class_name(self.object).lower()} '
            f'`{self.object}`.'
        )


class InvalidPermissions(_PermissionFormattingMixin, commands.CommandError):
    def __init__(self, message, *args):
        name, whitelisted, *_ = args
        self.whitelisted = whitelisted
        self.cog, _, self.command = _extract_from_node(name)

        super().__init__(message, *args)

    def __str__(self):
        message = {
            False: 'disabled',
            True: 'enabled',
            None: 'reset'
        }[self.whitelisted]

        return f'{self._get_header()} already {message}.'


_command_node = '{0.cog_name}.{0}'.format


class CommandName(BotCommand):
    async def convert(self, ctx, argument):
        command = await super().convert(ctx, argument)

        root = command.root_parent or command
        if root.name in {'enable', 'disable', 'undo'} or command_category(root) == 'owner':
            raise commands.BadArgument('You can\'t modify this command.')

        return _command_node(command)


class CommandCategoryOrAll(commands.Converter):
    __converters = [CommandName, Category]
    __converter_name_pairs = list(zip(__converters, ['Command', 'Category']))

    async def convert(self, ctx, argument):
        for _type, name in self.__converter_name_pairs:
            try:
                return await ctx.command.do_conversion(ctx, _type, argument), name
            except Exception:  # muh pycodestyle
                pass

        raise commands.BadArgument(f'{argument} is not a command or a category.')

    @staticmethod
    def random_example(ctx):
        try:
            converters = ctx.__cmd_cat_or_all_converters__
        except AttributeError:
            c = CommandCategoryOrAll.__converters
            ctx.__cmd_cat_or_all_converters__ = converters = iter(random.sample(c, len(c)))

        return next(converters).random_example(ctx)


PermissionEntity = disambiguate.Union(discord.Member, discord.Role, discord.TextChannel)
Plonkable = disambiguate.Union(discord.TextChannel, discord.Member)


class Server(namedtuple('Server', 'server')):
    """This class is needed to ensure that an ID of None is possible while still having the original Server object."""

    __slots__ = ()

    @property
    def id(self):
        return None

    def __str__(self):
        return str(self.server)


class _DummyEntry(namedtuple('_DummyEntry', 'id')):
    """This class makes sure that the object for ignore is mentionable."""

    __slots__ = ()

    @property
    def mention(self):
        return f'<Not Found: {self.id}>'


_value_embed_mappings = {
    True: (0x00FF00, 'enabled', emoji_url('\N{WHITE HEAVY CHECK MARK}')),
    False: (0xFF0000, 'disabled', emoji_url('\N{NO ENTRY SIGN}')),
    None: (0x7289DA, 'reset', emoji_url('\U0001f504')),
    -1: (0xFF0000, 'deleted', emoji_url('\N{PUT LITTER IN ITS PLACE SYMBOL}')),
}
_plonk_embed_mappings = {
    True: (0xF44336, 'plonk'),
    False: (0x4CAF50, 'unplonk'),
}
PLONK_ICON = emoji_url('\N{HAMMER}')


class Permissions:
    """Used for enabling or disabling commands for a channel, member, role or even the whole server."""

    def __init__(self, bot):
        self.bot = bot

    async def __global_check_once(self, ctx):
        if not ctx.guild:
            return True

        if await ctx.bot.is_owner(ctx.author):
            return True

        query = 'SELECT 1 FROM plonks WHERE guild_id = $1 AND entity_id IN ($2, $3) LIMIT 1;'
        row = await ctx.db.fetchrow(query, ctx.guild.id, ctx.author.id, ctx.channel.id)
        return row is None

    async def on_command_error(self, ctx, error):
        if isinstance(error, (PermissionDenied, InvalidPermissions)):
            await ctx.send(error)

    async def __error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            if await ctx.bot.is_owner(ctx.author):
                return

            missing = [perm.replace('_', '').replace('guild', 'server').title() for perm in error.missing_perms]
            message = (f'You need the {formats.human_join(missing)} permissions, because ~~somebody doesn\'t want you to use this command~~ '
                       f'it is pretty advanced, I think hehe.')
            await ctx.send(message)

    @staticmethod
    async def _set_one_permission(connection, guild_id, name, entity, whitelist):
        if not whitelist:
            if not entity.id:
                query = 'DELETE FROM permissions WHERE guild_id = $1 AND name = $2 AND snowflake IS NULL;'
                status = await connection.execute(query, guild_id, name)
            else:
                query = 'DELETE FROM permissions WHERE guild_id = $1 AND name = $2 AND snowflake = $3;'
                status = await connection.execute(guild_id, name, entity.id)

            count = status.partition(' ')[-2]

            if count == '0':
                raise InvalidPermissions(f'{name} was neither disabled nor enabled.', name, whitelist)

        else:
            if not entity.id:
                query = """
                    UPDATE permissions
                    SET    whitelist = $3
                    WHERE  guild_id = $1 AND name = $2 AND snowflake IS NULL;
                """
                status = await connection.execute(query, guild_id, name, whitelist)
                if status.rpartition(' ')[-1] != '0':
                    return

                query = """
                    INSERT INTO   permissions (guild_id, name, snowflake, whitelist)
                    VALUES        ($1, $2, $3, $4)
                    ON CONFLICT   (name, snowflake)
                    DO UPDATE SET whitelist = $4;
                """
                await connection.execute(query, guild_id, entity.id, name, whitelist)

    @staticmethod
    async def _bulk_set_permissions(connection, guild_id, name, *entities, whitelist):
        ids = tuple(unique(entity.id for entity in entities))

        # Fuck this
        query = """
            DELETE FROM permissions
            WHERE       guild_id = $1 AND name = $2 AND snowflake = ANY($3::BIGINT[]);
        """
        await connection.execute(query, guild_id, name, ids)

        if not whitelist:
            # Permissions shall not be created during a reset
            return

        columns = ('guild_id', 'name', 'snowflake', 'whitelist')
        to_insert = [(guild_id, name, id, whitelist) for id in ids]

        await connection.copy_records_to_table('permissions', columns=columns, records=to_insert)

    async def _set_permissions(self, connection, guild_id, name, *entities, whitelist):
        method = self._set_one_permission if len(entities) == 1 else self._bulk_set_permissions
        await method(connection, guild_id, name, *entities, whitelist=whitelist)

    @cache.cache(max_size=None, make_key=lambda a, kw: a[-1])
    async def _get_permissions(self, connection, guild_id):
        query = 'SELECT name, snowflake, whitelist FROM permissions WHERE guild_id = $1;'
        records = await connection.fetch(query, guild_id)

        lookup = defaultdict(lambda: (set(), set()))
        for name, snowflake, whitelist in records:
            lookup[snowflake][whitelist].add(name)

        # Converting this into a dict for future retrievals of this via cache
        return dict(lookup)

    async def __global_check(self, ctx):
        if not ctx.guild:  # Custom permissions in DMs? Nope
            return True

        if await ctx.bot.is_owner(ctx.author):
            return True

        lookup = await self._get_permissions(ctx.db, ctx.guild.id)
        if not lookup:
            return True

        root = ctx.command.root_parent or ctx.command
        if root in {self.enable, self.disable, self.reset}:
            return True

        server = Server(ctx.guild)

        objects = itertools.chain(
            [('user', ctx.author)],
            zip(itertools.repeat('role'), sorted(ctx.author.roles, reverse=True)),
            [('channel', ctx.channel),
             ('server', server)],
        )

        parent = command_category(ctx.command)
        names = itertools.chain(
            map(_command_node, walk_parents(ctx.command)),
            (parent, ALL_COMMANDS_KEY)
        )

        # Ew, shit, now the real crap begins

        for (typename, obj), name in itertools.product(objects, names):
            if obj.id not in lookup:
                continue

            if name in lookup[obj.id][True]:
                return True

            if name in lookup[obj.id][False]:
                raise PermissionDenied(f'{name} is denied on the {typename} level', name, obj)

        return True

    async def _display_embed(self, ctx, name=None, *entities, whitelist, _type):
        color, action, icon = _value_embed_mappings[whitelist]

        def name_values():
            sorted_entities = sorted(entities, key=_get_class_name)
            for k, group in itertools.groupby(sorted_entities, _get_class_name):
                group = list(group)

                name = f'{k}{"s" * (len(group) != 1)}'
                value = truncate(', '.join(map(str, group)), 1024, '...')
                yield name, value

        if ctx.bot_has_embed_links():
            embed = (discord.Embed(color=color)
                     .set_author(name=f'{_type} {action}!', icon_url=icon))

            if name not in {ALL_COMMANDS_KEY, None}:
                cog, _, name = _extract_from_node(name)
                embed.add_field(name=_type, value=name or cog)

            for name, value in name_values():
                embed.add_field(name=name, value=value, inline=False)

            await ctx.send(embed=embed)

        else:
            cog, _, name = _extract_from_node(name)
            joined = '\n'.join(f'**{name}:** {value}' for name, value in name_values())
            message = f'Successfully {action} {_type.lower()} {name or cog}!\n\n{joined}'

            await ctx.send(message)

    async def _set_permissions_command(self, ctx, name, *entities, whitelist, _type):
        entities = entities or (Server(ctx.guild), )

        await self._set_permissions(ctx.db, ctx.guild.id, name, *entities, whitelist=whitelist)
        self._get_permissions.invalidate(None, None, ctx.guild.id)

        await self._display_embed(ctx, name, *entities, whitelist=whitelist, _type=_type)

    def _make_command(value, name, *, desc):
        @commands.group(
            name=name, help=f'{desc} a command, category, or *all* commands.',
            usage='<command, category, or all> [channels, members, or roles...]',
            invoke_without_command=True
        )
        @commands.has_permissions(manage_guild=True)
        async def group(self, ctx, command_category_or_all: CommandCategoryOrAll, *entities: PermissionEntity):
            thing, _type = command_category_or_all
            await self._set_permissions_command(ctx, thing, *entities, whitelist=value, _type=_type)

        @group.command(
            name='command', help=f'{desc} a command.', aliases=['cmd'],
            usage='<command> [channels, members, or roles...]',
        )
        @commands.has_permissions(manage_guild=True)
        async def group_command(self, ctx, command: CommandName, *entities: PermissionEntity):
            await self._set_permissions_command(ctx, command, *entities, whitelist=value, _type='Command')

        @group.command(
            name='category', help=f'{desc} a category.', aliases=['cog', 'module'],
            usage='<category> [channels, members, or roles...]',
        )
        @commands.has_permissions(manage_guild=True)
        async def group_category(self, ctx, category: Category, *entities: PermissionEntity):
            await self._set_permissions_command(ctx, category, *entities, whitelist=value, _type='Category')

        @group.command(name='all', help=f'{desc} all commands.\n', usage='[channels, members, or roles...]')
        @commands.has_permissions(manage_guild=True)
        async def group_all(self, ctx, *entities: PermissionEntity):
            await self._set_permissions_command(ctx, ALL_COMMANDS_KEY, *entities, whitelist=value, _type='All commands')

        return group, group_command, group_category, group_all

    enable, enable_command, enable_cog, enable_all = _make_command(True, 'enable', desc='Enables')
    disable, disable_command, disable_cog, disable_all = _make_command(False, 'disables', desc='Disables')
    reset, reset_command, reset_cog, reset_all = _make_command(None, 'reset', desc='Resets the permissions for')
    del _make_command

    @commands.command(name='resetperms', aliases=['clearperms'])
    @commands.has_permissions(administrator=True)
    async def _reset_perms(self, ctx):
        """Clears **all** the permissions for commands and cogs.

        This is a very risky action which means that you have to replace all permissions.
        Only do this if you *really* messed up.

        If you wish to just delete on perm or multiple, use `{prefix}reset` instead.
        """

        query = 'DELETE FROM permissions WHERE guild_id = $1;'
        await ctx.db.execute(query, ctx.guild.id)
        self._get_permissions.invalidate(None, None, ctx.guild.id)

        await self._display_embed(ctx, None, Server(ctx.guild), whitelist=-1, _type='All permissions')

    async def _bulk_ignore_entries(self, ctx, entries):
        query = 'SELECT entitiy_id FROM plonks WHERE guild_id = $1;'

        ignored = {result[0] for result in await ctx.db.fetch(query, ctx.guild.id)}
        to_insert = [(ctx.guild.id, entry.id) for entry in entries if entry.id not in ignored]

        await ctx.db.copy_records_to_table('plonks', columns=('guild_id', 'entity_id'), records=to_insert)

    async def _display_plonked(self, ctx, entries, plonk):
        color, action = _plonk_embed_mappings[plonk]

        def name_values():
            for thing in map(list, partition(lambda e: isinstance(e, discord.TextChannel), entries)):
                if not thing:
                    continue

                name = f'{_get_class_name(thing[0])}{"s" * (len(thing) != 1)}'
                value = truncate(', '.join(map(str, thing)), 1024, '...')
                yield name, value

        if ctx.bot_has_embed_links():
            embed = (discord.Embed(color=color)
                     .set_author(name=f'{action.title()} successful!', icon_url=PLONK_ICON))

            for name, value in name_values():
                embed.add_field(name=name, value=value, inline=False)

            await ctx.send(embed=embed)

        else:
            joined = '\n'.join(f'**{name}:** {value}' for name, value in name_values())
            await ctx.send(f'Successfully {ctx.command}d\n{joined}')

    @commands.command(name='ignore', aliases=['plonk'])
    @commands.has_permissions(manage_guild=True)
    async def _ignore(self, ctx, *channels_or_members: Plonkable):
        """Ignores text channels or members from using this bot.

        If no channel or member is specified, the current channel is ignored.
        """

        channels_or_members = channels_or_members or [ctx.channel]

        if len(channels_or_members) == 1:
            thing = channels_or_members[0]
            query = 'INSERT INTO plonks (guild_id, entity_id) VALUES ($1, $2);'

            try:
                await ctx.db.execute(query, ctx.guild.id, thing.id)
            except asyncpg.UniqueViolationError:
                return await ctx.send(f'I\'m already ignoring {thing}.')

        else:
            await self._bulk_ignore_entries(ctx, channels_or_members)

        await self._display_plonked(ctx, channels_or_members, plonk=True)

    @commands.command(name='unignore', aliases=['unplonk'])
    @commands.has_permissions(manage_guild=True)
    async def _unignore(self, ctx, *channels_or_members: Plonkable):
        """Allows channels or members to use the bot again.

        If no channel or member is specified, it unignores the current channel.
        """

        entities = channels_or_members or (ctx.channel, )
        if len(entities) == 1:
            query = 'DELETE FROM plonks WHERE guild_id = $1 AND entity_id = $2;'
            await ctx.db.execute(query, ctx.guild.id, entities[0].id)
        else:
            query = 'DELETE FROM plonks WHERE guild_id = $1 AND entity_id = ANY($2::BIGINT[]);'
            await ctx.db.execute(query, ctx.guild.id, [entity.id for entity in entities])

        await self._display_plonked(ctx, entities, plonk=False)

    @commands.command(name='ignores', aliases=['plonks'])
    @commands.has_permissions(manage_guild=True)
    async def _ignores(self, ctx):
        """Tells you what channels or members are currently ignored on this server."""

        query = 'SELECT entity_id FROM plonks WHERE guild_id = $1;'
        entries = [
            (ctx.guild.get_channel(entity_id) or ctx.guild.get_member(entity_id) or _DummyEntry(entity_id)).mention
            for entity_id, in await ctx.db.fetch(query, ctx.guild.id)
        ]
        if not entries:
            return await ctx.send('Nothing\'s being ignored in here.')

        pages = Paginator(ctx, entries, title=f'Currently ignoring...', per_page=20)
        await pages.interact()


def setup(bot):
    bot.add_cog(Permissions(bot))
