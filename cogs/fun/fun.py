import contextlib
import logging
import random
import typing
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class IdiotError(Exception):
    pass


api_endpoints = {
    "api_endpoints": {
        "Generators": ("achievement", "batslap", "beautiful", "blame", "crush", "facepalm", "pls", "respect", "slap",
                       "snapchat", "stepped", "superpunch", "tattoo", "thesearch", "triggered", "vault", "wanted")
    }
}

dev_endpoints = {
    "effects": ("brightness", "darkness", "greyscale", "invert", "invertGreyscale", "invertThreshold", "sepia",
                "silhouette", "threshold"),

    "generators": ("achievement", "batslap", "beautiful", "blame", "bobross", "challenger", "changemymind",
                   "coffee", "colour", "confused", "crush", "facepalm", "fanslap", "garbage", "girls", "hates",
                   "heavyfear", "hide", "ignore", "karen", "kirby", "missing", "painting", "pls", "religion",
                   "respect", "snapchat", "sniper", "steam", "stepped", "suggestion", "superpunch", "superspank",
                   "tattoo", "thesearch", "time", "tinder", "triggered", "vault", "vr", "waifuinsult", "wanted",
                   "wreckit", "zerotwopicture", "osu"),

    "greetings": ("anime_goodbye", "anime_welcome", "unified"),

    "overlays": ("approved", "discord", "rainbow", "rejected"),

    "profile": "card",

    "text": ("cursive", "mock", "owoify", "tinytext", "vaporwave"),
    }


def get_endpoint(endpoint):
    for key, values in api_endpoints.items():
        if endpoint.lower() in values:
            return key + "/" + endpoint.lower()

    raise IdiotError("The endpoint you are trying to make a request to is invalid.")


def get_dev_endpoint(endpoint):
    for key, values in dev_endpoints.items():
        if endpoint.lower() in values:
            return key + "/" + endpoint.lower()

    raise IdiotError("The endpoint you are trying to make a request to is invalid.")


class IdiotResponse:
    def __init__(self, **data):
        self.type = data.get('type')
        self.text = data.get('text')

        img_data = data.get('data')
        self.data = bytes(img_data) if img_data else None

    @classmethod
    def parse_result(cls, result, *, status_code):
        """Parses a response from the API."""

        status_codes = {
            "404": "Endpoint not found.",
            "403": "Either your API key is missing or an improper one was passed.",
            "400": "You are missing some required fields."
        }

        for key, value in status_codes.items():
            if status_code == int(key):
                raise IdiotError(value)

        return cls(**result)


class IdiotClient:
    def __init__(self, key, *, dev=False, **kwargs):
        self.api_key = key
        self.dev = dev
        self.base_url = 'https://dev.anidiots.guide/' if dev else 'https://api.anidiots.guide/'
        self.session = kwargs.get('session') or aiohttp.ClientSession(loop=kwargs.get('loop'))

        self.headers = {"Authorization" if dev else "token": self.api_key}

    async def _get_image(self, endpoint: str, **kwargs):
        """Makes a request to an endpoint of the API."""

        params = {k: v for k, v in kwargs.items() if v is not None}

        async with self.session.get(self.base_url + endpoint, headers=self.headers, params=params) as response:
            json_response = await response.json()
            status = response.status

        return IdiotResponse.parse_result(result=json_response, status_code=status)

    async def _get_text(self, endpoint: str, text: str, style=None):
        """Makes a request to a text endpoint of the API."""

        params = {'text': text}
        if style:
            params['style'] = style

        async with self.session.get(self.base_url + endpoint, headers=self.headers, params=params) as response:
            json_response = await response.json()
            status = response.status

        return IdiotResponse.parse_result(result=json_response, status_code=status)

    async def retrieve_greeting(self, type, version, bot, avatar, username, discriminator, guild_name, member_count, *, message=None):
        """This represents the base for Welcome/Goodbye messages."""

        result = await self._get_image(
            get_dev_endpoint('unified'),
            type=type,
            version=version,
            message=message,
            bot=bot,
            avatar=avatar,
            username=username,
            discriminator=discriminator,
            guildName=guild_name,
            memberCount=member_count
        )

        if not result.data:
            raise IdiotError('Failed to retrieve a Greeting Image.')

        return discord.File(result.data, 'greeting.png')


class Fun(IdiotClient):
    def __init__(self, bot):
        super().__init__(bot.idiotic_api_key, dev=True, session=bot.session)

        self.bot = bot

    async def __error(self, ctx, error):
        if isinstance(error, IdiotError):
            await ctx.send(error)

    @commands.command(name='osu')
    async def _osu(self, ctx, theme: typing.Optional[int] = 3, *, user: str = None):
        """Returns an osu profile card for a given user.

        You can choose a theme by providing a number. Defaults to `darker`.
        `light`  => 1
        `dark`   => 2
        `darker` => 3

        If no user is provided, it will try to retrieve data using your nickname.

        Examples:
            {prefix}osu dark itsVale
            {prefix}osu itsVale
        """

        themes = ['light', 'dark', 'darker']

        if not 0 <= theme < 4:
            raise IdiotError('You must provide a theme as a integer.\n```\nlight  => 1\ndark  => 2\ndarker => 3```')

        user = user or ctx.author.display_name

        async with ctx.typing():
            try:
                result = await self._get_image(get_dev_endpoint('osu'), user=user, theme=themes[theme - 1])

                res = result.data
            except KeyError:
                return await ctx.send('Nothing found for the given username.')

            with contextlib.suppress(discord.HTTPException):
                await ctx.send(file=discord.File(res, 'osu.png'))

    @commands.command(name='lmgtfy', aliases=['google', 'search'])
    async def _lmgtfy(self, ctx, *args):
        """Use this command if someone is unable to google for stuff on his own."""

        if not args:
            return await ctx.send('This command requires arguments on what to google for.')

        query = quote(' '.join(args))
        await ctx.send(f'Someone who doesn\'t know how to google, huh? Let me show you how to do this. <http://lmgtfy.com/?iie=1&q={query}>')

    @commands.command(name='mock')
    async def _mock(self, ctx, *, text):
        """Who doesn't like the Spongebob mock meme?"""

        # Quality code
        await ctx.send(''.join([random.choice([char.upper(), char.lower()]) for char in text]))


def setup(bot):
    bot.add_cog(Fun(bot))
