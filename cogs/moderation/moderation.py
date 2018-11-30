import asyncio
import contextlib
import datetime
import functools
import heapq
import itertools
import random
import typing
from collections import Counter, namedtuple
from operator import attrgetter

import discord
from discord.ext import commands

from utils import db, formats, time
from utils.colors import random_color
from utils.context_managers import temporary_attribute
from utils.examples import get_example, static_example, wrap_example
from utils.jsonfile import JSONFile
from utils.misc import ordinal
from utils.paginator import FieldPaginator, Paginator


class WarnEntries(db.Table, table_name='warn_entries'):
    id = db.Column(db.Serial, primary_key=True)
    guild_id = db.Column(db.BigInt)
    user_id = db.Column(db.BigInt)
    mod_id = db.Column(db.BigInt)
    reason = db.Column(db.Text)
    warned_at = db.Column(db.Timestamp)


class WarnTimeouts(db.Table, table_name='warn_timeouts'):
    guild_id = db.Column(db.BigInt, primary_key=True)
    timeout = db.Column(db.Interval)


class WarnPunishments(db.Table, table_name='warn_punishments'):
    guild_id = db.Column(db.BigInt)
    warns = db.Column(db.BigInt)
    type = db.Column(db.Text)
    duration = db.Column(db.Integer, nullable=True, default=0)

    __create_extra__ = ['PRIMARY KEY (guild_id, warns)']


class MutedRoles(db.Table, table_name='muted_roles'):
    guild_id = db.Column(db.BigInt, primary_key=True)
    role_id = db.Column(db.BigInt)


class AlreadyWarned(commands.CommandError):
    __ignore__ = True


class AlreadyMuted(commands.CommandError):
    __ignore__ = True


_DummyPunishment = namedtuple('_DummyPunishment', 'warns type duration')
_default_punishment = _DummyPunishment(warns=3, type='mute', duration=60 * 10)
del _DummyPunishment


def _get_lower_member(ctx):
    member = random.choice([
        member for member in ctx.guild.members
        if ctx.author.id != member.id
        and member.id != ctx.bot.user.id
        and member != ctx.guild.owner
        and ctx.author.top_role > member.top_role < ctx.me.top_role
    ] or ctx.guild.members)

    return f'@{member}'


class _ProxyMember:
    def __init__(self, id):
        self.id = id

    def __str__(self):
        return str(self.id)


