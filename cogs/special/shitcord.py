"""
This cog is just for the Shitcord guild.
It's for management-related things and some nice utilities.

Shitcord is a Discord API library for Python.
https://github.com/itsVale/Shitcord

And here's an invite to the support server
https://discord.gg/HbKGrVT
"""

import re
from functools import wraps

import discord
from discord.ext import commands

DE_INVITE_CODE = 'ZE2eYtz'

SHITCORD_GUILD_ID = 486621752202625024
SHITCORD_DEFAULT_ROLE = 490678926843052035
SHITCORD_UPDATES_ROLE = 486643133270982657
SHITCORD_BOT_ROLE = 505062783201837056
SHITCORD_GERMAN_ROLE = 493854126116175883
SHITCORD_HELPER_ROLE = 490678567093665797

fmt = re.compile(r'##(?P<number>[0-9]+)')


def find_issue(func):
    @wraps(func)
    async def decorator(self, message):
        # Kinda abuse but it's the simplest way
        if not message.guild or message.guild.id != SHITCORD_GUILD_ID:
            return

        match = fmt.match(message.content)
        if match:
            url = 'https://github.com/itsVale/Shitcord/issues/' + match.group('number')
            await message.channel.send(url)

        return await func(self, message)

    return decorator


class ShitcordExclusive:
    def __init__(self, bot):
        self.bot = bot
        self._invite_cache = {}
        self.invites_task = self.bot.loop.create_task(self._prepare_invites())

    def __local_check(self, ctx):
        return ctx.guild and ctx.guild.id == SHITCORD_GUILD_ID

    async def _prepare_invites(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(SHITCORD_GUILD_ID)
        invites = await guild.invites()

        self._invite_cache = {
            invite.code: invite.uses
            for invite in invites
        }

    async def on_member_join(self, member):
        # Only the Shitcord guild is interesting
        if member.guild.id != SHITCORD_GUILD_ID:
            return

        # Automatically assign bots the `Running on Shitcord` role when they're invited to the guild.
        if member.bot:
            await member.add_roles(discord.Object(SHITCORD_BOT_ROLE))
            return

        # Assign the default `Shitter` role to new members.
        await member.add_roles(discord.Object(SHITCORD_DEFAULT_ROLE))

        invites = await member.guild.invites()
        for invite in invites:
            if invite.code in DE_INVITE_CODE and invite.uses > self._invite_cache[invite.code]:
                await member.add_roles(discord.Object(SHITCORD_GERMAN_ROLE))

            self._invite_cache[invite.code] = invite.uses

    @find_issue
    async def on_message(self, message):
        # This listener is just here because of the issue/pull request search for the Shitcord GitHub repo.

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

    @commands.command(name='shitupdates', hidden=True)
    async def _shitupdates(self, ctx):
        """Gives you the `Shitupdates` role.

        Necessary to receive notifications about Shitcord updates.

        **Only usable on the Shitcord server!**
        """

        await self.toggle_role(ctx, SHITCORD_UPDATES_ROLE)

    @commands.command(name='kartoffelbauer', hidden=True)
    async def _kartoffelbauer(self, ctx):
        """Gives you the `Kartoffelbauer` role.

        This is necessary to get write access to the `Kartoffelecke`, a category with channels for german people.
        Please only assign yourself that role if you actually do speak german.
        *Shitposting or broken Google Translator German won't be tolerated!*

        **Only usable on the Shitcord server!**
        """

        await self.toggle_role(ctx, SHITCORD_GERMAN_ROLE)

    @commands.command(name='helper', hidden=True)
    async def _shitcord_helper(self, ctx):
        """Gives you the `Shitcord Helper` role.

        For explanation, our system in providing help for people is the following:
          - Someone asks a question or needs help with a problem
          - Nobody responds within 20 minutes or nobody is able to answer the question
          - The person is allowed to ping the Shitcord Helper role.

        **So please only assign yourself this role if you are fine with being pinged and if you are willing to help!**

        **Only usable on the Shitcord server!**
        """

        await self.toggle_role(ctx, SHITCORD_HELPER_ROLE)


def setup(bot):
    bot.add_cog(ShitcordExclusive(bot))
