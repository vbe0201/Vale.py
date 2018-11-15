"""
This represents a simple database wrapper that helps in
visualizing tables as classes.

It is not my intention to create a full ORM!
If that's what you are looking for, you might better have a look at peewee.
"""

import inspect
import itertools


class SchemaError(Exception):
    pass


class SQLType:
    def __init_subclass__(cls, sql=None, real_type=True, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.real_type = real_type

        if sql is not None:
            cls.sql = sql


class Binary(SQLType, sql='BYTEA'):
    pass


class Boolean(SQLType, sql='BOOLEAN'):
    pass


class Date(SQLType, sql='DATE'):
    pass


class Double(SQLType, sql='REAL'):
    pass


class Float(SQLType, sql='FLOAT'):
    pass


class Integer(SQLType, sql='INTEGER'):
    pass


class BigInt(SQLType, sql='BIGINT'):
    pass


class SmallInt(SQLType, sql='SMALLINT'):
    pass


class Serial(SQLType, sql='SERIAL', real_type=False):
    pass


class BigSerial(SQLType, sql='BIGSERIAL', real_type=False):
    pass


class SmallSerial(SQLType, sql='SMALLSERIAL', real_type=False):
    pass


class Timestamp(SQLType):
    def __init__(self, *, timezone=False):
        self.timezone = timezone

    @property
    def sql(self):
        if self.timezone:
            return 'TIMESTAMP WITH TIMEZONE'

        return 'TIMESTAMP'


class Interval(SQLType):
    def __init__(self, *, field=None):
        self.field = field

    @property
    def sql(self):
        if self.field:
            return 'INTERVAL ' + self.field

        return 'INTERVAL'


class Numeric(SQLType):
    def __init__(self, *, precision=None, scale=0):
        if precision is not None:
            if not 0 <= precision <= 1000:
                raise SchemaError('Precision must be between 0 and 1000.')

        self.precision = precision
        self.scale = scale

    @property
    def sql(self):
        return 'NUMERIC'


class String(SQLType):
    def __init__(self, *, length=None, fixed=False):
        self.length = length
        self.fixed = fixed

        if fixed and not length:
            raise SchemaError('Cannot have fixed string with no length.')

    @property
    def sql(self):
        if not self.length:
            return 'TEXT'
        if self.fixed:
            return f'CHAR({self.length})'
        return f'VARCHAR({self.length})'


class Text(SQLType, sql='TEXT'):
    def __init__(self):
        super().__init__()


class JSON(SQLType, sql='JSON'):
    pass


class JSONB(SQLType, sql='JSONB'):
    pass


def _check_type(type):
    if inspect.isclass(type):
        type = type()

    if not isinstance(type, SQLType):
        raise SchemaError('Type should be derived from SQLType.')

    return type


class Array(SQLType):
    def __init__(self, type, size=None):
        self._sql_type = _check_type(type).sql
        self.size = size

    @property
    def sql(self):
        if not self.size:
            return f'{self._sql_type}[]'

        return f'{self._sql_type}[{self.size}]'


def _check_action(action, name):
    action = action.upper()
    valid_actions = ['NO ACTION', 'RESTRICT', 'CASCADE', 'SET NULL', 'SET DEFAULT']

    if action not in valid_actions:
        raise SchemaError(f'{name!r} must be one of {valid_actions}.')
    return action


class ForeignKey(SQLType, real_type=False):
    def __init__(self, column, *, type=None, on_delete='CASCADE', on_update='NO ACTION'):
        if not type:
            type = Integer

        self.name = None
        self.column = column
        self.type = _check_type(type)
        self.on_delete = _check_action(on_delete, 'on_delete')
        self.on_update = _check_action(on_update, 'on_update')

    def __set_name__(self, owner, name):
        self.name = name

    @property
    def table(self):
        return self.column.table

    def create_sql(self):
        return (
            f'{self.name} {self.type.sql} REFERENCES {self.table.__tablename__} ({self.column.name}) '
            f'ON DELETE {self.on_delete} ON UPDATE {self.on_update}'
        )

    @property
    def sql(self):
        return self.create_sql()


class Column:
    __slots__ = ('type', 'primary_key', 'nullable', 'default', 'unique', 'name', 'table')

    def __init__(self, type, *, primary_key=False, nullable=False, unique=False, default=None):
        if sum(map(bool, (unique, primary_key, default is not None))) > 1:
            raise ValueError('Cannot specify primary_key, unique, and default at the same time.')

        self.type = _check_type(type)
        self.nullable = nullable
        self.unique = unique
        self.primary_key = primary_key
        self.default = default
        self.name = None
        self.table = None

    def __set_name__(self, owner, name):
        self.name = name
        self.table = owner

    def create_sql(self):
        if not self.name:
            raise RuntimeError('Column should be defined inside a table subclass.')

        builder = [self.name, self.type.sql]
        build = builder.append

        default = self.default
        if default is not None:
            build('DEFAULT')

            if isinstance(default, str) and isinstance(self.type, String):
                build(f"'{default}'")
            elif isinstance(default, bool):
                build(str(default).upper())
            else:
                build(f'({default})')
        elif self.unique:
            build('UNIQUE')
        elif self.primary_key:
            build('PRIMARY KEY')

        nullable_string = 'NULL'
        if not self.nullable:
            nullable_string = 'NOT NULL'
        build(nullable_string)

        return ' '.join(builder)


class Index:
    def __init__(self, *columns, unique=False):
        self.columns = columns
        self.unique = unique
        self.name = None
        self.table = None

    def __set_name__(self, owner, name):
        self.table = owner
        self.name = name

    def create_sql(self):
        builder = ['CREATE']

        if self.unique:
            builder.append('UNIQUE')

        builder.extend([
            'INDEX IF NOT EXISTS',
            self.name,
            'ON',
            self.table.__tablename__,
            f'({", ".join(column.name if isinstance(column, Column) else column for column in self.columns)});'
        ])

        return ' '.join(builder)


class Table:
    def __init_subclass__(cls, *, table_name='', **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__tablename__ = table_name or cls.__name__.lower()

        cls.columns = [value for value in cls.__dict__.values() if isinstance(value, (Column, ForeignKey))]
        cls.indexes = [value for value in cls.__dict__.values() if isinstance(value, Index)]

        cls.__create_extra__ = getattr(cls, '__create_extra__', [])

    @classmethod
    def create_sql(cls, *, exist_ok=True):
        """Returns the CREATE TABLE statement for this table."""

        builder = ['CREATE TABLE']
        build = builder.append

        if exist_ok:
            build('IF NOT EXISTS')
        build(cls.__tablename__)

        column_sql = (column.create_sql() for column in cls.columns)
        column_statements = ',\n'.join(itertools.chain(column_sql, cls.__create_extra__))
        build(f'(\n{column_statements}\n);')

        statements = [' '.join(builder)]
        statements.extend(index.create_sql() for index in cls.indexes)
        return "\n".join(statements)

    @classmethod
    def build(cls, bot, *, exist_ok=True):
        """Actually creates a table."""

        return bot.loop.create_task(bot.pool.execute(cls.create_sql(exist_ok=exist_ok)))


def all_tables():
    return Table.__subclasses__()
