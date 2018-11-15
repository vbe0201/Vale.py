"""
Utilites to produce examples based off of args.
"""

import functools
import itertools
import random
import re
import typing

import discord
from discord.ext import commands

from . import varpos
from .commands import all_qualified_names

__all__ = ['command_example', 'get_example', 'static_example', 'wrap_example']

_random_generators = {}


# Stuff for builtins or discord.py models
def _example(func):
    try:
        _random_generators[typing.get_type_hints(func)['return']] = func
    except KeyError:
        pass

    return func


@_example
def _random_int(ctx) -> int:
    return random.randint(1, 100)


@_example
def _random_float(ctx) -> float:
    f = float(f'{random.randint(1, 100)}.{random.randint(0, 99)}')
    return int(f) if f.is_integer() else f


@_example
def _random_bool(ctx) -> bool:
    return random.choice([True, False])


@_example
def _random_text_channel(ctx) -> discord.TextChannel:
    return f'#{random.choice(ctx.guild.text_channels)}'


@_example
def _random_voice_channel(ctx) -> discord.VoiceChannel:
    return random.choice(ctx.guild.voice_channels)


@_example
def _random_category_channel(ctx) -> discord.CategoryChannel:
    return random.choice(ctx.guild.categories)


@_example
def _random_user(ctx) -> discord.User:
    return random.choice(ctx.bot.users)


@_example
def _random_member(ctx) -> discord.Member:
    return f'@{random.choice(ctx.guild.members)}'


@_example
def _random_guild(ctx) -> discord.Guild:
    guild = random.choice(ctx.bot.guilds)
    return random.choice([guild.id, guild.name])


@_example
def _random_role(ctx) -> discord.Role:
    return random.choice(ctx.guild.roles)


DEFAULT_TEXT = 'Lorem ipsum dolor sit amet.'
_arg_examples = {}


def _load_arg_examples():
    import json
    import logging

    try:
        with open('data/arg_examples.json', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:  # muh pycodestyle
        logging.getLogger(__name__).error('Failed to load static examples')
    else:
        _arg_examples.update(data)


_load_arg_examples()


def _get_static_example(key, command=''):
    for key in (f'{command}.{key}', key):
        examples = _arg_examples.get(key)
        if not examples:
            continue

        if isinstance(examples, list):
            return random.choice(examples)
        return examples

    return DEFAULT_TEXT


def _actual_command(ctx):
    command = ctx.command

    return ctx.kwargs['command'] if command.name == 'help' else command


@_example
def _random_str(ctx) -> str:
    return _get_static_example(ctx._current_parameter.name, _actual_command(ctx))


def _get_name(obj):
    try:
        return obj.__name__
    except AttributeError:
        return obj.__class__.__name__


def _is_discord_ext_converter(converter):
    module = getattr(converter, '__module__', '')
    return module.startswith('discord') and module.endswith('converter')


def _aways_classy(obj):
    return obj if isinstance(obj, type) else type(obj)


# Skidded the inspect module
def _format_annotation(annotation, base_module=None):
    if getattr(annotation, '__module__', None) == 'typing':
        return repr(annotation).replace('typing.', '')

    if isinstance(annotation, type):
        if annotation.__module__ in ('builtins', base_module):
            return annotation.__qualname__

        return f'{annotation.__module__}.{annotation.__qualname__}'

    return repr(annotation)


_NoneType = type(None)


def get_example(converter, ctx):
    """Returns a random example based on the converter."""

    if hasattr(converter, 'random_example'):
        return converter.random_example(ctx)

    if getattr(converter, '__origin__', None) is typing.Union:
        converters = converter.__args__
        if len(converters) == 2 and converters[-1] is _NoneType:
            converter = converters[0]
        else:
            converter = random.choice(converters)

        return get_example(converter, ctx)

    if _is_discord_ext_converter(converter):
        if _aways_classy(converter) is commands.clean_content:
            converter = str
        else:
            converter = getattr(discord, _get_name(converter).replace('Converter', ''))

    try:
        func = _random_generators[converter]
    except KeyError as e:
        raise ValueError(f'Unable to get an example for {_format_annotation(converter)}') from e
    else:
        return func(ctx)


# Helper functions


def wrap_example(target):
    """Wraps a converter to use a function for example generation."""

    def decorator(func):
        target.random_example = func
        return func

    return decorator


def static_example(converter):
    """Marks a converter to use the static example generator (str)."""

    converter.random_example = _random_str
    return converter


# Example generation

_get_converter = functools.partial(commands.Command._get_converter, None)

_quote_pattern = '|'.join(map(re.escape, commands.view._all_quotes))
_quote_regex = re.compile(rf'\\(.)|({_quote_pattern})')
_escape_quotes = functools.partial(_quote_regex.sub, f'\\\1\2')


def _quote(string):
    string = _escape_quotes(string)

    if any(map(str.isspace, string)):
        string = f'"{string}"'

    return string


def _is_required_parameter(param):
    return param.default is param.empty and param.kind is not param.VAR_POSITIONAL


MAX_REPEATS_FOR_VARARGS = 4


def _parameter_examples(parameters, ctx, command=None):
    command = command or ctx.command

    def parameter_example(parameter):
        ctx._current_parameter = parameter
        example = str(get_example(_get_converter(parameter), ctx))

        if not (parameter.kind == parameter.KEYWORD_ONLY and not command.rest_is_raw or example.startswith(('#', '@'))):
            example = _quote(example)

        return example

    for parameter in parameters:
        yield parameter_example(parameter)
        if parameter.kind is parameter.VAR_POSITIONAL:
            for _ in range(random.randint(varpos.requires_var_positional(parameter), MAX_REPEATS_FOR_VARARGS)):
                yield parameter_example(parameter)


def _split_params(command):
    """Splits a command's parameters into required and optional parts."""

    params = command.clean_params.values()
    required = list(itertools.takewhile(_is_required_parameter, params))

    optional = []
    for param in itertools.dropwhile(_is_required_parameter, params):
        if param.kind is param.VAR_POSITIONAL:
            args = required if varpos.requires_var_positional(command) else optional
            args.append(param)
            break

        optional.append(param)
        if param.kind is param.KEYWORD_ONLY:
            break

    return required, optional


def command_example(command, ctx):
    """Generate a working example given a command.

    If a command has optional arguments, it will generate two examples,
    one with required arguments only and one with all arguments included.
    """

    qualified_names = list(all_qualified_names(command))
    required, optional = _split_params(command)

    def generate(parameters):
        resolved = ' '.join(_parameter_examples(parameters, ctx, command))
        return f'`{ctx.clean_prefix}{random.choice(qualified_names)} {resolved}`'

    usage = generate(required)
    if not optional:
        return usage

    joined = '\n'.join(generate(required + optional[:index+1]) for index in range(len(optional)))
    return f'{usage}\n{joined}'
