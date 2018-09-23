import discord
from discord.ext import commands
from utils.checks import Checks
from utils import db
import logging
import io

logger = logging.getLogger(__name__)


class GuildPrefixesList(db.Table, table_name="guild_prefixes"):
    guild_id = db.Column(db.BigInt, primary_key=True)
    prefixes = db.Column(db.Array(db.Text))


class PrefixManagement:
    """A cog for managing the specific prefixes for a guild."""

    def __init__(self, bot):
        self.bot = bot

    @classmethod
    async def set_prefixes(cls, ctx, *, check=False, sql_result=None, prefixes):
        new_prefixes = []
        changes = []

        if check:
            if not sql_result:
                logger.error("sql_result is a required argument that is missing.")
                return

            if len(sql_result) + len(prefixes) > 5:
                return await ctx.send("Not more than 5 custom prefixes per guild.")

            new_prefixes.extend(sql_result)
            for prefix in prefixes:
                new_prefixes.append(prefix)
                changes.append(prefix)
        else:
            new_prefixes.extend(prefixes)
            changes.extend(prefixes)

        return [new_prefixes, changes]

    @classmethod
    async def remove_prefixes(cls, ctx, sql_result, prefixes):
        changes = []

        for prefix in prefixes:
            if prefix in sql_result:
                changes.append(prefix)
                sql_result.remove(prefix)
            else:
                return await ctx.send("You can't remove these prefixes. Either they don't exist or they are protected.")

        return [sql_result, changes]

    @staticmethod
    async def _format_result(ctx, action: str, prefixes: str):
        if len(prefixes) > 1500:
            file = io.BytesIO(prefixes.encode("utf-8"))
            await ctx.send(f"The following prefixes were successfully {action}:", file=discord.File(file, "prefixes.txt"))
        else:
            await ctx.send(f"The following prefixes were successfully {action}: `{prefixes}`")

    @staticmethod
    async def _list_result(ctx, prefixes):
        if len(prefixes) > 1950:
            file = io.BytesIO(prefixes.encode("utf-8"))
            await ctx.send(f"The following prefixes are available on this guild:", file=discord.File(file, "prefixes.txt"))
        else:
            await ctx.send(f"The following prefixes are available on this guild:\n```\n{prefixes}\n```")

    @commands.group(name="prefix")
    @commands.guild_only()
    async def _prefixes(self, ctx):
        """A command group for all prefix-related commands."""
        if ctx.invoked_subcommand is None:
            return

    @_prefixes.command(name="list")
    @commands.guild_only()
    async def _list_prefixes(self, ctx):
        """Lists all prefixes that are available for this guild."""

        prefixes = await self.bot.get_prefix(ctx.message)
        return await self._list_result(ctx, (', '.join(prefixes)))

    @_prefixes.command(name="add")
    @commands.guild_only()
    async def _add_prefix(self, ctx, *prefixes: commands.clean_content):
        """Adds guild-specific prefixes. Cannot have more than 5 per guild."""

        if prefixes is None:
            return await ctx.send("Please enter the prefixes that should be added for this guild!")
        elif len(prefixes) > 10:
            return await ctx.send("You cannot add more than 10 prefixes at the same time, mate.")

        for prefix in prefixes:
            if len(prefix) > 10:
                return await ctx.send("I think the prefixes you want to add contain too many characters. Cool it.")

        query = """SELECT prefixes FROM guild_prefixes WHERE guild_id = $1;"""
        async with ctx.db.transaction():
            guild_prefixes = await ctx.pool.fetch(query, ctx.guild.id)

            if not guild_prefixes or not guild_prefixes[0]["prefixes"]:
                result = await self.set_prefixes(ctx, prefixes=prefixes)
            else:
                result = await self.set_prefixes(ctx, check=True, sql_result=guild_prefixes[0]["prefixes"], prefixes=prefixes)

            query = """INSERT INTO guild_prefixes (guild_id, prefixes) VALUES ($1, $2::TEXT[]) ON CONFLICT
                    (guild_id) DO UPDATE SET prefixes = $3::TEXT[];"""
            await ctx.pool.execute(query, ctx.guild.id, result[0], result[0])

        await self._format_result(ctx, "added", (', '.join(result[1])))

    @_prefixes.command(name="remove")
    @commands.guild_only()
    @Checks.has_permissions(manage_guild=True)
    async def _remove_prefix(self, ctx, *prefixes: str):
        """Removes guild-specific prefixes."""

        if prefixes is None:
            return await ctx.send("Please enter the prefixes you want to remove.")
        elif len(prefixes) > 10:
            return await ctx.send("You cannot remove more than 10 prefixes at the same time, mate.")

        query = """SELECT prefixes FROM guild_prefixes WHERE guild_id = $1;"""
        async with ctx.db.transaction():
            guild_prefixes = await ctx.db.fetch(query, ctx.guild.id)

            if not guild_prefixes or not guild_prefixes[0]["prefixes"]:
                return await ctx.send("There are no specific prefixes for this guild.")
            else:
                result = await self.remove_prefixes(ctx, guild_prefixes[0]["prefixes"], prefixes)

                query = """UPDATE guild_prefixes SET prefixes = $1::TEXT[] WHERE guild_id = $2;"""
                await ctx.db.execute(query, result[0], ctx.guild.id)

            await self._format_result(ctx, "removed", (', '.join(result[1])))


def setup(bot):
    GuildPrefixesList.build(bot)
    bot.add_cog(PrefixManagement(bot))
