"""
This cog is just for the Dreamhub guild.
It mainly provides Welcome and Goodbye messages.
"""

from cogs.fun.fun import IdiotClient

DREAMHUB_GUILD_ID = 505407672028495872
DREAMHUB_WELCOME_CHANNEL = 508633975540023309
DREAMHUB_FAREWELL_CHANNEL = 508635141539627019
DREAMHUB_INFO_CHANNEL = 512290391220027433


class DreamhubExclusive:
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.bot.wait_until_ready())

        client = IdiotClient(bot.idiotic_api_key, dev=True, session=bot.session)
        self.get_image = client.retrieve_greeting
        del client

    def __local_check(self, ctx):
        # For future reference if any special commands will be implemented.
        return ctx.guild and ctx.guild.id == DREAMHUB_GUILD_ID

    async def on_member_join(self, member):
        if not self.__local_check(member):
            return

        channel = member.guild.get_channel(DREAMHUB_WELCOME_CHANNEL)

        try:
            img = await self.get_image('welcome', 'anime', str(member.bot).lower(), member.avatar_url_as(format='png', size=128),
                                       member.name, member.discriminator, member.guild.name, len(member.guild.members))
        except Exception:  # muh pycodestyle
            await channel.send(f'{member.mention}, welcome on **Dreamhub**! Enjoy your stay and make sure to check out <#{DREAMHUB_INFO_CHANNEL}>!')
        else:
            await channel.send(file=img)

    async def on_member_remove(self, member):
        if not self.__local_check(member):
            return

        channel = member.guild.get_channel(DREAMHUB_FAREWELL_CHANNEL)

        try:
            img = await self.get_image('goodbye', 'anime', str(member.bot).lower(), member.avatar_url_as(format='png', size=128),
                                       member.name, member.discriminator, member.guild.name, len(member.guild.members))
        except Exception:  # muh pycodestyle
            await channel.send(f'{member} left **Dreamhub**. We hope you enjoyed your stay!')
        else:
            await channel.send(file=img)


def setup(bot):
    bot.add_cog(DreamhubExclusive(bot))
