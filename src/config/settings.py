import os
from dotenv import load_dotenv

load_dotenv()   # reads .env file into environment variables

def _env_bool(name: str, default: bool = False) -> bool:
    """
    Read a boolean from the environment.

    Accepts the spellings people actually write in a .env file. Anything
    unrecognised is False rather than truthy — a typo should leave an external
    API OFF, never silently spend quota.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

class Settings:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")

    # Per-provider switches for the RapidAPI integrations. Env-driven because
    # a container cannot edit its own source: these were hardcoded False with
    # a "TEMP: quota reached" comment, so setting them in .env did nothing and
    # the flag-on path could not be exercised at all.
    #
    # Default False. Each free tier has a small monthly quota that a dev loop
    # exhausts quickly, and the mock path is the same code that runs on an API
    # failure — so flags-off is a real degradation test, not a special mode.
    SKYSCANNER_ENABLED: bool = _env_bool("SKYSCANNER_ENABLED")
    BOOKING_ENABLED: bool = _env_bool("BOOKING_ENABLED")
    AIRBNB_ENABLED: bool = _env_bool("AIRBNB_ENABLED")

    @classmethod
    def validate(cls) -> None:
        """Call this at startup to catch missing keys early."""
        missing = [
            key for key in ["ANTHROPIC_API_KEY", "RAPIDAPI_KEY"]
            if not getattr(cls, key)
        ]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Copy .env.example to .env and fill in your keys."
            )

settings = Settings()