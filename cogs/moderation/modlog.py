import asyncio
import collections
import contextlib
import enum
import json
import logging
import operator
import random
import re
from datetime import datetime, timedelta
from functools import partial, reduce

import discord
from discord.ext import commands

from utils import cache, db
from utils.colors import random_color
from utils.misc import emoji_url, truncate, unique
from utils.paginator import FieldPaginator
from utils.time import duration_units, parse_delta

logger = logging.getLogger(__name__)

ModAction = collections.namedtuple('ModAction', 'repr emoji color')

_mod_actions = {
    'warn'    : ModAction('warned', '\N{WARNING SIGN}', 0xFFF200),
    'mute'    : ModAction('muted', '\N{SPEAKER WITH CANCELLATION STROKE}', 0x161616),
    'kick'    : ModAction('kicked', '\N{MANS SHOE}', 0x42E5F4),
    'softban' : ModAction('soft banned', '\N{BIOHAZARD SIGN}', 0xFF3FAB),
    'tempban' : ModAction('temporarily banned', '\N{ALARM CLOCK}', 0xFF3F3F),
    'ban'     : ModAction('banned', '\N{HAMMER}', 0xFF0000),
    'unban'   : ModAction('unbanned', '\N{DOVE OF PEACE}', 0x59FF00),
    'hackban' : ModAction('prematurely banned', '\N{NO ENTRY}', 0x66008C),
    'massban' : ModAction('massbanned', '\N{NO ENTRY}', 0x8C0000),
}


class EnumConverter(enum.IntFlag):
    """Mixin used for converting enums."""

    @classmethod
    async def convert(cls, ctx, argument):
        try:
            return cls[argument.lower()]
        except KeyError:
            raise commands.BadArgument(f'{argument} is not a valid {ctx.__name__}')

    @classmethod
    def random_example(cls, ctx):
        return random.choice(list(cls)).name


ActionFlag = enum.IntFlag('ActionFlag', list(_mod_actions), type=EnumConverter)
_default_flags = (2 ** len(_mod_actions) - 1) & ~ActionFlag.hackban

for key, value in list(_mod_actions.items()):
    _mod_actions[f'auto-{key}'] = value._replace(repr=f'auto-{value.repr}')


class ModLogError(Exception):
    pass


class ModLogEntry(db.Table, table_name='modlog'):
    id = db.Column(db.Serial, primary_key=True)
    channel_id = db.Column(db.BigInt)
    message_id = db.Column(db.BigInt)
    guild_id = db.Column(db.BigInt)
    action = db.Column(db.String(length=16))
    mod_id = db.Column(db.BigInt)
    reason = db.Column(db.Text)
    extra = db.Column(db.Text)

    modlog_guild_id_index = db.Index(guild_id)


class ModLogTargets(db.Table, table_name='modlog_targets'):
    id = db.Column(db.Serial, primary_key=True)
    entry_id = db.ForeignKey(ModLogEntry.id)
    user_id = db.Column(db.BigInt)
    mod_id = db.Column(db.BigInt)


class ModLogConfig(db.Table, table_name='modlog_config'):
    guild_id = db.Column(db.BigInt, primary_key=True)
    channel_id = db.Column(db.BigInt, default=0)

    enabled = db.Column(db.Boolean, default=True)
    log_auto = db.Column(db.Boolean, default=True)
    dm_user = db.Column(db.Boolean, default=True)
    poll_audit_log = db.Column(db.Boolean, default=True)

    events = db.Column(db.Integer, default=_default_flags.value)


MASSBAN_THUMBNAIL = emoji_url('\N{NO ENTRY}')

fields = 'channel_id enabled, log_auto dm_user poll_audit_log events'
ModlogConfig = collections.namedtuple('ModlogConfig', fields)
del fields


def _is_mod_action(ctx):
    return ctx.command.qualified_name in _mod_actions


@cache.cache(max_size=512)
async def _get_message(channel, message_id):
    fake = discord.Object(message_id + 1)
    msg = await channel.history(limit=1, before=fake).next()

    if msg.id != message_id:
        return None

    return msg


@cache.cache(max_size=None, make_key=lambda a, kw: a[-1])
async def _get_number_of_cases(connection, guild_id):
    query = 'SELECT COUNT(*) FROM modlog WHERE guild_id = $1;'
    row = await connection.fetchrow(query, guild_id)
    return row['count']


