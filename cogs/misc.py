import discord
from discord.ext import commands
from urllib.parse import quote
from utils.embed import EmbedUtils
from cogs.owner import Owner
import os
import psutil
from datetime import datetime
import random


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
                        "[Invite](https://discordapp.com/oauth2/authorize?client_id={self.bot.user.id}&scope=bot&permissions=2146958847) | "
                        f"[Creator: Vale#5252](https://www.twitch.tv/itsvaleee)"
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
                        f"\n```\n• Adding auto sharding.\n• Ability to search discord.py docs\n• A few bugfixes\n• Some dumb shit like sudo retard\n```"
        )

        await ctx.send(embed=embed)

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

        output = []
        for i in text:
            num = random.randint(1, 2)

            if num == 1:
                output.insert(len(output) + 1, i.upper())
            else:
                output.insert(len(output) + 1, i.lower())

        msg = "".join(output)
        await ctx.send(msg)

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
