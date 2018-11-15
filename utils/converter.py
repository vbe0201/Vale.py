import difflib
import random
from collections import OrderedDict

from discord.ext import commands

from .commands import command_category
from .examples import get_example, wrap_example


def _unique(iterable):
    return iter(OrderedDict.fromkeys(iterable))


class Category(commands.Converter):
    @staticmethod
    def __get_categories(ctx):
        return (command_category(command, 'other') for command in ctx.bot.commands)

    async def convert(self, ctx, argument):
        parents = set(map(str.lower, self.__get_categories(ctx)))
        lower = argument.lower()

        if lower not in parents:
            raise commands.BadArgument(f'"{argument}" isn\'t a category!')

        return lower

    @staticmethod
    def random_example(ctx):
        categories = set(map(str.title, Category.__get_categories(ctx)))
        return random.sample(categories, 1)[0]


class BotCommand(commands.Converter):
    async def convert(self, ctx, argument):
        command = ctx.bot.get_command(argument)
        if not command:
            names = map(str, _unique(ctx.bot.walk_commands()))
            closest = difflib.get_close_matches(argument, names, cutoff=0.5)

            joined = 'Did you mean...\n' + '\n'.join(closest) if closest else ''
            raise commands.BadArgument(f'No {argument} command found. {joined}')

        return command

    @staticmethod
    def random_example(ctx):
        return random.sample(set(ctx.bot.walk_commands()), 1)[0]


def number(s):
    for type_ in (int, float):
        try:
            return type_(s)
        except ValueError:
            continue

    raise commands.BadArgument(f'{s} is not a number!')


@wrap_example(number)
def _number_example(ctx):
    return get_example(random.choice([int, float]), ctx)
