from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    database_url: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/rag'
    aws_region: str = 'us-east-1'
    aws_endpoint_url: str | None = None
    sqs_sync_queue_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
