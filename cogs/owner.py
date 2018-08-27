import discord
from discord.ext import commands
import logging
import traceback
import textwrap
from contextlib import redirect_stdout
from subprocess import check_output
import io
import platform
from utils.db import TableFormat


logger = logging.getLogger(__name__)


class Owner:
    """The commands from this cog can only be used by the bot owner."""

    def __init__(self, bot):
        self.bot = bot
        self._last_result = None

    @staticmethod
    def clean_code(code):
        """Returns the content from a codeblock."""

        if code.startswith("```") and code.endswith("```"):
            return "\n".join(code.split("\n")[1:-1])

        return code.strip("` \n")

    async def react(self, message: discord.Message, unicode: str):
        try:
            await message.add_reaction(unicode)
        except Exception:
            logger.error(f"Unable to add reaction {unicode} to the message with the content {message.content}")

    @staticmethod
    def get_version():
        os = platform.system()

        if os == "Windows":
            python = check_output("python3 --version").decode()
        elif os == "Linux" or os == "Darwin":
            python = check_output("python3 --version", shell=True).decode()
        else:
            python = "Unknown"

        return python

    def get_embed(self, body: str):
        """Generates a nice Embed for our eval output."""

        python = self.get_version()

        exec_embed = discord.Embed(title="Eval", description="━━━━━━━━━━━━━━━━━━━", color=0xffff00)
        exec_embed.add_field(name="Output:", value=body)
        exec_embed.set_footer(
            text=f"Python version: {python}",
            icon_url="https://www.python.org/static/opengraph-icon-200x200.png"
        )

        return exec_embed

    @commands.command(name="load")
    @commands.is_owner()
    async def _load(self, ctx, *, cog: str):
        """Loads a cog."""
        try:
            self.bot.load_extension(cog)
        except ImportError:
            await self.react(ctx.message, "\u274C")
            await ctx.send(f"The extension {cog} could not be imported. Maybe wrong path?")
        except discord.errors.ClientException:
            await self.react(ctx.message, "\u274C")
            await ctx.send(f"The extension {cog} must have a function setup!")
        else:
            await self.react(ctx.message, "\u2705")

    @commands.command(name="unload")
    @commands.is_owner()
    async def _unload(self, ctx, *, cog: str):
        """Unloads a cog"""
        try:
            self.bot.unload_extension(cog)
        except:
            await self.react(ctx.message, "\u274C")
            await ctx.send(f"```py\n{traceback.format_exc()}\n```")
        else:
            await self.react(ctx.message, "\u2705")

    @commands.command(name="reload")
    @commands.is_owner()
    async def _reload(self, ctx, *, cog: str):
        """Reloads a cog"""
        try:
            self.bot.unload_extension(cog)
            self.bot.load_extension(cog)
        except:
            await self.react(ctx.message, "\u274C")
            await ctx.send(f"```py\n{traceback.format_exc()}\n```")
        else:
            await self.react(ctx.message, "\u2705")

    @commands.command(name="eval")
    @commands.is_owner()
    async def _eval(self, ctx, *, code: str):
        """Evaluates Python code"""

        env = {
            "bot": self.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "self": self,
            "_": self._last_result
        }

        env.update(globals())

        body = self.clean_code(code)
        stdout = io.StringIO()

        to_eval = f"async def eval_func(self):\n{textwrap.indent(body, ' ')}"

        try:
            exec(to_eval, env)
        except Exception as e:
            embed = self.get_embed(f"```py\n{e.__class__.__name__}: {e}\n```")
            return await ctx.send(embed=embed)

        eval_func = env["eval_func"]
        try:
            with redirect_stdout(stdout):
                res = await eval_func(self)
        except:
            value = stdout.getvalue()

            await self.react(ctx.message, "\u274C")

            embed = self.get_embed(f"```py\n{value}{traceback.format_exc()}\n```")
            return await ctx.send(embed=embed)
        else:
            value = stdout.getvalue()
            await self.react(ctx.message, "\u2705")

            if res is None:
                if value:
                    embed = self.get_embed(f"```py\n{value}\n```")
                    return await ctx.send(embed=embed)
            else:
                self._last_result = res
                embed = self.get_embed(f"```py\n{value}{res}\n```")
                return await ctx.send(embed=embed)

    @commands.command(name="sql")
    @commands.is_owner()
    async def _sql(self, ctx, *, code: str):
        """Run SQL code."""

        query = self.clean_code(code)

        # if there are multiple queries, we'll use execute since fetch can only execute one query
        if query.count(";") > 1:
            sql = ctx.db.execute
        else:
            sql = ctx.db.fetch

        try:
            result = await sql(query)
        except:
            return await ctx.send(f"```py\n{traceback.format_exc()}\n```")

        rows = len(result)
        if query.count(";") > 1 or rows == 0:
            return await ctx.send(f"```py\n{result}\n```")

        headers = list(result[0].keys())
        table = TableFormat()
        table.set(headers)
        table.add(list(res.values()) for res in result)
        render = table.render()

        format_table = f"```\n{render}\n```"
        # if a query's result is too big for a message, we'll send it as a file
        if len(format_table) > 2000:
            f = io.BytesIO(format_table.encode("utf-8"))
            await ctx.send("Too many results", file=discord.File(f, "result.txt"))
        else:
            await ctx.send(format_table)


def setup(bot):
    bot.add_cog(Owner(bot))
