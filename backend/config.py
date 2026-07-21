from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://agentuser:agentpass2024@localhost:5432/demodb"
    ANTHROPIC_API_KEY: str = ""
    APIFY_API_TOKEN: str = ""
    UNSPLASH_ACCESS_KEY: str = ""
    JINA_API_KEY: str = ""
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "website-agent-bilder"
    R2_PUBLIC_URL: str = ""
    DEMO_DOMAIN: str = "https://deine-neue-website.ch"

    class Config:
        env_file = [".env", "../.env"]
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
