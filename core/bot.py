import asyncio
import collections
import contextlib
import importlib
import inspect
import logging
import os
import pkgutil
import random
import re
import sys
from datetime import datetime

import aiohttp
import discord
import psutil
from discord.ext import commands

from . import context

from utils import db
from utils.jsonfile import JSONFile
from utils.scheduler import DatabaseScheduler
from utils.transformdict import CaseInsensitiveDict
from utils.time import duration_units

import config

logger = logging.getLogger(__name__)
command_logger = logging.getLogger('commands')


# Permissions stuff starting here
def _define_permissions(*perms):
    permissions = discord.Permissions.none()
    permissions.update(**dict.fromkeys(perms, True))
    return permissions


_MINIMAL_PERMISSIONS = [
    'send_messages',
    'embed_links',
    'add_reactions',
    'attach_files',
    'use_external_emojis',
]

_FULL_PERMISSIONS = [
    *_MINIMAL_PERMISSIONS,
    'manage_guild',
    'manage_roles',
    'manage_channels',
    'kick_members',
    'ban_members',
    'create_instant_invite',
    'manage_messages',
    'read_message_history',
    'mute_members',
    'deafen_members',
]

# Let's make actual permissions out of that stuff.
_MINIMAL_PERMISSIONS = _define_permissions(*_MINIMAL_PERMISSIONS)
_FULL_PERMISSIONS = _define_permissions(*_FULL_PERMISSIONS)
del _define_permissions


# Some other irrelevant stuff
def _is_submodule(parent, child):
    return parent == child or child.startswith(parent + '.')


class _UnicodeEmoji(discord.PartialEmoji):
    __slots__ = ()

    def __new__(cls, name):
        return super().__new__(cls, animated=False, name=name, id=None)

    @property
    def url(self):
        hex_values = '-'.join(hex(ord(char))[2:] for char in str(self))
        return f'https://twemoji.maxcdn.com/2/72x72/{hex_values}.png'


MAX_FORMATTER_WIDTH = 90


def _callable_prefix(bot, message):
    prefixes = [f'<@{bot.user.id}> ', f'<@!{bot.user.id}> ', bot.default_prefix]
    if message.guild:
        prefixes.extend(bot.prefixes.get(message.guild.id, []))

    return prefixes


_sentinel = object()


def _is_cog_hidden(cog):
    hidden = getattr(cog, '__hidden__', _sentinel)
    if hidden is not _sentinel:
        return hidden

    try:
        module_name = cog.__module__
    except AttributeError:
        return False

    while module_name:
        module = sys.modules[module_name]
        hidden = getattr(module, '__hidden__', _sentinel)
        if hidden is not _sentinel:
            return hidden

        module_name = module_name.rpartition('.')[0]

    return False


# Activity-related stuffs...
def _parse_type(type_):
    with contextlib.suppress(AttributeError):
        type_ = type_.lower()

    try:
        return discord.ActivityType[type_]
    except KeyError:
        pass

    _type = discord.enums.try_enum(discord.ActivityType, type_)
    if _type is type_:
        raise ValueError(f'Inappropriate activity type passed: {type_!r}')
    return _type


def _get_proper_activity(type, name, url=''):
    if type is discord.ActivityType.playing:
        return discord.Game(name=name)

    if type is discord.ActivityType.streaming:
        # TODO: Validate twitch.tv url
        return discord.Streaming(name=name, url=url)

    return discord.Activity(type=type, name=name)


VersionInfo = collections.namedtuple('VersionInfo', 'major minor micro releaselevel serial')


