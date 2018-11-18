import json

import discord
from discord.ext import commands

from utils.misc import emoji_url, truncate
from utils.paginator import FieldPaginator
from utils.time import FutureTime, human_timedelta


MAX_REMINDERS = 10
ALARM_CLOCK_URL = emoji_url('\N{ALARM CLOCK}')
CLOCK_URL = emoji_url('\N{MANTELPIECE CLOCK}')
CANCELED_URL = emoji_url('\N{BELL WITH CANCELLATION STROKE}')

# Idea from Danno, Skidded? Not this time.


class Reminder:
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _create_reminder_embed(ctx, when, message):
        # Discord attempts to be smart with breaking up long lines. If a line
        # is extremely long, it will attempt to insert a line break before the next word.
        # This will lead to overstretched embeds to the right.
        #
        # To not give myself a headache, I will not attempt to do that manually.

        return (discord.Embed(colour=0x00FF00, description=message, timestamp=when)
                .set_author(name='Reminder set!', icon_url=CLOCK_URL)
                .set_thumbnail(url=ctx.author.avatar_url)
                .add_field(name='For', value=f'{ctx.channel.mention} in {ctx.guild}', inline=False)
                .set_footer(text=f'In {human_timedelta(when)} at')
                )

    async def _add_reminder(self, ctx, when, message):
        channel_id = ctx.channel.id if ctx.guild else None
        args = (ctx.author.id, channel_id, message)

        await ctx.bot.db_scheduler.add_abs(when, 'reminder_complete', args)
        await ctx.send(embed=self._create_reminder_embed(ctx, when, message))

    @commands.group(invoke_without_command=True)
    async def remind(self, ctx, when: FutureTime, *, message: commands.clean_content = 'nothing'):
        """Adds a reminder that will go off after a certain amount of time."""

        await self._add_reminder(ctx, when.dt, message)

    @remind.command(name='cancel', aliases=['del'])
    async def cancel_reminder(self, ctx, index: int = 1):
        """Cancels a running reminder with a given index.

        Reminders start at 1.
        If an index is not given, it defaults to the one that will end first.
        You can't cancel reminders that you've set to go off in 30 seconds or less.
        """

        query = """
            SELECT   id, expires, args_kwargs
            FROM     scheduler
            WHERE    event = 'reminder_complete'
            AND      args_kwargs #>> '{args,0}' = $1
            ORDER BY expires
            OFFSET   $2
            LIMIT    1;
        """

        entry = await ctx.db.fetchrow(query, str(ctx.author.id), index - 1)
        if entry is None:
            return await ctx.send(f'Reminder #{index} does not exist.')

        await ctx.bot.db_scheduler.remove(discord.Object(id=entry['id']))

        args_kwargs = json.loads(entry['args_kwargs'])
        _, channel_id, message = args_kwargs['args']
        channel = self.bot.get_channel(channel_id) or 'deleted-channel'
        server = getattr(channel, 'guild', None)

        embed = (discord.Embed(colour=0xFF0000, description=message, timestamp=entry['expires'])
                 .set_author(name=f'Reminder #{index} cancelled!', icon_url=CANCELED_URL)
                 .add_field(name='Was for', value=f'{channel.mention} in {server}')
                 .set_footer(text='Was set to go off at')
                 )

        await ctx.send(embed=embed)

    @commands.command()
    async def reminders(self, ctx):
        """Lists all the pending reminders that you currently have.

        Reminder that you've set to go off in 30 seconds or less will not be shown, however.
        """

        query = """
            SELECT   expires, args_kwargs #>> '{args,1}', args_kwargs #>> '{args,2}'
            FROM     scheduler
            WHERE    event = 'reminder_complete'
            AND      args_kwargs #>> '{args,0}' = $1
            ORDER BY expires;
        """
        reminders = await ctx.db.fetch(query, str(ctx.author.id))

        if not reminders:
            return await ctx.send("You have no reminders at the moment.")

        def entries():
            for i, (expires, channel_id, message) in enumerate(reminders, start=1):
                channel = f'<#{channel_id}>' if channel_id else 'Direct Message'

                name = f'{i}. In {human_timedelta(expires)} from now.'
                value = truncate(f'{channel}: {message}', 1024, '...')
                yield name, value

        pages = FieldPaginator(
            ctx, entries(),
            per_page=5, title=f'Reminders for {ctx.author}', inline=False
        )

        await pages.interact()

    async def on_reminder_complete(self, timer):
        user_id, channel_id, message = timer.args
        human_delta = human_timedelta(timer.created)

        if channel_id is None:
            user = self.bot.get_user(user_id)
            try:
                channel = await user.create_dm()
            except Exception:  # user was either gone or deleted
                return
        else:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                return

        is_private = isinstance(channel, discord.abc.PrivateChannel)
        destination_format = ('Direct Message' if is_private else f'#{channel} in {channel.guild}!')

        embed = (discord.Embed(description=message, colour=0x00ff00, timestamp=timer.utc)
                 .set_author(name=f'Reminder for {destination_format}', icon_url=ALARM_CLOCK_URL)
                 .set_footer(text=f'From {human_delta}.')
                 )

        try:
            await channel.send(f"<@{user_id}>", embed=embed)
        except discord.HTTPException:  # can't embed
            await channel.send(
                f'<@{user_id}> {human_delta} ago, you wanted to be reminded of **{message}**.'
            )


def setup(bot):
    bot.add_cog(Reminder(bot))
