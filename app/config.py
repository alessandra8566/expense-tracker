from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from urllib.parse import quote_plus


class Settings(BaseSettings):
    LINE_CHANNEL_SECRET: str = ""
    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    
    # Database configuration
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "expense_tracker"
    APP_ENV: str = "development"

    @property
    def DATABASE_URL(self) -> str:
        password = quote_plus(self.POSTGRES_PASSWORD)
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{password}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
