class TableFormat:
    """This class handles all related things to the visual presentation of a table."""

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

        for index, row in enumerate(rows):
            width = len(row) + 2
            if width > self._widths[index]:
                self._widths[index] = width

    def add(self, rows):
        for row in rows:
            self.add_row(row)

    def render(self):
        """Renders a table in rST format for graphical presentation in Discord chat."""

        table = '+' + ('+'.join('-' * width for width in self._widths)) + '+'
        to_draw = [table]

        def get(results):
            element = '|'.join(f'{result:^{self._widths[index]}}' for index, result in enumerate(results))
            return f'|{element}|'

        to_draw.append(get(self._columns))
        to_draw.append(table)

        for row in self._rows:
            to_draw.append(get(row))

        to_draw.append(table)
        return '\n'.join(to_draw)
