import discord
from discord.ext import commands
import re
import logging
import lxml.etree as etree
from utils.embed import EmbedUtils

logger = logging.getLogger(__name__)


class DiscordPy:
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def finder(text: str, collection, *, key=None, lazy=True):
        suggestions = []
        pattern = ".*?".join(map(re.escape, text))
        regex = re.compile(pattern, flags=re.IGNORECASE)
        for item in collection:
            to_search = key(item) if key else item
            r = regex.search(to_search)
            if r:
                suggestions.append((len(r.group()), r.start(), item))

        def sort_key(tup):
            if key:
                return tup[0], tup[1], key(tup[2])
            return tup

        if lazy:
            return (z for _, _, z in sorted(suggestions, key=sort_key))
        else:
            return [z for _, _, z in sorted(suggestions, key=sort_key)]

    async def build_docs_cache(self, ctx):
        cache = {}

        page_types = {
            "rewrite": (
                "https://discordpy.readthedocs.org/en/rewrite/api.html",
                "https://discordpy.readthedocs.org/en/rewrite/ext/commands/api.html"
            ),
            "latest": (
                "https://discordpy.readthedocs.org/en/latest/api.html",
            )
        }

        for branch, pages in page_types.items():
            sub = cache[branch] = {}

            for page in pages:
                async with ctx.session.get(page) as resp:
                    if resp.status != 200:
                        return await ctx.send("Couldn't build documentation cache. Please try again later.")

                    text = await resp.text(encoding="utf-8")
                    root = etree.fromstring(text, etree.HTMLParser())
                    nodes = root.findall(".//dt/a[@class='headerlink']")

                    for node in nodes:
                        href = node.get("href", "")
                        key = href.replace("#discord.", "").replace("ext.commands.", "")
                        sub[key] = page + href

        self._docs_cache = cache

    async def search_docs(self, ctx, branch, search):
        base_url = f"https://discordpy.readthedocs.org/en/{branch}/"

        if search is None:
            return await ctx.send(base_url)

        if not hasattr(self, "_docs_cache"):
            await ctx.trigger_typing()
            await self.build_docs_cache(ctx)

        search = search.replace(" ", "_")

        if branch == "rewrite":
            helpers = {
                "vc": "VoiceClient",
                "msg": "Message",
                "color": "Color",
                "perm": "Permissions",
                "channel": "TextChannel",
            }

            q = search.lower()
            for name in dir(discord.abc.Messageable):
                if name[0] == "_":
                    continue

                if q == name:
                    search = f"abc.Messageable.{name}"
                    break

            def replace(o):
                return helpers.get(o.group(0), '')

            pattern = re.compile("|".join(fr"\b{key}\b" for key in helpers.keys()))
            search = pattern.sub(replace, search)

        cache = list(self._docs_cache[branch].items())

        matches = self.finder(search, cache, key=lambda t: t[0], lazy=False)[:10]

        e = discord.Embed(title="discord.py documentation search", colour=EmbedUtils.random_color())

        if len(matches) == 0:
            return await ctx.send("I'm sorry but I couldn't find anything that matches what you are looking for.")

        e.description = "━━━━━━━━━━━━━━━━━━━\n" + '\n'.join(f'[{key}]({url})' for key, url in matches)
        await ctx.send(embed=e)

    @commands.group(name="docs", aliases=["rtd", "rtfd", "rtfm"], invoke_without_command=True)
    async def _docs(self, ctx, *, search: str = None):
        """Searches the discord.py  docs and lists the results in an embed."""

        await self.search_docs(ctx, 'latest', search)

    @_docs.command(name="rewrite")
    async def _docs_rewrite(self, ctx, search: str = None):
        """Searches the discord.py rewrite docs and lists the results in an embed."""

        await self.search_docs(ctx, 'rewrite', search)


def setup(bot):
    bot.add_cog(DiscordPy(bot))
