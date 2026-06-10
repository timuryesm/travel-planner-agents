import os
from dotenv import load_dotenv

load_dotenv()   # reads .env file into environment variables

class Settings:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")

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