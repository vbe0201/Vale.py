import logging
import re
import discord

from discord.ext import commands
import lxml.etree as etree

from utils.embed import EmbedUtils


logger = logging.getLogger(__name__)

BASE_URL = "https://discordpy.readthedocs.io"

# Discord pages used to build documentation cache
PAGE_TYPES = {
    "rewrite": (
        "en/rewrite/api.html",
        "en/rewrite/ext/commands/api.html"
    ),
    "latest": (
        "en/latest/api.html",
    )
}

# Helpers to convert search terms to the proper documentation keys
HELPERS = {
    "vc": "VoiceClient",
    "msg": "Message",
    "color": "Color",
    "perm": "Permissions",
    "channel": "TextChannel",
}


class DiscordPy:
    """Bot extension to search discord.py docs."""

    def __init__(self, bot):
        self.bot = bot
        self._docs_cache = None

    @staticmethod
    def finder(text: str, collection: dict, topn=None):
        """Find text in a cache (collection) of documents."""

        suggestions = []
        pattern = ".*?".join(map(re.escape, text))
        regex = re.compile(pattern, flags=re.IGNORECASE)
        for key, val in collection:
            result = regex.search(key)
            if result:
                suggestions.append((len(result.group()), result.start(), (key, val)))

        suggestions.sort(key=lambda tup: (tup[0], tup[1], tup[2][0]))
        gen_output = (z for _, _, z in suggestions)
        if topn is None:
            return gen_output

        return list(gen_output)[:topn]

    async def build_docs_cache(self, ctx):
        """Build documentation cache."""

        cache = {}
        for branch, pages in PAGE_TYPES.items():
            sub = cache[branch] = {}

            for page in pages:
                page = f"{BASE_URL}/{page}"
                async with ctx.session.get(page) as resp:
                    if resp.status != 200:
                        return await ctx.send("Couldn't build documentation cache. Please try again later.")

                    text = await resp.text(encoding="utf-8")
                    root = etree.fromstring(text, etree.HTMLParser())
                    nodes = root.iterfind(".//dt/a[@class='headerlink']")

                    for node in nodes:
                        href = node.get("href", "")
                        key = href.replace("#discord.", "").replace("ext.commands.", "")
                        sub[key] = page + href

        self._docs_cache = cache

    async def search_docs(self, ctx, branch: str, search: str):
        """Base function to search discord.py docs and list results in an embed."""

        if search is None:
            return await ctx.send(f"{BASE_URL}/en/{branch}/")

        if self._docs_cache is None:
            await ctx.trigger_typing()
            await self.build_docs_cache(ctx)

        search = search.replace(" ", "_")

        if branch == "rewrite":
            q = search.lower()
            if hasattr(discord.abc.Messageable, q):
                search = f"abc.Messageable.{q}"

            def replace(o):
                return HELPERS.get(o.group(0), '')

            pattern = re.compile("|".join(fr"\b{key}\b" for key in HELPERS))
            search = pattern.sub(replace, search)

        cache = self._docs_cache[branch].items()

        matches = self.finder(search, cache, topn=10)

        e = discord.Embed(title="discord.py documentation search", colour=EmbedUtils.random_color())

        if not matches:
            return await ctx.send("I'm sorry but I couldn't find anything that matches what you are looking for.")

        e.description = "━━━━━━━━━━━━━━━━━━━\n" + '\n'.join(f'[{key}]({url})' for key, url in matches)
        await ctx.send(embed=e)

    @commands.group(name="docs", aliases=["rtd", "rtfd", "rtfm"], invoke_without_command=True)
    async def _docs(self, ctx, *, search: str = None):
        """Searches the discord.py docs and lists the results in an embed."""

        await self.search_docs(ctx, 'latest', search)

    @_docs.command(name="rewrite")
    async def _docs_rewrite(self, ctx, search: str = None):
        """Searches the discord.py rewrite docs and lists the results in an embed."""

        await self.search_docs(ctx, 'rewrite', search)


def setup(bot):
    bot.add_cog(DiscordPy(bot))
