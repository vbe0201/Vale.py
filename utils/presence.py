import discord
import asyncio
import random


class Presence:
    def __init__(self, bot):
        self.bot = bot

        self.current_presence = None

        self.presences = [
            (discord.Status.dnd, discord.ActivityType.watching, f"Shitcode in {len(bot.guilds)} guilds."),
            (discord.Status.online, discord.ActivityType.playing, "await the future."),
            (discord.Status.dnd, discord.ActivityType.playing, "on another level than you shitbots."),
            (discord.Status.online, discord.ActivityType.playing, "on https://github.com/itsVale"),
            (discord.Status.online, discord.ActivityType.listening, "your help cries."),
            (discord.Status.idle, discord.ActivityType.listening, "your commands. | sudo help"),
            (discord.Status.online, discord.ActivityType.playing, "async is the future!"),
            (discord.Status.dnd, discord.ActivityType.playing, "my eyes are bleeding."),
        ]

    def random_presence(self):
        return random.choice(self.presences)

    def get_current_presence(self):
        return self.current_presence

    async def change_status(self):
        while True:
            presence = status, activity_type, activity = self.random_presence()
            self.current_presence = (presence)

            await self.bot.change_presence(status=status, activity=discord.Activity(type=activity_type, name=activity))
            await asyncio.sleep(60)
