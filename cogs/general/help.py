import discord
from discord.ext import commands

from utils.colors import random_color
from utils.converter import Category
from utils.help import CogPages, help_command


class Help:
    def __init__(self, bot):
        self.bot = bot
        self.bot.remove_command('help')
        self.bot.remove_command('h')

    help = help_command(name='help', aliases=['h'])

    async def _invite_embed(self, ctx):
        embed = (discord.Embed(description=self.bot.description, color=random_color())
                 .add_field(name='Want me in your server?', value=f'[Click me]({self.bot.invite_url})', inline=False)
                 .add_field(name='Invite me only with core perms', value=f'[Click me]({self.bot.minimal_invite_url})', inline=False)
                 .add_field(name='Need help with this shitbot?', value=f'[Join the official support server]({self.bot.support_server})', inline=False)
                 .add_field(name='Curious about how Vale ~~skidded~~ wrote this bot?',
                            value=f'Check out my source code [here]({self.bot.source})', inline=False)
                 )
        await ctx.send(embed=embed)

    @commands.command(name='invite')
    async def invite(self, ctx):
        """Get some additional information about this bot.

        Will give you invite links and source code.
        """

        if ctx.bot_has_embed_links():
            await self._invite_embed(ctx)
        else:
            content = (
                'Alright, my friends. Spamping this shithead who doesn\'t allow me to send embeds!'
                f'Invite me with full permissions: <{self.bot.invite_url}>'
                f'Invite me with minimal permissions: <{self.bot.minimal_invite_url}>'
                f'Here\'s the source code, `{self.bot.creator}` has ~~skidded from other bots~~ written: <{self.bot.source}>'
            )
            await ctx.send(content)

    @commands.command(name='commands', aliases=['cmds'])
    async def _commands(self, ctx, *, category: Category = None):
        """Shows all commands in a given category.

        If no category is provided, this lists all commands.
        """

        if not category:
            return await ctx.invoke(self.help)

        paginator = await CogPages.create(ctx, category)
        await paginator.interact()


def setup(bot):
    bot.add_cog(Help(bot))
