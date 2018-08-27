class Database:
    """This class is used to handle all the database-related stuff."""

    @staticmethod
    async def get_guild_prefixes(bot, message):
        db = await bot.pool.acquire()
        query = """SELECT prefixes FROM guild_prefixes WHERE guild_id = $1;"""

        async with db.transaction():
            guild_prefixes = await db.fetch(query, message.guild.id)
        await bot.pool.release(db)

        if not guild_prefixes:
            return []
        else:
            return guild_prefixes[0]["prefixes"]


class TableFormat:
    """This class handles all related things for the visual presentation of a table."""
    def __init__(self):
        self._widths = []
        self._columns = []
        self._rows = []

    def set(self, columns):
        self._columns = columns
        self._widths = [len(column) + 2 for column in columns]

    def add_row(self, rows):
        rows = [str(row) for row in rows]
        self._rows.append(rows)

        for index, element in enumerate(rows):
            width = len(element) + 2
            if width > self._widths[index]:
                self._widths[index] = width

    def add(self, rows):
        for row in rows:
            self.add_row(row)

    def render(self):
        """Renders a table in rST format for graphical presentation in Discord chat."""

        table = "+".join("-" * width for width in self._widths)
        table = f"+{table}+"

        to_draw = [table]

        def get(d):
            element = "|".join(f"{element:^{self._widths[index]}}" for index, element in enumerate(d))
            return f"|{element}|"

        to_draw.append(get(self._columns))
        to_draw.append(table)

        for row in self._rows:
            to_draw.append(get(row))

        to_draw.append(table)
        return "\n".join(to_draw)
