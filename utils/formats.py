import re
from functools import partial

from more_itertools import one


def pluralize(**sentence):
    name, value = one(sentence.items())

    if name.endswith('y') and name[-2] not in 'aeiou':
        name = f'{name[:-1]}ies' if value != 1 else name
        return f'{value} {name}'

    return f'{value} {name}{"s" * (value != 1)}'


def human_join(iterable, delim=', ', *, final='and'):
    """Joins an iterable in a human-readable way.

    The items are joined such that the last two items will be joined with a
    different delimiter than the rest.
    """

    seq = tuple(iterable)
    if not seq:
        return ''

    return f"{delim.join(seq[:-1])} {final} {seq[-1]}" if len(seq) != 1 else seq[0]


def multi_replace(string, replacements):
    substrs = sorted(replacements, key=len, reverse=True)
    pattern = re.compile("|".join(map(re.escape, substrs)))
    return pattern.sub(lambda m: replacements[m.group(0)], string)


def finder(text, collection, *, count=None):
    """Find text in a cache (collection) of documents."""

    suggestions = []
    pattern = '.*?'.join(map(re.escape, text))
    regex = re.compile(pattern, flags=re.IGNORECASE)

    for key, value in collection.items():
        result = regex.search(key)
        if result:
            suggestions.append((len(result.group()), result.start(), (key, value)))

    suggestions.sort(key=lambda tup: (tup[0], tup[1], tup[2][0]))
    gen_output = (suggestion for _, _, suggestion in suggestions)
    if not count:
        return gen_output

    return list(gen_output)[:count]


_markdown_replacements = {c: f'\\{c}' for c in ('*', '`', '_', '~', '\\')}
escape_markdown = partial(multi_replace, replacements=_markdown_replacements)
del _markdown_replacements
