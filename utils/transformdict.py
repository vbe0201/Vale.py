from collections import abc
from reprlib import recursive_repr

# See also: https://stackoverflow.com/questions/3387691/how-to-perfectly-override-a-dict


class TransformedDict(abc.MutableMapping):
    """A dictionary that applies an arbitary key-altering function before accessing the keys."""

    __slots__ = ('store', )

    def __init__(self, *args, **kwargs):
        self.store = {}
        self.update(dict(*args, **kwargs))

    @recursive_repr()
    def __repr__(self):
        return f'<{self.__class__.__name__}({list(self.items())})>'

    def __getitem__(self, key):
        return self.store[self._transform_key(key)]

    def __setitem__(self, key, value):
        self.store[self._transform_key(key)] = value

    def __delitem__(self, key):
        del self.store[self._transform_key(key)]

    def __iter__(self):
        return iter(self.store)

    def __len__(self):
        return len(self.store)

    def copy(self):
        """Creates a shallow copy of the current instance."""
        return self.__class__(self)

    def _transform_key(self, key):
        return key


class CaseInsensitiveDict(TransformedDict):
    def _transform_key(self, key):
        return str(key).lower()
