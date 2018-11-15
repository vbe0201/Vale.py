import itertools
import logging

import asyncpg
import discord
from discord.ext import commands

from utils import db, formats
from utils.colors import random_color
from utils.examples import _get_static_example
from utils.formats import escape_markdown
from utils.paginator import Paginator

logger = logging.getLogger(__name__)


class TagTable(db.Table, table_name='tags'):
    guild_id = db.Column(db.BigInt)
    name = db.Column(db.Text)
    content = db.Column(db.Text)
    is_alias = db.Column(db.Boolean)

    # meta data
    created_at = db.Column(db.Timestamp, default="now() at time zone 'utc'")
    created_by = db.Column(db.BigInt)
    uses = db.Column(db.Integer, default=0)

    tags_index = db.Index('LOWER(name)', guild_id)
    __create_extra__ = ['PRIMARY KEY(name, guild_id)']


class TagError(commands.UserInputError):
    pass


class MemberTagPaginator(Paginator):
    def __init__(self, *args, member, **kwargs):
        super().__init__(*args, **kwargs)

        self.member = member

    def create_embed(self, page):
        header = f'Tags made by {self.member.display_name}:'
        return (super().create_embed(page)
                .set_author(name=header, icon_url=self.member.avatar_url))


class ServerTagPaginator(Paginator):
    def create_embed(self, page):
        guild = self.ctx.guild
        embed = super().create_embed(page).set_author(name=f'Tags in {guild}')
        if guild.icon:
            return embed.set_author(name=embed.author.name, icon_url=guild.icon_url)

        return embed


class TagName(commands.clean_content):
    async def convert(self, ctx, argument):
        converted = await super().convert(ctx, argument)
        lower = converted.lower()

        if len(lower) > 50:
            raise commands.BadArgument('Tag name cannot be longer than 50 characters.')

        first_word, _, _ = lower.partition(' ')

        root = ctx.bot.get_command('tag')
        if first_word in root.all_commands:
            raise commands.BadArgument('A tag cannot have the name of another command.')

        return lower

    @staticmethod
    def random_example(ctx):
        ctx.__tag_example__ = example = _get_static_example('tag_examples')
        return example[0]


class TagContent(commands.clean_content):
    @staticmethod
    def random_example(ctx):
        return ctx.__tag_example__[1]


