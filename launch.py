import asyncio
import logging
import sys

import click

from core import ValePy
from utils import db, context_managers

try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
finally:
    loop = asyncio.get_event_loop()

import config


@click.group(invoke_without_command=True)
@click.option('--stream-log', is_flag=True, help='Adds a stderr stream handler to the bot\'s logging component.')
@click.option('--init-db', is_flag=True, help='Initializes the database. Recommended on first bot start.')
def root(stream_log, init_db):
    bot = ValePy()

    if init_db:
        bot.loop.create_task(init_database())

    with context_managers.log(stream_log):
        try:
            bot.run()
        except KeyboardInterrupt:
            bot.loop.create_task(bot.logout())


async def _create_tables(pool):
    async with pool.transaction():
        for table in db.all_tables():
            query = table.create_sql(exist_ok=True)
            logging.info('Creating table %s\nusing query %r', table.__tablename__, query)
            await pool.execute(query)


async def init_database():
    """This initializes our database.

    It runs the queries for the table creation of all database tables the bot will use.
    On first bot start, you should ALWAYS run this!
    """

    pool = await db.create_pool(config)
    con = await pool.acquire()

    await _create_tables(con)
    await pool.release(con)


if __name__ == '__main__':
    sys.exit(root())
