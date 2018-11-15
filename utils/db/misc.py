import json

import asyncpg

__all__ = ['create_pool']


async def _set_codec(con):
    await con.set_type_codec(
        'jsonb',
        schema='pg_catalog',
        encoder=json.dumps,
        decoder=json.loads,
        format='text'
    )


async def _create_pool(*, init=None, **kwargs):
    if not init:
        async def new_init(con):
            await _set_codec(con)
    else:
        async def new_init(con):
            await _set_codec(con)
            await init(con)

    return await asyncpg.create_pool(init=new_init, **kwargs)


async def create_pool(config):
    """This is what actually creates the connection pool for the bot."""

    postgresql = dict(
        user=config.pgsql_user,
        password=config.pgsql_pass,
        host=config.pgsql_host,
        port=config.pgsql_port,
        database=config.pgsql_db
    )

    return await _create_pool(**postgresql, command_timeout=60)
