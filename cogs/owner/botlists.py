import asyncio
import json
import logging

logger = logging.getLogger(__name__)

DISCORD_BOT_LIST_URL = 'https://discordbots.org/api/'


class Botlists:
    def __init__(self, bot):
        self.bot = bot
        self._handlers = []

        import config

        dbl_key = config.dbl_key
        assert dbl_key, 'No key was specified.'

        # For later when the bot is in more bot lists.
        if dbl_key:
            self._dbl_key = dbl_key
            self._handlers.append(self._update_dbl)

    async def _update_dbl(self):
        headers = {
            'Authorization': self._dbl_key,
            'Content-Type': 'application/json'
        }

        data = json.dumps({
            'server_count': self.bot.guild_count,
            'shard_count': len(self.bot.shards)
        })

        result = await self.bot.session.post(f'{DISCORD_BOT_LIST_URL}bots/{self.bot.user.id}/stats', headers=headers, data=data)
        logger.info('Discord Bot List stats returned %s for %s', result.status, data)

    async def update(self):
        await asyncio.gather(*(handler() for handler in self._handlers))

    async def on_guild_join(self, guild):
        await self.update()

    async def on_guild_remove(self, guild):
        await self.update()

    async def on_ready(self):
        await self.update()


def setup(bot):
    import config

    if config.dbl_key:
        bot.add_cog(Botlists(bot))
