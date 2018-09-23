import discord
from discord.ext import commands
from urllib.parse import quote
from utils.embed import EmbedUtils
from cogs.owner import Owner
import os
import inspect
import psutil
import asyncio
from asyncio.subprocess import PIPE
from datetime import datetime
import random


class CommandOrCog(commands.Converter):
    async def convert(self, ctx, argument):

        command = ctx.bot.get_command(argument)

        if command is not None:
            code = inspect.getsourcelines(command.callback)
            return code[0]
        else:
            cog = ctx.bot.get_cog(argument)
            if cog is None:
                raise commands.BadArgument()

            code = inspect.getsourcelines(cog.__class__)
            return code[0]


class Miscellaneous:
    """A class with all shitty and stupid commands that fit nowhere else."""
    def __init__(self, bot):
        self.bot = bot

    def uptime(self):
        delta_uptime = datetime.utcnow() - self.bot.launch
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        return f"{days} days, {hours} hours, {minutes} minutes, {seconds} seconds"

    @commands.command(name="stats", aliases=["statistics"], invoke_without_command=True)
    async def _stats(self, ctx):
        """Shows some stats about the bot."""

        process = psutil.Process(os.getpid())
        memory = process.memory_info().rss / float(2**20)

        embed = discord.Embed(
            title=f"<:statistics:480855204594581516> {self.bot.user.name}'s stats",
            color=EmbedUtils.random_color(),
            description="[GitHub-Repository](https://github.com/itsVale/Vale.py) | "
                        f"[Invite](https://discordapp.com/oauth2/authorize?client_id={self.bot.user.id}&scope=bot&permissions=2146958847) | "
                        f"[Creator: Vale#5252](https://www.twitch.tv/itsvaleee)\n\n"
                        f"**Vale.py's currently looking out for contributors! Request new features by creating issues or fix shitcode. Thank you!**"
                        "\n━━━━━━━━━━━━━━━━━━━\n\n"
                        f"<:version:480852031742017546> Version: **{self.bot.version}**\n"
                        f"<:green_dot:480852448198524929> Online for: **{self.uptime()}**\n"
                        f"<:signal:480853405863247872> Latency: **{round(self.bot.latency * 1000)}ms**\n"
                        f"<:server:480853504693501963> Guilds: **{len(self.bot.guilds)}**\n"
                        f"<:cpu:480852762284916763> CPU usage: **{psutil.cpu_percent()}%**\n"
                        f"<:memory:480852912428417035> RAM usage: **{round(memory, 2)} mb**\n"
                        f"<:shard:483733328151707648> Shard count: **{int(self.bot.shard_count)}**\n"
                        f"<:py:481154314593763355> Python version: **{Owner.get_version().rstrip()}**\n"
                        f"<:discordpy:481163331693182977> discord.py version: **{discord.__version__}**\n"
                        f"\n<:announcement:480853853408067605> Recent updates: "
                        f"\n```css\n• Making the prefix add command idiot-safe\n"
                        f"• Ability to search cogs and commands of Vale.py\n"
                        f"• A few code improvements\n"
                        f"• See what happens if you ping Vale.py without a command."
                        f"```"
        )

        await ctx.send(embed=embed)

    @commands.command(name="ping")
    async def _ping(self, ctx):
        """Shows an actual, real ping to discordapp.com"""

        process = await asyncio.create_subprocess_shell("ping https://discordapp.com/ -c 10", stdout=PIPE, stderr=PIPE, loop=self.bot.loop)
        await ctx.trigger_typing()

        try:
            future = process.communicate()
            stdout, stderr = await asyncio.wait_for(future, 60, loop=self.bot.loop)
        except Exception as e:
            return await ctx.send(f"An error occurred while processing this command: {e}")

        embed = discord.Embed(description=f"```\n{stdout.decode()}\n```", color=EmbedUtils.random_color())
        await ctx.send(embed=embed)

    @commands.command(name="source", aliases=["skid"])
    async def _source(self, ctx, *, command: CommandOrCog):
        """Retrieves the source code for a given command or cog of Vale.py"""

        paginator = commands.Paginator(prefix="```py", suffix="```")
        for line in command:
            paginator.add_line(line.rstrip().replace("`", "\u200b`"))

        for page in paginator.pages:
            await ctx.send(page)

    @commands.command(name="lmgtfy", aliases=["google", "search"])
    async def _lmgtfy(self, ctx, *args):
        """Shows how to google for some shit to an idiot."""

        if not args:
            return await ctx.send("This command requires arguments on what to google.")

        query = quote(" ".join(args))
        await ctx.send("Someone who doesn't know how to google, huh? Let me show you how to do it, mate.\n"
                       f"<http://lmgtfy.com/?q={query}>")

    @commands.command(name="retard")
    async def _retard(self, ctx, *, text: str):
        """Translates some normal text to retard language."""

        await ctx.send("".join([random.choice([char.upper(), char.lower()]) for char in text]))

    @commands.command(name="retard2")
    async def _retard2(self, ctx, *sentence: str):
        """The fucking next generation of retard language."""

        if not sentence:
            return await ctx.send("Please add words that should be translated into the ultimate retard sentence.")

        words = list(sentence)
        random.shuffle(words)

        await ctx.send(" ".join(words))


def setup(bot):
    bot.add_cog(Miscellaneous(bot))
