import colorsys
import random

import discord

__all__ = ['random_color']


def random_color():
    """Generates nice random colors that can be used for embeds."""

    values = [int(element * 255) for element in colorsys.hsv_to_rgb(random.random(), 1, 1)]
    return discord.Color.from_rgb(*values)
