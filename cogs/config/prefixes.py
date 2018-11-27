import random
import string
from itertools import starmap

import discord
from discord.ext import commands

from utils.colors import random_color

_prefixes = list(set(string.punctuation) - {'@', '#'})


class Prefix(commands.Converter):
    async def convert(self, ctx, argument):
        if not argument:
            raise commands.BadArgument(f'You should actually provide a prefix..... {ctx.bot.bot_emojis.get("retard")}')

        if not argument.strip():
            raise commands.BadArgument('A space isn\'t a prefix you know...')

        if argument.startswith((f'<@{ctx.bot.user.id}>', f'<@!{ctx.bot.user.id}>', 'sudo')):
            raise commands.BadArgument('That is a reserved prefix already in use.')

        if len(argument) > 10:
            raise commands.BadArgument('Having prefixes with more than 10 characters is stupid.')

        return argument

    @staticmethod
    def random_example(ctx):
        return random.choice(_prefixes)


class RemovablePrefix(Prefix):
    @staticmethod
    def random_example(ctx):
        return random.choice(ctx.bot.get_guild_prefixes(ctx.guild.id))


class Prefixes:
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def create_fake_message(ctx):
        fake_msg = discord.Object(1234567890)
        fake_msg.guild = ctx.guild
        fake_msg.content = ctx.message.content

        return fake_msg

    @commands.group(name='prefix', invoke_without_command=True)
    async def _prefix(self, ctx):
        """Shows the prefixes that you can use in this server."""

        if ctx.invoked_subcommand:
            return

        prefixes = self.bot.get_guild_prefixes(ctx.guild)
        del prefixes[0]    # To make the mention not show up twice.

        description = '\n'.join(starmap('`{0}.` **{1}**'.format, enumerate(prefixes, 1)))
        embed = discord.Embed(title=f'Prefixes you can use in {ctx.guild}', description=description, color=random_color())
        await ctx.send(embed=embed)

    @_prefix.command(name='add', ignore_extra=False)
    @commands.has_permissions(manage_guild=True)
    async def _add_prefix(self, ctx, prefix: Prefix):
        """Adds a custom prefix for this server.

        If you want to have a word or multiple words as prefixes, you have to quote them. E.g. `"hello "`, `"vale py "`
        because Discord trims the whitespaces. They are not preserved.

        (Unless you want to do hellohelp or something like this...)
        """

        if prefix in self.bot.get_guild_prefixes(ctx.guild):
            return await ctx.send(f'`{prefix}` is already a custom prefix for this guild or it is reserved.')

        prefixes = self.bot.get_raw_guild_prefixes(ctx.guild.id)
        prefixes += (prefix, )
        if self.bot.default_prefix in prefixes:  # The thing is that we don't want to store our default prefix a second time
            prefixes.remove(self.bot.default_prefix)

        await self.bot.set_guild_prefixes(ctx.guild.id, prefixes)
        await ctx.send(f'Successfully added prefix `{prefix}`')

    @_prefix.command(name='remove', ignore_extra=False)
    @commands.has_permissions(manage_guild=True)
    async def _remove_prefix(self, ctx, prefix: RemovablePrefix):
        """Removes a prefix from this server.

        Note that you cannot remove reserved prefixes.
        """

        prefixes = self.bot.get_raw_guild_prefixes(ctx.guild.id)
        if not prefixes:
            return await ctx.send('There are no custom prefixes on this server.')

        try:
            prefixes.remove(prefix)
        except ValueError:
            return await ctx.send(f'There\'s no such prefix like `{prefix}` registered.')

        await self.bot.set_guild_prefixes(ctx.guild.id, prefixes)
        await ctx.send(f'Successfully removed `{prefix}`.')

    @_prefix.command(name='reset', aliases=['clear'])
    @commands.has_permissions(manage_guild=True)
    async def _reset_prefixes(self, ctx):
        """Clears all prefixes from this server."""

        await self.bot.set_guild_prefixes(ctx.guild.id, [])
        await ctx.message.add_reaction(self.bot.bot_emojis.get('success'))

    @_add_prefix.error
    @_remove_prefix.error
    async def prefix_error(self, ctx, error):
        if isinstance(error, commands.TooManyArguments):
            await ctx.send('Too many prefixes, you shitter! Put them in quotes or only provide one!')
        else:
            original = getattr(error, 'original', None)
            if original:
                await ctx.send(original)


def setup(bot):
    bot.add_cog(Prefixes(bot))
