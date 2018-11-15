import copy
from itertools import starmap

from discord.ext import commands

from utils import db
from utils.examples import _get_static_example
from utils.paginator import Paginator


class CommandAliases(db.Table, table_name='command_aliases'):
    id = db.Column(db.Serial, primary_key=True)
    guild_id = db.Column(db.BigInt)
    alias = db.Column(db.Text)
    command = db.Column(db.Text)

    command_alias_index = db.Index(guild_id, alias, unique=True)


def _first_word(string):
    return string.split(' ', 1)[0]


def _first_word_is_command(group, string):
    return _first_word(string) in group.all_commands


class AliasName(commands.Converter):
    async def convert(self, ctx, argument):
        lower = argument.lower().strip()
        if not lower:
            raise commands.BadArgument('A good idea would be to actually provide an alias, mate.')

        if _first_word_is_command(ctx.bot, lower):
            raise commands.BadArgument('Dude, you cannot create an alias which has the same name as an existing command.')

        return lower

    @staticmethod
    def random_example(ctx):
        ctx.__alias_example__ = example = _get_static_example('alias_examples')
        return example[0]


class AliasCommand(commands.Converter):
    async def convert(self, ctx, argument):
        if not _first_word_is_command(ctx.bot, argument):
            raise commands.BadArgument(f'{argument} isn\'t an actual command.')

        return argument

    @staticmethod
    def random_example(ctx):
        return ctx.__alias_example__[1]


class Aliases:
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='alias', invoke_without_command=True)
    async def _alias(self, ctx, alias: AliasName, *, command: AliasCommand):
        """Creates an alias for a certain command.

        Aliases are **case-insensitive**.

        If the alias already exists, using this command will overwrite the corresponding command for the alias.

        For multi-word aliases, you must use quotes, e.g `{prefix}alias "my alias" some_command`

        **You need the Manage Server permission to use this command.**
        """

        # We can't use the has_permissions decorator because of the affection it has on the subcommands
        if not ctx.channel.permissions_for(ctx.author).manage_guild:
            return

        query = """
            INSERT INTO   command_aliases
            VALUES        (DEFAULT, $1, $2, $3)
            ON CONFLICT   (guild_id, alias)
            DO UPDATE SET command = $3;
        """
        await ctx.db.execute(query, ctx.guild.id, alias, command)

        await ctx.send(f'Ok, "{ctx.prefix}{alias}" will now have the same result as "{ctx.prefix}{command}".')

    @_alias.command(name='delete')
    @commands.has_permissions(manage_guild=True)
    async def _delete_alias(self, ctx, *, alias: AliasName):
        """Deletes an existing alias."""

        query = """
            DELETE FROM command_aliases
            WHERE       guild_id = $1 AND alias = $2;
        """
        await ctx.db.execute(query, ctx.guild.id, alias)

        await ctx.send(f'Alias `{alias}` was successfully deleted.')

    @_alias.command(name='show')
    async def _show_aliases(self, ctx):
        """Shows all aliases that exist on this server."""

        query = """
            SELECT   alias, command FROM command_aliases
            WHERE    guild_id = $1
            ORDER BY alias;
        """
        entries = starmap('`{0}` => `{1}`'.format, await ctx.db.fetch(query, ctx.guild.id))
        pages = Paginator(ctx, entries)
        await pages.interact()

    async def _get_alias(self, guild_id, content, *, con=None):
        con = con or self.bot.pool
        query = """
            SELECT   alias, command FROM command_aliases
            WHERE    guild_id = $1
            AND      ($2 ILIKE alias || ' %' OR $2 = alias)
            ORDER BY length(alias)
            LIMIT    1;
        """
        return await con.fetchrow(query, guild_id, content)

    def _get_prefix(self, message):
        # The fucking good old way of doing shitty things with shitty methods
        prefixes = self.bot.get_guild_prefixes(message.guild)
        return next(filter(message.content.startswith, prefixes), None)

    async def on_message(self, message):
        if not message.guild:
            return

        prefix = self._get_prefix(message)
        if not prefix:
            return
        len_prefix = len(prefix)

        row = await self._get_alias(message.guild.id, message.content[len_prefix:])
        if not row:
            return

        alias, command = row

        new_message = copy.copy(message)
        args = message.content[len_prefix + len(alias):]
        new_message.content = f'{prefix}{command}{args}'

        await self.bot.process_commands(new_message)


def setup(bot):
    bot.add_cog(Aliases(bot))
