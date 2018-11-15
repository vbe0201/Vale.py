from contextlib import contextmanager
import logging
import os
from datetime import datetime
from pathlib import Path

_sentinel = object()


@contextmanager
def temporary_attribute(obj, attr, value):
    """Temporarily sets an object's attribute to a value."""

    old_value = getattr(obj, attr, _sentinel)
    setattr(obj, attr, value)

    try:
        yield
    finally:
        if old_value is _sentinel:
            delattr(obj, attr)
        else:
            setattr(obj, attr, old_value)


@contextmanager
def temporary_item(obj, item, new_value):
    obj[item] = new_value

    try:
        yield new_value
    finally:
        if item in obj:
            del obj[item]


class temporary_message:
    """Sends a temporary message, then deletes it."""

    def __init__(self, destination, content=None, *, file=None, embed=None):
        self.destination = destination
        self.content = content
        self.file = file
        self.embed = embed

    async def __aenter__(self):
        self.message = await self.destination.send(self.content, file=self.file, embed=self.embed)
        return self.message

    async def __aexit__(self, exc_type, exc, tb):
        await self.message.delete()


@contextmanager
def log(stream=False):
    logging.getLogger('discord').setLevel(logging.INFO)

    log_dir = Path(os.path.dirname(__file__)).parent / 'logs'
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(
        filename=f'logs/vale-py.{datetime.now()}.log',
        encoding='utf-8',
        mode='w'
    )

    formatter = logging.Formatter('[{levelname}] ({asctime}) - {name}:{lineno} - {message}', '%Y-%m-%d %H:%M:%S', style='{')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    try:
        yield
    finally:
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
