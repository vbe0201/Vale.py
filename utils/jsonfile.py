import asyncio
import collections
import contextlib
import json
import os
import uuid

JSON_PATH = 'jsonfiles/'
os.makedirs(JSON_PATH, exist_ok=True)


# Skidded from Danny *dab*
class JSONFile(collections.abc.MutableMapping):
    """Yeah, well. This is actually shit that is used instead of a DB.

    Why? Because I'm cool and I can and this will save my ass on things a lot of querying would happen. Ez.
    """

    _transform_key = str

    def __init__(self, name, **options):
        self._name = JSON_PATH + name
        self._db = {}

        self._loop = options.pop('loop', asyncio.get_event_loop())
        self._lock = asyncio.Lock()
        if options.pop('load_later', False):
            self._loop.create_task(self.load())
        else:
            self._load()

    def __getitem__(self, item):
        return self._db[str(item)]

    def __setitem__(self, key, value):
        self._db[str(key)] = value

    def __delitem__(self, key):
        del self._db[str(key)]

    def __iter__(self):
        return iter(self._db)

    def __len__(self):
        return len(self._db)

    def _load(self):
        with contextlib.suppress(FileNotFoundError), open(self._name, 'r') as f:
            self._db.update(json.load(f))

    async def load(self):
        async with self._lock:
            await self._loop.run_in_executor(None, self._load)

    def _dump(self):
        temp = f'{self._name}-{uuid.uuid4()}.tmp'
        with open(temp, 'w', encoding='utf-8') as tmp:
            json.dump(self._db.copy(), tmp, ensure_ascii=True, sort_keys=True, indent=4, separators=(',', ':'))

        os.replace(temp, self._name)

    async def save(self):
        async with self._lock:
            await self._loop.run_in_executor(None, self._dump)

    async def put(self, key, value):
        """Edits a config entry."""

        self[key] = value
        await self.save()

    async def remove(self, key):
        """Removes a config entry."""

        del self[key]
        await self.save()
