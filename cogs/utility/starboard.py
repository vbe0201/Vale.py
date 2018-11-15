import asyncio
import collections
import datetime
import logging
import re
import time
import typing
import weakref

import asyncpg
import discord
from discord.ext import commands

from utils import db, cache
from utils.formats import pluralize, human_join
from utils.paginator import Paginator

# Skidded from Danny, but with some "improvements".

logger = logging.getLogger(__name__)


class StarBoardError(Exception):
    pass


def requires_starboard():
    async def predicate(ctx):
        if not ctx.guild:
            return False

        starboard = ctx.bot.get_cog('StarBoard')

        ctx.starboard = await starboard.get_starboard(ctx.guild.id, connection=ctx.db)
        if not ctx.starboard.channel:
            raise StarBoardError('\N{WARNING SIGN} Starboard channel not found.')

        return True

    return commands.check(predicate)


class MessageID(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            return int(argument, base=10)
        except ValueError:
            raise StarBoardError(f'`{argument}` is not a valid message ID. Use Developer Mode to get the `Copy ID` option.')

    @staticmethod
    def random_example(ctx):
        return ctx.message.id


class Starboard(db.Table):
    id = db.Column(db.BigInt, primary_key=True)
    channel_id = db.Column(db.BigInt)
    threshold = db.Column(db.Integer, default=1)
    locked = db.Column(db.Boolean, default=False)
    max_age = db.Column(db.Interval, default="'7 days'::interval")


class StarboardEntry(db.Table, table_name='starboard_entries'):
    id = db.Column(db.Serial, primary_key=True)
    bot_message_id = db.Column(db.BigInt, nullable=True)
    message_id = db.Column(db.BigInt, unique=True)
    channel_id = db.Column(db.BigInt)
    author_id = db.Column(db.BigInt)
    guild_id = db.ForeignKey(Starboard.id, type=db.BigInt)

    # There is some fuckery with ForeignKeys that I don't want to fix rn. They must be referenced as strings.
    starboard_entries_index = db.Index(bot_message_id, message_id, 'guild_id')


class Starrers(db.Table):
    id = db.Column(db.Serial, primary_key=True)
    author_id = db.Column(db.BigInt)
    entry_id = db.ForeignKey(StarboardEntry.id, type=db.BigInt)

    starrers_index = db.Index(author_id, 'entry_id', unique=True)


class StarBoardConfig:
    __slots__ = ('bot', 'id', 'channel_id', 'threshold', 'locked', 'needs_migration', 'max_age')

    def __init__(self, *, guild_id, bot, record=None):
        self.id = guild_id
        self.bot = bot

        if record:
            self.channel_id = record['channel_id']
            self.threshold = record['threshold']
            self.locked = record['locked']
            self.needs_migration = self.locked is None
            if self.needs_migration:
                self.locked = True

            self.max_age = record['max_age']
        else:
            self.channel_id = None

    @property
    def channel(self):
        guild = self.bot.get_guild(self.id)
        return guild and guild.get_channel(self.channel_id)


class StarBoard:
    def __init__(self, bot):
        self.bot = bot

        # To save Discord some HTTP requests
        self._message_cache = {}
        self._cleaner = self.bot.loop.create_task(self.clean_message_cache())

        self._about_to_be_deleted = set()
        self._locks = weakref.WeakValueDictionary()

    def __unload(self):
        self._cleaner.cancel()

    async def __error(self, ctx, error):
        if isinstance(error, StarBoardError):
            await ctx.send(error)

    async def clean_message_cache(self):
        try:
            while not self.bot.is_closed():
                self._message_cache.clear()
                await asyncio.sleep(3600)

        except asyncio.CancelledError:
            pass

    @cache.cache(max_size=None)
    async def get_starboard(self, guild_id, *, connection=None):
        connection = connection or self.bot.pool

        query = 'SELECT * FROM starboard WHERE id = $1;'
        record = await connection.fetchrow(query, guild_id)

        return StarBoardConfig(guild_id=guild_id, bot=self.bot, record=record)

    @staticmethod
    def star_emoji(stars):
        if 5 > stars >= 0:
            return '\N{WHITE MEDIUM STAR}'
        elif 10 > stars >= 5:
            return '\N{GLOWING STAR}'
        elif 25 > stars >= 10:
            return '\N{DIZZY SYMBOL}'
        else:
            return '\N{SPARKLES}'

    @staticmethod
    def star_gradient_color(stars):
        percentage = stars / 13
        if percentage > 1.0:
            percentage = 1.0

        red = 255
        green = int((194 * percentage) + (253 * (1 - percentage)))
        blue = int((12 * percentage) + (247 * (1 - percentage)))
        return (red << 16) + (green << 8) + blue

    def get_emoji_message(self, message, stars):
        emoji = self.star_emoji(stars)

        if stars > 1:
            content = f'{emoji} **{stars}** {message.channel.mention} ID: {message.id}'
        else:
            content = f'{emoji} {message.channel.mention} ID: {message.id}'

        embed = discord.Embed(title='Jump to message', description=message.content, url=message.jump_url)
        if message.embeds:
            data = message.embeds[0]
            if data.type == 'image':
                embed.set_image(url=data.url)

        if message.attachments:
            file = message.attachments[0]
            if file.url.lower().endswith(('png', 'jpg', 'jpeg', 'gif', 'webp')):
                embed.set_image(url=file.url)
            else:
                embed.add_field(name='Attachment:', value=f'[{file.filename}]({file.url})', inline=False)

        embed.set_author(name=message.author.display_name, icon_url=message.author.avatar_url_as(format='png'))
        embed.timestamp = message.created_at
        embed.colour = self.star_gradient_color(stars)

        return content, embed

    async def get_message(self, channel, message_id):
        try:
            return self._message_cache[message_id]
        except KeyError:
            try:
                fake = discord.Object(message_id + 1)
                msg = await channel.history(limit=1, before=fake).next()

                if msg.id != message_id:
                    return None

                self._message_cache[message_id] = msg
                return msg

            except Exception:  # muh pycodestyle
                return None

    async def reaction_action(self, fmt, payload):
        if str(payload.emoji) != '\N{WHITE MEDIUM STAR}':
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        method = getattr(self, f'{fmt}_message')

        user = self.bot.get_user(payload.user_id)
        if not user or user.bot:
            return

        async with self.bot.pool.acquire() as con:
            query = 'SELECT snowflake FROM blacklist WHERE snowflake = $1;'
            result = await con.fetchrow(query, channel.guild.id)
            if result:
                return

            try:
                await method(channel, payload.message_id, payload.user_id, connection=con)
            except StarBoardError:
                pass

    async def on_guild_channel_delete(self, channel):
        if not isinstance(channel, discord.TextChannel):
            return

        starboard = await self.get_starboard(channel.guild.id)
        if not starboard.channel or starboard.channel.id != channel.id:
            return

        async with self.bot.pool.acquire() as con:
            query = 'DELETE FROM starboard WHERE id = $1;'
            await con.execute(query, channel.guild.id)

    async def on_raw_reaction_add(self, payload):
        await self.reaction_action('star', payload)

    async def on_raw_reaction_remove(self, payload):
        await self.reaction_action('unstar', payload)

    async def on_raw_message_delete(self, payload):
        if payload.message_id in self._about_to_be_deleted:
            self._about_to_be_deleted.discard(payload.message_id)
            return

        starboard = await self.get_starboard(payload.guild_id)
        if not starboard.channel or starboard.channel.id != payload.channel_id:
            return

        async with self.bot.pool.acquire() as con:
            query = 'DELETE FROM starboard_entries WHERE bot_message_id = $1;'
            await con.execute(query, list(payload.message_id))

    async def on_raw_bulk_message_delete(self, payload):
        if payload.message_ids <= self._about_to_be_deleted:
            self._about_to_be_deleted.difference_update(payload.message_ids)
            return

        starboard = await self.get_starboard(payload.guild_id)
        if not starboard.channel or starboard.channel.id != payload.channel_id:
            return

        async with self.bot.pool.acquire() as con:
            query = 'DELETE FROM starboard_entries WHERE bot_message_id = ANY($1::BIGINT[]);'
            await con.execute(query, list(payload.message_ids))

    async def on_raw_reaction_clear(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        async with self.bot.pool.acquire() as con:
            starboard = await self.get_starboard(channel.guild.id, connection=con)
            if not starboard.channel:
                return

            query = 'DELETE FROM starboard_entries WHERE message_id = $1 RETURNING bot_message_id;'
            bot_message_id = await con.fetchrow(query, payload.message_id)

            if not bot_message_id:
                return

            bot_message_id = bot_message_id[0]
            msg = await self.get_message(starboard.channel, bot_message_id)
            if msg:
                await msg.delete()

    async def star_message(self, channel, message_id, starrer_id, *, connection):
        guild_id = channel.guild.id
        lock = self._locks.get(guild_id)
        if not lock:
            self._locks[guild_id] = lock = asyncio.Lock(loop=self.bot.loop)

        async with lock:
            await self._star_message(channel, message_id, starrer_id, connection=connection)

    async def _star_message(self, channel, message_id, starrer_id, *, connection):
        """Stars a message."""

        guild_id = channel.guild.id
        starboard = await self.get_starboard(guild_id)
        if not starboard.channel:
            raise StarBoardError('\N{WARNING SIGN} Starboard channel not found.')

        if starboard.locked:
            raise StarBoardError('\N{WARNING SIGN} Starboard is locked.')

        if channel.id == starboard.channel.id:
            query = 'SELECT channel_id, message_id FROM starboard_entries WHERE bot_message_id = $1;'
            record = await connection.fetchrow(query, message_id)
            if not record:
                raise StarBoardError('Couldn\'t find message in the starboard.')

            ch = channel.guild.get_channel(record['channel_id'])
            if not ch:
                raise StarBoardError('Couldn\'t find original channel.')

            return await self._star_message(ch, record['message_id'], starrer_id, connection=connection)

        msg = await self.get_message(channel, message_id)
        if not msg:
            raise StarBoardError('\N{BLACK QUESTION MARK ORNAMENT} This message couldn\'t be found.')

        if msg.author.id == starrer_id:
            raise StarBoardError('\N{NO ENTRY SIGN} You cannot star your own message.')

        if (len(msg.content) == 0 and len(msg.attachments) == 0) or msg.type is not discord.MessageType.default:
            raise StarBoardError('\N{NO ENTRY SIGN} This message cannot be starred.')

        oldest_allowed = datetime.datetime.utcnow() - starboard.max_age
        if msg.created_at < oldest_allowed:
            raise StarBoardError('\N{NO ENTRY SIGN} This message is too old.')

        # Ew shit. Fuckery incoming
        query = """
            WITH to_insert AS (
                INSERT INTO starboard_entries AS entries (message_id, channel_id, guild_id, author_id)
                VALUES      ($1, $2, $3, $4)
                ON CONFLICT (message_id)
                DO NOTHING
                RETURNING   entries.id
            )
            INSERT INTO starrers (author_id, entry_id)
            SELECT      $5, entry.id
            FROM (
                SELECT    id
                FROM      to_insert
                UNION ALL
                SELECT    id
                FROM      starboard_entries
                WHERE     message_id = $1
                LIMIT     1
            ) AS entry
            RETURNING entry_id;
        """
        try:
            record = await connection.fetchrow(query, message_id, channel.id, guild_id, msg.author.id, starrer_id)
        except asyncpg.UniqueViolationError:
            raise StarBoardError('\N{NO ENTRY SIGN} You already starred this message.')

        entry_id = record[0]

        query = 'SELECT COUNT(*) FROM starrers WHERE entry_id = $1;'
        record = await connection.fetchrow(query, entry_id)

        count = record[0]
        if count < starboard.threshold:
            return

        content, embed = self.get_emoji_message(msg, count)

        query = 'SELECT bot_message_id FROM starboard_entries WHERE message_id = $1;'
        record = await connection.fetchrow(query, message_id)
        bot_message_id = record[0]

        if not bot_message_id:
            new_msg = await starboard.channel.send(content, embed=embed)
            query = 'UPDATE starboard_entries SET bot_message_id = $1 WHERE message_id = $2;'
            await connection.execute(query, new_msg.id, message_id)
        else:
            new_msg = await self.get_message(starboard.channel, bot_message_id)
            if not new_msg:
                query = 'DELETE FROM starboard_entries WHERE message_id = $1;'
                await connection.execute(query, message_id)
            else:
                await new_msg.edit(content=content, embed=embed)

    async def unstar_message(self, channel, message_id, starrer_id, *, connection):
        guild_id = channel.guild.id
        lock = self._locks.get(guild_id)
        if not lock:
            self._locks[guild_id] = lock = asyncio.Lock(loop=self.bot.loop)

        async with lock:
            await self._unstar_message(channel, message_id, starrer_id, connection=connection)

    async def _unstar_message(self, channel, message_id, starrer_id, *, connection):
        """Unstars a message."""

        guild_id = channel.guild.id
        starboard = await self.get_starboard(guild_id)
        if not starboard.channel:
            raise StarBoardError('\N{WARNING SIGN} Starboard channel not found.')

        if starboard.locked:
            raise StarBoardError('\N{NO ENTRY SIGN} Starboard is locked.')

        if channel.id == starboard.channel.id:
            query = 'SELECT channel_id, message_id FROM starboard_entries WHERE bot_message_id = $1;'
            record = await connection.fetchrow(query, message_id)
            if not record:
                raise StarBoardError('Couldn\'t find message in the starboard.')

            ch = channel.guild.get_channel(record['channel_id'])
            if not ch:
                raise StarBoardError('Couldn\'t find original message.')

            return await self._unstar_message(ch, record['message_id'], starrer_id, connection=connection)

        query = """
            DELETE FROM starrers
            USING       starboard_entries entry
            WHERE       entry.message_id = $1
            AND         entry.id = starrers.entry_id
            AND         starrers.author_id = $2
            RETURNING   starrers.entry_id, entry.bot_message_id;
        """
        record = await connection.fetchrow(query, message_id, starrer_id)
        if not record:
            raise StarBoardError('\N{NO ENTRY SIGN} You haven\'t starred this message.')

        entry_id = record[0]
        bot_message_id = record[1]

        query = 'SELECT COUNT(*) FROM starrers WHERE entry_id = $1;'
        count = await connection.fetchrow(query, entry_id)
        count = count[0]

        if count == 0:
            query = 'DELETE FROM starboard_entries WHERE id = $1;'
            await connection.execute(query, entry_id)

        if not bot_message_id:
            return

        bot_message = await self.get_message(starboard.channel, bot_message_id)
        if not bot_message:
            return

        if count < starboard.threshold:
            self._about_to_be_deleted.add(bot_message_id)
            if count:
                query = 'UPDATE starboard_entries SET bot_message_id = NULL WHERE id = $1;'
                await connection.execute(query, entry_id)

            await bot_message.delete()
        else:
            msg = await self.get_message(channel, message_id)
            if not msg:
                raise StarBoardError('\N{BLACK QUESTION MARK ORNAMENT} This message couldn\'t be found.')

            content, embed = self.get_emoji_message(msg, count)
            await bot_message.edit(content=content, embed=embed)

    @commands.command(name='starboard')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def _starboard(self, ctx, *, name_or_channel: typing.Union[discord.TextChannel, str] = 'starboard'):
        """Sets up the starboard for this server.

        You can either reference an existing channel by mentioning it like `{prefix}starboard #channel`.
        This will make a starboard out of an already existing channel.

        If you want a new channel, you can provide a name like `{prefix}starboard shitcode`.
        In that case, the bot will create a new channel called `shitcode` which will be the starboard channel.
        *(Assuming there is no such channel with that name)*

        Or just use `{prefix}starboard`. This will create a channel called starboard.
        """

        self.get_starboard.invalidate(self, ctx.guild.id)

        starboard = await self.get_starboard(ctx.guild.id, connection=ctx.db)
        if starboard.channel:
            return await ctx.send(f'This server already has a starboard ({starboard.channel.mention}).')

        if hasattr(starboard, 'locked'):
            try:
                confirm = await ctx.confirm('Apparently, a previously configured starboard channel was deleted. Is this true?')
            except RuntimeError as e:
                await ctx.send(e)
            else:
                if confirm:
                    await ctx.db.execute('DELETE FROM starboard WHERE id = $1;', ctx.guild.id)
                else:
                    return await ctx.send(f'Aborting starboard creation. DM {self.bot.creator} for more information.')

        overwrites = {
            ctx.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True,
                                                embed_links=True, read_message_history=True),
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False,
                                                                read_message_history=True)
        }

        reason = f'{ctx.author} (ID: {ctx.author.id}) has created the starboard channel.'

        try:
            if isinstance(name_or_channel, discord.TextChannel):
                for target, ow in overwrites.items():
                    await name_or_channel.set_permissions(target, overwrite=ow, reason=reason)

            elif isinstance(name_or_channel, str):
                name_or_channel = await ctx.guild.create_text_channel(name=name_or_channel, overwrites=overwrites, reason=reason)

        except discord.Forbidden:
            return await ctx.send('\N{NO ENTRY SIGN} I do not have permissions to create a channel.')
        except discord.HTTPException:
            return await ctx.send('\N{NO ENTRY SIGN} This channel name is bad or an unknown error happened. No idea.')

        query = 'INSERT INTO starboard (id, channel_id) VALUES ($1, $2);'
        try:
            await ctx.db.execute(query, ctx.guild.id, name_or_channel.id)
        except Exception:  # muh pycodestyle
            await name_or_channel.delete(reason='Failure on creating the starboard.')
            await ctx.send(f'Could not create starboard due to an internal error. DM {self.bot.creator} for more information.')
        else:
            self.get_starboard.invalidate(self, ctx.guild.id)
            await ctx.send(f'\N{GLOWING STAR} Starboard created at {name_or_channel.mention}.')

    @commands.group(name='star', invoke_without_command=True, ignore_extra=False)
    @commands.guild_only()
    async def _star(self, ctx, message: MessageID):
        """Stars a message via message ID.

        To star a message, right click on the message and use the option `Copy ID`.
        You must have Developer Mode enabled to get that functionality.

        Though it's recommended that you react to a message with \N{WHITE MEDIUM STAR} instead.

        You can only star a message once.
        """

        await self.star_message(ctx.channel, message, ctx.author.id, connection=ctx.db)
        await ctx.message.delete()

    @commands.command(name='unstar')
    @commands.guild_only()
    async def _unstar(self, ctx, message: MessageID):
        """Unstars a message via message ID.

        To unstar a message, right click on the message and use the option `Copy ID`.
        You must have Developer Mode enabled to get that functionality.
        """

        await self.unstar_message(ctx.channel, message, ctx.author.id, connection=ctx.db)
        await ctx.message.delete()

    @_star.command(name='clean')
    @commands.has_permissions(manage_guild=True)
    @requires_starboard()
    async def _star_clean(self, ctx, stars=1):
        """Cleans the starboard.

        This removes messages in the starboard that only have less than or equal to the number of specified stars.
        This defaults to 1.

        *This only checks the last 100 messages in the starboard.*

        **This command requires the Manage Server permission.**
        """

        stars = max(stars, 1)
        channel = ctx.starboard.channel

        last_messages = await channel.history(limit=100).map(lambda m: m.id).flatten()

        query = """
            WITH bad_entries AS (
                SELECT     entry_id
                FROM       starrers
                INNER JOIN starboard_entries
                ON         starboard_entries.id = starrers.entry_id
                WHERE      starboard_entries.guild_id = $1
                AND        starboard_entries.bot_message_id = ANY($2::BIGINT[])
                GROUP BY   entry_id
                HAVING     COUNT(*) <= $3
            )
            DELETE FROM starboard_entries USING bad_entries
            WHERE       starboard_entries.id = bad_entries.entry_id
            RETURNING   starboard_entries.bot_message_id;
        """

        to_delete = await ctx.db.fetch(query, ctx.guild.id, last_messages, stars)

        min_snowflake = int((time.time() - 14 * 24 * 60 * 60) * 1000.0 - 1420070400000) << 22
        to_delete = [discord.Object(r[0]) for r in to_delete if r[0] > min_snowflake]

        try:
            self._about_to_be_deleted.update(o.id for o in to_delete)
            await channel.delete_messages(to_delete)
        except discord.HTTPException:
            await ctx.send('Could not delete the messages.')
        else:
            await ctx.send(f'\N{PUT LITTER IN ITS PLACE SYMBOL} Deleted {pluralize(**{"message": len(to_delete)})}.')

    @_star.command(name='show')
    @requires_starboard()
    @commands.cooldown(1, 10.0, commands.BucketType.user)
    async def _star_show(self, ctx, message: MessageID):
        """Shows the starred message via its ID.

        To get the ID of a message, right click on the message and use the option `Copy ID`.
        You must have Developer Mode enabled to get that functionality.

        You can only use this command once per 10 seconds.
        """

        query = """
            SELECT     entry.channel_id,
                       entry.message_id,
                       entry.bot_message_id,
                       COUNT(*) OVER(PARTITION BY entry_id) AS "Stars"
            FROM       starrers
            INNER JOIN starboard_entries entry
            ON         entry.id = starrers.id
            WHERE      entry.guild_id = $1
            AND        (entry.message_id = $2 OR entry.bot_message_id = $2)
            LIMIT      1;
        """

        record = await ctx.db.fetchrow(query, ctx.guild.id, message)
        if not record:
            return await ctx.send('This message hasn\'t been starred.')

        bot_message_id = record['bot_message_id']
        if bot_message_id is not None:
            msg = await self.get_message(ctx.starboard.channel, bot_message_id)
            if msg:
                embed = msg.embeds[0] if msg.embeds else None
                return await ctx.send(msg.content, embed=embed)
            else:
                query = 'DELETE FROM starboard_entries WHERE message_id = $1;'
                await ctx.db.execute(query, record['message_id'])
                return

        channel = ctx.guild.get_channel(record['channel_id'])
        if not channel:
            return await ctx.send('The message\'s channel has been deleted.')

        msg = await self.get_message(channel, record['message_id'])
        if not msg:
            return await ctx.send('The message has been deleted.')

        content, embed = self.get_emoji_message(msg, record['Stars'])
        await ctx.send(content, embed=embed)

    @_star.command(name='who')
    @requires_starboard()
    async def _star_who(self, ctx, message: MessageID):
        """Shows who starred a message.

        The ID can either be the starred message ID or the message ID in the starboard channel.
        """

        query = """
            SELECT     starrers.author_id
            FROM       starrers
            INNER JOIN starboard_entries entry
            ON         entry.id = starrers.entry_id
            WHERE      entry.message_id = $1
            OR         entry.bot_message_id = $1;
        """
        records = await ctx.db.fetch(query, message)
        if not records:
            return await ctx.send('No one starred this message or you provided an invalid message ID.')

        members = [
            str(ctx.guild.get_member(r[0]))
            for r in records
            if ctx.guild.get_member(r[0])
        ]

        try:
            base = pluralize(**{'star': len(records)})
            if len(records) > len(members):
                title = f'{base} ({len(records) - len(members)} left server)'
            else:
                title = base

            pages = Paginator(ctx, entries=members, per_page=20, title=title)
            await pages.interact()
        except Exception as e:
            await ctx.send(e)

    @_star.command(name='migrate')
    @requires_starboard()
    async def _star_migrate(self, ctx):
        """Migrates the starboard to the newest version.

        If you don't do this, the starboard will be locked for you until you do so.

        __**Please note that this is an incredibly expensive operation! It will take a very long time!**__

        You must have the Manage Server permission to use this command.
        """

        if not ctx.starboard.needs_migration:
            return await ctx.send('You are already migrated.')

        _avatar_id = re.compile(r'\/avatars\/(?P<id>[0-9]{15,})')
        start = time.time()

        perms = ctx.starboard.channel.permissions_for(ctx.me)
        if not perms.read_message_history:
            return await ctx.send(f'Bot does not have Read Message History permissions in {ctx.starboard.channel.mention}.')

        await ctx.send('Please be patient, this is going to take a long time!')
        async with ctx.typing():
            channel = ctx.starboard.channel

            # As this will take a while..
            await ctx.release()

            current_messages = await channel.history(limit=None).filter(lambda m: m.channel_mentions).flatten()

            message_ids = [m.id for m in current_messages]
            channel_ids = [m.raw_channel_mentions[0] for m in current_messages]

            await ctx.acquire()
            query = 'DELETE FROM starboard_entries WHERE guild_id = $1 AND NOT (bot_message_id = ANY($2::BIGINT[]));'
            status = await ctx.db.execute(query, ctx.guild.id, message_ids)

            _, _, deleted = status.partition(' ')
            deleted = int(deleted)

            # Get the up-to-date resolution of bot_message_id -> message_id
            query = 'SELECT bot_message_id, message_id FROM starboard_entries WHERE guild_id = $1;'
            records = await ctx.db.fetch(query, ctx.guild.id)
            records = dict(records)

            author_ids = []

            needs_requests = collections.defaultdict(list)

            # Just ignore this gore here
            for index, message in enumerate(current_messages):
                if message.embeds:
                    icon_url = message.embeds[0].author.icon_url
                    if icon_url:
                        match = _avatar_id.search(icon_url)
                        if match:
                            author_ids.append(int(match.group('id')))
                            continue

                author_ids.append(None)
                message_id = records.get(message.id)
                if message_id:
                    needs_requests[channel_ids[index]].append(message_id)

            query = """
                UPDATE starboard_entries
                SET    channel_id = t.channel_id, author_id = t.author_id
                FROM   UNNEST($1::BIGINT[], $2::BIGINT[], $3::BIGINT[])
                AS     t(channel_id, message_id, author_id)
                WHERE  starboard_entries.guild_id = $4
                AND    starboard_entries.bot_message_id = t.message_id;
            """
            status = await ctx.db.execute(query, channel_ids, message_ids, author_ids, ctx.guild.id)
            _, _, updated = status.partition(' ')
            updated = int(updated)
            await ctx.release()

            needed_requests = sum(len(a) for a in needs_requests.values())
            bad_data = 0

            async def send_confirmation():
                """Sends the confirmation messages."""

                delta = time.time() - start

                await ctx.acquire()
                query = 'UPDATE starboard SET locked = FALSE WHERE id = $1;'
                await ctx.db.execute(query, ctx.guild.id)
                self.get_starboard.invalidate(self, ctx.guild.id)

                if ctx.bot_has_embed_links():
                    embed = (discord.Embed(title='Starboard Migration', color=discord.Color.gold())
                             .add_field(name='Deleted:', value=deleted)
                             .add_field(name='Updated:', value=updated)
                             .add_field(name='Requests:', value=needed_requests)

                             .add_field(name='Name:', value=ctx.guild.name)
                             .add_field(name='ID:', value=ctx.guild.id)
                             .add_field(name='Owner:', value=f'{ctx.guild.owner} (ID: {ctx.guild.owner.id})', inline=False)
                             .add_field(name='Failed Updates:', value=bad_data)
                             .set_footer(text=f'Took {delta:.2f}s to migrate.'))
                    await ctx.send(embed=embed)

                else:
                    await ctx.send(
                        f'{ctx.author.mention}, I\'m done migrating!\n'
                        f'Deleted {deleted} out of date entries.\n'
                        f'Updated {updated} entries to the new format ({bad_data} failures).'
                        f'Took {delta:.2f}s.'
                    )

            if needed_requests == 0:
                await send_confirmation()
                return

            me = ctx.guild.me

            data_to_pass = {}
            for channel_id, messages in needs_requests.items():
                channel = ctx.guild.get_channel(channel_id)
                if not channel:
                    needed_requests -= len(messages)
                    bad_data += len(messages)
                    continue

                perms = channel.permissions_for(me)
                if not (perms.read_message_history and perms.read_messages):
                    needed_requests -= len(messages)
                    bad_data += len(messages)
                    continue

                for message_id in sorted(messages):
                    msg = await self.get_message(channel, message_id)
                    if msg:
                        data_to_pass[message_id] = msg.author.id
                    else:
                        bad_data += 1

            query = """
                UPDATE starboard_entries
                SET    author_id = t.author_id
                FROM   UNNEST($1::BIGINT[], $2::BIGINT[])
                AS     t(message_id, author_id)
                WHERE  starboard_entries.message_id = t.message_id;
            """

            await ctx.acquire()
            status = await ctx.db.execute(query, list(data_to_pass.keys()), list(data_to_pass.values()))
            _, _, second_update = status.partition(' ')
            updated += int(second_update)
            updated = min(updated, len(current_messages))

            # Fuck yeah, it's finally over
            await ctx.release()
            await send_confirmation()

    @staticmethod
    def records_to_value(records, fmt=None, default='None!'):
        if not records:
            return default

        emoji = 0x1f947
        fmt = fmt or (lambda o: o)
        return '\n'.join(f'{chr(emoji + i)}: {fmt(r["ID"])} ({pluralize(**{"star": r["Stars"]})})' for i, r in enumerate(records))

    async def star_guild_stats(self, ctx):
        embed = discord.Embed(title='Starboard Server Stats', color=discord.Color.gold())
        embed.timestamp = ctx.starboard.channel.created_at
        embed.set_footer(text='Adding stars since')

        # messages starred
        query = 'SELECT COUNT(*) FROM starboard_entries WHERE guild_id = $1;'

        record = await ctx.db.fetchrow(query, ctx.guild.id)
        total_messages = record[0]

        # total stars given
        query = """
            SELECT     COUNT(*)
            FROM       starrers
            INNER JOIN starboard_entries entry
            ON         entry.id = starrers.entry_id
            WHERE      entry.guild_id = $1;
        """

        record = await ctx.db.fetchrow(query, ctx.guild.id)
        total_stars = record[0]

        embed.description = f'{pluralize(**{"message": total_messages})} starred with a total of {total_stars} stars.'

        # Why am I doing this to myself?
        query = """
            WITH t AS (
                SELECT
                    entry.author_id AS entry_author_id,
                    starrers.author_id,
                    entry.bot_message_id
                FROM       starrers
                INNER JOIN starboard_entries entry
                ON         entry.id = starrers.entry_id
                WHERE      entry.guild_id = $1
            )
            (
                SELECT     t.entry_author_id AS "ID", 1 AS "Type", COUNT(*) AS "Stars"
                FROM       t
                WHERE      t.entry_author_id IS NOT NULL
                GROUP BY   t.entry_author_id
                ORDER BY   "Stars"
                DESC LIMIT 3
            )
            UNION ALL
            (
                SELECT     t.author_id AS "ID", 2 AS "Type", COUNT(*) AS "Stars"
                FROM       t
                GROUP BY   t.author_id
                ORDER BY   "Stars"
                DESC LIMIT 3
            )
            UNION ALL
            (
                SELECT     t.bot_message_id AS "ID", 3 AS "Type", COUNT(*) AS "Stars"
                FROM       t
                WHERE      t.bot_message_id IS NOT NULL
                GROUP BY   t.bot_message_id
                ORDER BY   "Stars"
                DESC LIMIT 3
            );
        """

        records = await ctx.db.fetch(query, ctx.guild.id)
        starred_posts = [r for r in records if r['Type'] == 3]
        embed.add_field(name='Top Starred Posts:', value=self.records_to_value(starred_posts), inline=False)

        to_mention = lambda o: f'<@{o}>'

        star_receivers = [r for r in records if r['Type'] == 1]
        value = self.records_to_value(star_receivers, to_mention, default='No one!')
        embed.add_field(name='Top Star Receivers:', value=value, inline=False)

        star_givers = [r for r in records if r['Type'] == 2]
        value = self.records_to_value(star_givers, to_mention, default='No one!')
        embed.add_field(name='Top Star Givers:', value=value, inline=False)

        await ctx.send(embed=embed)

    async def star_member_stats(self, ctx, member):
        embed = (discord.Embed(color=discord.Color.gold())
                 .set_author(name=member.display_name, icon_url=member.avatar_url_as(format='png')))

        query = """
            WITH t AS (
                SELECT
                    entry.author_id AS entry_author_id,
                    starrers.author_id,
                    entry.message_id
                FROM       starrers
                INNER JOIN starboard_entries entry
                ON         entry.id = starrers.entry_id
                WHERE      entry.guild_id = $1
            )
            (
                SELECT     '0'::BIGINT AS "ID", COUNT(*) AS "Stars"
                FROM       t
                WHERE      t.entry_author_id = $2
            )
            UNION ALL
            (
                SELECT     '0'::BIGINT AS "ID", COUNT(*) AS "Stars"
                FROM       t
                WHERE      t.author_id = $2
            )
            UNION ALL
            (
                SELECT     t.message_id AS "ID", COUNT(*) AS "Stars"
                FROM       t
                WHERE      t.entry_author_id = $2
                GROUP BY   t.message_id
                ORDER BY   "Stars"
                DESC LIMIT 3
            );
        """

        records = await ctx.db.fetch(query, ctx.guild.id, member.id)
        received = records[0]['Stars']
        given = records[1]['Stars']
        top_three = records[2:]

        query = 'SELECT COUNT(*) FROM starboard_entries WHERE guild_id = $1 AND author_id = $2;'
        record = await ctx.db.fetchrow(query, ctx.guild.id, member.id)
        messages_starred = record[0]

        embed.add_field(name='Messages Starred:', value=messages_starred)
        embed.add_field(name='Stars Received:', value=received)
        embed.add_field(name='Stars given:', value=given)

        embed.add_field(name='Top Starred Posts:', value=self.records_to_value(top_three), inline=False)

        await ctx.send(embed=embed)

    @_star.command(name='stats')
    @requires_starboard()
    async def _star_stats(self, ctx, *, member: discord.Member = None):
        """Shows statistics on the starboard usage of the server or a member."""

        if not member:
            await self.star_guild_stats(ctx)
        else:
            await self.star_member_stats(ctx, member)

    @_star.command(name='random')
    @requires_starboard()
    async def _star_random(self, ctx):
        """Shows a random starred message."""

        query = """
            SELECT bot_message_id
            FROM   starboard_entries
            WHERE  guild_id = $1
            AND    bot_message_id IS NOT NULL
            OFFSET FLOOR(RANDOM() * (
                SELECT COUNT(*)
                FROM   starboard_entries
                WHERE  guild_id = $1
                AND    bot_message_id IS NOT NULL
            ))
            LIMIT  1;
        """

        record = await ctx.db.fetchrow(query, ctx.guild.id)
        if not record:
            return await ctx.send('Couldn\'t find anything.')

        message_id = record[0]
        message = await self.get_message(ctx.starboard.channel, message_id)
        if not message:
            return await ctx.send(f'Message {message_id} has been deleted somehow.')

        if message.embeds:
            await ctx.send(message.content, embed=message.embeds[0])
        else:
            await ctx.send(message.content)

    @_star.command(name='lock')
    @commands.has_permissions(manage_guild=True)
    @requires_starboard()
    async def _star_lock(self, ctx):
        """Locks the starboard from being processed.

        This is a moderation tool that allows you to temporarily disable the starboard to aid in dealing with star spam.

        When the starboard is locked, no new entries are added to the starboard
        as the bot will no longer listen to reactions or star/unstar commands.

        To unlock the starboard, use the unlock command.

        To use this command, you need the Manage Server permission.
        """

        if ctx.starboard.needs_migration:
            return await ctx.send('Your starboard requires migration.')

        query = 'UPDATE starboard SET locked = TRUE WHERE id = $1;'
        await ctx.db.execute(query, ctx.guild.id)
        self.get_starboard.invalidate(self, ctx.guild.id)

        await ctx.send('Starboard is now locked.')

    @_star.command(name='unlock')
    @commands.has_permissions(manage_guild=True)
    @requires_starboard()
    async def _star_unlock(self, ctx):
        """Unlocks the starboard for re-processing.

        To use this command, you need the Manage Server permission.
        """

        if ctx.starboard.needs_migration:
            return await ctx.send('Your starboard requires migration.')

        query = 'UPDATE starboard SET locked = FALSE WHERE id = $1;'
        await ctx.db.execute(query, ctx.guild.id)
        self.get_starboard.invalidate(self, ctx.guild.id)

        await ctx.send('Starboard is now unlocked.')

    @_star.command(name='limit')
    @commands.has_permissions(manage_guild=True)
    @requires_starboard()
    async def _star_limit(self, ctx, stars: int):
        """Sets the minimum number of stars required to show up.

        When this limit is set, messages must have this number or more stars to show up in the starboard.

        You cannot have a negative limit and the maximum star limit you can set is 30.

        Note that messages that previously didn't meet the limit but now do will still not show up in the starboard until starred again.

        You must have the Manage Server permission to use this command.
        """

        if ctx.starboard.needs_migration:
            return await ctx.send('You starboard requires migration.')

        stars = min(max(stars, 1), 25)
        query = 'UPDATE starboard SET threshold = $2 WHERE id = $1;'
        await ctx.db.execute(query, ctx.guild.id, stars)
        self.get_starboard.invalidate(self, ctx.guild.id)

        await ctx.send(f'Messages now require {pluralize(**{"star": stars})} to show up in the starboard.')

    @_star.command(name='age')
    @commands.has_permissions(manage_guild=True)
    @requires_starboard()
    async def _star_age(self, ctx, number: int, units='days'):
        """Sets the maximum age of a message valid for starring.

        By default, the maximum age is 7 days.
        Any message older than this specified age is invalid of being starred.

        To set the limit, you must specify a number followed by a unit.
        The valid units are "days", "weeks", "months", or "years". They do not have to be pluralized.
        The default unit is "days".

        The number cannot be negative, and it must be a maximum of 35.
        If the unit is years, then the cap is 10 years.

        You cannot mix and match units.

        You must have the Manage Server permission to use this command.
        """

        valid_units = ('days', 'weeks', 'months', 'years')

        if units[-1] != 's':
            units = units + 's'

        if units not in valid_units:
            return await ctx.send(f'Not a valid unit! I expect only {human_join(valid_units)}.')

        number = min(max(number, 1), 35)

        if units == 'years' and number > 10:
            return await ctx.send('The maximum is 10 years!')

        query = f"UPDATE starboard SET max_age = '{number} {units}'::INTERVAL WHERE id = $1;"
        await ctx.db.execute(query, ctx.guild.id)
        self.get_starboard.invalidate(self, ctx.guild.id)

        if number == 1:
            age = f'1 {units[:-1]}'
        else:
            age = f'{number} {units}'

        await ctx.send(f'Messages must be less than {age} old to be starred.')

    @_star.command(name='jump')
    @requires_starboard()
    async def _star_jump(self, ctx, message: MessageID):
        """Shows a link to jump to a starred message given its ID.

        The ID can either be the starred message or the message in the starboard channel.
        """

        query = """
            SELECT
                entry.channel_id,
                entry.message_id
            FROM       starrers
            INNER JOIN starboard_entries entry
            ON         entry.id = starrers.entry_id
            WHERE      entry.guild_id = $1
            AND        (entry.message_id = $2 OR entry.bot_message_id = $2)
            LIMIT      1;
        """

        record = await ctx.db.fetchrow(query, ctx.guild.id, message)
        if not record:
            return await ctx.send('This message hasn\'t been starred.')

        await ctx.send(f'https://discordapp.com/channels/{ctx.guild.id}/{record["channel_id"]}/{record["message_id"]}')

    @commands.command(name='star_announce', hidden=True)
    @commands.is_owner()
    async def _star_announce(self, ctx, *, message):
        """Announce something in every starboard."""

        query = 'SELECT id, channel_id FROM starboard;'
        records = await ctx.db.fetch(query)
        await ctx.release()

        to_send = []
        for guild_id, channel_id in records:
            guild = self.bot.get_guild(guild_id)
            if guild:
                channel = self.bot.get_channel(channel_id)

                if channel and channel.permissions_for(guild.me).send_messages:
                    to_send.append(channel)

        await ctx.send(f'Preparing to send to {len(to_send)} channels (out of {len(records)}).')

        success = 0
        for channel in to_send:
            try:
                await channel.send(message)
            except Exception:  # muh pycodestyle
                pass
            else:
                success += 1

        await ctx.send(f'Successfully sent to {success} channels (out of {len(to_send)}).')


def setup(bot):
    bot.add_cog(StarBoard(bot))
