import functools

from discord.ext import commands

# All copied from Milky, sorry for that


class RequireVarPositionalCommand(commands.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not any(p.kind is p.VAR_POSITIONAL for p in self.params.values()):
            raise TypeError('callback must be able to take variable positional arguments')

    async def call_before_hooks(self, ctx):
        # We have to hijack this function, because this is the function that is
        # called *right after* all the arguments are parsed, and it's the
        # simplest function to override. Overriding the argument parsing would
        # end up resulting in large amounts of copy+pasted code.
        parameters = self.params.values()

        # There could be default keyword-only args after the var-positional.
        num_positional_params = sum(p.kind is p.POSITIONAL_OR_KEYWORD for p in parameters)

        if len(ctx.args) <= num_positional_params:
            # Get the var positional argument and raise the error
            param = self.var_arg_parameter
            raise commands.MissingRequiredArgument(param)

        await super().call_before_hooks(ctx)

    @property
    def signature(self):
        param = self.var_arg_parameter.name
        return super().signature.replace(f'[{param}...]', f'<{param}...>')

    @property
    def var_arg_parameter(self):
        return next(p for p in self.params.values() if p.kind is p.VAR_POSITIONAL)


RequireVarArgCommand = RequireVarPositionalCommand  # alias

require_va_command = functools.partial(commands.command, cls=RequireVarPositionalCommand)
require_va_command.__doc__ = """\
Decorator that transforms a function into a RequireVarPositionalCommand.
Like commands.Command, but if the function has variable arguments, they must
be passed in.
"""


def requires_var_positional(command):
    """Return True if a command has required varargs, False otherwise"""
    return (isinstance(command, RequireVarPositionalCommand)
            or getattr(command, 'require_var_positional', False))
