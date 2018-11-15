import inspect
import os
import platform
import re

import discord
import psutil
from discord.ext import commands

from utils.colors import random_color
from utils.converter import BotCommand

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

    @commands.command(name='about')
    async def _about(self, ctx):
        """Get some cool information about this bot."""

        process = psutil.Process(os.getpid())
        memory = process.memory_info().rss / float(2 ** 20)
        version = '.'.join(map(str, ctx.bot.version_info[:3]))

        description = (
            f'[Source Code]({self.bot.source}) | '
            '[My creator on Twitch](https://twitch.tv/itsvaleee)\n'
            '━━━━━━━━━━━━━━━━━━━━━━━━\n'
            f'__[Invite me with minimal perms]({self.bot.minimal_invite_url})__\n'
            f'__[Invite me with full perms]({self.bot.invite_url})__\n\n'
            f'{self.emojis.get("version")} Version: **{version}**\n'
            f'{self.emojis.get("status")} Online for: **{self.bot.uptime}**\n'
            f'{self.emojis.get("signal")} Latency: **{round(self.bot.latency * 1000)}ms**\n'
            f'{self.emojis.get("server")} Guilds: **{self.bot.guild_count}**\n'
            f'{self.emojis.get("cpu")} CPU usage: **{psutil.cpu_percent()}**\n'
            f'{self.emojis.get("memory")} RAM usage: **{round(memory, 2)}mb**\n'
            f'{self.emojis.get("shard")} Shard count: **{int(self.bot.shard_count)}**\n'
            f'{self.emojis.get("python")} Python version: **{platform.python_version()}**\n'
            f'{self.emojis.get("discordpy")} discord.py version: **{discord.__version__}**\n\n'
            f'{self.emojis.get("announcements")} Recent updates:\n```css\n{_format_changelog_without_embed(version)}\n```'
        )

        embed = discord.Embed(title=f'{self.emojis.get("statistics")} {self.bot.user.name}\'s stats', description=description, color=random_color())
        await ctx.send(embed=embed)

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
