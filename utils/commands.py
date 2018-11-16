"""
Some nice utilites for discord.ext.commands

Thanks, Milky!
"""

import itertools
import operator

from more_itertools import iterate

__all__ = ['all_names', 'all_qualified_names', 'command_category', 'walk_parents']


def all_names(command):
    """Returns a list of all possible names in a command."""

    return [command.name, *command.aliases]


def walk_parents(command):
    """Walks up a command's parent chain."""

    return iter(iterate(operator.attrgetter('parent'), command).__next__, None)


def all_qualified_names(command):
    """Returns an iterator of all possible names in a command."""

    reversed_names = reversed(list(walk_parents(command)))
    product = itertools.product(*map(all_names, reversed_names))

    return map(' '.join, product)


def command_category(command, default='\u200bOther'):
    """Return the category that a command would fall into, using the module the command was defined in."""

    _, category, *rest = command.module.split('.', 2)
    return category if rest else default
