import logging

import discord
from discord.ext import commands

from utils.colors import random_color
from utils.examples import _get_static_example
from utils.misc import truncate

logger = logging.getLogger(__name__)

# Only some common programming languages are featured in here.
# You need to replace the emojis yourself. They are here because
# otherwise they would bloat the config.py as fuck.
BASH_EMOTE         = '<:bash:481893449633890304>'
BRAINFUCK_EMOTE    = '<:brainfuck:477434846738907137>'
C_LANG_EMOTE       = '<:clang:481893204111654922>'
COFFEESCRIPT_EMOTE = '<:coffeescript:481895170783313920>'
CPP_EMOTE          = '<:cpp:477434843219755008>'
CSHARP_EMOTE       = '<:csharp:477433027010756608>'
DART_EMOTE         = '<:dartlang:481897509887934476>'
ELIXIR_EMOTE       = '<:elixir:481896314175750146>'
GOLANG_EMOTE       = '<:go:476742208045711362>'
HASKELL_EMOTE      = '<:haskell:481894936279515136>'
JAVA_EMOTE         = '<:java:380372941616971777>'
KOTLIN_EMOTE       = '<:kotlin:477434839071457282>'
LUA_EMOTE          = '<:lua:477434841822920714>'
NODEJS_EMOTE       = '<:nodejs:380374647302258690>'
PASCAL_EMOTE       = '<:pascal:481894128872062980>'
PERL_EMOTE         = '<:perl:481894462772215808>'
PHP_EMOTE          = '<:php:477436804035772416>'
PYTHON_EMOTE       = '<:py:481154314593763355>'
RUBY_EMOTE         = '<:ruby:477436800026148865>'
RUST_EMOTE         = '<:rust:477436806959202324>'
SCALA_EMOTE        = '<:scala:477436801762590733>'
SQL_EMOTE          = '<:mysql:477436808704032768>'
SWIFT_EMOTE        = '<:swift:477436796855255050>'

# And again, languages ahoy!
# The keys represent the possible Discord code blocks for the languages.
languages = {
    'bash':         ('bash', 2, BASH_EMOTE),
    'sh':           ('bash', 2, BASH_EMOTE),
    'brainfuck':    ('brainfuck', 0, BRAINFUCK_EMOTE),
    'bf':           ('brainfuck', 0, BRAINFUCK_EMOTE),
    'c':            ('c', 3, C_LANG_EMOTE),
    'coffeescript': ('coffeescript', 2, COFFEESCRIPT_EMOTE),
    'cpp':          ('cpp14', 2, CPP_EMOTE),
    'cs':           ('csharp', 2, CSHARP_EMOTE),
    'dart':         ('dart', 2, DART_EMOTE),
    'elixir':       ('elixir', 2, ELIXIR_EMOTE),
    'golang':       ('go', 2, GOLANG_EMOTE),
    'go':           ('go', 2, GOLANG_EMOTE),
    'hs':           ('haskell', 2, HASKELL_EMOTE),
    'java':         ('java', 2, JAVA_EMOTE),
    'kotlin':       ('kotlin', 1, KOTLIN_EMOTE),
    'lua':          ('lua', 1, LUA_EMOTE),
    'javascript':   ('nodejs', 2, NODEJS_EMOTE),
    'js':           ('nodejs', 2, NODEJS_EMOTE),
    'pascal':       ('pascal', 2, PASCAL_EMOTE),
    'perl':         ('perl', 2, PERL_EMOTE),
    'php':          ('php', 2, PHP_EMOTE),
    'python':       ('python3', 2, PYTHON_EMOTE),
    'py':           ('python3', 2, PYTHON_EMOTE),
    'ruby':         ('ruby', 2, RUBY_EMOTE),
    'rust':         ('rust', 2, RUST_EMOTE),
    'scala':        ('scala', 2, SCALA_EMOTE),
    'sql':          ('sql', 2, SQL_EMOTE),
    'swift':        ('swift', 2, SWIFT_EMOTE),
}


class JDoodleRequestFailedError(Exception):
    pass


class JDoodleCode(commands.clean_content):
    @staticmethod
    def random_example(ctx):
        return _get_static_example('jdoodle_eval')


