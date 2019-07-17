"""
This cog is just for the Clamor guild.
It's for management-related things and some nice utilities.

Clamor is a Discord API library for Python.
https://github.com/clamor-py/Clamor

And here's an invite to the support server
https://discord.gg/HbKGrVT
"""

import re
from functools import wraps

import discord
from discord.ext import commands

DE_INVITE_CODE = 'ZE2eYtz'

CLAMOR_GUILD_ID = 486621752202625024
CLAMOR_BOT_ROLE = 505062783201837056
CLAMOR_GERMAN_ROLE = 493854126116175883
CLAMOR_HELPER_ROLE = 490678567093665797

fmt = re.compile(r'##(?P<number>[0-9]+)')


def find_issue(func):
    @wraps(func)
    async def decorator(self, message):
        # Kinda abuse but it's the simplest way
        if not message.guild or message.guild.id != CLAMOR_GUILD_ID:
            return

        match = fmt.match(message.content)
        if match:
            url = 'https://github.com/clamor-py/Clamor/issues/' + match.group('number')
            await message.channel.send(url)

        return await func(self, message)

    return decorator


class ClamorExclusive(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot
        self._invite_cache = {}
        self.invites_task = self.bot.loop.create_task(self._prepare_invites())

    def cog_check(self, ctx):
        return ctx.guild and ctx.guild.id == CLAMOR_GUILD_ID

    async def _prepare_invites(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(CLAMOR_GUILD_ID)
        invites = await guild.invites()

        self._invite_cache = {
            invite.code: invite.uses
            for invite in invites
        }

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Only the CLAMOR guild is interesting
        if member.guild.id != CLAMOR_GUILD_ID:
            return

        # Automatically assign bots the `Running on Clamor` role when they're invited to the guild.
        if member.bot:
            await member.add_roles(discord.Object(CLAMOR_BOT_ROLE))
            return

        invites = await member.guild.invites()
        for invite in invites:
            if invite.code in DE_INVITE_CODE and invite.uses > self._invite_cache[invite.code]:
                await member.add_roles(discord.Object(CLAMOR_GERMAN_ROLE))

            self._invite_cache[invite.code] = invite.uses

    @commands.Cog.listener()
    @find_issue
    async def on_message(self, message):
        # This listener is just here because of the issue/pull request search for the Clamor GitHub repo.

        pass

    @staticmethod
    async def toggle_role(ctx, role_id):
        if any(r.id == role_id for r in ctx.author.roles):
            try:
                await ctx.author.remove_roles(discord.Object(id=role_id))
            except Exception:  # muh pycodestyle
                await ctx.message.add_reaction('\N{NO ENTRY SIGN}')
            else:
                await ctx.message.add_reaction('\N{HEAVY MINUS SIGN}')
            finally:
                return

        try:
            await ctx.author.add_roles(discord.Object(id=role_id))
        except Exception:  # muh pycodestyle
            await ctx.message.add_reaction('\N{NO ENTRY SIGN}')
        else:
            await ctx.message.add_reaction('\N{HEAVY PLUS SIGN}')

    @commands.command(name='kartoffelbauer')
    async def _kartoffelbauer(self, ctx):
        """Gives you the `Kartoffelbauer` role.

        This is necessary to get write access to the `Kartoffelecke`, a category with channels for german people.
        Please only assign yourself that role if you actually do speak german.
        *Shitposting or broken Google Translator German won't be tolerated!*

        **Only usable on the Clamor server!**
        """

        await self.toggle_role(ctx, CLAMOR_GERMAN_ROLE)

    @commands.command(name='helper')
    async def _clamor_helper(self, ctx):
        """Gives you the `Clamor Helper` role.

        For explanation, our system in providing help for people is the following:
          - Someone asks a question or needs help with a problem
          - Nobody responds within 20 minutes or nobody is able to answer the question
          - The person is allowed to ping the Clamor Helper role.

        **So please only assign yourself this role if you are fine with being pinged and if you are willing to help!**

        **Only usable on the Clamor server!**
        """

        await self.toggle_role(ctx, CLAMOR_HELPER_ROLE)


def setup(bot):
    bot.add_cog(ClamorExclusive(bot))
