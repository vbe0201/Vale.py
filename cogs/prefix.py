from discord.ext import commands
import asyncio
from utils.checks import Checks
import logging

logger = logging.getLogger(__name__)


class PrefixManagement:
    """A cog for managing the specific prefixes for a guild."""

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def _create_table(pool):
        query = """CREATE TABLE IF NOT EXISTS guild_prefixes (guild_id BIGINT NOT NULL, prefixes TEXT[] NOT NULL, PRIMARY KEY (guild_id));"""
        await pool.execute(query)

    @classmethod
    def set_prefixes(cls, *, check=False, sql_result=None, prefixes):
        new_prefixes = []
        changes = []

        if check:
            if not sql_result:
                logger.error("sql_result is a required argument that is missing.")
                return

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

    @commands.group(name="prefix")
    @commands.guild_only()
    async def _prefixes(self, ctx):
        # A command group for all prefix-relating commands
        if ctx.invoked_subcommand is None:
            await ctx.send(f"Usage:\n```\nprefix <list | add | remove>\n```")

    @_prefixes.command(name="list")
    @commands.guild_only()
    async def _list_prefixes(self, ctx):
        # List all prefixes that are available for this guild
        prefixes = await self.bot.get_prefix(ctx.message)
        await ctx.send(f"The following prefixes are available on this guild: {', '.join(prefixes)}")

    @_prefixes.command(name="add")
    @commands.guild_only()
    async def _add_prefix(self, ctx, *prefixes: str):
        if prefixes is None:
            return await ctx.send("Please enter the prefixes that should be added for this guild!")

        query = """SELECT prefixes FROM guild_prefixes WHERE guild_id = $1;"""
        async with ctx.db.transaction():
            guild_prefixes = await ctx.pool.fetch(query, ctx.guild.id)

            if not guild_prefixes or not guild_prefixes[0]["prefixes"]:
                result = self.set_prefixes(prefixes=prefixes)
            else:
                result = self.set_prefixes(check=True, sql_result=guild_prefixes[0]["prefixes"], prefixes=prefixes)

            query = """INSERT INTO guild_prefixes (guild_id, prefixes) VALUES ($1, $2::TEXT[]) ON CONFLICT
                    (guild_id) DO UPDATE SET prefixes = $3::TEXT[];"""
            await ctx.pool.execute(query, ctx.guild.id, result[0], result[0])

        await ctx.send(f"The prefixes `{', '.join(result[1])}` were successfully added!")

    @_prefixes.command(name="remove")
    @commands.guild_only()
    @Checks.has_permissions(manage_guild=True)
    async def _remove_prefix(self, ctx, *prefixes: str):
        # Removes guild-specific prefixes
        if prefixes is None:
            return await ctx.send("Please enter the prefixes you want to remove.")

        query = """SELECT prefixes FROM guild_prefixes WHERE guild_id = $1;"""
        async with ctx.db.transaction():
            guild_prefixes = await ctx.db.fetch(query, ctx.guild.id)

            if not guild_prefixes or not guild_prefixes[0]["prefixes"]:
                return await ctx.send("There are no specific prefixes for this guild.")
            else:
                result = await self.remove_prefixes(ctx, guild_prefixes[0]["prefixes"], prefixes)

                query = """UPDATE guild_prefixes SET prefixes = $1::TEXT[] WHERE guild_id = $2;"""
                await ctx.db.execute(query, result[0], ctx.guild.id)

            await ctx.send(f"The prefixes `{', '.join(result[1])}` were successfully removed!")


def setup(bot):
    asyncio.ensure_future(PrefixManagement._create_table(bot.pool), loop=bot.loop)
    bot.add_cog(PrefixManagement(bot))
