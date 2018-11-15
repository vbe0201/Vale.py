import logging
import re

import discord
import lxml.etree as etree
from discord.ext import commands

from utils.colors import random_color
from utils.formats import finder

logger = logging.getLogger(__name__)

BASE_URL = 'https://discordpy.readthedocs.io/'

# TODO: Probably put these values into an Enum.
# discord.py pages used to build documentation cache
PAGE_TYPES = {
    'rewrite': (
        'en/rewrite/api.html',
        'en/rewrite/ext/commands/api.html',
    ),
    'latest': (
        'en/latest/api.html',
    )
}

# Helpers to convert search terms to the proper documentation keys
HELPERS = {
    'vc': 'VoiceClient',
    'msg': 'Message',
    'color': 'Color',
    'perms': 'Permissions',
    'channel': 'TextChannel',
}


class DiscordPy:
    """discord.py-related stuff"""

    def __init__(self, bot):
        self.bot = bot
        self._docs_cache = None
        self.faq_entries = None

    async def build_docs_cache(self, ctx):
        """Builds the documentation cache."""

        cache = {}
        for branch, pages in PAGE_TYPES.items():
            sub = cache[branch] = {}

            for page in pages:
                page = BASE_URL + page

                resp = await ctx.session.get(page)
                if resp.status != 200:
                    return await ctx.send('Unable to build documentation cache.')

                text = await resp.text(encoding='utf-8')
                root = etree.fromstring(text, etree.HTMLParser())
                nodes = root.iterfind(".//dt/a[@class='headerlink']")

                for node in nodes:
                    href = node.get('href', '')
                    key = href.replace('#discord.', '').replace('ext.commands.', '')
                    sub[key] = page + href

        self._docs_cache = cache

    async def search_docs(self, ctx, branch, search):
        if not search:
            return await ctx.send(BASE_URL + branch)

        if not self._docs_cache:
            await ctx.trigger_typing()
            await self.build_docs_cache(ctx)

        search = search.replace(' ', '_')

        if branch == 'rewrite':
            lower = search.lower()
            if hasattr(discord.abc.Messageable, lower):
                search = f'abc.Messageable.{lower}'

            def replace(o):
                return HELPERS.get(o.group(0), '')

            pattern = re.compile('|'.join(rf'\b{key}\b' for key in HELPERS))
            search = pattern.sub(replace, search)

        cache = self._docs_cache[branch]
        matches = finder(search, cache, count=10)
        if not matches:
            return await ctx.send('I\'m sorry but I couldn\'t find anything that matches what you are looking for.')

        description = '━━━━━━━━━━━━━━━━━━━\n' + '\n'.join(f'[{key}]({url})' for key, url in matches)
        embed = discord.Embed(title='discord.py documentation search', description=description, color=random_color())
        await ctx.send(embed=embed)

    @commands.group(name='docs', aliases=['rtd', 'rtfd', 'rtfm'], invoke_without_command=True)
    async def _docs(self, ctx, *, search=None):
        """Searches the discord.py docs and lists the results in an embed.

        If no search keys are provided, it will give you the documentation link.

        This will search the discord.py async docs.
        """

        await self.search_docs(ctx, 'latest', search)

    @_docs.command(name='rewrite')
    async def _docs_rewrite(self, ctx, *, search=None):
        """Searches the discord.py docs and lists the results in an embed.

        If no search keys are provided, it will give you the documentation link.

        This will search the discord.py rewrite docs.
        """

        await self.search_docs(ctx, 'rewrite', search)


def setup(bot):
    bot.add_cog(DiscordPy(bot))
