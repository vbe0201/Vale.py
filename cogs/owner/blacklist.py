from datetime import datetime

import asyncpg
import discord
from discord.ext import commands

from utils import db, disambiguate
from utils.colors import random_color
from utils.misc import emoji_url, truncate


class Blacklist(db.Table):
    snowflake = db.Column(db.BigInt, primary_key=True)
    blacklisted_when = db.Column(db.Timestamp)
    reason = db.Column(db.Text, nullable=True)


_blocked_icon = emoji_url('\N{NO ENTRY}')
_unblocked_icon = emoji_url('\N{WHITE HEAVY CHECK MARK}')


class Blacklisted(commands.CheckFailure):
    def __init__(self, message, reason, *args):
        self.message = message
        self.reason = reason
        super().__init__(message, *args)

    def to_embed(self):
        embed = (discord.Embed(description=self.reason, color=random_color())
                 .set_author(name=self.message, icon_url=_blocked_icon))

        if self.reason:
            embed.description = self.reason

        return embed


_GuildOrUser = disambiguate.Union(discord.Guild, discord.User)


class Blacklists:
    def __init__(self, bot):
        self.bot = bot

    @property
    def emojis(self):
        return self.bot.bot_emojis

    async def __local_check(self, ctx):
        return await ctx.bot.is_owner(ctx.author)

    async def __global_check_once(self, ctx):
        row = await self.get_blacklist(ctx.author.id, con=ctx.db)
        if row:
            raise Blacklisted('You have been blacklisted by my owner.', row['reason'])

        if not ctx.guild:
            return True

        row = await self.get_blacklist(ctx.guild.id, con=ctx.db)
        if row:
            raise Blacklisted('This server has been blacklisted by my owner.', row['reason'])

        return True

    async def on_command_error(self, ctx, error):
        if isinstance(error, Blacklisted):
            await ctx.send(embed=error.to_embed())

    async def get_blacklist(self, snowflake, *, con):
        query = 'SELECT reason FROM blacklist WHERE snowflake = $1;'
        return await con.fetchrow(query, snowflake)

    async def _blacklist_embed(self, ctx, action, icon, thing, reason, time):
        type_name = 'Server' if isinstance(thing, discord.Guild) else 'User'
        reason = truncate(reason, 1024, '...') if reason else 'None'

        embed = (discord.Embed(timestamp=time, color=random_color())
                 .set_author(name=f'{type_name} {action}', icon_url=icon)
                 .add_field(name='Name:', value=thing)
                 .add_field(name='ID:', value=thing.id)
                 .add_field(name='Reason:', value=reason, inline=False))
        await ctx.send(embed=embed)

    @commands.command(name='blacklist', aliases=['bl', 'block'])
    async def _blacklist(self, ctx, server_or_user: _GuildOrUser, *, reason=''):
        """Blacklists either a server or a user from using the bot."""

        if await self.bot.is_owner(server_or_user):
            return await ctx.send('You can\'t blacklist my owner, you shitter.')

        time = datetime.utcnow()
        query = 'INSERT INTO blacklist VALUES ($1, $2, $3);'

        try:
            await ctx.db.execute(query, server_or_user.id, time, reason)
        except asyncpg.UniqueViolationError:
            return await ctx.send(f'{server_or_user} has already been blacklisted.')
        else:
            await self._blacklist_embed(ctx, 'blacklisted', _blocked_icon, server_or_user, reason, time)

    @commands.command(name='unblacklist', aliases=['ubl', 'unblock'])
    async def _unblacklist(self, ctx, server_or_user: _GuildOrUser, *, reason=''):
        """Unblacklists either a server or a user."""

        if await self.bot.is_owner(server_or_user):
            return await ctx.send(f'You can\'t even block my owner, so you can\'t unblock him. {self.emojis.get("smart")}')

        query = 'DELETE FROM blacklist WHERE snowflake = $1;'
        result = await ctx.db.execute(query, server_or_user.id)

        if result[-1] == '0':
            return await ctx.send(f'{server_or_user} isn\'t blacklisted.')

        await self._blacklist_embed(ctx, 'unblacklisted', _unblocked_icon, server_or_user, reason, datetime.utcnow())


def setup(bot):
    bot.add_cog(Blacklists(bot))
