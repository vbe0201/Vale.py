# This is an example for your bot's configuration file.
# Please fill out everything that is necessary and rename the file to `config.py`.


# ---------------------- CORE ----------------------
# These is the core config your bot will need at any time.

# This is your bot's token. Not your Client Secret or the Client ID, remember that!
# KEEP THIS PRIVATE AT ANY TIME!
token = ''

# The bot's default prefix. Without any spaces. It will be regexed to forgive one extra space between prefix and command.
prefix = ''

# A brief description about your bot.
description = ''

# A WebHook url for the bot. Isn't required yet, but may be in the future.
wh_url = ''

# The ID of the bot's owner.
owner_id = 1234567890

# The invite code for the bot's support server (if given)
support_server = ''

# The initial extensions that will be loaded when the bot starts. Specify the directory where to search for the extensions.
cog_dir = 'cogs'   # Only change this if you want to load cogs from another directory.

# You also have the possibility to just set some specific cogs that should be loaded on startup.
# cogs = [
#     f'{cog_dir}.owner.owner',
#     f'{cog_dir}.fun.currency',
#     ...
# ]

# -------------------- PRESENCE --------------------


# The possible games the bot will randomly choose from for the playing status.
# These are not cycled.
#
# To cover the new activity types, an entry in this list can be one of
# three types:
# str = just the name of the game, this will default to the "playing" status.
# tuple/list of (activity_type, name, Optional[url])
# dict of {'type': activity_type, 'name': name}
#
# The activity_type can be one of 4 types:
# * 0 - 'Playing'
# * 1 - 'Streaming' (Requires a twitch.tv url)
# * 2 - 'Listening'
# * 3 - 'Watching'
# You can either use the number (e.g. 2), or the name (e.g. 'listening')
#
# There are a few formats you can put in your playing status. These are:
# {server_count} = how many servers the bot is in
# {user_count} = how many users the bots shares a server with
# {version} = the bot's version number
#
# Note that if you want to have either { or } in your name you have
# to double them up. For e.g. {{status}}
games = []

# Twitch URL, you only need to provide this as a default if you use
# streaming status.
#
# This must be a valid twitch.tv URL, meaning it needs to include
# the https:// part as well
# (e.g. https://twitch.tv/itsvaleee)
twitch_url = ''

# --------------------- EMOJIS ---------------------


# Some emotes that are required for the bot's commands.

emoijs = dict(
    ping_emote='',  # Specify this emote without `<>`, it will be used to react to messages.
    success='\u2705',
    failure='\u274C',
    smart='',
    retard='',

    # ---- These emojis will all be used for the bot's about command.
    statistics='',
    version='',
    status='',
    signal='',
    server='',
    cpu='',
    memory='',
    shard='',
    python='',
    discordpy='',
    announcements='',
    postgres='',
)


# -------------------- API KEYS --------------------
# API keys for APIs the bot is going to use.

# JDoodle
jdoodle_client_id = ''
jdoodle_client_secret = ''

# Idiotic API
idiotic_api_key = ''

# -------------------- BOT LIST --------------------
# API keys for Discord Bot Lists your bot is in.

dbl_key = ''


# ------------------- POSTGRESQL -------------------
# This is the configuration your bot needs to connect to a PostgreSQL database.
# Create a new user for PostgreSQL with the permissions `can login` and probably `superuser`.
# Then create a new database for your bot and make that new user its owner.
# Also, you need to run `CREATE EXTENSION pg_trgm;` on the database in order to fully support all of the bot's features.

# Your PostgreSQL credentials.
pgsql_user = ''
pgsql_pass = ''
pgsql_host = '127.0.0.1'  # If your bot runs on the same machine as the database, the host is `127.0.0.1`
pgsql_port = '5432'       # The default port is `5432`
pgsql_db = ''