class JDoodleResponse:
    def __init__(self, **kwargs):
        self.output = kwargs.get('output')
        self.status_code = kwargs.get('status_code')
        self.memory = kwargs.get('memory', 0)
        self.cpu_time = kwargs.get('cpu_time')
        self.used = kwargs.get('used')

    @classmethod
    def parse_result(cls, *, result):
        """Parses an API response."""

        # Makes this an enum?
        status_codes = {
            '400': 'Invalid request.',
            '401': 'Invalid API credentials.',
            '415': 'Invalid request.',
            '429': 'The daily rate limit for the API is reached.',
            '500': 'An internal server issue occurred. Please try again later.'
        }
        for code, error in status_codes.items():
            if result.get('statusCode', 200) == int(code):
                raise JDoodleRequestFailedError(f'Status code {code}: {error}')

        return cls(
            output=result.get('output'),
            status_code=result.get('statusCode', 200),
            memory=result.get('memory', '1000'),
            cpu_time=result.get('cpuTime', 0),
            used=result.get('used')
        )


class JDoodleWrapper:
    """A very, very simple API wrapper for the JDoodle API that also represents an interface between the user and the cog."""

    def __init__(self, bot):
        self.bot = bot
        self.base_url = 'https://api.jdoodle.com/v1'

        self.__client_id = bot.jdoodle_client_id
        self.__client_secret = bot.jdoodle_client_secret

    async def _request(self, route, **kwargs):
        """Makes a request to the JDoodle API."""

        url = f'{self.base_url}/{route}'
        params = {
            'clientId': self.__client_id,
            'clientSecret': self.__client_secret,
        }
        if kwargs:
            params.update(kwargs)

        logger.debug(f'Making POST request to the JDoodle API with body {params}.')

        result = await self.bot.session.post(url, headers={'Content-Type': 'application/json'}, json=params)
        response = await result.json()

        logger.debug(f'Received {response} from the JDoodle API.')
        return JDoodleResponse.parse_result(result=response)


class JDoodle(JDoodleWrapper):
    """Commands to interact with the JDoodle compiler API."""

    def __init__(self, bot):
        super().__init__(bot)

    async def __error(self, ctx, error):
        if isinstance(error, (commands.BadArgument, JDoodleRequestFailedError)):
            await ctx.send(error)

    @staticmethod
    async def send_embed(ctx, lang, emote, result):
        # The thing is that we need to format the title properly...
        title = f'Code evaluation: {lang.capitalize()} {emote}'

        # Potentially risky shit for not displaying the embed. Don't ask me why this isn't handled while parsing the response.
        if not result.memory:
            result.memory = 0
        if not result.cpu_time:
            result.cpu_time = 0.00

        embed = (discord.Embed(title=title, description='━━━━━━━━━━━━━━━━━━━', color=random_color())
                 .add_field(name='Memory usage:', value=f'{int(result.memory) / 1000}mb')
                 .add_field(name='Evaluated in:', value=f'{result.cpu_time}ms')
                 .add_field(name='Output:', value=f'```\n{truncate(result.output, 1013, "...")}```', inline=False)
                 .set_footer(text='Evaluated using the JDoodle API.', icon_url='https://bit.ly/2CvWRiA'))
        await ctx.send(embed=embed)

    @staticmethod
    def clean_code(code):
        if code.startswith('```') and code.endswith('```'):
            base = code.split('\n')
            return [base[0].strip('```'), base[1:-1]]
        else:
            raise commands.BadArgument('You need to use multiline codeblocks.')

    @commands.command(name='exec', aliases=['execute', 'run', 'debug'])
    @commands.cooldown(1, 60.0, commands.BucketType.user)
    async def _execute(self, ctx, *, code: JDoodleCode):
        """Evaluates code in multiple languages.

        **You need to specify the language in the codeblock!**

        Available languages:
            *Bash, Brainfuck, C, CoffeeScript, C++, C#, Dart, Elixir, Go, Haskell, Java, Kotlin, Lua,
            NodeJS, Pascal, Perl, PHP, Python, Ruby, Rust, Scala, SQL, Swift*

        Example:
            {prefix}exec
            ```py
            print('Hello, World!')
            ```
        """

        body = self.clean_code(code)
        try:
            language, version, emoji = languages[body[0]]
        except KeyError:
            return await ctx.send('Unsupported language!')

        to_eval = '\n'.join(body[1])
        await ctx.trigger_typing()

        result = await self._request('execute', script=to_eval, language=language, version_index=version)
        await self.send_embed(ctx, language, emoji, result)

    @commands.command(name='jdoodle')
    @commands.is_owner()
    async def _jdoodle(self, ctx):
        """Checks some stats about the JDoodle API.

        *This command can only be used by the bot owner.*
        """

        result = await self._request('credit-spent')
        embed = (discord.Embed(description=f'The bot made **{result.used}** requests, **{200 - result.used}** remaining.', color=random_color())
                 .set_author(name='JDoodle API requests', icon_url=ctx.author.avatar_url))
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(JDoodle(bot))
