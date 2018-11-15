import discord
from discord.ext import commands


class DeprecatedCommand(commands.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._removed_version = kwargs.get('version', None)
        self._instead = kwargs.get('instead', None)
        self._author_cache = set()

    @discord.utils.cached_property
    def warning(self):
        version = self._removed_version or 'the future, baby'
        base = f'\N{WARNING SIGN} `{self}` will be removed in {version}.'

        if self._instead:
            base = f'{base}, use `{self._instead}` instead.'

        return base

    async def prepare(self, ctx):
        await super().prepare(ctx)

        if ctx.author.id in self._author_cache:
            return

        await ctx.send(self.warning)
        self._author_cache.add(ctx.author.id)


def deprecated(name=None, **attrs):
    return commands.command(name=name, cls=DeprecatedCommand, **attrs)