class MemberID(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            return await commands.MemberConverter().convert(ctx, argument)
        except commands.BadArgument:
            pass

        try:
            id = int(argument)
        except ValueError:
            raise commands.BadArgument(f'{argument} is neither a member nor an ID.')
        else:
            return _ProxyMember(id)

    @staticmethod
    def random_example(ctx):
        if random.random() > 0.5:
            return _get_lower_member(ctx)

        exists = ctx.guild.get_member
        user_ids = [user.id for user in ctx.bot.users]
        user_ids = list(itertools.filterfalse(exists, user_ids)) or user_ids

        return random.choice(user_ids)


class BannedMember(commands.Converter):
    async def convert(self, ctx, argument):
        ban_list = await ctx.guild.bans()
        try:
            member_id = int(argument, base=10)
        except ValueError:
            thing = discord.utils.find(lambda e: str(e.user) == argument, ban_list)
        else:
            thing = discord.utils.find(lambda e: e.user == member_id, ban_list)

        if not thing:
            raise commands.BadArgument(f'{argument} wasn\'t previously banned in this server.')

        return thing

    @staticmethod
    def random_example(_):
        return 'BannedFaggot#1337'


class _CheckedMember(commands.Converter):
    def __init__(self, type=commands.MemberConverter):
        self.converter = type()

    async def convert(self, ctx, argument):
        member = await self.converter.convert(ctx, argument)

        if not isinstance(member, discord.Member):
            return member

        if ctx.author.id == member.id:
            raise commands.BadArgument('You are trying to ban yourself? Good meme.')
        if member.id == ctx.bot.user.id:
            raise commands.BadArgument('Am I Mee6? I don\'t deserve to be banned.')
        if member == ctx.guild.owner:
            raise commands.BadArgument(f'We won\'t {ctx.command} the server owner, okay?')
        if member.top_role >= ctx.me.top_role:
            if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
                extra = 'the both of us'
            else:
                extra = 'me'

            raise commands.BadArgument(f'{member} is higher than {extra}')
        if member.top_role >= ctx.author.top_role:
            raise commands.BadArgument(f'{member} is higher than you.')

        return member

    def random_example(self, ctx):
        if self.converter is commands.MemberConverter:
            return _get_lower_member(ctx)

        return get_example(self.converter, ctx)


CheckedMember = _CheckedMember()
CheckedMemberID = _CheckedMember(MemberID)


@static_example
class Reason(commands.Converter):
    async def convert(self, ctx, argument):
        result = f'{ctx.author} \N{EM DASH} {argument}'

        if len(result) > 512:
            _max = 512 - len(result) - len(argument)
            raise commands.BadArgument(f'Maximum reason length is {abs(_max)} (got {len(argument)}).')

        return result


_warn_punishments = ['mute', 'kick', 'softban', 'tempban', 'ban']
_punishment_needs_duration = {'mute', 'tempban'}.__contains__
_is_valid_punishment = frozenset(_warn_punishments).__contains__


def warn_punishment(arg):
    view = commands.view.StringView(arg)
    punishment = commands.view.quoted_word(view)
    lower = punishment.lower()

    if not _is_valid_punishment(lower):
        raise commands.BadArgument(f'{punishment} is not a valid punishment.\nValid punishments: {", ".join(_warn_punishments)}')

    if not _punishment_needs_duration(lower):
        return lower, None

    view.skip_ws()
    duration = commands.view.quoted_word(view)
    if not duration:
        raise commands.BadArgument(f'{punishment} requires a duration.')

    duration = time.Delta(duration)
    return lower, duration


@wrap_example(warn_punishment)
def _warn_punishment_example(ctx):
    punishment = random.choice(_warn_punishments)
    if not _punishment_needs_duration(punishment):
        return punishment

    duration = time.Delta.random_example(ctx)
    return f'{punishment} {duration}'


num_warns = functools.partial(int)


@wrap_example(num_warns)
def _num_warns_example(_):
    return random.randint(3, 5)


class Moderation:
    def __init__(self, bot):
        self.bot = bot

        self.slowmodes = JSONFile('slowmodes.json')
        self.slowmode_bucket = {}

        if hasattr(self.bot, '__mod_mute_role_create_bucket__'):
            self._mute_role_create_cooldowns = self.bot.__mod_mute_role_create_bucket__
        else:
            self._mute_role_create_cooldowns = commands.CooldownMapping.from_cooldown(2, 600, commands.BucketType.guild)

    def __unload(self):
        self.bot.__mod_mute_role_create_bucket__ = self._mute_role_create_cooldowns

    async def call_mod_log_invoke(self, invoke, ctx):
        mod_log = ctx.bot.get_cog('ModLog')
        if mod_log:
            await getattr(mod_log, f'mod_{invoke}')(ctx)

    __before_invoke = functools.partialmethod(call_mod_log_invoke, 'before_invoke')
    __after_invoke = functools.partialmethod(call_mod_log_invoke, 'after_invoke')

    @staticmethod
    def _is_slowmode_immune(member):
        return member.guild_permissions.manage_guild

    async def check_slowmode(self, message):
        if not message.guild:
            return

        guild_id = message.guild.id
        if guild_id not in self.slowmodes:
            return

        slowmodes = self.slowmodes[guild_id]

        is_immune = self._is_slowmode_immune(message.author)

        for thing in (message.channel, message.author):
            key = str(thing.id)
            if key not in slowmodes:
                continue

            config = slowmodes[key]
            if not config['no_immune'] and is_immune:
                continue

            bucket = self.slowmode_bucket.setdefault(thing.id, {})
            time = bucket.get(message.author.id)
            if not time or (message.created_at - time).total_seconds() >= config['duration']:
                bucket[message.author.id] = message.created_at
            else:
                await message.delete()
                break

    @commands.group(name='slowmode', invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def _slowmode(self, ctx, duration: time.Delta, *, member: discord.Member = None):
        """Activates the slowmode.

        If a member is given as an argument, it puts only the member in slowmode on the whole server,
        otherwise it puts the current channel in slowmode for all.

        Those with Manage Server permissions will not be affected. If you want to put them in slowmode too, use `{prefix}slowmode noimmune`.
        """

        pronoun = 'They'
        if not member:
            member = ctx.channel
            pronoun = 'Everyone'
        elif self._is_slowmode_immune(member):
            message = (
                f'{member} is immune from slowmode due to having the Manage Server permission. '
                f'Consider using `{ctx.prefix}slowmode noimmune`.'
            )
            return await ctx.send(message)

        config = self.slowmodes.get(ctx.guild.id, {})
        slowmode = config.setdefault(str(member.id), {'no_immune': False})
        if slowmode['no_immune']:
            return await ctx.send(
                f'{member.mention} is already in **noimmune** slowmode. You need to turn it off first.'
            )

        slowmode['duration'] = duration.duration
        await self.slowmodes.put(ctx.guild.id, config)

        await ctx.send(
            f'{member.mention} is now in slowmode! {pronoun} must wait {duration} between each message they send.'
        )

    @_slowmode.command(name='noimmune')
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def _slowmode_no_immune(self, ctx, duration: time.Delta, *, member: discord.Member = None):
        """Puts the channel or member in "noimmune" slowmode.

        Unlike `{prefix}slowmode`, no one is immune to this slowmode, even those with Manage Server permissions.
        """

        if not member:
            member, pronoun = ctx.channel, 'They'
        else:
            pronoun = 'Everyone'

        config = self.slowmodes.get(ctx.guild.id, {})
        slowmode = config.setdefault(str(member.id), {'no_immune': True})
        slowmode['duration'] = duration.duration
        await self.slowmodes.put(ctx.guild, config)

        await ctx.send(f'{member.mention} is now in **noimmune** slowmode. {pronoun} must wait {duration} after each message they send.')

    @_slowmode.command(name='off')
    async def _slowmode_off(self, ctx, *, member: discord.Member = None):
        """Turns off the slowmode for either a member or a channel."""

        member = member or ctx.channel
        config = self.slowmodes.get(ctx.guild.id, {})
        try:
            del config[str(member.id)]
        except ValueError:
            await ctx.send(f'{member.mention} was never in slowmode.')
        else:
            await self.slowmodes.put(ctx.guild.id, config)
            self.slowmode_bucket.pop(member.id, None)
            await ctx.send(f'{member.mention} is no longer in slowmode.')

    @commands.command(name='newusers', aliases=['newmembers', 'joined'])
    @commands.guild_only()
    async def _new_users(self, ctx, *, count: int = 5):
        """Tells you the recently joined members on this server.

        The minimum is 3 members. If no number is given, I will show the last 5 members that joined.
        """

        human_delta = time.human_timedelta
        count = max(count, 3)
        members = heapq.nlargest(count, ctx.guild.members, key=attrgetter('joined_at'))

        names = map(str, members)
        values = (
            (f'**Joined:** {human_delta(member.joined_at)}\n'
             f'**Created:** {human_delta(member.created_at)}\n{"-" * 40}')
            for member in members
        )
        entries = zip(names, values)

        title = f'The {formats.pluralize(**{"newest members": len(members)})}'
        pages = FieldPaginator(ctx, entries, per_page=5, title=title, color=random_color())
        await pages.interact()

    @commands.command(name='clear')
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def _clear(self, ctx, arg: typing.Union[int, discord.Member]):
        """Clears some messages in a channel.

        The argument can either be a user or a number. If it's a number, it deletes *up to* that many messages.
        If it's a user, it deletes any message by that user up to the last 100 messages.
        If no argument was specified, it deletes my messages.
        """

        if isinstance(arg, int):
            if arg < 1:
                return await ctx.send(f'How can I delete {arg} messages?')

            deleted = await ctx.channel.purge(limit=min(arg, 1000) + 1)
        elif isinstance(arg, discord.Member):
            deleted = await ctx.channel.purge(check=lambda m: m.author.id == arg.id)

        messages = formats.pluralize(message=len(deleted) - 1)
        await ctx.send(f'Successfully deleted {messages}.', delete_after=2)

    @commands.command(name='clean')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def _clean(self, ctx, limit=100):
        """Cleans up my messages from the channel.

        Give me Manage Messages and Read Message History permissions, and I'll also delete messages that invoked my commands.
        """

        prefixes = tuple(self.bot.get_guild_prefixes(ctx.guild))
        bot_id = self.bot.user.id

        bot_perms = ctx.channel.permissions_for(ctx.me)
        purge = functools.partial(ctx.channel.purge, limit=limit, before=ctx.message)
        can_bulk_delete = bot_perms.manage_messages and bot_perms.read_message_history

        if can_bulk_delete:
            def is_possible_command_invoke(m):
                if m.author.id == bot_id:
                    return True

                return m.content.startswith(prefixes) and not m.content[1:2].isspace()

            deleted = await purge(check=is_possible_command_invoke)

        else:
            deleted = await purge(check=lambda m: m.author.id == bot_id, bulk=False)

        spammers = Counter(str(m.author) for m in deleted)
        total_deleted = sum(spammers.values())

        second_part = ' was' if total_deleted == 1 else 's were'
        title = f'{total_deleted} message{second_part} removed.'
        joined = '\n'.join(itertools.starmap('**{0}**: {1}'.format, spammers.most_common()))

        if ctx.bot_has_embed_links():
            spammer_stats = joined or discord.Embed.Empty

            embed = (discord.Embed(description=spammer_stats, color=random_color())
                     .set_author(name=title))
            embed.timestamp = ctx.message.created_at

            await ctx.send(embed=embed, delete_after=10)

        else:
            message = f'{title}\n{joined}'
            await ctx.send(message, delete_after=10)

        await asyncio.sleep(20)
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

    @_clear.error
    @_clean.error
    async def _clear_error(self, ctx, error):
        cause = error.__cause__
        if not isinstance(cause, discord.HTTPException):
            ctx.__bypass_local_error__ = True
            return

        await ctx.send(f'Couldn\'t delete the messages for some reason. Here\'s the error:\n```py\n{type(cause).__name__}: {cause}```')

    @staticmethod
    async def _get_warn_timeout(connection, guild_id):
        query = 'SELECT timeout FROM warn_timeouts WHERE guild_id = $1;'
        row = await connection.fetchrow(query, guild_id)
        return row['timeout'] if row else datetime.timedelta(minutes=15)

    @commands.command(name='warn')
    @commands.has_permissions(manage_guild=True)
    async def _warn(self, ctx, member: discord.Member, *, reason):
        """Warns a user."""

        author, current_time, guild_id = ctx.author, ctx.message.created_at, ctx.guild.id
        timeout = await self._get_warn_timeout(ctx.db, guild_id)

        query = """
            SELECT   warned_at
            FROM     warn_entries
            WHERE    guild_id = $1 AND user_id = $2 AND warned_at + $3 > $4
            ORDER BY id;
        """
        records = await ctx.db.fetch(query, guild_id, member.id, timeout, current_time)
        warn_queue = [record[0] for record in records]

        try:
            last_warn = warn_queue[-1]
        except IndexError:
            pass
        else:
            retry_after = (current_time - last_warn).total_seconds()
            if retry_after <= 60:
                raise AlreadyWarned(f'{member} has been warned already, try again in {60 - retry_after :.2f} seconds.')

        query = """
            INSERT INTO warn_entries (guild_id, user_id, mod_id, reason, warned_at)
            VALUES      ($1, $2, $3, $4, $5);
        """
        await ctx.db.execute(query, guild_id, member.id, author.id, reason, current_time)

        current_warn_number = len(warn_queue) + 1
        query = 'SELECT type, duration FROM warn_punishments WHERE guild_id = $1 AND warns = $2;'
        row = await ctx.db.fetchrow(query, guild_id, current_warn_number)

        if not row:
            if current_warn_number == 3:
                row = _default_punishment
            else:
                return await ctx.send(f'\N{WARNING SIGN} Warned {member.mention} successfully!')

        # Auto-punish this faggot who dares to break the rules
        args = [member]
        duration = row['duration']
        if duration > 0:
            args.append(duration)
            punished_for = f' for {time.duration_units(duration)}'
        else:
            punished_for = ''

        punishment = row['type']
        punishment_command = getattr(self, punishment)
        punishment_reason = f'{reason}\n({ordinal(current_warn_number)} warning)'

        with temporary_attribute(ctx, 'send', lambda *a, **kw: asyncio.sleep(0)):
            await ctx.invoke(punishment_command, *args, reason=punishment_reason)

        message = (
            f'{member.mention} has {current_warn_number} warnings! Mate, you fucked up. Now take a {punishment}{punished_for}.'
        )
        await ctx.send(message)

        ctx.auto_punished = True
        ctx.command = punishment_command
        ctx.args[2:] = args
        ctx.kwargs['reason'] = punishment_reason

    @_warn.error
    async def _warn_error(self, ctx, error):
        if isinstance(error, AlreadyWarned):
            await ctx.send(error)
        else:
            ctx.__bypass_local_error__ = True

    @commands.command(name='warns')
    @commands.has_permissions(manage_guild=True)
    async def _warns(self, ctx, *, member: discord.Member = None):
        """Shows a given user's warns on this server.

        If no user is given, this command shows all warned users on this server.
        """

        if not member:
            query = 'SELECT user_id, reason FROM warn_entries WHERE guild_id = $1;'
            records = await ctx.db.fetch(query, ctx.guild.id)

            title = f'Warns in {ctx.guild}'
        else:
            query = 'SELECT user_id, reason FROM warn_entries WHERE guild_id = $1 AND user_id = $2;'
            records = await ctx.db.fetch(query, ctx.guild.id, member.id)

            title = f'Warns for {member}'

        entries = (
            itertools.starmap('`{0}.` <@{1[0]}> => **{1[1]}**'.format, enumerate(records, 1)) if records else
            ('No warns found.', )
        )

        pages = Paginator(ctx, entries, per_page=5, title=title)
        await pages.interact()

    @commands.command(name='clearwarns', aliases=['resetwarns'])
    @commands.has_permissions(manage_guild=True)
    async def _clear_warns(self, ctx, member: discord.Member):
        """Clears a member's warns."""

        query = 'DELETE FROM warn_entries WHERE guild_id = $1 AND user_id = $2;'
        await ctx.db.execute(query, ctx.guild.id, member.id)

        await ctx.send(f'{member}\'s warns have been reset!')

    @commands.command(name='warnpunish')
    @commands.has_permissions(manage_guild=True)
    async def _warn_punish(self, ctx, num: num_warns, *, punishment: warn_punishment):
        """Sets the punishment a user receives upon exceeding a given warn limit.

        Valid punishments:
            `mute` (Requires a given duration)
            `kick`
            `softban`
            `tempban` (Requires a given duration)
            `ban`
        """

        punishment, duration = punishment
        true_duration = None if not duration else duration.duration

        query = """
            INSERT INTO   warn_punishments (guild_id, warns, type, duration)
            VALUES        ($1, $2, $3, $4)
            ON CONFLICT   (guild_id, warns)
            DO UPDATE SET type = $3, duration = $4;
        """
        await ctx.db.execute(query, ctx.guild.id, num, punishment, true_duration)

        extra = f' for {duration}' if duration else ''
        await ctx.send(f'\N{OK HAND SIGN} If a user has been warned {num} times, I will {punishment} them{extra}.')

    @commands.command(name='warnpunishments')
    async def _warn_punishments(self, ctx):
        """Shows the list of warn punishments."""

        query = """
            SELECT   warns, initcap(type), duration
            FROM     warn_punishments
            WHERE    guild_id = $1
            ORDER BY warns;
        """
        punishments = await ctx.db.fetch(query, ctx.guild.id) or (_default_punishment, )

        entries = (
            f'{warns} strikes => **{type}** {(f"for " + time.duration_units(duration)) if duration else ""}'
            for warns, type, duration in punishments
        )

        pages = Paginator(ctx, entries, title=f'Punishments for {ctx.guild}')
        await pages.interact()

    @commands.command(name='warntimeout')
    @commands.has_permissions(manage_guild=True)
    async def _warn_timeout(self, ctx, duration: time.Delta):
        """Sets the maximum time between the oldest and the most recent warn.

        If a user hits a warn limit within this timeframe, they will be punished.
        """

        query = """
            INSERT INTO   warn_timeouts (guild_id, timeout)
            VALUES        ($1, $2)
            ON CONFLICT   (guild_id)
            DO UPDATE SET timeout = $2;
        """
        await ctx.db.execute(query, ctx.guild.id, datetime.timedelta(seconds=duration.duration))

        await ctx.send(f'Aye, if a user was warned within **{duration}** after the oldest warn, bad things are going to happen.')

    async def _get_muted_role_from_db(self, guild, *, connection=None):
        connection = connection or self.bot.pool

        query = 'SELECT role_id FROM muted_roles WHERE guild_id = $1;'
        row = await connection.fetchrow(query, guild.id)

        if not row:
            return None

        return discord.utils.get(guild.roles, id=row['role_id'])

    async def _get_muted_role(self, guild, connection=None):
        role = await self._get_muted_role_from_db(guild, connection=connection)
        if role:
            return role

        def probably_mute_role(r):
            lower = r.name.lower()
            return lower == 'muted' or 'mute' in lower

        return discord.utils.find(probably_mute_role, reversed(guild.roles))

    async def _update_muted_role(self, guild, new_role, connection=None):
        connection = connection or self.bot.pool
        query = """
            INSERT INTO   muted_roles (guild_id, role_id)
            VALUES        ($1, $2)
            ON CONFLICT   (guild_id)
            DO UPDATE SET role_id = $2;
        """
        await connection.execute(query, guild.id, new_role.id)

    @staticmethod
    async def _regen_muted_role_perms(role, *channels):
        muted_perms = dict.fromkeys(['send_messages', 'manage_messages', 'add_reactions', 'speak', 'connect', 'use_voice_activation'], False)

        permissions_in = channels[0].guild.me.permissions_in
        for channel in channels:
            if not permissions_in(channel).manage_roles:
                continue

            await asyncio.sleep(random.uniform(0, 0.5))

            try:
                await channel.set_permissions(role, **muted_perms)
            except discord.NotFound as e:
                if 'Unknown Overwrite' in str(e):
                    raise
            except discord.HTTPException:
                pass

    async def _do_mute(self, member, when, role, *, connection=None, reason=None):
        if role in member.roles:
            raise AlreadyMuted(f'{member.mention} has already been muted.')

        await member.add_roles(role, reason=reason)

        if when is not None:
            args = (member.guild.id, member.id, role.id)
            await self.bot.db_scheduler.add_abs(when, 'mute_complete', args)

    async def _create_muted_role(self, ctx):
        # Creating roles can take sooooo fucking much time. Better release the pool.
        await ctx.release()

        bucket = self._mute_role_create_cooldowns.get_bucket(ctx.message)
        if not bucket.get_tokens():
            retry_after = bucket.update_rate_limit() or 0
            raise commands.CommandOnCooldown(bucket, retry_after)

        if not await ctx.ask_confirmation('No `muted` role found. Create a new one?', delete_after=False):
            await ctx.send(f'A `muted` role couldn\'t be found. Set one with `{ctx.clean_prefix}setmuterole Role`')
            return None

        bucket.update_rate_limit()
        async with ctx.typing():
            ctx.__new_mute_role_message__ = await ctx.send('Creating `muted` role. Please wait...')
            role = await ctx.guild.create_role(
                name='Vale.py-Muted',
                color=discord.Color.red(),
                reason='Creating new muted role'
            )

            with contextlib.suppress(discord.HTTPException):
                await role.edit(position=ctx.me.top_role.position - 1)

            await self._regen_muted_role_perms(role, *ctx.guild.channels)
            await ctx.acquire()
            await self._update_muted_role(ctx.guild, role, ctx.db)
            return role

    @commands.command(name='mute')
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def _mute(self, ctx, member: CheckedMember, duration: typing.Optional[time.Delta] = None, *, reason: Reason = None):
        """Mutes a user for an optional amount of time."""

        reason = reason or f'By {ctx.author}'

        async def try_edit(content):
            try:
                await ctx.__new_mute_role_message__.edit(content=content)
            except (AttributeError, discord.NotFound):
                await ctx.send(content)

        role = await self._get_muted_role(ctx.guild, ctx.db)
        if role is None:
            try:
                role = await self._create_muted_role(ctx)
            except discord.NotFound:
                return await ctx.send('Please don\'t delete this role while I\'m setting it up.')
            except asyncio.TimeoutError:
                return await ctx.send('Sorry. You took too long...')
            except commands.CommandOnCooldown as e:
                return await ctx.send(
                    f'You\'re deleting the `muted` role too often. Please wait {time.duration_units(e.retry_after)} before trying again, '
                    f'or set a `muted` role with `{ctx.clean_prefix}setmuterole Role`.'
                )

            if role is None:
                return

        if duration is None:
            when = None
            for_how_long = 'permanently'
        else:
            when = ctx.message.created_at + duration.delta
            for_how_long = f'for {duration}'

        await self._do_mute(member, when, role, connection=ctx.db, reason=reason)
        await try_edit(f'Done. {member.mention} will now be muted {for_how_long}.')

    @_mute.error
    async def _mute_error(self, ctx, error):
        if isinstance(error, AlreadyMuted):
            await ctx.send(error)
        else:
            ctx.__bypass_local_error__ = True

    @commands.command(name='mutetime')
    async def _mute_time(self, ctx, member: discord.Member = None):
        """Shows the time left for a member's mute. Defaults to yourself."""

        member = member or ctx.author

        role = await self._get_muted_role(ctx.guild, ctx.db)
        if role not in member.roles:
            return await ctx.send(f'{member} is not muted...')

        query = """
            SELECT expires
            FROM   scheduler
            WHERE  event = 'mute_complete'
            AND    args_kwargs #>> '{args,0}' = $1
            AND    args_kwargs #>> '{args,1}' = $2

            -- The below condition is in case we have this scenario:
            --  - Member was muted
            --  - Mute role was changed while the user was muted
            --  - Member was muted again with the new role

            AND    args_kwargs #>> '{args,2}' = $3
            LIMIT  1;
        """
        entry = await ctx.db.fetchrow(query, str(ctx.guild.id), str(member.id), str(role.id))
        if not entry:
            return await ctx.send(f'{member} has been perm-muted. Probably the role was added manually...')

        when = entry['expires']
        await ctx.send(f'{member} has {time.human_timedelta(when)} remaining. Unmute on {when: %c}.')

    async def _remove_time_entry(self, guild, member, connection=None, *, event='mute_complete'):
        connection = connection or self.bot.pool

        query = """
            SELECT   id, expires
            FROM     scheduler
            WHERE    event = $3
            AND      args_kwargs #>> '{args,0}' = $1
            AND      args_kwargs #>> '{args,1}' = $2
            ORDER BY expires
            LIMIT    1;
        """
        entry = await connection.fetchrow(query, str(guild.id), str(member.id), event)
        if not entry:
            return None

        await self.bot.db_scheduler.remove(discord.Object(entry['id']))
        return entry['expires']

    @commands.command(name='unmute')
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member, *, reason: Reason = None):
        """Unmutes a user."""

        reason = reason or f'Unmute by {ctx.author}'

        role = await self._get_muted_role(member.guild, ctx.db)
        if role not in member.roles:
            return await ctx.send(f'{member} hasn\'t been muted.')

        await member.remove_roles(role, reason=reason)
        await self._remove_time_entry(member.guild, member, ctx.db)
        await ctx.send(f'{member.mention} is no longer muted.')

    @commands.command(name='setmuterole', aliases=['muterole'])
    @commands.has_permissions(manage_guild=True, manage_roles=True)
    async def _set_mute_role(self, ctx, *, role: discord.Role):
        """Sets the `muted` role for the server."""

        await self._update_muted_role(ctx.guild, role, ctx.db)
        await ctx.send(f'Set the `muted` role to **{role}**.')

    @commands.command(name='kick')
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def _kick(self, ctx, member: CheckedMember, *, reason: Reason = None):
        """Kicks a user."""

        reason = reason or f'By {ctx.author}'
        await member.kick(reason=reason)
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.command(name='softban')
    @commands.has_permissions(kick_members=True, manage_guild=True)
    @commands.bot_has_permissions(ban_members=True)
    async def _soft_ban(self, ctx, member: CheckedMember, *, reason: Reason = None):
        """Softbans a user."""

        reason = reason or f'By {ctx.author}'
        await member.ban(reason=reason)
        await member.unban(reason=f'Softban (Original reason: {reason})')
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.command(name='tempban')
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def _temp_ban(self, ctx, member: CheckedMember, duration: time.Delta, reason: Reason = None):
        """Temporarily bans a user."""

        reason = reason or f'By {ctx.author}'
        await ctx.guild.ban(member, reason=reason)
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

        await self.bot.db_scheduler.add(duration.delta, 'tempban_complete', (ctx.guild.id, member.id))

    @commands.command(name='ban')
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def _ban(self, ctx, member: CheckedMemberID, *, reason: Reason = None):
        """Bans a member.

        You can use this to ban someone even if he's not in the server, just use the ID.
        """

        reason = reason or f'By {ctx.author}'
        await ctx.guild.ban(member, reason=reason)
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.command(name='unban')
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def _unban(self, ctx, user: BannedMember, *, reason: Reason = None):
        """Unbans the user."""

        reason = reason or f'By {ctx.author}'
        await ctx.guild.unban(user, reason=reason)
        await self._remove_time_entry(ctx.guild, user, ctx.db, event='tempban_complete')
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.command(name='massban')
    @commands.has_permissions(ban_members=True)
    async def _mass_ban(self, ctx, members: commands.Greedy[_CheckedMember], delete_days: typing.Optional[int] = 0, *, reason: Reason):
        """Bans multiple users from the server.
        """

        for member in members:
            await ctx.guild.ban(member, reason=reason, delete_message_days=delete_days)

        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    # Corresponding events for that crap

    async def on_message(self, message):
        await self.check_slowmode(message)

    async def on_guild_channel_create(self, channel):
        guild = channel.guild
        role = await self._get_muted_role_from_db(guild)
        if not role:
            return

        await self._regen_muted_role_perms(role, channel)

    async def on_member_join(self, member):
        expires = await self._remove_time_entry(member.guild, member)
        if not expires:
            return

        role = await self._get_muted_role(member.guild)
        if not role:
            return

        await self._do_mute(member, expires + datetime.timedelta(seconds=3600), role, reason='Mute Evasion')

    async def on_member_update(self, before, after):
        removed_roles = set(before.roles).difference(after.roles)
        if not removed_roles:
            return

        role = await self._get_muted_role(before.guild)
        if role in removed_roles:
            await self._remove_time_entry(before.guild, before)

    # And some custom events

    async def _wait_for_cache(self, name, guild_id, member_id):
        mod_log = self.bot.get_cog('ModLog')
        if mod_log:
            await mod_log.wait_for_cache(name, guild_id, member_id)

    async def on_mute_complete(self, timer):
        guild_id, member_id, mute_role_id = timer.args
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        member = guild.get_member(member_id)
        if not member:
            return

        role = discord.utils.get(guild.roles, id=mute_role_id)
        if not role:
            return

        await member.remove_roles(role)

    async def on_tempban_complete(self, timer):
        guild_id, user_id = timer.args
        await self._wait_for_cache('tempban', guild_id, user_id)

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        await guild.unban(discord.Object(user_id), reason='Unban from tempban.')


def setup(bot):
    bot.add_cog(Moderation(bot))
