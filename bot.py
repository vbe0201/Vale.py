#!/usr/bin/env python3

"""
Vale.py, a bot to support Discord servers that I like.
(c) Vale 2018
"""

import discord
from discord.ext import commands
import asyncio
import aiohttp
import asyncpg
import logging
import re
from datetime import datetime
from utils import config, db, context, presence

# For a faster event loop. Doesn't work on Windows.
try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

fmt = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(format=fmt, level=logging.INFO)

config = config.ConfigJson()

cogs = [
    "cogs.prefix",
    "cogs.error",
    "cogs.owner",
    "cogs.discordpy",
    "cogs.tags",
    "cogs.misc",
    "cogs.eval",
]


async def _get_prefix(bot, message):
    prefixes = []
    add = prefixes.append

    match = re.match(r"sudo\s+?", message.content)
    if bot.pool is not None and message.guild is not None:
        # Getting the guild-specific prefixes.
        guild_prefixes = await db.get_guild_prefixes(bot, message)
        prefixes.extend(guild_prefixes)

    if match:
        add(match.group())
    else:
        add("sudo")

    return commands.when_mentioned_or(*prefixes)(bot, message)


async def run():
    """Actually runs the bot and creates a connection pool for a PostgreSQL database as well as the config file."""

    settings = config.create_config()

    login_data = {
        "user": settings["pg_user"],
        "password": settings["pg_pass"],
        "database": settings["pg_db"],
        "host": settings["pg_host"],
        "port": settings["pg_port"]
    }

    pool = await asyncpg.create_pool(**login_data)

    description = "Hello, I was coded by Vale#5252 to support Discord server that he likes."

    bot = ValePy(
        description=description, pool=pool,
        owner_id=int(settings["owner_id"]),
        client_id=settings["jdoodle_client"],
        client_secret=settings["jdoodle_secret"]
    )

    try:
        await bot.start(settings["token"])
    except KeyboardInterrupt:
        await pool.close()
        await bot.logout()


class ValePy(commands.AutoShardedBot):
    """This is a subclass of commands.Bot to give more freedom in customizing it."""
    def __init__(self, **kwargs):
        super().__init__(
            command_prefix=_get_prefix,
            description=kwargs.pop("description"),
            case_insensitive=True,
            owner_id=kwargs.pop("owner_id"),
            fetch_offline_members=False
        )

        self.pool = kwargs.pop("pool")
        self.version = "0.2b"
        self.launch = datetime.utcnow()
        self.presence_manager = None    # Will be set later.
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.jdoodle_client = kwargs.pop("client_id")
        self.jdoodle_secret = kwargs.pop("client_secret")

        for cog in cogs:
            try:
                self.load_extension(cog)
            except ImportError:
                logging.error(f"The extension {cog} could not be imported. Maybe wrong path?")
            except discord.errors.ClientException:
                logging.error(f"The extension {cog} must have a function setup!")

    async def on_ready(self):
        logging.info(f"\n====================\nLogged in as:\n{self.user.name}\n{self.user.id}\n====================\n")
        await self.wait_until_ready()

        if self.presence_manager is None:
            self.presence_manager = presence.Presence(self)

        await self.presence_manager.change_status()

        if not hasattr(self, 'launch'):
            self.launch = datetime.utcnow()

    async def on_message(self, message):
        if message.author.bot:
            return

        await self.process_commands(message)

    async def process_commands(self, message: discord.Message):
        """This method is overloaded to be able to pass our own context to the commands. It will make things easier."""

        ctx = await self.get_context(message, cls=context.Context)
        if ctx.command is None:
            if ctx.message.content.startswith(self.user.mention):
                # Send a ping emote.
                await ctx.send("<:ValePing:488418658574663690>")
            return

        async with ctx.acquire():  # Acquire the pool from the database connection
            await self.invoke(ctx)

    async def logout(self):
        await super().logout()
        await self.pool.close()
        await self.session.close()


asyncio.get_event_loop().run_until_complete(run())
