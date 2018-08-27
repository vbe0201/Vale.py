class JDoodleRequestFailedError(Exception):
    pass


class JDoodleResponse(object):
    def __init__(self, **kwargs):
        self.output = kwargs.pop("output")
        self.status_code = kwargs.pop("status_code")
        self.memory = kwargs.pop("memory")
        self.cpu_time = kwargs.pop("cpu_time")

    @classmethod
    def parse_result(cls, *, result: dict):
        """Parses the response from the API."""

        status_codes = {
            "401": "Invalid API credentials.",
            "429": "The daily rate limit for the API is reached.",
            "500": "An internal server issue occurred. Please try again later."
        }

        for code, error in status_codes.items():
            if result["statusCode"] == int(code):
                raise JDoodleRequestFailedError(f"Status Code {code}: {error}")

        return cls(
            output=result["output"],
            status_code=result["statusCode"],
            memory=result["memory"],
            cpu_time=result["cpuTime"]
        )


class JDoodle:
    def __init__(self, bot, client_id, client_secret):
        self.bot = bot
        self.base_url = "https://api.jdoodle.com/v1/execute"

        self.client_id = client_id
        self.client_secret = client_secret

    async def _request(self, **kwargs):
        """Makes a request to the JDoodle Compiler API."""

        params = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "script": kwargs.pop("script"),
            "language": kwargs.pop("language"),
            "versionIndex": kwargs.pop("version_index")
        }

        result = await self.bot.session.post(self.base_url, json=params)
        return JDoodleResponse.parse_result(result=await result.json())