class Tags:
    def __init__(self, bot):
        self.bot = bot

    async def __error(self, ctx, error):
        if isinstance(error, TagError):
            await ctx.send(error)

    @staticmethod
    async def _spot_error(con, name, guild_id):
        message = f'Tag {name} not found...'

        query = """
            SELECT     name
            FROM       tags
            WHERE      guild_id = $1 AND name % $2
            ORDER BY   similarity(name, $2)
            DESC LIMIT 5;
        """
        try:
            results = await con.fetch(query, guild_id, name)
        except asyncpg.SyntaxOrAccessError:
            # similarity() and % aren't supported because
            # some shithead forgot to run `CREATE EXTENSION pg_trgm;`
            # on his database
            logger.error('Missing extension pg_trgm on the database! Please install it in order to support tags!')
        else:
            if results:
                message += 'Did you mean...\n' + '\n'.join(result['name'] for result in results)

        return TagError(message)

    async def _get_tag(self, con, name, guild_id):
        query = 'SELECT * FROM tags WHERE lower(name) = $1 AND guild_id = $2;'
        tag = await con.fetchrow(query, name, guild_id)
        if not tag:
            raise await self._spot_error(con, name, guild_id)

        return tag

    async def _get_original_tag(self, con, name, guild_id):
        tag = await self._get_tag(con, name, guild_id)
        if tag['is_alias']:
            return await self._get_tag(con, tag['content'], guild_id)

        return tag

    @staticmethod
    async def _update_uses(con, name, guild_id):
        query = 'UPDATE tags SET uses = uses + 1 WHERE name = $1 AND guild_id = $2;'
        await con.execute(query, name, guild_id)

    @staticmethod
    async def _get_tag_rank(con, tag):
        query = """
            SELECT COUNT(*)
            FROM   tags
            WHERE  guild_id = $1
            AND    (uses, created_at) >= ($2, $3);
        """
        row = await con.fetchrow(query, tag['guild_id'], tag['uses'], tag['created_at'])
        return row[0]

    @commands.group(name='tag', invoke_without_command=True)
    async def _tag(self, ctx, *, name: TagName):
        """Retrieves a tag if one exists."""

        tag = await self._get_original_tag(ctx.db, name, ctx.guild.id)
        await ctx.send(tag['content'])

        await self._update_uses(ctx.db, tag['name'], ctx.guild.id)

    @_tag.command(name='create', aliases=['add'])
    async def _tag_create(self, ctx, name: TagName, *, content: TagContent):
        """Creates a new tag.

        If you want the tag name to contain multiple words, please put it in quotes, e.g. `{prefix}tag create "hello world" Hello, World!`
        """

        query = """
            INSERT INTO tags (guild_id, name, content, is_alias, created_by)
            VALUES           ($1, $2, $3, FALSE, $4);
        """
        try:
            await ctx.db.execute(query, ctx.guild.id, name, content, ctx.author.id)
        except asyncpg.UniqueViolationError:
            await ctx.send(f'Tag "{name}" already exists.')
        else:
            await ctx.send(f'Successfully created tag "{name}".')

    @_tag.command(name='edit')
    async def _tag_edit(self, ctx, name: TagName, *, new_content: TagContent):
        """Edits a tag created by **you**.

        You can only edit actual tags, no aliases.
        """

        tag = await self._get_tag(ctx.db, name, ctx.guild.id)
        if tag['is_alias']:
            return await ctx.send('This tag is an alias and cannot be edited.')

        if tag['created_by'] != ctx.author.id:
            return await ctx.send('You don\'t own this tag.')

        query = 'UPDATE tags SET content = $1 WHERE name = $2 AND guild_id = $3;'
        await ctx.db.execute(query, new_content, name, ctx.guild.id)

        await ctx.send(f'Successfully edited tag "{name}".')

    @_tag.command(name='alias')
    async def _tag_alias(self, ctx, alias: TagName, *, original: TagName):
        """Creates an alias for an existing tag.

        You own the alias you create, but if the original tag gets deleted, so does your alias.
        Either way, aliases cannot be edited.
        """

        tag = await self._get_original_tag(ctx.db, original, ctx.guild.id)

        query = """
            INSERT INTO tags (guild_id, name, content, is_alias, created_by)
            VALUES           ($1, $2, $3, TRUE, $4);
        """
        try:
            await ctx.db.execute(query, ctx.guild.id, alias, tag['name'], ctx.author.id)
        except asyncpg.UniqueViolationError:
            await ctx.send(f'A tag or an alias with the name "{alias}" already exists.')
        else:
            await ctx.send(f'Successfully created alias "{alias}" that points to "{original}".')

    @_tag.command(name='delete', aliases=['remove', 'destroy'])
    async def _tag_delete(self, ctx, *, name: TagName):
        """Deletes a tag or an alias.

        Only the owner of the tag/alias is able to delete it.
        However, if you have the Manage Guild permission, you can delete the tag regardless whether or not you're its owner.
        """

        required_perms = ctx.author.permissions_in(ctx.channel).manage_guild

        # Waste of performance but I don't have a better idea
        tag = await self._get_tag(ctx.db, name, ctx.guild.id)
        if tag['created_by'] != ctx.author.id and not required_perms:
            return await ctx.send('You don\'t have permissions to delete this tag.')

        query = """
            DELETE FROM tags
            WHERE       guild_id = $1
            AND         ((is_alias AND lower(content) = $2) OR (lower(name) = $2));
        """
        await ctx.db.execute(query, ctx.guild.id, name)

        if not tag['is_alias']:
            await ctx.send(f'Tag "{name}" and all of its aliases have been deleted.')
        else:
            await ctx.send(f'Alias "{name}" successfully deleted.')

    @_tag.command(name='claim')
    async def _tag_claim(self, ctx, *, name: TagName):
        """Claims an existing tag.

        Please note that you can only claim tags whose owners have left the server before.
        You can also claim aliases.
        """

        tag = await self._get_tag(ctx.db, name, ctx.guild.id)
        owner = ctx.guild.get_member(tag['created_by'])

        query = 'UPDATE tags SET created_by = $1 WHERE guild_id = $2 AND name = $3;'
        if not owner:
            await ctx.db.execute(query, ctx.author.id, ctx.guild.id, name)
        else:
            await ctx.send('This tag\'s owner is still on this server.')

    @_tag.command(name='info', aliases=['stats'])
    async def _tag_info(self, ctx, *, name: TagName):
        """Shows some information about an existing tag."""

        # Ouch, big performance loss. Querying takes about 10ms.
        # I will ignore this for now until the bot becomes bigger and querying the tags becomes expensive.
        tag = await self._get_tag(ctx.db, name, ctx.guild.id)
        rank = await self._get_tag_rank(ctx.db, tag)

        user = self.bot.get_user(tag['created_by'])
        creator = user.mention if user else f'Mysterious person (ID: {tag["created_by"]})'
        icon_url = user.avatar_url if user else discord.Embed.Empty

        embed = (discord.Embed(color=random_color(), timestamp=tag['created_at'])
                 .set_author(name=tag['name'], icon_url=icon_url)
                 .add_field(name='Created by:', value=creator)
                 .add_field(name='Used:', value=f'{formats.pluralize(time=tag["uses"])}', inline=False)
                 .add_field(name='Rank:', value=f'#{rank}', inline=False))

        if tag['is_alias']:
            embed.description = f'Original tag: **{tag["content"]}**'

        await ctx.send(embed=embed)

    @_tag.command(name='raw')
    async def _tag_raw(self, ctx, *, name: TagName):
        """Shows the raw content of a tag.

        This is escaped with Markdown, useful for editing.
        """

        tag = await self._get_tag(ctx.db, name, ctx.guild.id)
        await ctx.send(escape_markdown(tag['content']))

    @_tag.command(name='search')
    async def _tag_search(self, ctx, *, name: TagName):
        """Searches and shows up the 50 closest matches for a given name."""

        query = """
            SELECT     name
            FROM       tags
            WHERE      guild_id = $1 AND name % $2
            ORDER BY   similarity(name, $2)
            DESC LIMIT 5;
        """
        tags = [tag['name'] for tag in (await ctx.db.fetch(query, ctx.guild.id, name))]
        entries = (
            itertools.starmap('`{0}`.  {1}'.format, enumerate(tags, 1)) if tags else
            (f'There are no tags available. Consider creating a new one.', )
        )

        pages = Paginator(ctx, entries, title=f'Tags relating to {name}')
        await pages.interact()

    @_tag.command(name='list', aliases=['all'])
    async def _tag_list(self, ctx):
        """Shows all tags that are currently available on this server."""

        query = 'SELECT name FROM tags WHERE guild_id = $1 ORDER BY name;'
        tags = [tag[0] for tag in await ctx.db.fetch(query, ctx.guild.id)]

        entries = (
            itertools.starmap('`{0}`.  {1}'.format, enumerate(tags, 1)) if tags else
            (f'There are no tags. Use `{ctx.prefix}tag create` to add a new one.', )
        )

        pages = ServerTagPaginator(ctx, entries)
        await pages.interact()

    @_tag.command(name='from', aliases=['by'])
    async def _tag_from(self, ctx, *, member: discord.Member = None):
        """Shows all tags created by a given member.

        If no member is provided, defaults to the person who invoked the command.
        """

        member = member or ctx.author

        query = 'SELECT name FROM tags WHERE guild_id = $1 AND created_by = $2 ORDER BY name;'
        tags = [tag[0] for tag in await ctx.db.fetch(query, ctx.guild.id, member.id)]

        entries = (
            itertools.starmap('`{0}`.  {1}'.format, enumerate(tags, 1)) if tags else
            (f'This member didn\'t create any tags yet.', )
        )

        pages = MemberTagPaginator(ctx, entries, member=member)
        await pages.interact()


def setup(bot):
    bot.add_cog(Tags(bot))
