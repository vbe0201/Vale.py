from urllib.parse import quote

import discord
from discord.ext import commands

from utils.colors import random_color


class Weeb:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='anime', aliases=['animu', 'material'])
    async def _anime(self, ctx, *, query):
        """Provides information about a given anime."""

        await ctx.trigger_typing()

        try:
            async with ctx.session.get(f'https://api.jikan.moe/search/anime/{quote(query)}') as resp:
                data = await resp.json()

            embed = (discord.Embed(title=data['result'][0].get('title', ''), color=random_color(), timestamp=ctx.message.created_at)
                     .add_field(name=':gem: Short description:',
                                value=f'{data["result"][0].get("description")}**\n'
                                      f'[Read more about {data["result"][0].get("title")}...]({data["result"][0].get("url")})**')
                     .add_field(name=':clapper: Episodes:', value=f'**{data["result"][0].get("episodes")}**')
                     .add_field(name=':heart_decoration: MyAnimeList rating:', value=f'**{data["result"][0].get("score")}/10**')
                     .add_field(name=':busts_in_silhouette: Members:', value=f'**{data["result"][0].get("type")}**')
                     .add_field(name=':performing_arts: Type:', value=f'**{data["result"][0].get("type")}**')
                     .set_thumbnail(url=data['result'][0].get('image_url'))
                     .set_footer(text=f'Anime search for: {query}', icon_url=ctx.author.avatar_url))

        except Exception:  # muh pycodestyle
            return await ctx.send(f':warning: No results found for ``{query}``.')

        await ctx.send(embed=embed)

    @commands.command(name='manga')
    async def _manga(self, ctx, *, query):
        """Provides information about a given manga."""

        await ctx.trigger_typing()

        try:
            async with ctx.session.get(f'https://api.jikan.moe/search/manga/{quote(query)}') as resp:
                data = await resp.json()

            embed = (discord.Embed(title=data['result'][0].get('title', ''), color=random_color(), timestamp=ctx.message.created_at)
                     .add_field(name=':gem: Short description:',
                                value=f'{data["result"][0].get("description")}**\n'
                                      f'[Read more about {data["result"][0].get("title")}...]({data["result"][0].get("url")})**')
                     .add_field(name=':clapper: Volumes:', value=f'**{data["result"][0].get("volumes")}**')
                     .add_field(name=':heart_decoration: MyAnimeList rating:', value=f'**{data["result"][0].get("score")}/10**')
                     .add_field(name=':busts_in_silhouette: Members:', value=f'**{data["result"][0].get("type")}**')
                     .add_field(name=':performing_arts: Type:', value=f'**{data["result"][0].get("type")}**')
                     .set_thumbnail(url=data['result'][0].get('image_url'))
                     .set_footer(text=f'Manga search for: {query}', icon_url=ctx.author.avatar_url))

        except Exception:  # muh pycodestyle
            return await ctx.send(f':warning: No results found for ``{query}``.')

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Weeb(bot))
