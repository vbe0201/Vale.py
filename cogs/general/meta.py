import inspect
import os
import platform
import re

import discord
import psutil
from discord.ext import commands

from utils.colors import random_color
from utils.converter import BotCommand
from utils.paginator import Paginator

# Thanks, Milky

VERSION_HEADER_PATTERN = re.compile(r'^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2}|Unreleased)$')
CHANGE_TYPE_PATTERN = re.compile(r'^### (Added|Changed|Deprecated|Removed|Fixed|Security)$')


def _is_bulleted(line):
    return line.startswith(('* ', '- '))


def _changelog_versions(lines):
    version = change_type = release_date = None
    changes = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = VERSION_HEADER_PATTERN.match(line)
        if match:
            if version:
                yield version, {'release_date': release_date, 'changes': changes.copy()}
            version = match[1]
            release_date = match[2]
            changes.clear()
            continue

        match = CHANGE_TYPE_PATTERN.match(line)
        if match:
            change_type = match[1]
            continue

        if _is_bulleted(line):
            changes.setdefault(change_type, []).append(line)
        else:
            changes[change_type][-1] += ' ' + line.lstrip()
    yield version, {'release_date': release_date, 'changes': changes.copy()}


def _load_changes():
    with open('CHANGELOG.md') as f:
        return dict(_changelog_versions(f.readlines()))


_CHANGELOG = _load_changes()


def _format_line(line):
    if _is_bulleted(line):
        return '\u2022 ' + line[2:]

    return line


def _format_changelog_without_embed(version):
    changes = _CHANGELOG[version]
    nl_join = '\n'.join

    change_lines = '\n\n'.join(
        f'{type_}\n{nl_join(map(_format_line, lines))}'
        for type_, lines in changes['changes'].items()
    )

    return f'Version {version} \u2014 {changes["release_date"]}\n\n{change_lines}'


def _format_changelog_with_embed(version, url):
    changes = _CHANGELOG[version]
    nl_join = '\n'.join

    change_lines = '\n\n'.join(
        f'**__{type_}__**\n{nl_join(map(_format_line, lines))}'
        for type_, lines in changes['changes'].items()
    )

    embed = discord.Embed(description=change_lines)

    name = f'Version {version} \u2014 {changes["release_date"]}'
    embed.set_author(name=name, url=url)
    return embed


class Meta:
    """Primary a class that provides some meta information about the bot."""

    def __init__(self, bot):
        self.bot = bot

    @property
    def emojis(self):
        return self.bot.bot_emojis

    @staticmethod
    async def _get_commits(repo):
        cmd = r'git show -s HEAD~5..HEAD --format="[{}](https://github.com/' + repo + '/commit/%H) %s (%cr)"'  # 10 commits
        if os.name == 'posix':
            cmd = cmd.format(r'\`%h\`')
        else:
            cmd = cmd.format(r'`%h`')

        try:
            revision = os.popen(cmd).read().strip()
        except OSError:
            revision = 'Couldn\'t fetch commits. Either a memory error or a non-existant repository was provided.'

        return revision

    @staticmethod
    def _get_os_information(cpu, memory):
        return inspect.cleandoc(f"""
        **System information:**

        ```yaml
        :Architecture: -{platform.architecture()[0]}-

        :System:       -{platform.system()}-
        :Node:         -{platform.node()}-
        :Release:      -{platform.release()}-
        :Version:      -{platform.version()}-
        :Machine:      -{platform.version()}-
        :Processor:    -{platform.processor()}-

        :CPU usage:    -{cpu}-
        :Memory usage: -{memory}-
        ```
        """)

    @commands.command(name='about')
    async def _about(self, ctx):
        """Get some cool information about the bot."""

        pages = []

        process = self.bot.process
        cpu = process.cpu_percent() / psutil.cpu_count()
        memory = process.memory_info().rss / float(2 ** 20)
        latency = round(self.bot.latency * 1000, 2)
        shards = len(self.bot.shards)
        version = '.'.join(map(str, ctx.bot.version_info[:3]))
        changelog = (
            f'**{self.emojis.get("announcements")} Recent updates:**\n\n'
            f'```css\n{_format_changelog_without_embed(version)}```'
        )

        commits = await self._get_commits('itsVale/Vale.py')
        system = self._get_os_information(cpu, memory)
        python = platform.python_version()
        postgres = '.'.join(map(str, ctx.db.get_server_version()[:3]))

        pages = [
            (
                f'[`Source Code`]({self.bot.source})\n'
                f'[`Invite me with minimal perms`]({self.bot.minimal_invite_url})\n'
                f'[`Invite me with full perms (Required for certain commands to work)`]({self.bot.invite_url})\n\n'
                f'[__**Need help with something? Check out the support server!**__]({self.bot.support_server})'
            ),
            (
                f'{self.emojis.get("version")} Version: **{version}**\n'
                f'{self.emojis.get("status")} Online for: **{self.bot.uptime}**\n'
                f'{self.emojis.get("signal")} Latency: **{latency} ms**\n'
                f'{self.emojis.get("server")} Guilds: **{self.bot.guild_count}**\n'
                f'{self.emojis.get("cpu")} CPU usage: **{cpu:.2f}%**\n'
                f'{self.emojis.get("memory")} RAM usage: **{memory:.2f} Mb**\n'
                f'{self.emojis.get("shard")} Shards: **{shards}**\n'
                f'{self.emojis.get("python")} Python version: **{python}**\n'
                f'{self.emojis.get("discordpy")} discord.py version: **{discord.__version__}**\n'
                f'{self.emojis.get("postgres")} PostgreSQL version: **{postgres}**\n'
            ),
            system,
            f'**\N{WRITING HAND} Latest commits:**\n\n' + commits,
            changelog
        ]

        paginator = Paginator(ctx, pages, per_page=1, title=f'{self.emojis.get("statistics")} Stats for Vale.py')
        await paginator.interact()

    @commands.command(name='source', aliases=['skid', 'steal'])
    async def _source(self, ctx, *, command: BotCommand = None):
        """Displays the source code for a command.

        If the source code has too many lines, it will send a GitHub URL instead.
        """

        if not command:
            return await ctx.send(self.bot.source)

        paginator = commands.Paginator(prefix='```py')

        source = command.callback.__code__
        lines, firstlineno = inspect.getsourcelines(command.callback)
        if len(lines) < 20:
            for line in lines:
                paginator.add_line(line.rstrip().replace('`', '\u200b'))

            for page in paginator.pages:
                await ctx.send(page)

            return

        lastline = firstlineno + len(lines) - 1
        location = os.path.relpath(source.co_filename).replace('\\', '/')

        url = f'<{self.bot.source}/tree/master/{location}#L{firstlineno}-L{lastline}>'
        await ctx.send(url)

    @commands.command(name='stats')
    async def _stats(self, ctx):
        """Shows some usage statistics about this bot."""

        content = (
            f'__**Usage statistics:**__\n',
            f'Commands invoked in total: **{self.bot.command_counter.get("total")}**',
            f'Commands invoked in this guild: **{self.bot.command_counter.get(str(ctx.guild.id))}**',
            f'Commands invoked in DMs: **{self.bot.command_counter.get("in DMs")}**\n',
            f'And here are the commands, which were invoked successfully in total: **{self.bot.command_counter.get("succeeded")}**\n',
            f'*Only applies to the period from since the bot was restarted for the last time until now.*',
        )

        if ctx.bot_has_embed_links():
            await ctx.send(embed=discord.Embed(description='\n'.join(content), color=random_color()))
        else:
            await ctx.send('\n'.join(content))


def setup(bot):
    bot.add_cog(Meta(bot))