class CaseNumber(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            num = int(argument)
        except ValueError:
            raise commands.BadArgument('You have to provide an actual number.')

        if num < 0:
            num_cases = await _get_number_of_cases(ctx.db, ctx.guild.id)
            if not num_cases:
                raise commands.BadArgument('There are no cases yet.')

            num += num_cases + 1
            if num < 0:
                raise commands.BadArgument('Wait....What?!')

        return num

    @staticmethod
    def random_example(ctx):
        return random.choice([-1, *range(1, 10)])


class ModLog:
    def __init__(self, bot):
        self.bot = bot
        self._cache_cleaner = asyncio.ensure_future(self._clean_cache())
        self._cache_locks = collections.defaultdict(asyncio.Event)
        self._cache = set()

    def __unload(self):
        self._cache_cleaner.cancel()

    async def _clean_cache(self):
        while True:
            await asyncio.sleep(60 * 20)
            _get_message.cache.clear()

    async def _get_case_config(self, guild_id, *, connection=None):
        connection = connection or self.bot.pool
        query = """
            SELECT channel_id, enabled, log_auto, dm_user, poll_audit_log, events
            FROM   modlog_config
            WHERE  guild_id = $1;
        """
        row = await connection.fetchrow(query, guild_id)
        return ModlogConfig(**row) if row else None

    async def _send_case(self, config, action, guild, mod, targets, reason, *, extra=None, auto=False, connection=None):
        if not (config and config.enabled and config.channel_id):
            return None

        if not config.events & ActionFlag[action]:
            return None

        if auto and not config.log_auto:
            return None

        channel = guild.get_channel(config.channel_id)
        if not channel:
            raise ModLogError(f'The channel ID you specified ({config.channel_id}) doesn\'t exist.')

        if auto:
            action = f'auto-{action}'

        connection = connection or self.bot.pool
        count = await _get_number_of_cases(connection, guild.id)

        embed = self._create_embed(count + 1, action, mod, targets, reason, extra)

        try:
            message = await channel.send(embed=embed)
        except discord.Forbidden:
            raise ModLogError(f'Unable to send messages to {channel.mention}. Check my perms please...')

        query = """
            INSERT INTO modlog (guild_id, channel_id, message_id, action, mod_id, reason, extra)
            VALUES      ($1, $2, $3, $4, $5, $6, $7::JSONB)
            RETURNING   id
        """

        if extra is not None:
            now = message.created_at
            delta = ((now + extra.delta) - now).total_seconds()  # Muttaficka, what?!
        else:
            delta = None

        args = (guild.id, channel.id, message.id, action, mod.id, reason, {'args': [delta]}, )
        return query, args

    def _create_embed(self, number, action, mod, targets, reason, extra, time=None):
        time = time or datetime.utcnow()
        action = _mod_actions[action]

        bot_avatar = self.bot.user.avatar_url

        if not extra:
            duration_string = ''
        elif isinstance(extra, (float, int)):
            duration_string = f' for {duration_units(extra)}'
        else:
            duration_string = f' for {parse_delta(extra.delta)}'

        action_field = f'{action.repr.title()}{duration_string} by {mod}'
        reason = reason or f'No reason. Please provide one.'

        embed = (discord.Embed(color=action.color, timestamp=time)
                 .set_author(name=f'Case #{number}', icon_url=emoji_url(action.emoji))
                 .add_field(name=f'User{"s" * (len(targets) != 1)}', value=', '.join(map(str, targets)))
                 .add_field(name='Action', value=action_field, inline=False)
                 .add_field(name='Reason', value=reason, inline=False)
                 .set_footer(text=f'ID: {mod.id}', icon_url=bot_avatar))

        if len(targets) == 1:
            avatar_url = getattr(targets[0], 'avatar_url', None)
        else:
            avatar_url = MASSBAN_THUMBNAIL

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        return embed

    async def _insert_case(self, guild_id, mod_id, targets, query, args, connection=None):
        connection = connection or self.bot.pool

        if len(targets) == 1:
            query = f"""
                WITH modlog_insert AS ({query})
                INSERT INTO modlog_targets (entry_id, user_id, mod_id)
                VALUES      ((SELECT id FROM modlog_insert), ${len(args) + 1}, ${len(args) + 2});
            """
            await connection.execute(query, *args, targets[0].id, mod_id)
        else:
            entry_id = await connection.execute(query, *args)
            columns = ('entry_id', 'user_id')
            to_insert = [(entry_id, target.id, mod_id) for target in targets]

            await connection.copy_records_to_table('modlog_targets', columns=columns, records=to_insert)

        _get_number_of_cases.invalidate(None, guild_id)

    @staticmethod
    async def _notify_user(config, action, guild, user, targets, reason, extra=None, auto=False):
        if action == 'massban':
            return

        if config and not config.dm_user:
            return

        # Should always be True, because we don't send DMs to massbanned users.
        assert len(targets) == 1, f'too many targets for {action}'

        mod_action = _mod_actions[action]
        action_applied = f'You have been {mod_action.repr}'
        if extra:
            action_applied += f' for {parse_delta(extra.delta)}'

        embed = (discord.Embed(color=mod_action.color, timestamp=datetime.utcnow())
                 .set_author(name=f'{action_applied}!', icon_url=emoji_url(mod_action.emoji))
                 .add_field(name='In', value=str(guild), inline=False)
                 .add_field(name='By', value=str(user), inline=False))

        if reason:
            embed.add_field(name='Reason', value=reason, inline=False)

        for target in targets:
            with contextlib.suppress(discord.HTTPException):
                await target.send(embed=embed)

    def _add_to_cache(self, name, guild_id, member_id, *, seconds=2):
        args = (name, guild_id, member_id)
        self._cache.add(args)
        self._cache_locks[name, guild_id, member_id].set()

        async def delete_value():
            await asyncio.sleep(seconds)
            self._cache.discard(args)
            self._cache_locks.pop((name, guild_id, member_id), None)

        self.bot.loop.create_task(delete_value())

    def wait_for_cache(self, name, guild_id, member_id):
        return self._cache_locks[name, guild_id, member_id].wait()

    async def on_tempban_complete(self, timer):
        self._add_to_cache('tempban', *timer.args)

    async def mod_before_invoke(self, ctx):
        name = ctx.command.qualified_name
        if name not in _mod_actions:
            return

        targets = (m for m in ctx.args if isinstance(m, discord.Member))
        for member in targets:
            self._add_to_cache(name, ctx.guild.id, member.id)

    async def mod_after_invoke(self, ctx):
        name = ctx.command.qualified_name
        if name not in _mod_actions:
            return

        if ctx.command_failed:
            return

        targets = [m for m in ctx.args if isinstance(m, discord.Member)]
        auto = getattr(ctx, 'auto_punished', False)
        extra = ctx.args[3] if 'duration' in ctx.command.params else None
        reason = ctx.args[2] if name == 'massban' else ctx.kwargs.get('reason')
        if reason is not None:
            match = re.search(r'#[0-9]{4} — (.*)', reason)
            if match:
                reason = match[1]

        config = await self._get_case_config(ctx.guild.id, connection=ctx.db)
        args = [config, name, ctx.guild, ctx.author, targets, reason]

        await self._notify_user(*args, extra=extra, auto=auto)

        try:
            query_args = await self._send_case(*args, extra=extra, auto=auto, connection=ctx.db)
        except ModLogError:
            pass
        else:
            if query_args:
                query, args = query_args

                await self._insert_case(connection=ctx.db, guild_id=ctx.guild.id, mod_id=ctx.author.id, targets=targets, query=query, args=args)

    async def _poll_audit_log(self, guild, user, *, action):
        if (action, guild.id, user.id) in self._cache:
            return

        with contextlib.suppress(AttributeError):
            if not guild.me.guild_permissions.view_audit_log:
                return

        config = await self._get_case_config(guild.id)
        if not (config and config.poll_audit_log):
            return

        # Doesn't catch softbans
        audit_action = discord.AuditLogAction[action]

        after = datetime.utcnow() - timedelta(seconds=2)

        try:
            for attempt in range(3):
                await asyncio.sleep(0.5 * (attempt + 1))

                entry = await guild.audit_logs(action=audit_action, after=after).get(target=user)
                if entry is not None:
                    break

            else:
                logger.info('%s (ID: %d) in guild %s (ID: %d) never had an entry for event %r', user, user.id, guild, guild.id, action)
                return
        except discord.Forbidden:
            return

        with contextlib.suppress(ModLogError):
            targets = [entry.target]
            query_args = await self._send_case(config, action, guild, entry.user, targets, entry.reason)

            if query_args:
                query, args = query_args

                await self._insert_case(connection=self.bot.pool, guild_id=guild.id, mod_id='Audit Logs', targets=targets, query=query, args=args)

    async def _poll_ban(self, guild, user, *, action):
        if ('softban', guild.id, user.id) in self._cache:
            return

        if ('tempban', guild.id, user.id) in self._cache:
            return

        await self._poll_audit_log(guild, user, action=action)

    async def on_member_ban(self, guild, user):
        await self._poll_ban(guild, user, action='ban')

    async def on_member_unban(self, guild, user):
        await self._poll_ban(guild, user, action='unban')

    async def on_member_remove(self, member):
        await self._poll_audit_log(member.guild, member, action='kick')

    @staticmethod
    async def _get_case(guild_id, num, *, connection):
        query = 'SELECT * FROM modlog WHERE guild_id = $1 ORDER BY id OFFSET $2 LIMIT 1;'
        return await connection.fetchrow(query, guild_id, num - 1)

    # And finally the commands

    @commands.group(name='case', invoke_without_command=True)
    async def _case(self, ctx, num: CaseNumber = None):
        """Group for all case searching commands. If given a number, it retrieves the case with the given number.

        If no number is given, it shows the latest case.

        Negative numbers are allowed. They count starting from the most recent case.
        e.g. -1 will show the newest case.
        """

        if not num:
            num = await _get_number_of_cases(ctx.db, ctx.guild.id)
            if not num:
                return await ctx.send('There are no cases here.')

        if num == 0:
            num = 1

        case = await self._get_case(ctx.guild.id, num, connection=ctx.db)
        if not case:
            return await ctx.send(f'Case #{num} is not a valid case.')

        query = 'SELECT user_id FROM modlog_targets WHERE entry_id = $1;'
        targets = [
            self.bot.get_user(row[0]) or f'<Unknown: {row[0]}>'
            for row in await ctx.db.fetchrow(query, case['id'])
        ]

        extra = json.loads(case['extra'])
        extra = extra['args'][0] if extra else None

        embed = self._create_embed(
            num,
            case['action'],
            self.bot.get_user(case['mod_id']),
            targets,
            case['reason'],
            extra,
            discord.utils.snowflake_time(case['message_id'])
        )
        await ctx.send(embed=embed)

    @_case.command(name='user', aliases=['member'])
    async def _case_user(self, ctx, *, member: discord.Member):
        """Retrieves all the cases for a specific member.

        Only members who are in the server can be searched.
        """

        query = """
            SELECT   message_id, action, mod_id, reason
            FROM     modlog, modlog_targets
            WHERE    modlog.id = modlog_targets.entry_id
            AND      guild_id = $1
            AND      user_id = $2
            ORDER BY modlog.id;
        """
        results = await ctx.db.fetch(query, ctx.guild.id, member.id)

        get_time = discord.utils.snowflake_time
        get_user = self.bot.get_user

        entries = []
        for message_id, action, mod_id, reason in results:
            action = _mod_actions[action]
            name = f'{action.emoji} {action.repr.title()}'
            formatted = (
                f'**On:** {get_time(message_id) :%x %X}\n'
                f'**Moderator:** {get_user(mod_id) or f"<Unknown ID: {mod_id}>"}\n'
                f'**Reason:** {truncate(reason, 512, "...")}\n'
                '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
            )

            entries.append((name, formatted))

        if not entries:
            return await ctx.send(f'{member} is clean. For now...')

        await FieldPaginator(ctx, entries, title=f'Cases for {member}', color=random_color(), inline=False).interact()

    @staticmethod
    async def _check_modlog_channel(ctx, channel_id, message=None, *, embed=None):
        if not channel_id:
            message = f'Mod-logging should have a channel. To set one, use `{ctx.clean_prefix}modlog channel #channel`.\n\n' + message or ''

        await ctx.send(message, embed=embed)

    async def _show_config(self, ctx):
        config = await self._get_case_config(ctx.guild.id, connection=ctx.db)
        if not config:
            return await ctx.send('Mod-logging hasn\'t been configured yet. '
                                  f'To turn it on, use `{ctx.clean_prefix}{ctx.invoked_with} channel #channel`.')

        will, color = ('will', random_color()) if config.enabled else ('won\'t', random_color())
        flags = ', '.join(flag.name for flag in ActionFlag if config.events & flag)

        count = await _get_number_of_cases(ctx.db, ctx.guild.id)
        embed = (discord.Embed(description=f'I have made {count} cases so far.', color=color)
                 .set_author(name=f'In {ctx.guild}, I {will} be logging mod actions.')
                 .add_field(name='Logging Channel:', value=f'<#{config.channel_id}>')
                 .add_field(name='Actions that will be logged:', value=flags, inline=False))
        await ctx.send(embed=embed)

    @commands.group(name='modlog', invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def _modlog(self, ctx, enable: bool = None):
        """Sets whether or not I should log moderation actions at all.

        If no arguments are given, the basic configuration info will be shown.
        """

        if enable is None:
            return await self._show_config(ctx)

        query = """
            INSERT INTO   modlog_config (guild_id, enabled)
            VALUES        ($1, $2)
            ON CONFLICT   (guild_id)
            DO UPDATE SET enabled = $2
            RETURNING     channel_id;
        """
        channel_id = await ctx.db.fetchrow(query, ctx.guild.id, enable)

        message = 'Moderation actions will be logged from now on.' if enable else 'Moderation actions will no longer be logged.'
        await self._check_modlog_channel(ctx, channel_id, message)

    @_modlog.command(name='channel')
    @commands.has_permissions(manage_guild=True)
    async def _modlog_channel(self, ctx, *, channel: discord.TextChannel):
        """Sets the channel that will be used for logging moderation actions."""

        permissions = ctx.me.permissions_in(channel)
        if not permissions.read_messages:
            return await ctx.send(f'Give me perms to read messages in {channel.mention} first.')

        if not permissions.send_messages:
            return await ctx.send(f'Wot?! How am I supposed to log actions in {channel.mention} without being able to send messages?!')

        if not permissions.embed_links:
            return await ctx.send(f'I need the Embed Links permission in order to make {channel.mention} the mod-log channel.')

        query = """
            INSERT INTO   modlog_config (guild_id, channel_id)
            VALUES        ($1, $2)
            ON CONFLICT   (guild_id)
            DO UPDATE SET channel_id = $2;
        """
        await ctx.db.execute(query, ctx.guild.id, channel.id)

        await ctx.send(f'Ok, {channel.mention} is the new mod-log channel from now on.')

    @commands.group(name='modactions', invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def _mod_actions(self, ctx):
        """Shows all the actions that can be logged.

        For this command to work, it is necessary that you've set a channel for logging cases first.
        """

        config = await self._get_case_config(ctx.guild.id, connection=ctx.db)
        if not config:
            return await ctx.send(f'Please set a channel with `{ctx.clean_prefix}modlog channel #channel` first.')

        flags = ', '.join(flag.name for flag in ActionFlag)
        enabled_flags = ', '.join(flag.name for flag in ActionFlag if config.events & flag)

        embed = (discord.Embed(color=random_color())
                 .add_field(name='List of valid Mod Actions:', value=flags)
                 .add_field(name='Actions that will be logged:', value=enabled_flags))

        await self._check_modlog_channel(ctx, config.channel_id, embed=embed)

    async def _set_actions(self, ctx, query, flags, *, color, default_op):
        flags = unique(flags)
        reduced = reduce(operator.or_, flags)

        default = default_op(reduced)
        channel_id, events = await ctx.db.fetchrow(query, ctx.guild.id, reduced.value, default)

        enabled_flags = ', '.join(flag.name for flag in ActionFlag if events & flag)

        embed = (discord.Embed(description=', '.join(flag.name for flag in ActionFlag), color=color)
                 .set_author(name=f'Successfully {ctx.command.name}d the following actions')
                 .add_field(name='The following mod actions will now be logged:', value=enabled_flags, inline=False))

        await self._check_modlog_channel(ctx, channel_id, embed=embed)

    @_mod_actions.command(name='enable')
    @commands.has_permissions(manage_guild=True)
    async def _macts_enable(self, ctx, actions: commands.Greedy[ActionFlag]):
        """Enables case creation for all given mod actions."""

        query = """
            INSERT INTO   modlog_config (guild_id, events)
            VALUES        ($1, $3)
            ON CONFLICT   (guild_id)
            DO UPDATE SET events = modlog_config.events | $2
            RETURNING     channel_id, events;
        """

        await self._set_actions(ctx, query, actions, color=random_color(), default_op=partial(operator.or_, _default_flags))

    @_mod_actions.command(name='disable')
    @commands.has_permissions(manage_guild=True)
    async def _macts_disable(self, ctx, actions: commands.Greedy[ActionFlag]):
        """Disables case creation for all given mod actions."""

        query = """
            INSERT INTO   modlog_config (guild_id, events)
            VALUES        ($1, $3)
            ON CONFLICT   (guild_id)
            DO UPDATE SET events = modlog_config.events & ~cast($2 AS INTEGER)
            RETURNING     channel_id, events;
        """

        await self._set_actions(ctx, query, actions, color=random_color(), default_op=lambda f: _default_flags & ~f)

    @commands.command(name='pollauditlog')
    @commands.has_permissions(manage_guild=True)
    async def _poll_audit_log_command(self, ctx, enable: bool):
        """Sets whether or not I should pull the Audit Log for certain cases.

        When you invoke a moderation command, e.g. `{prefix}ban`, it will be automatically logged into the given mod-log channel.

        This is meant for times it is manually done or when it is done through another bot.

        Note that this is implicitly disabled if the bot can't see Audit Logs.
        However, this is still preferred as the bot needs to see the Audit Log for other commands too.

        Make sure you have set a channel for logging cases before using this command.
        """

        query = """
            INSERT INTO   modlog_config (guild_id, poll_audit_log)
            VALUES        ($1, $2)
            ON CONFLICT   (guild_id)
            DO UPDATE SET poll_audit_log = $2
            RETURNING     channel_id;
        """
        channel_id, = await ctx.db.fetchrow(query, ctx.guild.id, enable)

        message = '\N{WHITE HEAVY CHECK MARK}' if enable else '\N{CROSS MARK}'
        await self._check_modlog_channel(ctx, channel_id, message)

    @commands.command(name='moddm')
    @commands.has_permissions(manage_guild=True)
    async def _moddm(self, ctx, dm_user: bool):
        """Sets whether or not I should DM users when a mod-actions is applied to them."""

        query = """
            INSERT INTO   modlog_config (guild_id, dm_user)
            VALUES        ($1, $2)
            ON CONFLICT   (guild_id)
            DO UPDATE SET dm_user = $2
            RETURNING     channel_id;
        """

        channel_id, = await ctx.db.fetchrow(query, ctx.guild.id, dm_user)
        await self._check_modlog_channel(ctx, channel_id, '\N{OK HAND SIGN}')

    @commands.command(name='reason')
    @commands.has_permissions(manage_guild=True)
    async def _reason(self, ctx, num: CaseNumber, *, reason):
        """Sets the reason for a particular case.

        You must own the case in order to edit the reason.

        Negative numbers are allowed. They count starting from the most recent case.
        e.g. -1 will show the newest case.
        """

        case = await self._get_case(ctx.guild.id, num, connection=ctx.db)
        if not case:
            return await ctx.send(f'Case #{num} does not exist.')

        if case['mod_id'] != ctx.author.id:
            return await ctx.send('This case is not yours.')

        channel = ctx.guild.get_channel(case['channel_id'])
        if not channel:
            return await ctx.send('This channel no longer exists. :thinking:')

        message = await _get_message(channel, case['message_id'])
        if not message:
            return await ctx.send('Somehow the message belonging to the case was deleted.')

        embed = message.embeds[0]
        reason_field = embed.fields[-1]
        embed.set_field_at(-1, name=reason_field.name, value=reason, inline=False)

        try:
            await message.edit(embed=embed)
        except discord.NotFound:
            return await ctx.send('Somehow the message belonging to the case was deleted.')

        query = 'UPDATE modlog SET reason = $1 WHERE id = $2;'
        await ctx.db.execute(query, reason, case['id'])

        await ctx.message.add_reaction('\N{OK HAND SIGN}')


def setup(bot):
    bot.add_cog(ModLog(bot))
