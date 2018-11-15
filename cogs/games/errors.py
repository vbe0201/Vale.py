class RageQuit(Exception):
    """Exception raised when a player quits a game."""


class DrawRequested(Exception):
    """Exception raised when a player requests a draw."""


class NotEnoughMoney(Exception):
    """Exception raised when a user tries to create or join a game without having enough money for that."""

    def __init__(self, amount, required):
        self.amount = amount
        self.required = required

    def __str__(self):
        return f'Hey, hey, hey, you are missing **{self.required - self.amount}** \N{MONEY WITH WINGS} to create/join this game!'
