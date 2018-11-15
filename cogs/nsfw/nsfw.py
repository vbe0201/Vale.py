import random

import discord
from discord.ext import commands

from utils.colors import random_color


class NSFW:
    def __init__(self, bot):
        self.bot = bot
        self.thumbnail = 'https://i.imgur.com/ivmKTvu.png'
        self.tags = ('feet', 'yuri', 'trap', 'hololewd', 'lewdkemo', 'solog', 'feetg', 'cum',
                     'erokemo', 'les', 'wallpaper', 'lewdk', 'ngif', 'meow', 'tickle', 'lewd', 'feed', 'gecg',
                     'eroyuri', 'eron', 'cum_jpg', 'bj', 'nsfw_neko_gif', 'solo', 'kemonomimi', 'nsfw_avatar',
                     'gasm', 'poke', 'anal', 'slap', 'hentai', 'avatar', 'erofeet', 'holo', 'keta', 'blowjob',
                     'pussy', 'tits', 'holoero', 'lizard', 'pussy_jpg', 'pwankg', 'classic', 'kuni', 'waifu',
                     'pat', '8ball', 'kiss', 'femdom', 'neko', 'spank', 'cuddle', 'erok', 'fox_girl', 'boobs',
                     'Random_hentai_gif', 'smallboobs', 'hug', 'ero')

    @commands.is_nsfw()
    @commands.command(name='neko', aliases=['catgirl'])
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    async def _neko(self, ctx, *, tag=None):
        """Gives you a random neko picture.

        You can provide a tag on what you are looking for, or leave it empty for something random.

        Tags available:
            feet, yuri, trap, hololewd, lewdkemo, solog, feetg,
            cum, erokemo, les, wallpaper, lewdk, ngif, meow, tickle, lewd, feed, gecg,
            eroyuri, eron, cum_jpg, bj, nsfw_neko_gif, solo, kemonomimi, nsfw_avatar,
            gasm, poke, anal, slap, hentai, avatar, erofeet, holo, keta, blowjob, pussy,
            tits, holoero, lizard, pussy_jpg, pwankg, classic, kuni, waifu, pat, 8ball, kiss,
            femdom, neko, spank, cuddle, erok, fox_girl, boobs, Random_hentai_gif, smallboobs,
            hug, ero
        """

        await ctx.trigger_typing()

        if not tag:
            tag = random.choice(self.tags)

        if tag == 'random_hentai_gif':
            tag = tag.capitalize()

        async with ctx.session.get(f'https://nekos.life/api/v2/img/{tag}') as resp:
            data = await resp.json()

        try:
            embed = (discord.Embed(title=f'Neko - {tag}', color=random_color(), timestamp=ctx.message.created_at)
                     .set_image(url=f'{data.get("url")}')
                     .set_footer(text=f'Requested by {ctx.author.display_name}', icon_url=ctx.author.avatar_url))

        except Exception:  # muh pycodestyle
            embed = (discord.Embed(color=random_color(), timestamp=ctx.message.created_at)
                     .set_thumbnail(url=self.thumbnail)
                     .set_author(name=f'{ctx.author.display_name}, an error occurred.', icon_url=ctx.author.avatar_url))
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(NSFW(bot))
