<div align="center">
  <img src="https://user-images.githubusercontent.com/38182450/43689008-bce3ad5e-98f3-11e8-929c-4801a540cefb.png" width="300"/>
  <h1>Vale.py</h1>
  <strong>A bot to support Discord servers that I like.</strong>
  <br><br>
  <a href="https://github.com/itsVale/Vale.py/wiki"><img src="https://user-images.githubusercontent.com/38182450/43689699-b822f4fe-98fe-11e8-89c9-5fa5da75d088.png" width="200" /></a> &nbsp;
  <a href="#"><img src="https://user-images.githubusercontent.com/38182450/43689793-c45cbea2-98ff-11e8-828a-53d29f425d9c.png" width="200" /></a> &nbsp;
  <a href="https://discordapp.com/oauth2/authorize?client_id=458286335304794127&scope=bot&permissions=2146958847"><img src="https://user-images.githubusercontent.com/38182450/43689573-e7e657aa-98fc-11e8-84a4-38d99df2dade.png" width="200" /></a><br><br>
  <a class="badge-ci-passing" href="https://travis-ci.com/itsVale/Vale.py"><img src="https://travis-ci.com/itsVale/Vale.py.svg?branch=master" /></a>
  <a class="badge-align" href="https://www.codacy.com/app/itsVale/Vale.py?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=itsVale/Vale.py&amp;utm_campaign=Badge_Grade"><img src="https://api.codacy.com/project/badge/Grade/cf549d36684740199c1a98f33f57f415"/></a>
</div>

---

## This bot is under active development!

For now it doesn't make much sense to invite the bot since it won't be
online though. The bot is incomplete yet as well as this README but
feel free to contribute if
you spot a bug or have a suggestion on how to improve the bot!

### Installation
___
**Of course you can self-host the bot if you want to work on it, but I'd
rather prefer that you invite it to your guild instead of hosting your
own instance of it.**

### Get Python 3.6.5+
___
Any Python version higher or equal to 3.6.5 can be used to run the bot.

### Download or clone this repository and install the dependencies
___
After you got the source code of the bot, run

```$sql
    python3 -m pip install -r -U requirements.txt
```

to install all the requirements the bot has.

### Setup PostgreSQL on your machine
___
You can download and install it from [here](https://www.postgresql.org/)

It is important since you'll need a PostgreSQL database to connect your bot to.
The newest version should be fine but you'll need at least PostgreSQL 9.5.

__Type the following code into the psql tool:__
```$sql
    CREATE ROLE valepy WITH LOGIN PASSWORD 'your_password';
    CREATE DATABASE valepy OWNER valepy;
    CREATE EXTENSION pg_trgm;
```

### Run the bot
___
Now everything you need to do is to run the bot. Open your Console
and type

```python
    # Windows:
    py -3 bot.py

    # Linux & macOS:
    python3 bot.py
```

to run the bot. Now the bot will create a file called config.json.
You need to add the required information through the console.
But you can also create a config.json file manually before starting
the bot for the first time. It should look like:

```json
    {
        "owner_id": "301790265725943808 (Replace this with your ID)",
        "pg_db": "valepy",
        "pg_host": "127.0.0.1",
        "pg_pass": "your_password",
        "pg_port": "5432",
        "pg_user": "valepy",
        "token": "Your bot token",
        "jdoodle_client": "Your JDoodle Client-ID",
        "jdoodle_secret": "Your JDoodle Client-Secret"
    }
```