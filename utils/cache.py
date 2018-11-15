import asyncio
import functools
import inspect

from lru import LRU

_keyword_marker = object()


#  Key-making functions
def unordered(args, kwargs):
    if kwargs:
        args += (_keyword_marker, *kwargs.items())

    return frozenset(args)


default_key = functools.partial(functools._make_key, typed=False)
typed_key = functools.partial(functools._make_key, typed=True)


# Here's the original: https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/utils/cache.py
# Modified to allow custom key args and the strategy is determined by the max_size
def cache(max_size=128, make_key=default_key):
    def decorator(func):
        if max_size is None:
            cache = {}
            get_stats = lambda: (0, 0)
        else:
            cache = LRU(max_size)
            get_stats = cache.get_stats

        def wrap_and_store(key, coro):
            async def func():
                value = await coro
                cache[key] = value
                return value

            return func()

        def wrap_new(value):
            async def new_coro():
                return value

            return new_coro()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = make_key(args, kwargs)

            # Probably faster to use cache.get and compare to a sentinel
            try:
                value = cache[key]
            except KeyError:
                value = func(*args, **kwargs)

                if inspect.isawaitable(value):
                    return wrap_and_store(key, value)

                cache[key] = value
                return value
            else:
                if asyncio.iscoroutinefunction(func):
                    return wrap_new(value)

                return value

        def invalidate(*args, **kwargs):
            try:
                del cache[make_key(args, kwargs)]
            except KeyError:
                return False
            else:
                return True

        wrapper.cache = cache
        wrapper.get_key = lambda *args, **kwargs: make_key(args, kwargs)
        wrapper.invalidate = invalidate
        wrapper.get_stats = get_stats

        return wrapper

    return decorator


async_cache = cache
