from discord.ext import commands
import traceback
import logging

logger = logging.getLogger(__name__)


class ErrorHandling:
    def __init__(self, bot):
        self.bot = bot

    async def on_command_error(self, ctx, error):
        """Called when a command error occurs."""

        if hasattr(ctx.command, "on_error"):
            return

        error = getattr(error, "original", error)

        # From here, the actual error handling starts
        if isinstance(error, commands.CommandNotFound):
            return

        elif isinstance(error, commands.CommandInvokeError):
            logger.warning(f"Error when invoking the command {ctx.command}:")
            traceback.print_tb(error.original.__traceback__)
            logger.error(f"{error.original.__class__.__name__}: {error.original}")

        elif isinstance(error, commands.CommandOnCooldown):
            seconds = round(error.retry_after, 2)
            hours, remainder = divmod(int(seconds), 3600)
            minutes, seconds = divmod(remainder, 60)

            await ctx.send("That command is on cooldown!\n{hours} hours, {minutes} minutes and {seconds} seconds remaining.")

        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.author.send("This command can't be invoked in a DM channel!")

        elif isinstance(error, commands.NotOwner):
            await ctx.send("Sorry, but only the bot owner can invoke this command.")

        elif isinstance(error, commands.DisabledCommand):
            await ctx.author.send("Sorry, but this command is disabled. Nobody can invoke it.")

        elif isinstance(error, commands.BadArgument):
            # For this special case the bot checks what was the command that raised this error.
            # So we can tell the user what he did wrong.

            # Since there is currently no need for this, we just leave it blank by now.
            return

        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Your commands is missing some arguments. Please use `sudo help {ctx.command}`.")


def setup(bot):
    bot.add_cog(ErrorHandling(bot))
