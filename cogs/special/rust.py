"""
This cog is just for the german Rust guild.
It provides some useful utilities to support this guild.

Invite's here:
https://discord.gg/f5VRtWP
"""

import itertools
import random
import re
from functools import wraps

import discord
from discord.ext import commands

from utils.colors import random_color
from utils.examples import _get_static_example
from utils.jsonfile import JSONFile

RUST_GUILD_ID = 488103711885754408
RUST_GENERAL_CHAT = 488383699185041418

RUST_EMOTE = '<:rust:477436806959202324>'

fmt = re.compile(r'##(?P<number>[0-9]+)')


class WelcomeMessage(commands.Converter):
    async def convert(self, ctx, argument):
        if not argument:
            raise commands.BadArgument('You must provide a message, you know.')

        return argument

    @staticmethod
    def random_example(ctx):
        return random.choice([
            'Hey {member}, welcome to {guild}!',
            'Hi, have fun here on {guild} and enjoy your stay!',
            'Hey {member}, I just want to ping you. I know you like that.'
        ])


class RustCode(commands.clean_content):
    @staticmethod
    def random_example(ctx):
        return _get_static_example('rust')


def find_issue(func):
    @wraps(func)
    async def decorator(self, message):
        # Kinda abuse but it's the simplest way
        if not message.guild or message.guild.id != RUST_GUILD_ID:
            return

        match = fmt.match(message.content)
        if match:
            url = 'https://github.com/rust-lang/rust/issues/' + match.group('number')
            await message.channel.send(url)

        return await func(self, message)

    return decorator


class RustExclusive:
    def __init__(self, bot):
        self.bot = bot

        self.rust_guild = JSONFile('rust_guild.json')

    def __local_check(self, ctx):
        return ctx.guild and ctx.guild.id == RUST_GUILD_ID

    def get_welcome_messages(self):
        return self.rust_guild.get('welcome_messages', [])

    async def set_welcome_message(self, messages):
        messages = messages or []
        if len(messages) > 10:
            raise RuntimeError('You cannot have more than 10 welcome messages here.')

        await self.rust_guild.put('welcome_messages', sorted(set(messages), reverse=True))

    @staticmethod
    def cleanup_code(code):
        if code.startswith('```') and code.endswith('```'):
            return '\n'.join(code.split('\n')[1:-1])

        return code.strip('` \n')

    @find_issue
    async def on_message(self, message):
        """This is basically just here to give people the possibility to search for Issues and Pull Requests to the Rust repository."""

    async def on_member_join(self, member):
        if not self.__local_check(member):
            return

        message = random.choice(self.get_welcome_messages())
        channel = await member.guild.get_channel(RUST_GENERAL_CHAT)
        await channel.send(message.format(member=member.mention, guild=str(member.guild)))

    @commands.group(name='messages', invoke_without_command=True, hidden=True)
    async def _messages(self, ctx):
        """Shows all set welcome messages for this server."""

        if ctx.invoked_subcommand:
            return

        messages = self.get_welcome_messages()

        description = '\n'.join(itertools.starmap('`{0}.` => {1}'.format, enumerate(messages, 1))
                                if messages else ('No welcome messages set for this server yet', ))
        embed = discord.Embed(title=f'Custom welcome messages for {ctx.guild}', description=description, color=random_color())
        await ctx.send(embed=embed)

    @_messages.command(name='add')
    @commands.has_permissions(manage_guild=True)
    async def _messages_add(self, ctx, *, message: WelcomeMessage):
        """Adds a custom welcome message for this server.

        New members will be greeted with a randomly picked message.
        There are 2 variables that you can use inside the message:
          -> `member`  -  This will mention the member who joined
          -> `guild`   -  The name of this server
          Both of them must be surrounded with **curly brackets**.
          (See example)
        """

        messages = self.get_welcome_messages()

        if message in messages:
            return await ctx.send(f'"{message}" is already a welcome message for this server.')

        messages += (message, )
        await self.set_welcome_message(messages)

        await ctx.send(f'Successfully added message: {message}')

    @_messages.command(name='remove')
    @commands.has_permissions(manage_guild=True)
    async def _messages_remove(self, ctx, num: int):
        """Removes a message given a number.

        The number must be between 1 and 10 as a guild can only have 10 welcome messages.
        To see which number would remove which message, use `{prefix}messages` to list all messages and take the numbers from there.
        """

        if not 0 < num <= 10:
            return await ctx.send('Please provide a number between 1 and 10!')

        messages = self.get_welcome_messages()

        try:
            msg = messages.pop(num - 1)
        except IndexError:
            return await ctx.send('There is no such message registered.')

        await self.set_welcome_message(messages)
        await ctx.send(f'Successfully removed message with content: {msg}')

    @_messages.command(name='clear')
    @commands.has_permissions(manage_guild=True)
    async def _messages_clear(self, ctx):
        """Clears all custom welcome messages on this server."""

        await self.set_welcome_message([])
        await ctx.message.add_reaction(self.bot.bot_emojis.get('success'))

    @commands.command(name='rust', hidden=True)
    @commands.cooldown(1, 10.0, commands.BucketType.user)
    async def _rust(self, ctx, *, code: RustCode):
        """Evaluates some Rust code.

        It is not necessary to specifically provide a language for the codeblock.
        """

        body = self.cleanup_code(code)
        if not re.search(r"fn\s+main\s*\(\s*\)\s*\{", body):
            to_compile = "fn main() { println!(\"{:?}\", {" + code + "}) }"
        else:
            to_compile = body

        jdoodle = self.bot.get_cog('JDoodle')
        await ctx.trigger_typing()

        result = await jdoodle._request('execute', script=to_compile, language='rust', version=2)
        await jdoodle.send_embed(ctx, 'rust', RUST_EMOTE, result)


def setup(bot):
    bot.add_cog(RustExclusive(bot))
