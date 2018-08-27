"""
This file implements a few command checks the bot uses.
"""

from discord.ext import commands


class Checks:
    @staticmethod
    def has_permissions(**perms):
        """This is used instead of the default has_permissions. It makes it possible for the owner to use commands
        even if he doesn't have the permissions."""

        async def predicate(ctx):
            if await ctx.bot.is_owner(ctx.author):
                return True

            permissions = ctx.channel.permissions_for(ctx.author)

            missing = [perm for perm, value in perms.items() if getattr(permissions, perm, None) != value]

            if not missing:
                return True

            raise commands.MissingPermissions(missing)

        return commands.check(predicate)
