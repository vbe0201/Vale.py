import contextlib
import io
import logging
import os
import random
import re
import sys
import textwrap
import time
import traceback
from functools import partial

import discord
from discord.ext import commands

from utils import disambiguate
from utils.colors import random_color
from utils.db import TableFormat
from utils.examples import wrap_example
from utils.formats import pluralize
from utils.subprocesses import run_subprocess

logger = logging.getLogger(__name__)

_extension = partial(str)


@wrap_example(_extension)
def _extension_example(ctx):
    return random.choice(list(ctx.bot.extensions))


class Owner:
    def __init__(self, bot):
        self.bot = bot
        self._last_result = None

    @property
    def emojis(self):
        return self.bot.bot_emojis

    async def __local_check(self, ctx):
        return await ctx.bot.is_owner(ctx.author)

    def _create_env(self, ctx):
        return {
            'bot': self.bot,
            'ctx': ctx,
            'message': ctx.message,
            'guild': ctx.guild,
            'server': ctx.guild,
            'channel': ctx.channel,
            'author': ctx.author,
            **globals()
        }

    @staticmethod
    def cleanup_code(code):
        if code.startswith('```') and code.endswith('```'):
            return '\n'.join(code.split('\n')[1:-1])

        return code.strip('` \n')

    @staticmethod
    def get_syntax_error(e):
        if not e.text:
            return '```py\n{0.__class__.__name__}: {0}\n```'.format(e)

        return '```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```'.format(e, '^', type(e).__name__)

    @staticmethod
    def format_tb(error):
        return ''.join(re.sub(r'File ".*[\\/]([^\\/]+.py)"', r'File "\1"', line)
                       for line in traceback.format_exception(type(error), error, error.__traceback__))

    @commands.command(name='eval')
    async def _eval(self, ctx, *, code):
        """Evaluates code."""

        env = {**self._create_env(ctx), '_': self._last_result}
        body = self.cleanup_code(code)
        to_compile = f'async def eval():\n{textwrap.indent(body, "    ")}'

        async def safe_send(content):
            if self.bot.http.token in content:
                content = content.replace(self.bot.http.token, '<Censored Token>')

            if len(content) >= 1990:
                url = await ctx.hastebin(content.encode("utf-8"))
                await ctx.send(f'Content too long for Discord.\n<{url}>')
            else:
                await ctx.send(f'```py\n{content}\n```')

        await ctx.trigger_typing()
        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(self.get_syntax_error(e))

        func = env['eval']

        with io.StringIO() as stdout:
            try:
                with contextlib.redirect_stdout(stdout):
                    result = await func()

            except Exception as e:
                value = stdout.getvalue()

                with contextlib.suppress(discord.HTTPException):
                    await ctx.message.add_reaction(self.emojis.get('failure'))

                await safe_send(f'{value}{self.format_tb(e)}')

            else:
                value = stdout.getvalue()

                with contextlib.suppress(discord.HTTPException):
                    await ctx.message.add_reaction(self.emojis.get('success'))

                if not result:
                    if value:
                        await safe_send(value)

                else:
                    self._last_result = result
                    await safe_send(f'{value}{result}')

    @commands.command(name='sql')
    async def _sql(self, ctx, *, query):
        """Executes a SQL query."""

        query = self.cleanup_code(query)

        is_multi_statement = query.count(';') > 1
        method = ctx.db.execute if is_multi_statement else ctx.db.fetch

        try:
            start = time.perf_counter()
            results = await method(query)
            total = (time.perf_counter() - start) * 1000.0
        except Exception:
            await ctx.message.add_reaction(self.emojis.get('failure'))
            return await ctx.send(f'```py\n{traceback.format_exc()}\n```')
        else:
            await ctx.message.add_reaction(self.emojis.get('success'))

        if is_multi_statement or not results:
            return await ctx.send(f'`{total:.2f}ms: {results}`')

        num_rows = len(results)
        headers = list(results[0].keys())

        table = TableFormat()
        table.set(headers)
        table.add(list(result.values()) for result in results)
        rendered = table.render()

        fmt = f'```\n{rendered}\n```\n*Returned {pluralize(row=num_rows)} in {total:.2f}ms*'
        if len(fmt) > 2000:
            url = await ctx.hastebin(fmt.encode("utf-8"))
            await ctx.send(f'Too many results...\n<{url}>')
        else:
            await ctx.send(fmt)

    @commands.command(name='shell', aliases=['sh'])
    async def _shell(self, ctx, *, script):
        """Runs a shell script."""

        script = self.cleanup_code(script)

        embed = (discord.Embed(description=f'```\n{script}```', color=random_color())
                 .set_author(name='Output'))

        links = []

        async def maybe_put_content(content, *, name):
            if len(content) >= 1017:
                url = await ctx.hastebin(content.encode("utf-8"))
                links.append(f'<{url}>')
                content = 'Too big...'
            elif not content:
                content = 'Nothing...'
            else:
                content = f'```\n{content}```'

            embed.add_field(name=name, value=content, inline=False)

        stdout, stderr = await run_subprocess(script)
        await maybe_put_content(stdout, name='stdout')
        await maybe_put_content(stderr, name='stderr')

        links = links or ''
        await ctx.send('\n'.join(links), embed=embed)

    @commands.command(name='load')
    async def _load(self, ctx, *, cog: _extension):
        """Loads a bot extension."""

        ctx.bot.load_extension(cog)
        await ctx.message.add_reaction(self.emojis.get('success'))

    @commands.command(name='unload')
    async def _unload(self, ctx, *, cog: _extension):
        """Unloads a bot extension."""

        ctx.bot.unload_extension(cog)
        await ctx.message.add_reaction(self.emojis.get('success'))

    @commands.group(name='reload', invoke_without_command=True)
    async def _reload(self, ctx, *, cog: _extension):
        """Reloads a bot extension."""

        ctx.bot.unload_extension(cog)
        ctx.bot.load_extension(cog)
        await ctx.message.add_reaction(self.emojis.get('success'))

    @_reload.command(name='emojis')
    async def _reload_emojis(self, ctx):
        """Reloads the bot's emojis."""

        import emoji, importlib  # noqa

        importlib.reload(emoji)
        self.bot._load_emojis()
        await ctx.message.add_reaction(self.emojis.get('success'))

    @_reload.command(name='config')
    async def _reload_config(self, ctx):
        """Reloads the bot's config file."""

        import config, importlib  # noqa

        importlib.reload(config)
        await ctx.message.add_reaction(self.emojis.get('success'))

    @_load.error
    @_unload.error
    @_reload.error
    async def _error(self, ctx, error):
        traceback.print_exc()
        await ctx.message.add_reaction(self.emojis.get('failure'))
        await ctx.send(f'Yo, mate. My nigga ({ctx.bot.creator.name}) didn\'t code me properly. Blame him for {error}.')

    @commands.command(name='shutdown', aliases=['die', 'fuckoff'])
    async def _shutdown(self, ctx):
        """Shuts down the bot."""

        await ctx.release()
        await ctx.send('Bye, faggot.')
        await self.bot.logout()

    @commands.command(name='restart')
    async def _restart(self, ctx):
        """Restarts the entire bot."""

        await ctx.release()
        await ctx.send('Gimme a second.')

        try:
            process = self.bot.process
            for handler in process.open_files() + process.connections():
                os.close(handler.fd)
        except Exception as e:
            logger.error(e)

        python = sys.executable
        os.execl(python, python, *sys.argv)

    @commands.command(name='send')
    async def _send(self, ctx, channel: discord.TextChannel, *, message):
        """Sends a message to a given channel."""

        await channel.send(f'Message from **{self.bot.creator}**:\n{message}')
        await ctx.message.add_reaction(self.emojis.get('success'))

    @commands.command(name='leave')
    async def _leave(self, ctx, server: disambiguate.Guild):
        """Leaves a server.

        Defaults to the server the command is invoked in.
        """

        await server.leave()
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.add_reaction(self.emojis.get('success'))


def setup(bot):
    bot.add_cog(Owner(bot))
