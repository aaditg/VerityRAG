from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = 'dev'
    database_url: str
    redis_url: str

    aws_region: str = 'us-east-1'
    aws_endpoint_url: str | None = None
    sqs_sync_queue_url: str | None = None
    s3_artifacts_bucket: str = 'rag-artifacts-local'
    secrets_prefix: str = 'rag/dev'

    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = 'llama3.1:8b'
    ollama_embed_model: str = 'nomic-embed-text'
    ollama_timeout_seconds: int = 45
    ignored_source_name_patterns: str = '*readme*,*license*,*changelog*,.ds_store,*q1 enterprise notes*'

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_drive_redirect_uri: str | None = None

    slack_signing_secret: str | None = None
    slack_bot_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
