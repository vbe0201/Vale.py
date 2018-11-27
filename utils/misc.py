import asyncio
import functools
import inspect
import json
import os
from collections import OrderedDict
from typing import Callable

from more_itertools import grouper

REGIONAL_INDICATORS = [chr(i + 0x1f1e6) for i in range(26)]


def truncate(string, length, placeholder):
    return (string[:length] + placeholder) if len(string) > length + len(placeholder) else string


def str_join(delim, iterable):
    return delim.join(map(str, iterable))


def group_strings(string, n):
    return map(''.join, grouper(n, string, ''))


def nice_time(time):
    return time.strftime('%d/%m/%Y %H:%M')


def ordinal(num):
    # no questions asked.
    return '%d%s' % (num, 'tsnrhtdd'[(num // 10 % 10 != 1) * (num % 10 < 4) * num % 10::4])


def base_filename(name):
    return os.path.splitext(os.path.basename(name))[0]


def emoji_url(emoji):
    hexes = '-'.join(hex(ord(c))[2:] for c in str(emoji))
    return f'https://twemoji.maxcdn.com/2/72x72/{hexes}.png'


def unique(iterable):
    return list(OrderedDict.fromkeys(iterable))


async def maybe_awaitable(func, *args, **kwargs):
    maybe = func(*args, **kwargs)
    return await maybe if inspect.isawaitable(maybe) else maybe


def run_in_executor(func: Callable):
    """
    This decorator wraps a synchronous function to be executed using `loop.run_in_executor`.
    This allows functions to be wrapped into asynchronous functions and to be awaitable.
    This is to prevent functions that are expensive from blocking the bot's event loop.

    :param func:
        The synchronous function that should be wrapped.
    """

    @functools.wraps(func)
    async def decorator(*args, **kwargs):
        loop = asyncio.get_event_loop()
        partial = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(None, partial)

    return decorator


async def load_async(filename, loop=None):
    loop = loop or asyncio.get_event_loop()

    def ew_shit():
        with open(filename, encoding='utf-8') as f:
            return json.load(f)

    return await loop.run_in_executor(None, ew_shit)
