import json
import asyncio
import os


class ConfigJson:
    def __init__(self):
        self.options = {
            "token": "What is the bot token? ",
            "owner_id": "Enter the bot owner's ID: ",
            "pg_user": "What is your PostgreSQL username? ",
            "pg_pass": "What is your PostgreSQL password? ",
            "pg_db": "Please enter the database to connect to: ",
            "pg_host": "What's the IP of the host of the databse? (If it's your computer, enter 127.0.0.1) ",
            "pg_port": "What's the connection port for PostgreSQL? (By default it's 5432) ",
            "jdoodle_client": "What's your Client id for JDoodle API service? ",
            "jdoodle_secret": "What's your Client secret for JDoodle API service? ",
        }

    def create_config(self):
        if not os.path.isfile("config.json"):
            with open("config.json", "w") as f:
                # Create general configuration for the bot
                settings = {}
                settings.update((key, input(value)) for key, value in self.options.keys())

                json.dump(settings, f, sort_keys=True, indent=4)
        else:
            with open("config.json", "r") as f:
                settings = json.load(f)

            self.check_config(settings)

        return settings

    @classmethod
    def complete_config(cls, key_dict, settings):

        for key, value in key_dict.items():
            if key not in settings or len(settings.get(key)) == 0:
                settings[key] = input(value)

                with open("config.json", "w") as f:
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: json.dump(settings, f, sort_keys=True, indent=4)
                    )

    def check_config(self, settings):
        self.complete_config(self.options, settings)
