<div align="center">
  <h1>Vale.py</h1>
  <strong>A bot to support Discord servers that I like.</strong>
  <br><br>
  <a href="https://github.com/itsVale/Vale.py/wiki"><img src="https://user-images.githubusercontent.com/38182450/43689699-b822f4fe-98fe-11e8-89c9-5fa5da75d088.png" width="200" /></a> &nbsp;
  <a href="https://discord.gg/6cbxXVm"><img src="https://user-images.githubusercontent.com/38182450/43689793-c45cbea2-98ff-11e8-828a-53d29f425d9c.png" width="200" /></a> &nbsp;
  <a href="https://discordapp.com/oauth2/authorize?client_id=458286335304794127&scope=bot&permissions=281143415"><img src="https://user-images.githubusercontent.com/38182450/43689573-e7e657aa-98fc-11e8-84a4-38d99df2dade.png" width="200" /></a><br><br>
  <a class="badge-ci-passing" href="https://travis-ci.com/itsVale/Vale.py"><img src="https://travis-ci.com/itsVale/Vale.py.svg?branch=master" /></a>
  <a href="https://codeclimate.com/github/itsVale/Vale.py/maintainability"><img src="https://api.codeclimate.com/v1/badges/31d858820986fa7b3a34/maintainability" /></a>
  <a class="badge-align" href="https://www.codacy.com/app/itsVale/Vale.py?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=itsVale/Vale.py&amp;utm_campaign=Badge_Grade"><img src="https://api.codacy.com/project/badge/Grade/cf549d36684740199c1a98f33f57f415"/></a>
</div>

---

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
    python3 -m pip install -U -r requirements.txt
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
Now everything you need to do is to run the bot.  
Get to the `config.example.py` file, rename it to `config.py` and fill out all necessary fields.  
And the last step is to open your console and type
```python
    # Windows:
    py -3 launch.py

    # Linux & macOS:
    python3 launch.py
```
**Important:** If you want your bot's logs inside the console, use `py -3 launch.py --stream-log`.

**On the first bot start, it is necessary to add the `--init-db` flag. E.g: `python3 launch.py --init-db`.  
This will create all database tables the bot depends on.**
