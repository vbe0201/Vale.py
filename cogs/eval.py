import discord
from discord.ext import commands
import logging
import utils.jdoodle as jdoodle
from utils.embed import EmbedUtils


logger = logging.getLogger(__name__)

BASH_EMOTE         = "<:bash:481893449633890304>"  # noqa
BRAINFUCK_EMOTE    = "<:brainfuck:477434846738907137>"  # noqa
C_LANG_EMOTE       = "<:clang:481893204111654922>"  # noqa
COFFEESCRIPT_EMOTE = "<:coffeescript:481895170783313920>"  # noqa
CPP_EMOTE          = "<:cpp:477434843219755008>"  # noqa
CSHARP_EMOTE       = "<:csharp:477433027010756608>"  # noqa
DART_EMOTE         = "<:dartlang:481897509887934476>"  # noqa
ELIXIR_EMOTE       = "<:elixir:481896314175750146>"  # noqa
GOLANG_EMOTE       = "<:go:476742208045711362>"  # noqa
HASKELL_EMOTE      = "<:haskell:481894936279515136>"  # noqa
JAVA_EMOTE         = "<:java:380372941616971777>"  # noqa
KOTLIN_EMOTE       = "<:kotlin:477434839071457282>"  # noqa
LUA_EMOTE          = "<:lua:477434841822920714>"  # noqa
NODEJS_EMOTE       = "<:nodejs:380374647302258690>"  # noqa
PASCAL_EMOTE       = "<:pascal:481894128872062980>"  # noqa
PERL_EMOTE         = "<:perl:481894462772215808>"  # noqa
PHP_EMOTE          = "<:php:477436804035772416>"  # noqa
PYTHON_EMOTE       = "<:py:481154314593763355>"  # noqa
RUBY_EMOTE         = "<:ruby:477436800026148865>"  # noqa
RUST_EMOTE         = "<:rust:477436806959202324>"  # noqa
SCALA_EMOTE        = "<:scala:477436801762590733>"  # noqa
SQL_EMOTE          = "<:mysql:477436808704032768>"  # noqa
SWIFT_EMOTE        = "<:swift:477436796855255050>"  # noqa


class Evaluate(jdoodle.JDoodle):
    def __init__(self, bot):
        super().__init__(bot, client_id=bot.jdoodle_client, client_secret=bot.jdoodle_secret)

        self.bot = bot

        self.languages = {
            "bash":         ("bash", 2, BASH_EMOTE),  # noqa
            "sh":           ("bash", 2, BASH_EMOTE),  # noqa
            "brainfuck":    ("brainfuck", 0, BRAINFUCK_EMOTE),  # noqa
            "bf":           ("brainfuck", 0, BRAINFUCK_EMOTE),  # noqa
            "c":            ("c", 3, C_LANG_EMOTE),  # noqa
            "coffeescript": ("coffeescript", 2, COFFEESCRIPT_EMOTE),  # noqa
            "cpp":          ("cpp14", 2, CPP_EMOTE),  # noqa
            "cs":           ("csharp", 2, CSHARP_EMOTE),  # noqa
            "dart":         ("dart", 2, DART_EMOTE),  # noqa
            "elixir":       ("elixir", 2, ELIXIR_EMOTE),  # noqa
            "golang":       ("go", 2, GOLANG_EMOTE),  # noqa
            "go":           ("go", 2, GOLANG_EMOTE),  # noqa
            "hs":           ("haskell", 2, HASKELL_EMOTE),  # noqa
            "java":         ("java", 2, JAVA_EMOTE),  # noqa
            "kotlin":       ("kotlin", 1, KOTLIN_EMOTE),  # noqa
            "lua":          ("lua", 1, LUA_EMOTE),  # noqa
            "javascript":   ("nodejs", 2, NODEJS_EMOTE),  # noqa
            "js":           ("nodejs", 2, NODEJS_EMOTE),  # noqa
            "pascal":       ("pascal", 2, PASCAL_EMOTE),  # noqa
            "perl":         ("perl", 2, PERL_EMOTE),  # noqa
            "php":          ("php", 2, PHP_EMOTE),  # noqa
            "python":       ("python3", 2, PYTHON_EMOTE),  # noqa
            "py":           ("python3", 2, PYTHON_EMOTE),  # noqa
            "ruby":         ("ruby", 2, RUBY_EMOTE),  # noqa
            "rust":         ("rust", 2, RUST_EMOTE),  # noqa
            "scala":        ("scala", 2, SCALA_EMOTE),  # noqa
            "sql":          ("sql", 2, SQL_EMOTE),  # noqa
            "swift":        ("swift", 2, SWIFT_EMOTE),  # noqa
        }

    @staticmethod
    def get_embed(language, emote, output):
        """Returns an embed formatted with the output and the language that was evaluated."""

        embed = discord.Embed(
            title=f"Code Evaluation: {language} {emote}",
            description="━━━━━━━━━━━━━━━━━━━",
            color=EmbedUtils.random_color()
        )
        embed.add_field(
            name="Output",
            value=f"```\n{output}\n```"
        )
        embed.set_footer(
            text="Evaluated using the JDoodle API.",
            icon_url="https://bit.ly/2CvWRiA"
        )

        return embed

    @staticmethod
    def clean_code(code: str):
        """Removes codeblocks and returns the language as well as the code to be evaluated as a list."""

        if code.startswith("```") and code.endswith("```"):
            base_code = code.split("\n")
            language = base_code[0].strip("```")
            to_eval = base_code[1:-1]

            return [language, to_eval]

    @commands.command(name="execute", aliases=["exec"])
    @commands.cooldown(1, 60.0, commands.BucketType.user)
    async def _execute(self, ctx, *, code: str):
        """Evaluates Code in multiple languages.

        Example:
            (3 backticks)java
            Code here
            (3 backticks)

        Avaliable languages:
            Bash, Brainfuck, C, Coffeescript, C++, C#, Dart, Elixir, Go, Haskell, Java, Kotlin, Lua, NodeJS,
            Pascal, Perl, PHP, Python, Ruby, Rust, Scala, SQL, Swift

        Use a specific codeblock for a language to evaluate code like in the example above.
        """

        body = self.clean_code(code)

        if body[0] is None or len(body[0]) == 0:
            return await ctx.send("Please specify a language that should be evaluated in your code block.")

        language, version, emote = self.languages[body[0]]
        to_eval = "\n".join(body[1])

        try:
            result = await super()._request(script=to_eval, language=language, version_index=version)

            embed = self.get_embed(language, emote, result.output)
            await ctx.send(embed=embed)
        except jdoodle.JDoodleRequestFailedError as e:
            logger.error(e)


def setup(bot):
    bot.add_cog(Evaluate(bot))
