"""
This will be used to style embeds nicely. Just give it some time, it's not necessary right now.
"""

import discord
import colorsys
import random


class EmbedUtils:
    """This class contains helpful stuff for creating and formatting embeds."""
    @staticmethod
    def random_color():
        values = [int(i * 255) for i in colorsys.hsv_to_rgb(random.random(), 1, 1)]
        color = discord.Color.from_rgb(*values)

        return color