class ValePy(commands.AutoShardedBot):
    __version__ = '0.0.2a'
    version_info = VersionInfo(major=0, minor=0, micro=2, releaselevel='alpha', serial=0)

    def __init__(self):
        super().__init__(
            command_prefix=_callable_prefix,
            description=config.description,
            owner_id=config.owner_id,
            pm_help=None,
            case_insensitive=True,
            fetch_offline_members=False
        )

        self.cogs = CaseInsensitiveDict()

        self.command_counter = collections.Counter()
        self.bot_emojis = config.emoijs
        self.prefixes = JSONFile('prefixes.json')

        self.session = aiohttp.ClientSession(loop=self.loop)
        self.launch = datetime.utcnow()
        self.pool = self.loop.run_until_complete(db.create_pool(config))
        self.process = psutil.Process(os.getpid())

        self.db_scheduler = DatabaseScheduler(self.pool, timefunc=datetime.utcnow)
        self.db_scheduler.add_callback(self._dispatch_from_scheduler)

        self.jdoodle_client_id = config.jdoodle_client_id
        self.jdoodle_client_secret = config.jdoodle_client_secret
        self.idiotic_api_key = config.idiotic_api_key

        # Pass cogs manually so defining the actual cogs that should be loaded can already be done on startup.
        for name in os.listdir(config.cog_dir):
            if name.startswith('__'):
                continue

            self.load_extension(f'{config.cog_dir}.{name}')

        self.load_extension('core.errors')

        self._presence_task = self.loop.create_task(self.change_activity())

    def _load_emojis(self):
        import emoji

        emoji_cache = {}

        # Not recognized by the Unicode or Emoji standard, but Discord never followed standards
        is_edge_case_emoji = {
            *(chr(index + 0x1f1e6) for index in range(26)),
            *(f'{index}\u20e3' for index in [*range(10), '#', '*']),
        }.__contains__

        def parse_emoji(em):
            if isinstance(em, int) and not isinstance(em, bool):
                return self.get_emoji(em)

            if isinstance(em, str):
                match = re.match(r'<a?:[a-zA-Z0-9]+:([0-9]+)>$', em)
                if match:
                    return self.get_emoji(int(match[1]))
                if em in emoji.UNICODE_EMOJI or is_edge_case_emoji(em):
                    return _UnicodeEmoji(name=em)
                logger.warning('Unknown emoji: %r', em)

            return em

        for name, em in inspect.getmembers(emoji):
            if name[0] == '_':
                continue

            if hasattr(em, '__iter__') and not isinstance(em, str):
                em = list(map(parse_emoji, em))
            else:
                em = parse_emoji(em)

            emoji_cache[name] = em

        del emoji
        self.emoji_config = collections.namedtuple('EmojiConfig', emoji_cache)(**emoji_cache)

    def _dispatch_from_scheduler(self, entry):
        self.dispatch(entry.event, entry)

    async def logout(self):
        await self.session.close()
        self._presence_task.cancel()
        await super().logout()

    def add_cog(self, cog):
        super().add_cog(cog)

        if _is_cog_hidden(cog):
            for _, command in inspect.getmembers(cog, lambda m: isinstance(m, commands.Command)):
                command.hidden = True

    @staticmethod
    def search_extensions(name):
        spec = importlib.util.find_spec(name)
        if not spec:
            raise ModuleNotFoundError(f'No module called {name!r}')

        path = spec.submodule_search_locations
        if not path:
            return None

        return (name for info, name, is_pkg in pkgutil.iter_modules(path, spec.name + '.')
                if not is_pkg)

    def load_extension(self, name):
        modules = self.search_extensions(name)
        if not modules:
            return super().load_extension(name)

        for name in modules:
            try:
                super().load_extension(name)
            except discord.ClientException as e:
                if 'extension does not have a setup function' not in str(e):
                    raise

        self.extensions[name] = importlib.import_module(name)

    def unload_extension(self, name):
        super().unload_extension(name)

        for module_name in list(self.extensions):
            if _is_submodule(name, module_name):
                del self.extensions[module_name]

    @contextlib.contextmanager
    def temp_listener(self, func, name=None):
        """Context manager for temporary listeners."""

        self.add_listener(func, name)
        try:
            yield
        finally:
            self.remove_listener(func)

    def __format_name_for_activity(self, name):
        return name.format(server_count=self.guild_count, user_count=self.user_count, version=self.__version__)

    def __parse_activity(self, activity):
        if isinstance(activity, str):
            return discord.Game(name=self.__format_name_for_activity(activity))

        if isinstance(activity, collections.abc.Sequence):
            _type, name, url = (*activity, config.twitch_url)[:3]  # Not accepting a sequence of just "[type]"
            _type = _parse_type(_type)
            name = self.__format_name_for_activity(name)
            return _get_proper_activity(_type, name, url)

        if isinstance(activity, collections.abc.Mapping):
            def get(key):
                try:
                    return activity[key]
                except KeyError:
                    raise ValueError(f'Game must have {key!r} key, got {activity!r}')

            data = {
                **activity,
                'type': _parse_type(get('type')),
                'name': self.__format_name_for_activity(get('name'))
            }
            data.setdefault('url', config.twitch_url)

            return _get_proper_activity(**data)

        raise TypeError(f'Expected a str, sequence or mapping for activity, got {type(activity).__name__!r}!')

    async def change_activity(self):
        await self.wait_until_ready()

        while True:
            activity = random.choice(config.games)
            try:
                activity = self.__parse_activity(activity)
            except (TypeError, ValueError):
                logger.exception(f'Inappropriate game {activity!r}, removing it from the list.')
                config.games.remove(activity)

            await self.change_presence(activity=activity)
            await asyncio.sleep(random.uniform(0.5, 2) * 60)

    def run(self):
        super().run(config.token, reconnect=True)

    def get_guild_prefixes(self, guild):
        fake_msg = discord.Object(None)
        fake_msg.guild = guild
        return _callable_prefix(self, fake_msg)

    def get_raw_guild_prefixes(self, guild_id):
        return self.prefixes.get(guild_id, [self.default_prefix])

    async def set_guild_prefixes(self, guild_id, prefixes):
        prefixes = prefixes or []
        if len(prefixes) > 10:
            raise RuntimeError('Cannot have more than 10 custom prefixes per guild.')

        await self.prefixes.put(guild_id, sorted(set(prefixes), reverse=True))

    async def process_commands(self, message):
        """This overloads the original method from BotBase.

        This is necessary to have the ability to pass an own Context subclass to the commands.
        """

        ctx = await self.get_context(message, cls=context.Context)

        if ctx.command is None:
            if self.user.mention in message.content:
                await message.add_reaction(self.bot_emojis.get('ping_emote'))
            return

        async with ctx.acquire():   # Acquire the pool from the database connection
            await self.invoke(ctx)

    async def on_ready(self):
        logger.info(f'\n================\nLogged in as:\n{self.user.name}\n{self.user.id}\n\n================\n')
        self._load_emojis()
        self.db_scheduler.run()

        if not hasattr(self, 'appinfo'):
            self.appinfo = (await self.application_info())

        if not hasattr(self, 'creator'):
            self.creator = await self.get_user_info(self.owner_id)

        if not hasattr(self, 'launch'):
            self.launch = datetime.utcnow()

    async def on_message(self, message):
        if message.author.bot:
            return

        await self.process_commands(message)

    async def on_command(self, ctx):
        self.command_counter['total'] += 1
        if isinstance(ctx.channel, discord.abc.PrivateChannel):
            self.command_counter['in DMs'] += 1
        elif isinstance(ctx.channel, discord.abc.GuildChannel):
            self.command_counter[str(ctx.guild.id)] += 1

        # For the case it's a DM channel the guild attribute is not provided.
        if not ctx.guild:
            ctx.guild = discord.Object(123456789012345)
            ctx.guild.id = 'DM channel, no ID provided'

        fmt = ('Command executed in {0.channel} ({0.channel.id}) from {0.guild} ({0.guild.id})'
               ' by {0.author} ({0.author.id}) with content: {0.message.content}')
        command_logger.info(fmt.format(ctx))

    async def on_command_completion(self, ctx):
        self.command_counter['succeeded'] += 1

    async def on_command_error(self, ctx, error):
        if not (
                isinstance(error, commands.CheckFailure)
                and not isinstance(error, commands.BotMissingPermissions)
                and await self.is_owner(ctx.author)
        ):
            return

        try:
            await ctx.release()
            async with ctx.acquire():
                await ctx.reinvoke()

        except Exception as e:
            await ctx.command.dispatch_error(ctx, e)

    def guilds_view(self):
        return self._connection._guilds.values()

    def users_view(self):
        return self._connection._users.values()

    def voice_clients_view(self):
        return self._connection._voice_clients.values()

    @property
    def guild_count(self):
        return len(self._connection._guilds)

    @property
    def user_count(self):
        return len(self._connection._users)

    @property
    def vc_count(self):
        return len(self._connection._voice_clients)

    # The following properties are config-related.

    @property
    def default_prefix(self):
        return config.prefix

    @property
    def webhook(self):
        webhook_url = config.wh_url

        if webhook_url:
            return discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(self.session))

        return None

    @property
    def source(self):
        return f'https://github.com/itsVale/Vale.py'

    @property
    def support_server(self):
        code = config.support_server
        if not code:
            return '<No support server for this bot provided>'

        return f'https://discord.gg/{code}'

    @discord.utils.cached_property
    def minimal_invite_url(self):
        return discord.utils.oauth_url(self.user.id, _MINIMAL_PERMISSIONS)

    @discord.utils.cached_property
    def invite_url(self):
        return discord.utils.oauth_url(self.user.id, _FULL_PERMISSIONS)

    @property
    def uptime(self):
        return duration_units((datetime.utcnow() - self.launch).total_seconds())
